"""step 10: 순환 FK 마감 — approval_gates→revisions/tasks, gate_feedback→revisions, ai_tasks→gates/revisions."""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_approval_gates_active_revision_id", "approval_gates", "approval_gate_revisions",
        ["active_revision_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_approval_gates_approved_revision_id", "approval_gates", "approval_gate_revisions",
        ["approved_revision_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_approval_gates_last_ai_task_id", "approval_gates", "ai_tasks",
        ["last_ai_task_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_gate_feedback_target_revision_id", "gate_feedback", "approval_gate_revisions",
        ["target_revision_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_ai_tasks_gate_id", "ai_tasks", "approval_gates", ["gate_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_ai_tasks_revision_id", "ai_tasks", "approval_gate_revisions", ["revision_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_ai_tasks_revision_id", "ai_tasks", type_="foreignkey")
    op.drop_constraint("fk_ai_tasks_gate_id", "ai_tasks", type_="foreignkey")
    op.drop_constraint("fk_gate_feedback_target_revision_id", "gate_feedback", type_="foreignkey")
    op.drop_constraint("fk_approval_gates_last_ai_task_id", "approval_gates", type_="foreignkey")
    op.drop_constraint("fk_approval_gates_approved_revision_id", "approval_gates", type_="foreignkey")
    op.drop_constraint("fk_approval_gates_active_revision_id", "approval_gates", type_="foreignkey")
