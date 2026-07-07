"""approval_gates / approval_gate_revisions / gate_feedback (AXKG-SPEC-001/002/004).

approval_gates는 컨테이너, approval_gate_revisions가 실제 AI 제안 버전.
"""
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from axkg.models.base import JSONB, Base, created_at_col, updated_at_col, uuid_pk
from axkg.models.enums import (
    APPROVAL_GATE_STATUS,
    APPROVAL_REVISION_STATUS,
    GATE_FEEDBACK_STATUS,
    GATE_KIND,
    check_in,
)


class ApprovalGate(Base):
    __tablename__ = "approval_gates"
    __table_args__ = (
        sa.UniqueConstraint("source_id", "gate_kind", name="uq_approval_gates_source_id_gate_kind"),
        sa.CheckConstraint(check_in("gate_kind", GATE_KIND), name="ck_approval_gates_gate_kind"),
        sa.CheckConstraint(
            check_in("status", APPROVAL_GATE_STATUS), name="ck_approval_gates_status"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("sources.id"), nullable=False
    )
    gate_kind: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    # 순환 FK 회피: revisions/tasks FK 제약은 마이그레이션 step 10에서 추가.
    active_revision_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    approved_revision_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    last_ai_task_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class GateFeedback(Base):
    __tablename__ = "gate_feedback"
    __table_args__ = (
        sa.CheckConstraint(
            check_in("status", GATE_FEEDBACK_STATUS), name="ck_gate_feedback_status"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    gate_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("approval_gates.id"), nullable=False
    )
    # 순환 FK 회피: revisions FK 제약은 마이그레이션 step 10에서 추가.
    target_revision_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    quick_options: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="submitted")
    created_at: Mapped[datetime] = created_at_col()
    consumed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class ApprovalGateRevision(Base):
    __tablename__ = "approval_gate_revisions"
    __table_args__ = (
        sa.UniqueConstraint("gate_id", "version", name="uq_approval_gate_revisions_gate_id_version"),
        sa.CheckConstraint(
            check_in("status", APPROVAL_REVISION_STATUS),
            name="ck_approval_gate_revisions_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    gate_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("approval_gates.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    form_schema_version: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("approval_gate_revisions.id")
    )
    feedback_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("gate_feedback.id")
    )
    ai_task_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("ai_tasks.id"))
    open_kknaks_session_id: Mapped[str | None] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = created_at_col()
    approved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
