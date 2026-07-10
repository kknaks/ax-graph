"""step 16: source_summary_revisions + document lifecycle (PLAN-009-T-012).

버전 박제 통일 (AXKG-SPEC-002/003 C · SPEC-004 Document Lifecycle · SPEC-005 · DEC-005 C/D):
- source_summary_revisions: 요약 draft 버전을 게이트 revision과 same-format으로 별도 테이블에
  immutable 박제(SPEC-003 §7 OQ (나) 별도 테이블로 확정).
- sources.active_summary_revision_id: 현재 active 요약 버전 포인터(순환 FK 회피로 제약 없음).
- documents.status/version/producing_revision_id/source_id: 확정 문서 lifecycle
  (current/superseded 박제 보존, 재문서화 supersede/version++).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

SUMMARY_REVISION_STATUS = ("reviewable", "superseded")
DOCUMENT_STATUS = ("current", "superseded")


def upgrade() -> None:
    # 1) 요약 draft 버전 박제 테이블 (approval_gate_revisions 미러).
    op.create_table(
        "source_summary_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id", name="fk_source_summary_revisions_source_id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parent_revision_id", sa.Uuid(), sa.ForeignKey("source_summary_revisions.id", name="fk_source_summary_revisions_parent_revision_id"), nullable=True),
        sa.Column("ai_task_id", sa.Uuid(), sa.ForeignKey("ai_tasks.id", name="fk_source_summary_revisions_ai_task_id"), nullable=True),
        sa.Column("open_kknaks_session_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("source_id", "version", name="uq_source_summary_revisions_source_id_version"),
        sa.CheckConstraint(
            "status in ({})".format(", ".join(f"'{v}'" for v in SUMMARY_REVISION_STATUS)),
            name="ck_source_summary_revisions_status",
        ),
    )
    op.create_index(
        "ix_source_summary_revisions_source_id_status_version",
        "source_summary_revisions",
        ["source_id", "status", sa.text("version desc")],
    )
    op.create_index("ix_source_summary_revisions_ai_task_id", "source_summary_revisions", ["ai_task_id"])

    # 2) sources active 요약 버전 포인터 (순환 FK 회피로 제약 없이 컬럼만).
    op.add_column("sources", sa.Column("active_summary_revision_id", sa.Uuid(), nullable=True))

    # 3) documents lifecycle 컬럼 (current/superseded + version + producing 링크).
    op.add_column(
        "documents",
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'current'")),
    )
    op.add_column(
        "documents",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("documents", sa.Column("producing_revision_id", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("source_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        "ck_documents_status",
        "documents",
        "status in ({})".format(", ".join(f"'{v}'" for v in DOCUMENT_STATUS)),
    )
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index(
        "ix_documents_source_id_status",
        "documents",
        ["source_id", "status"],
        postgresql_where=sa.text("source_id is not null"),
    )


def downgrade() -> None:
    op.drop_index("ix_documents_source_id_status", table_name="documents")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_constraint("ck_documents_status", "documents", type_="check")
    op.drop_column("documents", "source_id")
    op.drop_column("documents", "producing_revision_id")
    op.drop_column("documents", "version")
    op.drop_column("documents", "status")

    op.drop_column("sources", "active_summary_revision_id")

    op.drop_index("ix_source_summary_revisions_ai_task_id", table_name="source_summary_revisions")
    op.drop_index(
        "ix_source_summary_revisions_source_id_status_version",
        table_name="source_summary_revisions",
    )
    op.drop_table("source_summary_revisions")
