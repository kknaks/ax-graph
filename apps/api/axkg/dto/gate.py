"""approval gate 내부 DTO (AXKG-SPEC-002). 서비스 계층 입출력 전용.

`approval_gates`(컨테이너) / `approval_gate_revisions`(AI 제안 버전) / `gate_feedback`
3층을 그대로 반영한다. gate.status(사용자 표시) / revision.status(제안 버전) /
ai_task.status(실행)는 섞지 않는다(SPEC-002 §5).
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ApprovalGateDTO(BaseModel):
    """source + gate_kind 단위 게이트 묶음(컨테이너)."""

    id: uuid.UUID
    source_id: uuid.UUID
    gate_kind: str
    status: str
    active_revision_id: uuid.UUID | None = None
    approved_revision_id: uuid.UUID | None = None
    last_ai_task_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class ApprovalGateRevisionDTO(BaseModel):
    """AI가 만든 실제 승인 대상 버전(v1, v2, …)."""

    id: uuid.UUID
    gate_id: uuid.UUID
    version: int
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    form_schema_version: str
    parent_revision_id: uuid.UUID | None = None
    feedback_id: uuid.UUID | None = None
    ai_task_id: uuid.UUID | None = None
    open_kknaks_session_id: str | None = None
    created_at: datetime
    approved_at: datetime | None = None


class GateFeedbackDTO(BaseModel):
    """사용자가 남긴 재생성 방향(피드백)."""

    id: uuid.UUID
    gate_id: uuid.UUID
    target_revision_id: uuid.UUID
    body: str
    quick_options: list[Any] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: datetime
    consumed_at: datetime | None = None
