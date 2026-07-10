"""drafts / apply_plans — 승인 전 payload·executor plan (AXKG-SPEC-004)."""
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from axkg.models.base import JSONB, Base, created_at_col, updated_at_col, uuid_pk
from axkg.models.enums import (
    APPLY_PLAN_STATUS,
    APPLY_PLAN_VALIDATION_STATUS,
    DRAFT_CHANGE_KIND,
    DRAFT_TYPE,
    check_in,
)


class Draft(Base):
    __tablename__ = "drafts"
    __table_args__ = (
        sa.CheckConstraint(check_in("draft_type", DRAFT_TYPE), name="ck_drafts_draft_type"),
        sa.CheckConstraint(
            check_in("change_kind", DRAFT_CHANGE_KIND), name="ck_drafts_change_kind"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("sources.id"))
    gate_revision_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("approval_gate_revisions.id"), nullable=False
    )
    draft_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    filename_candidate: Mapped[str | None] = mapped_column(sa.Text())
    target_path: Mapped[str | None] = mapped_column(sa.Text())
    change_kind: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class ApplyPlan(Base):
    __tablename__ = "apply_plans"
    __table_args__ = (
        sa.UniqueConstraint("gate_revision_id", name="uq_apply_plans_gate_revision_id"),
        sa.CheckConstraint(check_in("status", APPLY_PLAN_STATUS), name="ck_apply_plans_status"),
        sa.CheckConstraint(
            check_in("validation_status", APPLY_PLAN_VALIDATION_STATUS),
            name="ck_apply_plans_validation_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    gate_revision_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("approval_gate_revisions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    validation_status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    db_actions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    file_actions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    validation_errors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    # 실행 시 draft_markdown 없어 건너뛴 파생 제안(관측성, PLAN-009-T-016).
    skipped: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    applied_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
