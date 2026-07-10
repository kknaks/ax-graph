"""step 18: document_stale_marks (PLAN-009-T-030).

concept 개정 → 그 concept를 `[[ ]]`로 참조하는 permanent에 붙는 stale 배지
(AXKG-SPEC-004 Document Lifecycle §E / DEC-005 E). backlink 감지 결과만 저장하며,
어떤 자동 실행도 트리거하지 않는다. (document_id, concept_stem)당 한 행을 유지한다.
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

STALE_MARK_STATUS = ("active", "dismissed")


def upgrade() -> None:
    op.create_table(
        "document_stale_marks",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", name="fk_document_stale_marks_document_id"),
            nullable=False,
        ),
        sa.Column("concept_stem", sa.Text(), nullable=False),
        sa.Column("concept_path", sa.Text(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("triggering_revision_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "document_id", "concept_stem", name="uq_document_stale_marks_document_concept"
        ),
        sa.CheckConstraint(
            "status in ({})".format(", ".join(f"'{v}'" for v in STALE_MARK_STATUS)),
            name="ck_document_stale_marks_status",
        ),
    )
    op.create_index(
        "ix_document_stale_marks_status",
        "document_stale_marks",
        ["status"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_document_stale_marks_document_id",
        "document_stale_marks",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_stale_marks_document_id", table_name="document_stale_marks")
    op.drop_index("ix_document_stale_marks_status", table_name="document_stale_marks")
    op.drop_table("document_stale_marks")
