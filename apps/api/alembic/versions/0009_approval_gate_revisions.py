"""step 9: approval_gate_revisions."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

APPROVAL_REVISION_STATUS = (
    "drafting", "reviewable", "approved", "superseded", "rejected", "failed",
)


def upgrade() -> None:
    op.create_table(
        "approval_gate_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("gate_id", sa.Uuid(), sa.ForeignKey("approval_gates.id", name="fk_approval_gate_revisions_gate_id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("form_schema_version", sa.Text(), nullable=False),
        sa.Column("parent_revision_id", sa.Uuid(), sa.ForeignKey("approval_gate_revisions.id", name="fk_approval_gate_revisions_parent_revision_id"), nullable=True),
        sa.Column("feedback_id", sa.Uuid(), sa.ForeignKey("gate_feedback.id", name="fk_approval_gate_revisions_feedback_id"), nullable=True),
        sa.Column("ai_task_id", sa.Uuid(), sa.ForeignKey("ai_tasks.id", name="fk_approval_gate_revisions_ai_task_id"), nullable=True),
        sa.Column("open_kknaks_session_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("gate_id", "version", name="uq_approval_gate_revisions_gate_id_version"),
        sa.CheckConstraint(
            "status in ({})".format(", ".join(f"'{v}'" for v in APPROVAL_REVISION_STATUS)),
            name="ck_approval_gate_revisions_status",
        ),
    )
    op.create_index(
        "ix_approval_gate_revisions_gate_id_status_version",
        "approval_gate_revisions",
        ["gate_id", "status", sa.text("version desc")],
    )
    op.create_index("ix_approval_gate_revisions_ai_task_id", "approval_gate_revisions", ["ai_task_id"])
    op.create_index(
        "ix_approval_gate_revisions_open_kknaks_session_id",
        "approval_gate_revisions",
        ["open_kknaks_session_id"],
        postgresql_where=sa.text("open_kknaks_session_id is not null"),
    )


def downgrade() -> None:
    op.drop_table("approval_gate_revisions")
