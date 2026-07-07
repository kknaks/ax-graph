"""step 12: documents, document_edges (graph cache)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

DOCUMENT_TYPE = (
    "reference", "permanent", "concept", "baseline", "decision", "spec", "work", "source",
)


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("path", sa.Text(), nullable=False, unique=True),
        sa.Column("stem", sa.Text(), nullable=False, unique=True),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("aliases", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("frontmatter", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "document_type in ({})".format(", ".join(f"'{v}'" for v in DOCUMENT_TYPE)),
            name="ck_documents_document_type",
        ),
    )
    op.create_index("ix_documents_aliases", "documents", ["aliases"], postgresql_using="gin")
    op.create_index("ix_documents_tags", "documents", ["tags"], postgresql_using="gin")
    op.create_index("ix_documents_document_type", "documents", ["document_type"])

    op.create_table(
        "document_edges",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("from_document_id", sa.Uuid(), sa.ForeignKey("documents.id", name="fk_document_edges_from_document_id"), nullable=False),
        sa.Column("to_document_id", sa.Uuid(), sa.ForeignKey("documents.id", name="fk_document_edges_to_document_id"), nullable=True),
        sa.Column("to_target", sa.Text(), nullable=False),
        sa.Column("edge_type", sa.Text(), nullable=False),
        sa.Column("source_syntax", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("is_broken", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "from_document_id", "to_target", "edge_type", "source_syntax",
            name="uq_document_edges_from_target_type_syntax",
        ),
        sa.CheckConstraint("edge_type in ('assoc', 'lineage')", name="ck_document_edges_edge_type"),
        sa.CheckConstraint(
            "source_syntax in ('wikilink', 'up')", name="ck_document_edges_source_syntax"
        ),
    )
    op.create_index("ix_document_edges_from_document_id", "document_edges", ["from_document_id"])
    op.create_index("ix_document_edges_to_document_id", "document_edges", ["to_document_id"])
    op.create_index("ix_document_edges_edge_type", "document_edges", ["edge_type"])
    op.create_index("ix_document_edges_is_broken", "document_edges", ["is_broken"])


def downgrade() -> None:
    op.drop_table("document_edges")
    op.drop_table("documents")
