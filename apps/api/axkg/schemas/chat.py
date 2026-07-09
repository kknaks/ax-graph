"""graph chat API 요청/응답 (AXKG-SPEC-006 Interface Contract).

FE(profile-fe T-013)가 이 계약으로 붙는다. 필드명은 spec §4 Request/Response 표를 정확히 따른다.
- 새 채팅: POST /graph/chats → {chat_id, run_id, status, user_message_id}
- 기존 채팅: POST /graph/chats/{chat_id}/messages → {run_id, status, user_message_id}
- 폴링: GET /graph/chats/{chat_id}/runs/{run_id} → status + (성공 시) answer/evidence/…
Phase 1은 run이 queued라 폴링 응답의 answer/evidence 등은 대부분 null이다(Phase 2가 채움).
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from axkg.dto.chat import ChatMessageDTO, ChatRunDTO, ChatSessionDTO


# ---------------------------------------------------------------------------
# 요청
# ---------------------------------------------------------------------------


class ChatStartRequest(BaseModel):
    """POST /graph/chats. question 필수, selected_node_id/filters optional."""

    question: str
    selected_node_id: uuid.UUID | None = None
    filters: dict[str, Any] = Field(default_factory=dict)


class ChatMessageRequest(BaseModel):
    """POST /graph/chats/{chat_id}/messages. 이번 질문에서 우선할 노드/필터 optional."""

    question: str
    selected_node_id: uuid.UUID | None = None
    filters: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 응답 — 생성
# ---------------------------------------------------------------------------


class ChatStartResponse(BaseModel):
    chat_id: uuid.UUID
    run_id: uuid.UUID
    status: str
    user_message_id: uuid.UUID


class ChatMessageResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    user_message_id: uuid.UUID


# ---------------------------------------------------------------------------
# 응답 — 세션/메시지 이력
# ---------------------------------------------------------------------------


class ChatSessionSummary(BaseModel):
    """세션 목록 아이템 (GET /graph/chats)."""

    chat_id: uuid.UUID
    title: str
    status: str
    selected_node_id: uuid.UUID | None = None
    last_message_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dto(cls, dto: ChatSessionDTO) -> "ChatSessionSummary":
        return cls(
            chat_id=dto.id,
            title=dto.title,
            status=dto.status,
            selected_node_id=dto.selected_document_id,
            last_message_at=dto.last_message_at,
            created_at=dto.created_at,
            updated_at=dto.updated_at,
        )


class ChatSessionListResponse(BaseModel):
    chats: list[ChatSessionSummary]


class ChatMessageView(BaseModel):
    """메시지 이력 아이템 (GET /graph/chats/{chat_id})."""

    id: uuid.UUID
    role: str
    content: str
    sequence_no: int
    run_id: uuid.UUID | None = None
    selected_node_id: uuid.UUID | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @classmethod
    def from_dto(cls, dto: ChatMessageDTO) -> "ChatMessageView":
        return cls(
            id=dto.id,
            role=dto.role,
            content=dto.content,
            sequence_no=dto.sequence_no,
            run_id=dto.run_id,
            selected_node_id=dto.selected_document_id,
            evidence=dto.evidence,
            created_at=dto.created_at,
        )


class ChatDetailResponse(BaseModel):
    """세션 + 메시지 이력 (GET /graph/chats/{chat_id})."""

    chat_id: uuid.UUID
    title: str
    status: str
    selected_node_id: uuid.UUID | None = None
    last_message_at: datetime | None = None
    created_at: datetime
    messages: list[ChatMessageView]

    @classmethod
    def from_dto(
        cls, session: ChatSessionDTO, messages: list[ChatMessageDTO]
    ) -> "ChatDetailResponse":
        return cls(
            chat_id=session.id,
            title=session.title,
            status=session.status,
            selected_node_id=session.selected_document_id,
            last_message_at=session.last_message_at,
            created_at=session.created_at,
            messages=[ChatMessageView.from_dto(m) for m in messages],
        )


# ---------------------------------------------------------------------------
# 응답 — run 폴링
# ---------------------------------------------------------------------------


class ChatRunResponse(BaseModel):
    """GET /graph/chats/{chat_id}/runs/{run_id} 폴링 응답 (SPEC-006 §4).

    answer/evidence/…는 run.result_payload에서 조립한다. Phase 1(queued)에선 대부분 null이고
    Phase 2(T-012)가 성공 run의 result_payload에 채운다.
    """

    chat_id: uuid.UUID
    run_id: uuid.UUID
    status: str
    assistant_message: ChatMessageView | None = None
    answer: str | None = None
    evidence_documents: list[Any] | None = None
    evidence_edges: list[Any] | None = None
    used_paths: list[Any] | None = None
    confidence: float | None = None
    missing_context: Any | None = None
    suggested_actions: list[Any] | None = None
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def from_dto(
        cls, run: ChatRunDTO, *, assistant_message: ChatMessageDTO | None = None
    ) -> "ChatRunResponse":
        payload = run.result_payload or {}
        return cls(
            chat_id=run.session_id,
            run_id=run.id,
            status=run.status,
            assistant_message=(
                ChatMessageView.from_dto(assistant_message)
                if assistant_message is not None
                else None
            ),
            answer=payload.get("answer"),
            evidence_documents=payload.get("evidence_documents"),
            evidence_edges=payload.get("evidence_edges"),
            used_paths=payload.get("used_paths"),
            confidence=payload.get("confidence"),
            missing_context=payload.get("missing_context"),
            suggested_actions=payload.get("suggested_actions"),
            error_code=run.error_code,
            error_message=run.error_message,
        )
