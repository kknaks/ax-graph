"""step 19: users.role / users.is_active + 로스터 재시드 (AXKG-SPEC-008, WP6 BE-1).

역할 권한 경계(admin/staff)의 기반. 기존 행은 server_default(role='staff', is_active=true)로
backfill되고, seed_users가 활성 22명 로스터를 email 멱등으로 upsert한다
(기존 seed 계정 kknaks@medisolveai.com은 admin으로 흡수).
"""
import sqlalchemy as sa
from alembic import op

from axkg import seeds

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

ROLE_VALUES = ("admin", "staff")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role", sa.Text(), nullable=False, server_default=sa.text("'staff'")
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role in ({})".format(", ".join(f"'{v}'" for v in ROLE_VALUES)),
    )
    # 활성 로스터 upsert — kknaks를 admin으로 흡수하고 나머지 21명을 생성한다(멱등).
    seeds.seed_users(op.get_bind())


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")
