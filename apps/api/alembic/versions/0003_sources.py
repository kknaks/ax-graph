"""step 3: sources.

approved_classification_gate_id / approved_documentation_gate_id FK는
approval_gates 생성 후 step 7에서 추가한다 (순환 FK 회피).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SOURCE_STATUS = (
    "received", "summarizing", "summarized", "collection_failed",
    "ignored", "documented", "archived", "deleted",
)


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("source_channel", sa.Text(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), sa.ForeignKey("users.id", name="fk_sources_submitted_by"), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("visible_in_inbox", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("summary_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("destination_type", sa.Text(), nullable=True),
        sa.Column("approved_classification_gate_id", sa.Uuid(), nullable=True),
        sa.Column("approved_documentation_gate_id", sa.Uuid(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("documented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status in ({})".format(", ".join(f"'{v}'" for v in SOURCE_STATUS)),
            name="ck_sources_status",
        ),
        sa.CheckConstraint("source_channel in ('slack', 'manual')", name="ck_sources_source_channel"),
        sa.CheckConstraint(
            "destination_type in ('project', 'area', 'resource', 'archive')",
            name="ck_sources_destination_type",
        ),
    )
    op.create_index(
        "uq_sources_normalized_url_active",
        "sources",
        ["normalized_url"],
        unique=True,
        postgresql_where=sa.text("deleted_at is null"),
    )
    op.create_index(
        "ix_sources_status_visible_submitted",
        "sources",
        ["status", "visible_in_inbox", sa.text("submitted_at desc")],
    )
    op.create_index("ix_sources_destination_type", "sources", ["destination_type"])


def downgrade() -> None:
    op.drop_table("sources")
