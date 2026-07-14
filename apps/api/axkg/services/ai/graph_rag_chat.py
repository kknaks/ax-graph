"""chat 스테이지 ④ context builder (AXKG-SPEC-006 / SPEC-011 ④). WP4 Phase 2.

handler_kind=`graph_rag_chat`. 파이프라인(pipeline.py)에 등록되어 실행된다.

- 입력: 질문 + (선택 노드 컨텍스트) + retriever evidence 발췌 + 세션 대화 이력을 **런타임
  데이터 블록으로만** 공급한다. 답변 "규칙"(graph-chat-rules.md)은 seed된 DB 프롬프트
  본문 + worker 실행 workspace의 프로젝트 context가 담당한다 — api는 파일로 로드하지 않는다
  (PLAN-005-T-008 실행 모델 재설계, source_summary/classification_gate와 동일 원칙).
- retriever(GraphService.retrieve)가 관련 문서 + documents index 스냅샷을 제공한다.
  검색 스냅샷은 `last_retrieval_context`에 보관해 run.retrieval_context로 영속한다.
- 출력(`answer`/`evidence`/`missing_context`/`suggested_actions`)이 스키마 검증을 통과하면
  `handle_result`가 evidence stem을 실제 문서로 확인해 assistant 메시지 + run 결과를 저장한다.
- 근거 부족(evidence가 실제 문서로 하나도 확인되지 않음 또는 answer 공백)은 추측하지 않고
  run.result_payload에 `INSUFFICIENT_GRAPH_CONTEXT`로 표면화한다(SPEC-006 §5 "근거 없으면
  단정하지 않는다"). 이 경우 단정 answer를 assistant 메시지로 저장하지 않는다.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.ai import AiTaskDefinitionDTO, AiTaskDTO, AssembledBlockDTO
from axkg.models.base import utcnow
from axkg.repositories.chat import ChatRepository
from axkg.repositories.documents import DocumentRepository
from axkg.services.ai.context import ContextBuilder, ContextBuildError
from axkg.services.graph import GraphService, RetrievalResult
from axkg.services.qmd import QmdClient
from axkg.storage.markdown_root import MarkdownRoot

HANDLER_KIND = "graph_rag_chat"

# 근거 부족 표면화 코드 (SPEC-006 §5). run은 succeeded지만 result_payload로 표면화한다.
INSUFFICIENT_GRAPH_CONTEXT = "INSUFFICIENT_GRAPH_CONTEXT"

# 선택 문서 본문 주입 cap(문자). gates._STALE_MARKDOWN_CAP(supplement/stale 전문 주입) 선례와
# 동일값. 초과 시 앞부분 + 절단 표기. 워커엔 문서 마운트가 없어 본문은 주입으로만 공급한다(T-018).
SELECTED_DOC_MARKDOWN_CAP = 8000


class GraphRagChatContextBuilder(ContextBuilder):
    """chat 스테이지 데이터 블록 공급 + 답변/evidence 소비.

    session 바인딩 handler다. 파이프라인 실행 1회마다 그 실행의 session으로 생성한다
    (registry 자체는 앱 수명이 아니라 실행 수명). retriever는 GraphService가 소유한다.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        root: MarkdownRoot | None = None,
        qmd: QmdClient | None = None,
    ) -> None:
        self._chats = ChatRepository(session)
        self._docs = DocumentRepository(session)
        self._graph = GraphService(session, root=root, qmd=qmd)
        # 선택 문서 본문 read-through용(documents markdown_full 로딩과 동일 계열). 실행 경로는
        # 실제 root를 주입한다(graph_chat_execution). None(테스트/오프라인)이면 본문 없이 fallback.
        self._root = root
        # 실행 중 관찰용: build_data_blocks가 검색 스냅샷/질문/선택 노드를 남긴다.
        self.last_retrieval: RetrievalResult | None = None
        self.last_retrieval_context: dict[str, Any] = {}
        self.last_question: str = ""
        self.last_selected_stem: str | None = None
        # qmd 사이드카 장애 폴백 관찰 플래그(pipeline이 RETRIEVER_FALLBACK_USED로 수집).
        self.retriever_fallback_used: bool = False

    # ------------------------------------------------------------------
    # 입력 블록
    # ------------------------------------------------------------------

    async def build_data_blocks(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> list[AssembledBlockDTO]:
        payload = task.payload
        session_id = self._uuid(payload.get("session_id"))
        user_message_id = self._uuid(payload.get("user_message_id"))
        if session_id is None or user_message_id is None:
            raise ContextBuildError(
                "CHAT_RUN_INVALID", "chat task payload에 session_id/user_message_id가 없습니다."
            )

        messages = await self._chats.list_messages(session_id)
        current = next((m for m in messages if m.id == user_message_id), None)
        if current is None:
            raise ContextBuildError(
                "CHAT_MESSAGE_NOT_FOUND", f"질문 메시지 없음: {user_message_id}"
            )
        question = current.content.strip()
        self.last_question = question

        # 선택 노드 → 문서(stem + 본문). stem은 retriever neighborhood 우선 컨텍스트에 쓴다.
        selected_doc = await self._selected_document(payload.get("selected_document_id"))
        selected_stem = selected_doc.stem if selected_doc is not None else None
        self.last_selected_stem = selected_stem

        retrieval = await self._graph.retrieve(question, selected_stem=selected_stem)
        self.last_retrieval = retrieval
        self.retriever_fallback_used = retrieval.fallback_used
        self.last_retrieval_context = self._retrieval_context(retrieval, selected_stem)

        blocks: list[AssembledBlockDTO] = [
            AssembledBlockDTO(kind="data", label="question", text=f"[질문]\n{question}"),
        ]
        if selected_doc is not None:
            blocks.append(self._selected_document_block(selected_doc))
        blocks.append(
            AssembledBlockDTO(
                kind="data",
                label="evidence_candidates",
                text=self._render_evidence(retrieval),
            )
        )
        history = self._render_history(messages, current.sequence_no)
        if history:
            blocks.append(
                AssembledBlockDTO(kind="data", label="conversation_history", text=history)
            )
        return blocks

    def select_template_key(
        self, task: AiTaskDTO, definition: AiTaskDefinitionDTO
    ) -> str | None:
        return None

    # ------------------------------------------------------------------
    # 출력 소비
    # ------------------------------------------------------------------

    async def handle_result(self, task: AiTaskDTO, output: dict[str, Any]) -> None:
        """검증 통과한 답변을 evidence 문서로 확인해 assistant 메시지 + run 결과에 저장한다."""
        payload = task.payload
        run_id = self._uuid(payload.get("run_id"))
        session_id = self._uuid(payload.get("session_id"))
        if run_id is None or session_id is None:
            return
        selected_document_id = self._uuid(payload.get("selected_document_id"))

        answer = (output.get("answer") or "").strip()
        resolved = await self._resolve_evidence(output.get("evidence") or [])
        missing_context = list(output.get("missing_context") or [])
        suggested_actions = list(output.get("suggested_actions") or [])

        # 근거 부족: 실제 문서로 확인된 evidence가 없거나 answer가 비었으면 단정하지 않는다.
        if not resolved or not answer:
            result_payload = {
                "answer": None,
                "evidence_documents": [],
                "evidence_edges": [],
                "used_paths": [],
                "confidence": None,
                "missing_context": missing_context,
                "suggested_actions": suggested_actions,
                "error_code": INSUFFICIENT_GRAPH_CONTEXT,
            }
            await self._chats.set_run_status(
                run_id,
                "succeeded",
                finished_at=utcnow(),
                result_payload=result_payload,
                retrieval_context=self.last_retrieval_context,
                error_code=INSUFFICIENT_GRAPH_CONTEXT,
            )
            return

        evidence_edges = await self._evidence_edges(resolved)
        used_paths = [doc["stem"] for doc in resolved]
        result_payload = {
            "answer": answer,
            "evidence_documents": resolved,
            "evidence_edges": evidence_edges,
            "used_paths": used_paths,
            # confidence는 output_schema 밖(모델이 내지 않음)이라 서버가 단정하지 않는다.
            # 근거 강도 파생은 후속(OQ) — 지금은 null로 둔다.
            "confidence": None,
            "missing_context": missing_context,
            "suggested_actions": suggested_actions,
        }
        sequence_no = await self._chats.next_sequence_no(session_id)
        message = await self._chats.add_message(
            session_id=session_id,
            role="assistant",
            content=answer,
            sequence_no=sequence_no,
            run_id=run_id,
            selected_document_id=selected_document_id,
            evidence={
                "documents": resolved,
                "edges": evidence_edges,
                "used_paths": used_paths,
            },
        )
        await self._chats.set_run_status(
            run_id,
            "succeeded",
            finished_at=utcnow(),
            assistant_message_id=message.id,
            result_payload=result_payload,
            retrieval_context=self.last_retrieval_context,
        )

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    async def _selected_document(self, raw_document_id: Any):
        """선택 노드 문서(stem + path 보유). 없으면 None (선택 없이 진행)."""
        document_id = self._uuid(raw_document_id)
        if document_id is None:
            return None
        return await self._docs.get(document_id)

    def _selected_document_block(self, doc) -> AssembledBlockDTO:
        """선택 문서 블록 — 본문(cap 적용)을 주입하고 파일 접근 금지를 명시한다(T-018).

        본문 로드 실패/미존재면 stem-only 안전 fallback(현행 동작).
        """
        header = (
            f"[선택된 문서] stem={doc.stem} · {doc.title}\n"
            "질문이 모호하면 이 문서 관점으로 해석하고, 이 문서의 neighborhood를 우선 "
            "컨텍스트로 삼는다.\n"
            "파일 시스템에 접근할 수 없다 — 주어진 본문과 evidence 발췌만 근거로 답하고, "
            "원문 파일을 직접 읽으려 하지 마라."
        )
        body = self._read_capped(getattr(doc, "path", None))
        text = f"{header}\n\n[본문]\n{body}" if body else header
        return AssembledBlockDTO(kind="data", label="selected_document", text=text)

    def _read_capped(self, path: str | None) -> str:
        """선택 문서 markdown read-through(cap). 미존재/로드 실패면 빈 문자열(→ fallback)."""
        if not path or self._root is None or not self._root.exists(path):
            return ""
        try:
            text = self._root.read_text(path)
        except OSError:
            return ""
        if len(text) > SELECTED_DOC_MARKDOWN_CAP:
            return text[:SELECTED_DOC_MARKDOWN_CAP] + "\n… (truncated)"
        return text

    async def _resolve_evidence(
        self, evidence: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """모델이 낸 evidence stem을 실제 문서로 확인한다(없는 문서는 지어내지 않고 버린다)."""
        resolved: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in evidence:
            stem = (item.get("stem") or "").strip()
            if not stem or stem in seen:
                continue
            doc = await self._docs.get_by_stem(stem)
            if doc is None:
                continue
            seen.add(stem)
            resolved.append(
                {
                    "document_id": str(doc.id),
                    "stem": doc.stem,
                    "title": doc.title,
                    "document_type": doc.document_type,
                    "excerpt": (item.get("excerpt") or "").strip(),
                    "reason": (item.get("reason") or "").strip(),
                }
            )
        return resolved

    async def _evidence_edges(
        self, resolved: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """evidence 문서들 사이의 resolve된 엣지만 추린다("A와 B가 이렇게 이어진다")."""
        id_to_stem = {uuid.UUID(doc["document_id"]): doc["stem"] for doc in resolved}
        ids = set(id_to_stem)
        edges: list[dict[str, Any]] = []
        for edge in await self._docs.list_all_edges():
            if edge.is_broken or edge.to_document_id is None:
                continue
            if edge.from_document_id in ids and edge.to_document_id in ids:
                edges.append(
                    {
                        "from_stem": id_to_stem[edge.from_document_id],
                        "to_stem": id_to_stem[edge.to_document_id],
                        "edge_type": edge.edge_type,
                        "source_syntax": edge.source_syntax,
                        "label": edge.label,
                    }
                )
        return edges

    @staticmethod
    def _retrieval_context(
        retrieval: RetrievalResult, selected_stem: str | None
    ) -> dict[str, Any]:
        """run.retrieval_context에 남길 검색 스냅샷(관찰/디버깅용)."""
        return {
            "query": retrieval.query,
            "selected_stem": selected_stem,
            "documents": [
                {
                    "stem": doc.stem,
                    "title": doc.title,
                    "document_type": doc.document_type,
                    "score": doc.score,
                    "distance": doc.distance,
                    "snippet": doc.snippet,
                }
                for doc in retrieval.documents
            ],
            "index_size": len(retrieval.index_snapshot),
            # 2단 retriever 관찰(AXKG-WORK-008): 폴백 여부·모드·근거 경로.
            "retriever_mode": retrieval.retriever_mode,
            "retriever_fallback_used": retrieval.fallback_used,
            "used_paths": [
                {"seed_stem": p.seed_stem, "to_stem": p.to_stem, "stems": list(p.stems), "hop": p.hop}
                for p in retrieval.used_paths
            ],
            "evidence_edges": [
                {"from_stem": e.from_stem, "to_stem": e.to_stem, "edge_type": e.edge_type}
                for e in retrieval.evidence_edges
            ],
        }

    @staticmethod
    def _render_evidence(retrieval: RetrievalResult) -> str:
        if not retrieval.documents:
            return (
                "[retriever evidence 후보]\n"
                "검색된 관련 문서가 없다. 근거가 없으면 지어내지 말고 missing_context로 표면화하라."
            )
        lines = ["[retriever evidence 후보 — 이 발췌 안에서만 근거를 댄다]"]
        for doc in retrieval.documents:
            dist = "선택 노드" if doc.distance == 0 else (
                f"거리 {doc.distance}" if doc.distance is not None else "거리 -"
            )
            lines.append(
                f"- stem={doc.stem} · {doc.title} · type={doc.document_type} · {dist}\n"
                f"  발췌: {doc.snippet}"
            )
        return "\n".join(lines)

    @staticmethod
    def _render_history(messages: list, current_sequence_no: int) -> str:
        prior = [m for m in messages if m.sequence_no < current_sequence_no]
        if not prior:
            return ""
        lines = ["[이전 대화 이력 — 맥락 유지용, 근거는 매번 현재 evidence에서 다시 댄다]"]
        for msg in prior:
            speaker = "사용자" if msg.role == "user" else "어시스턴트"
            lines.append(f"{speaker}: {msg.content}")
        return "\n".join(lines)

    @staticmethod
    def _uuid(value: Any) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError):
            return None
