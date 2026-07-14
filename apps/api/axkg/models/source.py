"""sources — Source Inbox 상태 SoT (AXKG-SPEC-003). soft delete, metadata.slack_events 규약."""
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from axkg.models.base import JSONB, Base, created_at_col, updated_at_col, uuid_pk
from axkg.models.enums import (
    DESTINATION_TYPE,
    SOURCE_CHANNEL,
    SOURCE_STATUS,
    SUMMARY_REVISION_STATUS,
    check_in,
)


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
    # chat(대화 push)·upload(md 업로드) source는 URL이 없어 null이다 (AXKG-SPEC-003
    # Data Contract, WORK-009/010). slack/manual은 항상 값이 있다.
    source_url: Mapped[str | None] = mapped_column(sa.Text())
    normalized_url: Mapped[str | None] = mapped_column(sa.Text())
    source_channel: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id"))
    submitted_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    raw_text: Mapped[str | None] = mapped_column(sa.Text())
    # source_channel=upload의 업로드 원본 파일명 보존. 다른 채널이면 null (AXKG-SPEC-003
    # Data Contract, WORK-010).
    original_filename: Mapped[str | None] = mapped_column(sa.Text())
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    visible_in_inbox: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=True)
    summary_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # 현재 active 요약 draft 버전(source_summary_revisions.id) 포인터 (SPEC-002/003 C, T-012).
    # summary_payload는 이 active 버전 payload의 비정규 미러(FE 소비용). 버전 이력의 SoT는
    # source_summary_revisions 테이블(immutable 박제). 순환 FK 회피로 제약은 마이그레이션에서.
    active_summary_revision_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
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


class SourceSummaryRevision(Base):
    """요약 draft 버전 박제 (AXKG-SPEC-002/003 C, DEC-005 C).

    게이트 revision(`approval_gate_revisions`)과 **same-format**인 immutable 버전 체인이다.
    피드백 재요약은 직전 버전을 덮어쓰지 않고 새 버전을 append하며, 직전 버전은
    `superseded`로 read-only 보존한다(비덮어쓰기·v1 보존). 요약은 게이트가 아니므로
    approve/lock 상태 기계는 없고 status는 reviewable(active)·superseded 뿐이다.
    active 포인터는 `sources.active_summary_revision_id`가 보유한다.
    """

    __tablename__ = "source_summary_revisions"
    __table_args__ = (
        sa.UniqueConstraint(
            "source_id", "version", name="uq_source_summary_revisions_source_id_version"
        ),
        sa.CheckConstraint(
            check_in("status", SUMMARY_REVISION_STATUS),
            name="ck_source_summary_revisions_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("sources.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("source_summary_revisions.id")
    )
    ai_task_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("ai_tasks.id"))
    open_kknaks_session_id: Mapped[str | None] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = created_at_col()
