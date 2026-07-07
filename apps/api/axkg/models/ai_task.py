"""ai_task_definitions / ai_tasks — AI 실행 trace·retry 체인 (AXKG-SPEC-011, AXKG-SPEC-007).

실패 task는 불변 보존, 재시도는 retry_of_task_id로 새 row.
"""
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from axkg.models.base import JSONB, Base, created_at_col, updated_at_col, uuid_pk
from axkg.models.enums import (
    AI_HANDLER_KIND,
    AI_TASK_STATUS,
    AI_TASK_TYPE,
    PROVIDER,
    check_in,
)


class AiTaskDefinition(Base):
    __tablename__ = "ai_task_definitions"
    __table_args__ = (
        sa.CheckConstraint(
            check_in("handler_kind", AI_HANDLER_KIND),
            name="ck_ai_task_definitions_handler_kind",
        ),
        sa.CheckConstraint(
            check_in("default_provider", PROVIDER),
            name="ck_ai_task_definitions_default_provider",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(sa.Text(), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text())
    handler_kind: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    prompt_key: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    # documentation_gate handler에서만 설정 (AXKG-DEC-005).
    template_key: Mapped[str | None] = mapped_column(sa.Text())
    default_provider: Mapped[str | None] = mapped_column(sa.Text())
    default_model: Mapped[str | None] = mapped_column(sa.Text())
    default_options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    default_provider_options: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    enabled: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class AiTask(Base):
    __tablename__ = "ai_tasks"
    __table_args__ = (
        sa.CheckConstraint(check_in("status", AI_TASK_STATUS), name="ck_ai_tasks_status"),
        sa.CheckConstraint(check_in("task_type", AI_TASK_TYPE), name="ck_ai_tasks_task_type"),
        sa.CheckConstraint(check_in("provider", PROVIDER), name="ck_ai_tasks_provider"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    task_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    task_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("ai_task_definitions.id")
    )
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("sources.id"))
    # gate_id/revision_id/template_version_id FK 제약은 마이그레이션 후속 step에서 추가
    # (README 순서: ai_tasks(6)가 approval_gates(7)/revisions(9)/template_versions(14)보다 먼저).
    gate_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    revision_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    retry_of_task_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("ai_tasks.id")
    )
    retry_count: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=0)
    provider: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    model: Mapped[str | None] = mapped_column(sa.Text())
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provider_options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    open_kknaks_task_id: Mapped[str | None] = mapped_column(sa.Text())
    open_kknaks_session_id: Mapped[str | None] = mapped_column(sa.Text())
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("prompt_versions.id")
    )
    template_version_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(sa.Text())
    error_message: Mapped[str | None] = mapped_column(sa.Text())
    queued_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
