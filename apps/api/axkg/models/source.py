"""sources — Source Inbox 상태 SoT (AXKG-SPEC-003). soft delete, metadata.slack_events 규약."""
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from axkg.models.base import JSONB, Base, created_at_col, updated_at_col, uuid_pk
from axkg.models.enums import DESTINATION_TYPE, SOURCE_CHANNEL, SOURCE_STATUS, check_in


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        sa.CheckConstraint(check_in("status", SOURCE_STATUS), name="ck_sources_status"),
        sa.CheckConstraint(
            check_in("source_channel", SOURCE_CHANNEL), name="ck_sources_source_channel"
        ),
        sa.CheckConstraint(
            check_in("destination_type", DESTINATION_TYPE),
            name="ck_sources_destination_type",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_url: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    normalized_url: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_channel: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id"))
    submitted_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    raw_text: Mapped[str | None] = mapped_column(sa.Text())
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    visible_in_inbox: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=True)
    summary_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    destination_type: Mapped[str | None] = mapped_column(sa.Text())
    # 순환 FK 회피: FK 제약은 마이그레이션 step 7(approval_gates 생성 후)에서 추가.
    approved_classification_gate_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    approved_documentation_gate_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    documented_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
