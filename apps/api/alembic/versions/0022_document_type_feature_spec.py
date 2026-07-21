"""step 22: documents.document_type 확장(feature_spec) — 회사 프로젝트 팬아웃 (WP11 Phase 3).

기업 프로젝트 팬아웃(AXKG-SPEC-014/010)의 기능정의서(`projects/{corp}/spec/`)는 document_type
`feature_spec`으로 확정 문서화된다(원본요약은 기존 `baseline`). documents.document_type CHECK를
`feature_spec` 포함으로 확장한다. 신규 컬럼·데이터 마이그레이션은 없다(값 목록 확장만).
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

DOCUMENT_TYPE = (
    "reference",
    "permanent",
    "concept",
    "baseline",
    "feature_spec",
    "decision",
    "spec",
    "work",
    "source",
)
_OLD_DOCUMENT_TYPE = (
    "reference",
    "permanent",
    "concept",
    "baseline",
    "decision",
    "spec",
    "work",
    "source",
)


def _check(values: tuple[str, ...]) -> str:
    return "document_type in ({})".format(", ".join(f"'{v}'" for v in values))


def upgrade() -> None:
    op.drop_constraint("ck_documents_document_type", "documents", type_="check")
    op.create_check_constraint("ck_documents_document_type", "documents", _check(DOCUMENT_TYPE))


def downgrade() -> None:
    op.drop_constraint("ck_documents_document_type", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_document_type", "documents", _check(_OLD_DOCUMENT_TYPE)
    )
