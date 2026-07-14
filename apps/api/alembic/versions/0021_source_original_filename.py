"""step 21: sources.original_filename (PLAN-013-T-009, WORK-010).

md 업로드 intake(`source_channel=upload`)의 업로드 원본 파일명을 보존한다. 다른 채널이면
null이다(AXKG-SPEC-003 Data Contract). source_channel의 `upload` 값 자체는 0020(PLAN-013-T-008)에서
이미 추가됐다 — 이 마이그는 필드만 더한다.
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("original_filename", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "original_filename")
