"""step 6: ai_tasks.

gate_id/revision_id FK는 step 10, template_version_id FK는 step 14에서 추가한다
(approval_gates(7)/revisions(9)/document_template_versions(14)가 나중에 생성되므로).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

AI_TASK_TYPE = (
    "collect_source_summary",
    "generate_classification_gate",
    "regenerate_classification_gate",
    "generate_documentation_gate",
    "regenerate_documentation_gate",
    "graph_rag_chat",
)


def upgrade() -> None:
    op.create_table(
        "ai_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("task_definition_id", sa.Uuid(), sa.ForeignKey("ai_task_definitions.id", name="fk_ai_tasks_task_definition_id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id", name="fk_ai_tasks_source_id"), nullable=True),
        sa.Column("gate_id", sa.Uuid(), nullable=True),
        sa.Column("revision_id", sa.Uuid(), nullable=True),
        sa.Column("retry_of_task_id", sa.Uuid(), sa.ForeignKey("ai_tasks.id", name="fk_ai_tasks_retry_of_task_id"), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("provider_options", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("open_kknaks_task_id", sa.Text(), nullable=True),
        sa.Column("open_kknaks_session_id", sa.Text(), nullable=True),
        sa.Column("prompt_version_id", sa.Uuid(), sa.ForeignKey("prompt_versions.id", name="fk_ai_tasks_prompt_version_id"), nullable=True),
        sa.Column("template_version_id", sa.Uuid(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_ai_tasks_status",
        ),
        sa.CheckConstraint(
            "task_type in ({})".format(", ".join(f"'{v}'" for v in AI_TASK_TYPE)),
            name="ck_ai_tasks_task_type",
        ),
        sa.CheckConstraint("provider in ('claude', 'codex')", name="ck_ai_tasks_provider"),
    )
    op.create_index("ix_ai_tasks_status_queued_at", "ai_tasks", ["status", "queued_at"])
    op.create_index("ix_ai_tasks_task_type_status", "ai_tasks", ["task_type", "status"])
    op.create_index(
        "ix_ai_tasks_task_definition_id_created_at",
        "ai_tasks",
        ["task_definition_id", sa.text("created_at desc")],
    )
    op.create_index("ix_ai_tasks_prompt_version_id", "ai_tasks", ["prompt_version_id"])
    op.create_index("ix_ai_tasks_template_version_id", "ai_tasks", ["template_version_id"])
    op.create_index(
        "ix_ai_tasks_source_id_created_at", "ai_tasks", ["source_id", sa.text("created_at desc")]
    )
    op.create_index(
        "ix_ai_tasks_gate_id_created_at", "ai_tasks", ["gate_id", sa.text("created_at desc")]
    )
    op.create_index("ix_ai_tasks_retry_of_task_id", "ai_tasks", ["retry_of_task_id"])
    op.create_index(
        "uq_ai_tasks_open_kknaks_task_id",
        "ai_tasks",
        ["open_kknaks_task_id"],
        unique=True,
        postgresql_where=sa.text("open_kknaks_task_id is not null"),
    )
    op.create_index(
        "ix_ai_tasks_open_kknaks_session_id",
        "ai_tasks",
        ["open_kknaks_session_id"],
        postgresql_where=sa.text("open_kknaks_session_id is not null"),
    )


def downgrade() -> None:
    op.drop_table("ai_tasks")
