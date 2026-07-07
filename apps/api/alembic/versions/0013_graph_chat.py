"""step 13: graph_chat_sessions, graph_chat_messages, graph_chat_runs.

messages↔runs의 nullable 순환: messages를 먼저 만들고(run_id FK 없이),
runs 생성 후 messages.run_id FK를 추가한다 (database README 규칙).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_chat_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", name="fk_graph_chat_sessions_user_id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("selected_document_id", sa.Uuid(), sa.ForeignKey("documents.id", name="fk_graph_chat_sessions_selected_document_id"), nullable=True),
        sa.Column("last_open_kknaks_session_id", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('active', 'archived', 'deleted')", name="ck_graph_chat_sessions_status"
        ),
    )
    op.create_index(
        "ix_graph_chat_sessions_user_status_last_message",
        "graph_chat_sessions",
        ["user_id", "status", sa.text("last_message_at desc")],
    )
    op.create_index(
        "ix_graph_chat_sessions_selected_document_id",
        "graph_chat_sessions",
        ["selected_document_id"],
    )
    op.create_index(
        "ix_graph_chat_sessions_last_open_kknaks_session_id",
        "graph_chat_sessions",
        ["last_open_kknaks_session_id"],
        postgresql_where=sa.text("last_open_kknaks_session_id is not null"),
    )

    op.create_table(
        "graph_chat_messages",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("graph_chat_sessions.id", name="fk_graph_chat_messages_session_id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("selected_document_id", sa.Uuid(), sa.ForeignKey("documents.id", name="fk_graph_chat_messages_selected_document_id"), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "session_id", "sequence_no", name="uq_graph_chat_messages_session_id_sequence_no"
        ),
        sa.CheckConstraint(
            "role in ('user', 'assistant', 'system')", name="ck_graph_chat_messages_role"
        ),
    )
    op.create_index(
        "ix_graph_chat_messages_session_id_created_at",
        "graph_chat_messages",
        ["session_id", "created_at"],
    )
    op.create_index("ix_graph_chat_messages_run_id", "graph_chat_messages", ["run_id"])

    op.create_table(
        "graph_chat_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("graph_chat_sessions.id", name="fk_graph_chat_runs_session_id"), nullable=False),
        sa.Column("user_message_id", sa.Uuid(), sa.ForeignKey("graph_chat_messages.id", name="fk_graph_chat_runs_user_message_id"), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), sa.ForeignKey("graph_chat_messages.id", name="fk_graph_chat_runs_assistant_message_id"), nullable=True),
        sa.Column("ai_task_id", sa.Uuid(), sa.ForeignKey("ai_tasks.id", name="fk_graph_chat_runs_ai_task_id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("open_kknaks_session_id", sa.Text(), nullable=True),
        sa.Column("selected_document_id", sa.Uuid(), sa.ForeignKey("documents.id", name="fk_graph_chat_runs_selected_document_id"), nullable=True),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("retrieval_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_graph_chat_runs_status",
        ),
    )
    op.create_index(
        "ix_graph_chat_runs_session_id_created_at",
        "graph_chat_runs",
        ["session_id", sa.text("created_at desc")],
    )
    op.create_index("ix_graph_chat_runs_status_queued_at", "graph_chat_runs", ["status", "queued_at"])
    op.create_index("ix_graph_chat_runs_ai_task_id", "graph_chat_runs", ["ai_task_id"])
    op.create_index(
        "ix_graph_chat_runs_open_kknaks_session_id",
        "graph_chat_runs",
        ["open_kknaks_session_id"],
        postgresql_where=sa.text("open_kknaks_session_id is not null"),
    )

    op.create_foreign_key(
        "fk_graph_chat_messages_run_id", "graph_chat_messages", "graph_chat_runs",
        ["run_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_graph_chat_messages_run_id", "graph_chat_messages", type_="foreignkey")
    op.drop_table("graph_chat_runs")
    op.drop_table("graph_chat_messages")
    op.drop_table("graph_chat_sessions")
