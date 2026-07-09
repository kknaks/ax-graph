"""apply_plan 내부 DTO (AXKG-SPEC-004/002). Apply Executor 입출력 전용."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ApplyPlanDTO(BaseModel):
    """문서화 게이트 revision의 실행 계획(apply_plan.v1) 실행 레코드.

    validation_status: pending → valid/invalid, status: pending → applying → applied/failed.
    db_actions는 AI가 아니라 executor가 정본으로 derive한다(SPEC-004 §5).
    """

    id: uuid.UUID
    gate_revision_id: uuid.UUID
    status: str
    validation_status: str
    db_actions: list[Any] = Field(default_factory=list)
    file_actions: list[Any] = Field(default_factory=list)
    validation_errors: list[Any] = Field(default_factory=list)
    applied_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
