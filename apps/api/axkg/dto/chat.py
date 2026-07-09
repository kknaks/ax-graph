"""graph chat 내부 DTO (AXKG-SPEC-006). 서비스 계층 입출력 전용.

session / message / run row 스냅샷. Phase 1은 lifecycle·영속·폴링까지이고
AI 실행(retrieval_context/result_payload 채우기)은 Phase 2(T-012) 소관이다.
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatSessionDTO(BaseModel):
    """graph_chat_sessions row 스냅샷 (chat_id = id)."""

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    status: str
    selected_document_id: uuid.UUID | None = None
    last_open_kknaks_session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None
    deleted_at: datetime | None = None


class ChatMessageDTO(BaseModel):
    """graph_chat_messages row 스냅샷. assistant 메시지의 근거는 evidence에 담긴다."""

    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    sequence_no: int
    run_id: uuid.UUID | None = None
    selected_document_id: uuid.UUID | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ChatRunDTO(BaseModel):
    """graph_chat_runs row 스냅샷. FE는 status를 폴링하고 성공 시 result_payload를 읽는다."""

    id: uuid.UUID
    session_id: uuid.UUID
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID | None = None
    ai_task_id: uuid.UUID | None = None
    status: str
    open_kknaks_session_id: str | None = None
    selected_document_id: uuid.UUID | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    retrieval_context: dict[str, Any] = Field(default_factory=dict)
    result_payload: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
