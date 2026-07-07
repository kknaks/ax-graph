"""step 8: gate_feedback. target_revision_id FK는 step 10에서 추가 (revisions가 step 9)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gate_feedback",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("gate_id", sa.Uuid(), sa.ForeignKey("approval_gates.id", name="fk_gate_feedback_gate_id"), nullable=False),
        sa.Column("target_revision_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("quick_options", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'submitted'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('submitted', 'consumed', 'cancelled')", name="ck_gate_feedback_status"
        ),
    )
    op.create_index(
        "ix_gate_feedback_gate_id_created_at",
        "gate_feedback",
        ["gate_id", sa.text("created_at desc")],
    )
    op.create_index("ix_gate_feedback_target_revision_id", "gate_feedback", ["target_revision_id"])


def downgrade() -> None:
    op.drop_table("gate_feedback")
