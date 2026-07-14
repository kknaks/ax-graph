"""qmd 사이드카 클라이언트 유닛 테스트 (AXKG-WORK-008 C-1/C-3).

라이브 사이드카 없이 파싱·에러 정규화·팩토리를 검증한다. MCP 응답(structuredContent)
파서와 collection prefix strip, SSE/JSON 디코드, 실패→QmdUnavailable 정규화를 커버한다.
"""
import json

import httpx
import pytest

from axkg.services.qmd import (
    HttpMcpQmdClient,
    NullQmdClient,
    QmdUnavailable,
    _strip_collection_prefix,
    build_qmd_client,
)


async def test_null_client_always_unavailable() -> None:
    with pytest.raises(QmdUnavailable):
        await NullQmdClient().search("q", top_k=5)


def test_build_qmd_client_empty_url_is_null() -> None:
    assert isinstance(build_qmd_client(mcp_url="", rerank_default=False), NullQmdClient)
    assert isinstance(build_qmd_client(mcp_url="   ", rerank_default=False), NullQmdClient)
    client = build_qmd_client(mcp_url="http://qmd:8181/mcp", rerank_default=False)
    assert isinstance(client, HttpMcpQmdClient)


@pytest.mark.parametrize(
    "file,expected",
    [
        ("qmd://axkg/permanent/concepts/x.md", "permanent/concepts/x.md"),
        ("axkg/references/note.md", "references/note.md"),
        ("axkg/top.md", "top.md"),
    ],
)
def test_strip_collection_prefix(file: str, expected: str) -> None:
    assert _strip_collection_prefix(file) == expected


def test_parse_results_from_structured_content() -> None:
    result = {
        "structuredContent": {
            "results": [
                {"docid": "#1", "file": "axkg/references/a.md", "title": "A", "score": 1.0},
                {"docid": "#2", "file": "axkg/references/b.md", "title": "B", "score": 0.5},
                {"title": "no file", "score": 0.3},  # file 없음 → 스킵
            ]
        }
    }
    cands = HttpMcpQmdClient._parse_results(result)
    assert [c.path for c in cands] == ["references/a.md", "references/b.md"]
    assert cands[0].score == 1.0
    assert cands[0].docid == "#1"


def test_decode_jsonrpc_json_body() -> None:
    resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        text=json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"ok": 1}}),
    )
    assert HttpMcpQmdClient._decode_jsonrpc(resp) == {"ok": 1}


def test_decode_jsonrpc_sse_body() -> None:
    body = "event: message\ndata: " + json.dumps(
        {"jsonrpc": "2.0", "id": 2, "result": {"ok": 2}}
    ) + "\n\n"
    resp = httpx.Response(
        200, headers={"content-type": "text/event-stream"}, text=body
    )
    assert HttpMcpQmdClient._decode_jsonrpc(resp) == {"ok": 2}


def test_decode_jsonrpc_rpc_error_raises() -> None:
    resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        text=json.dumps({"jsonrpc": "2.0", "id": 2, "error": {"code": -32602, "message": "bad"}}),
    )
    with pytest.raises(QmdUnavailable):
        HttpMcpQmdClient._decode_jsonrpc(resp)


async def test_http_client_normalizes_connection_error(monkeypatch) -> None:
    """사이드카 미기동(연결 실패)은 QmdUnavailable로 정규화된다(→ retriever 폴백)."""
    client = HttpMcpQmdClient("http://127.0.0.1:59999/mcp", timeout_s=0.2)
    with pytest.raises(QmdUnavailable):
        await client.search("무엇이든", top_k=5)


async def test_http_client_empty_query_returns_empty() -> None:
    client = HttpMcpQmdClient("http://qmd:8181/mcp")
    assert await client.search("   ", top_k=5) == []
