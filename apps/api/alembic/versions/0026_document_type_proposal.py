"""step 26: documents.document_type 확장(proposal) — 회사 제안서 층.

회사 프로젝트에 고객 제시용 제안서 `projects/{corp}/proposal/{문서}.md`(document_type
`proposal`)를 그래프 노드로 인덱싱하기 위해 CHECK를 확장한다. 기존 계층(origin→baseline→
spec)은 전부 "고객이 요구한 것"이라, 우리가 제안하는 해결책·로드맵을 담을 자리가 없었다.

구현 상세 스펙 층(`projects/{corp}/work/`)은 이미 CHECK에 있는 `work` 값을 재사용하므로
이 마이그레이션 대상이 아니다. 신규 컬럼·데이터 마이그레이션 없음(값 목록 확장만).
"""
from alembic import op

revision = "0026"
down_revision = "0025"
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
    "proposal",
    "decision",
    "spec",
    "work",
    "source",
)
_OLD_DOCUMENT_TYPE = tuple(v for v in DOCUMENT_TYPE if v != "proposal")


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
