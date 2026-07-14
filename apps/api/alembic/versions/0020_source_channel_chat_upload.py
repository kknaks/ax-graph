"""step 20: source_channel 확장(chat·upload) + URL nullable (PLAN-013-T-008, WORK-009/010).

채팅④ 방안 push(`chat`)와 md 업로드 intake(`upload`)를 위해 source_channel CHECK를 4값으로
확장하고(WORK-009·WORK-010 중복 마이그레이션 방지로 한 번에 추가), URL이 없는 이 두 채널을
위해 `source_url`·`normalized_url`을 nullable로 완화한다. NULL은 partial unique index
`uq_sources_normalized_url_active`에서 서로 distinct하게 취급되어 다건 공존이 가능하다
(AXKG-SPEC-003 Data Contract: chat·upload은 source_url=null). original_filename(upload 전용)은
WORK-010 BE(PLAN-013-T-009)에서 별도로 추가한다.
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

SOURCE_CHANNEL = ("slack", "manual", "chat", "upload")
_OLD_SOURCE_CHANNEL = ("slack", "manual")


def upgrade() -> None:
    # source_channel: slack/manual → +chat/upload.
    op.drop_constraint("ck_sources_source_channel", "sources", type_="check")
    op.create_check_constraint(
        "ck_sources_source_channel",
        "sources",
        "source_channel in ({})".format(", ".join(f"'{v}'" for v in SOURCE_CHANNEL)),
    )
    # chat·upload source는 URL이 없다 → nullable로 완화.
    op.alter_column("sources", "source_url", existing_type=sa.Text(), nullable=True)
    op.alter_column("sources", "normalized_url", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("sources", "normalized_url", existing_type=sa.Text(), nullable=False)
    op.alter_column("sources", "source_url", existing_type=sa.Text(), nullable=False)
    op.drop_constraint("ck_sources_source_channel", "sources", type_="check")
    op.create_check_constraint(
        "ck_sources_source_channel",
        "sources",
        "source_channel in ({})".format(", ".join(f"'{v}'" for v in _OLD_SOURCE_CHANNEL)),
    )
