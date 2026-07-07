"""step 5: ai_task_definitions."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_task_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("handler_kind", sa.Text(), nullable=False),
        sa.Column("prompt_key", sa.Text(), nullable=False),
        sa.Column("template_key", sa.Text(), nullable=True),
        sa.Column("default_provider", sa.Text(), nullable=True),
        sa.Column("default_model", sa.Text(), nullable=True),
        sa.Column("default_options", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("default_provider_options", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "handler_kind in ('source_summary', 'classification_gate', 'documentation_gate', 'graph_rag_chat')",
            name="ck_ai_task_definitions_handler_kind",
        ),
        sa.CheckConstraint(
            "default_provider in ('claude', 'codex')",
            name="ck_ai_task_definitions_default_provider",
        ),
    )
    op.create_index(
        "ix_ai_task_definitions_enabled_handler_kind",
        "ai_task_definitions",
        ["enabled", "handler_kind"],
    )
    op.create_index("ix_ai_task_definitions_prompt_key", "ai_task_definitions", ["prompt_key"])


def downgrade() -> None:
    op.drop_table("ai_task_definitions")
