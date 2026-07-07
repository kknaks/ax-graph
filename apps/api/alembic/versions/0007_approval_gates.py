"""step 7: approval_gates (+ sources의 승인 게이트 FK 추가).

active_revision_id/approved_revision_id/last_ai_task_id FK는 step 10에서 추가.
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

APPROVAL_GATE_STATUS = (
    "not_started", "generating", "review_pending", "feedback_pending",
    "regenerating", "approved", "failed", "cancelled",
)


def upgrade() -> None:
    op.create_table(
        "approval_gates",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id", name="fk_approval_gates_source_id"), nullable=False),
        sa.Column("gate_kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("active_revision_id", sa.Uuid(), nullable=True),
        sa.Column("approved_revision_id", sa.Uuid(), nullable=True),
        sa.Column("last_ai_task_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("source_id", "gate_kind", name="uq_approval_gates_source_id_gate_kind"),
        sa.CheckConstraint(
            "gate_kind in ('classification', 'documentation')", name="ck_approval_gates_gate_kind"
        ),
        sa.CheckConstraint(
            "status in ({})".format(", ".join(f"'{v}'" for v in APPROVAL_GATE_STATUS)),
            name="ck_approval_gates_status",
        ),
    )
    op.create_index("ix_approval_gates_status_gate_kind", "approval_gates", ["status", "gate_kind"])
    op.create_index("ix_approval_gates_active_revision_id", "approval_gates", ["active_revision_id"])
    op.create_index("ix_approval_gates_approved_revision_id", "approval_gates", ["approved_revision_id"])

    op.create_foreign_key(
        "fk_sources_approved_classification_gate_id", "sources", "approval_gates",
        ["approved_classification_gate_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_sources_approved_documentation_gate_id", "sources", "approval_gates",
        ["approved_documentation_gate_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_sources_approved_documentation_gate_id", "sources", type_="foreignkey")
    op.drop_constraint("fk_sources_approved_classification_gate_id", "sources", type_="foreignkey")
    op.drop_table("approval_gates")
