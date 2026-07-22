"""step 24: documents.document_type 확장(company, context) — 회사 루트 + context 층 (WORK-013).

회사 루트 앵커 `projects/{corp}/{corp}.md`(document_type `company`)와 회사 배경지식 단일 문서
`projects/{corp}/context/{문서}.md`(document_type `context`)를 그래프 노드로 인덱싱하기 위해
documents.document_type CHECK를 두 값 포함으로 확장한다(AXKG-DEC-009). 신규 컬럼·데이터
마이그레이션 없음(값 목록 확장만). 팬아웃 결과 계약(baseline/feature_spec)은 불변.
"""
import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

DOCUMENT_TYPE = (
    "reference",
    "permanent",
    "concept",
    "baseline",
    "feature_spec",
    "company",
    "context",
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
    "feature_spec",
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
