"""step 17: apply_plans.skipped (PLAN-009-T-016).

Apply Executor가 draft_markdown 없이 건너뛴 파생 제안을 apply_plans에 박제한다(관측성).
ApplyResult.skipped가 반환만 되고 증발하던 것을 감사 이력에 남긴다(SPEC-004).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "apply_plans",
        sa.Column(
            "skipped",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("apply_plans", "skipped")
