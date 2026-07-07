"""step 11: drafts, apply_plans."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drafts",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id", name="fk_drafts_source_id"), nullable=True),
        sa.Column("gate_revision_id", sa.Uuid(), sa.ForeignKey("approval_gate_revisions.id", name="fk_drafts_gate_revision_id"), nullable=False),
        sa.Column("draft_type", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("filename_candidate", sa.Text(), nullable=True),
        sa.Column("target_path", sa.Text(), nullable=True),
        sa.Column("change_kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "draft_type in ('main_document', 'derived_suggestion')", name="ck_drafts_draft_type"
        ),
        sa.CheckConstraint("change_kind in ('create', 'modify')", name="ck_drafts_change_kind"),
    )
    op.create_index("ix_drafts_gate_revision_id_draft_type", "drafts", ["gate_revision_id", "draft_type"])
    op.create_index("ix_drafts_target_path", "drafts", ["target_path"])

    op.create_table(
        "apply_plans",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("gate_revision_id", sa.Uuid(), sa.ForeignKey("approval_gate_revisions.id", name="fk_apply_plans_gate_revision_id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("validation_status", sa.Text(), nullable=False),
        sa.Column("db_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("file_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("validation_errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("gate_revision_id", name="uq_apply_plans_gate_revision_id"),
        sa.CheckConstraint(
            "status in ('pending', 'valid', 'invalid', 'applying', 'applied', 'failed')",
            name="ck_apply_plans_status",
        ),
        sa.CheckConstraint(
            "validation_status in ('pending', 'valid', 'invalid')",
            name="ck_apply_plans_validation_status",
        ),
    )
    op.create_index("ix_apply_plans_status_validation_status", "apply_plans", ["status", "validation_status"])


def downgrade() -> None:
    op.drop_table("apply_plans")
    op.drop_table("drafts")
