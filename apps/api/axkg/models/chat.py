"""graph_chat_sessions / graph_chat_messages / graph_chat_runs — Graph Chat (AXKG-SPEC-006).

run은 assistant 응답 생성 1회 시도. FE는 run status를 폴링한다.
"""
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from axkg.models.base import JSONB, Base, created_at_col, updated_at_col, uuid_pk
from axkg.models.enums import (
    CHAT_MESSAGE_ROLE,
    CHAT_RUN_STATUS,
    CHAT_SESSION_STATUS,
    check_in,
)


class GraphChatSession(Base):
    __tablename__ = "graph_chat_sessions"
    __table_args__ = (
        sa.CheckConstraint(
            check_in("status", CHAT_SESSION_STATUS), name="ck_graph_chat_sessions_status"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="active")
    selected_document_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("documents.id")
    )
    last_open_kknaks_session_id: Mapped[str | None] = mapped_column(sa.Text())
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    last_message_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class GraphChatMessage(Base):
    __tablename__ = "graph_chat_messages"
    __table_args__ = (
        sa.UniqueConstraint(
            "session_id", "sequence_no", name="uq_graph_chat_messages_session_id_sequence_no"
        ),
        sa.CheckConstraint(
            check_in("role", CHAT_MESSAGE_ROLE), name="ck_graph_chat_messages_role"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("graph_chat_sessions.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    content: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    sequence_no: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    # 순환 FK 회피(messages↔runs): FK 제약은 마이그레이션 step 13에서 runs 생성 후 추가.
    run_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    selected_document_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("documents.id")
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = created_at_col()


class GraphChatRun(Base):
    __tablename__ = "graph_chat_runs"
    __table_args__ = (
        sa.CheckConstraint(check_in("status", CHAT_RUN_STATUS), name="ck_graph_chat_runs_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("graph_chat_sessions.id"), nullable=False
    )
    user_message_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("graph_chat_messages.id"), nullable=False
    )
    assistant_message_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("graph_chat_messages.id")
    )
    ai_task_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("ai_tasks.id"))
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    open_kknaks_session_id: Mapped[str | None] = mapped_column(sa.Text())
    selected_document_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("documents.id")
    )
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    retrieval_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(sa.Text())
    error_message: Mapped[str | None] = mapped_column(sa.Text())
    queued_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
