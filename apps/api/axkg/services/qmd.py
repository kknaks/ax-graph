"""qmd 사이드카 클라이언트 — Graph RAG 2단 retriever의 1단 후보 발굴 (AXKG-WORK-008 C-1/C-3).

qmd(github.com/tobi/qmd)는 로컬 마크다운 하이브리드 검색엔진이다 — BM25 + 로컬 embedding
벡터검색을 RRF로 융합하고(선택적 LLM 리랭크), SQLite 인덱스를 쓴다. 이 모듈은 그 사이드카를
**HTTP MCP transport**(`qmd mcp --http`)로 호출하는 얇은 클라이언트다.

## 통합 형태 결정 (AXKG-SPEC-011 §7 OQ — 구현 기본값으로 확정, PLAN-013-T-006 C-1 실측 근거)

- **subprocess CLI 대신 HTTP MCP 사이드카**를 쓴다. 실측(2026-07-14, CPU-only): CLI는 호출마다
  GGUF 모델 ~2.2GB를 재로드해 하이브리드+리랭크 1회에 **~186s**가 걸린다. HTTP 사이드카는 모델을
  상주시켜(mem ~2.3GB) **rerank off 하이브리드 0.03~0.32s**로 응답한다.
- **리랭크 기본 off**(`AXKG_QMD_RERANK_DEFAULT=false`). CPU-only 하드웨어에서 qwen3-reranker 0.6b
  LLM 리랭크는 40후보에 60s+이며 qmd 문서도 "CPU-only는 rerank=false 권장"이다. GPU 배포 시
  설정으로 on 가능(리랭크 토글 설정 표면 소유는 AXKG-SPEC-007). query-expansion(1.7B)은 MCP에
  명시적 `searches`(lex+vec)를 넘겨 건너뛴다(자동 확장 미사용).

## graceful fallback (C-5)

이 클라이언트는 **인프라 컴포넌트**다. 사이드카 미기동/장애/타임아웃/파싱실패는 예외가 아니라
`QmdUnavailable`로 정규화되고, retriever(GraphService)가 `keyword score + edge distance`
1단 폴백으로 강등한다. 실패는 사용자 오류가 아니라 품질 강등이며 관찰 기록된다
(`RETRIEVER_FALLBACK_USED`, AXKG-SPEC-011 Case Matrix).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class QmdCandidate:
    """qmd 1단 후보 1건. `path`는 collection prefix를 벗긴 markdown root 상대경로."""

    path: str
    score: float
    docid: str = ""
    title: str = ""
    snippet: str = ""


class QmdUnavailable(Exception):
    """qmd 사이드카를 쓸 수 없음(미설정·기동실패·타임아웃·프로토콜/파싱 실패).

    retriever는 이 예외를 잡아 keyword+edge 폴백으로 강등한다(사용자 실패 아님).
    """


class QmdClient(Protocol):
    """1단 후보 발굴 인터페이스. retriever가 주입받아 mock/실물을 교체한다."""

    async def search(
        self, query: str, *, top_k: int, rerank: bool | None = None
    ) -> list[QmdCandidate]:
        """질문 관련 top_k 하이브리드 후보. 실패 시 QmdUnavailable을 던진다."""
        ...


class NullQmdClient:
    """qmd 미설정 기본 클라이언트 — 항상 QmdUnavailable(→ keyword+edge 폴백).

    사이드카 URL이 설정되지 않은 환경(로컬/테스트)의 기본값. retrieve()가 기존
    keyword+edge 동작을 그대로 유지하도록 보장한다.
    """

    async def search(
        self, query: str, *, top_k: int, rerank: bool | None = None
    ) -> list[QmdCandidate]:
        raise QmdUnavailable("qmd sidecar not configured")


def _strip_collection_prefix(file: str) -> str:
    """qmd `file`("qmd://axkg/permanent/x.md" 또는 "axkg/permanent/x.md") → root 상대경로.

    qmd는 collection 이름을 경로 앞에 붙인다. markdown root 상대경로(DB `documents.path`)로
    맞추기 위해 scheme과 첫 세그먼트(collection 이름)를 벗긴다.
    """
    path = file
    if path.startswith("qmd://"):
        path = path[len("qmd://") :]
    # 첫 세그먼트 = collection 이름 → 벗긴다.
    if "/" in path:
        path = path.split("/", 1)[1]
    return path


class HttpMcpQmdClient:
    """qmd `qmd mcp --http` 사이드카를 MCP streamable-HTTP로 호출하는 클라이언트.

    MCP 핸드셰이크(initialize → notifications/initialized)를 세션당 1회 수행하고
    `query` 툴을 호출한다. 응답은 `structuredContent.results[]`(docid/file/score/title/
    snippet)를 파싱한다. 어떤 실패든 QmdUnavailable로 정규화한다.
    """

    _PROTOCOL_VERSION = "2024-11-05"

    def __init__(
        self,
        base_url: str,
        *,
        rerank_default: bool = False,
        timeout_s: float = 8.0,
    ) -> None:
        # base_url 예: "http://qmd:8181/mcp"
        self._url = base_url
        self._rerank_default = rerank_default
        self._timeout = timeout_s

    async def search(
        self, query: str, *, top_k: int, rerank: bool | None = None
    ) -> list[QmdCandidate]:
        q = (query or "").strip()
        if not q:
            return []
        use_rerank = self._rerank_default if rerank is None else rerank
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                session_id = await self._initialize(client)
                result = await self._call_query(client, session_id, q, top_k, use_rerank)
        except QmdUnavailable:
            raise
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError) as exc:
            raise QmdUnavailable(f"qmd query failed: {exc}") from exc
        return self._parse_results(result)

    # ------------------------------------------------------------------
    # MCP streamable-HTTP 최소 구현
    # ------------------------------------------------------------------

    async def _initialize(self, client: httpx.AsyncClient) -> str:
        resp = await self._post(
            client,
            None,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": self._PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "axkg-retriever", "version": "1"},
                },
            },
        )
        session_id = resp.headers.get("mcp-session-id")
        self._decode_jsonrpc(resp)  # initialize 결과 검증(에러면 여기서 던짐)
        # 핸드셰이크 완료 통지(notification — 응답 없음).
        await self._post(
            client,
            session_id,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            notification=True,
        )
        return session_id or ""

    async def _call_query(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        query: str,
        top_k: int,
        rerank: bool,
    ) -> dict[str, Any]:
        resp = await self._post(
            client,
            session_id,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "query",
                    "arguments": {
                        # 명시적 lex+vec 서브쿼리 → 자동 query-expansion(1.7B) 미사용.
                        "searches": [
                            {"type": "lex", "query": query},
                            {"type": "vec", "query": query},
                        ],
                        "limit": top_k,
                        "rerank": rerank,
                    },
                },
            },
        )
        return self._decode_jsonrpc(resp)

    async def _post(
        self,
        client: httpx.AsyncClient,
        session_id: str | None,
        body: dict[str, Any],
        *,
        notification: bool = False,
    ) -> httpx.Response:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if session_id:
            headers["mcp-session-id"] = session_id
        resp = await client.post(self._url, json=body, headers=headers)
        if resp.status_code >= 400:
            raise QmdUnavailable(f"qmd http {resp.status_code}")
        return resp

    @staticmethod
    def _decode_jsonrpc(resp: httpx.Response) -> dict[str, Any]:
        """application/json 또는 text/event-stream(SSE) 본문에서 JSON-RPC result를 추출."""
        ctype = resp.headers.get("content-type", "")
        text = resp.text
        payload: dict[str, Any] | None = None
        if "text/event-stream" in ctype:
            # SSE: `data: {json}` 줄만 모은다(마지막 message 이벤트가 결과).
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    chunk = line[len("data:") :].strip()
                    if chunk:
                        payload = json.loads(chunk)
        else:
            payload = json.loads(text) if text.strip() else None
        if payload is None:
            raise QmdUnavailable("empty qmd response")
        if "error" in payload:
            raise QmdUnavailable(f"qmd rpc error: {payload['error']}")
        return payload.get("result", {})

    @staticmethod
    def _parse_results(result: dict[str, Any]) -> list[QmdCandidate]:
        structured = result.get("structuredContent") or {}
        rows = structured.get("results") or []
        candidates: list[QmdCandidate] = []
        for row in rows:
            file = row.get("file")
            if not file:
                continue
            candidates.append(
                QmdCandidate(
                    path=_strip_collection_prefix(str(file)),
                    score=float(row.get("score") or 0.0),
                    docid=str(row.get("docid") or ""),
                    title=str(row.get("title") or ""),
                    snippet=str(row.get("snippet") or ""),
                )
            )
        return candidates


def build_qmd_client(
    *, mcp_url: str, rerank_default: bool, timeout_s: float = 8.0
) -> QmdClient:
    """설정에서 qmd 클라이언트를 만든다. url이 비면 NullQmdClient(폴백 강제)."""
    if not (mcp_url or "").strip():
        return NullQmdClient()
    return HttpMcpQmdClient(
        mcp_url.strip(), rerank_default=rerank_default, timeout_s=timeout_s
    )
