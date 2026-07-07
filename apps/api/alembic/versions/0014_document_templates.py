"""step 14: document_templates, document_template_versions (+ ai_tasks.template_version_id FK 마감)."""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_templates",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("active_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "document_template_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("template_id", sa.Uuid(), sa.ForeignKey("document_templates.id", name="fk_document_template_versions_template_id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", name="fk_document_template_versions_created_by"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "template_id", "version", name="uq_document_template_versions_template_id_version"
        ),
    )
    op.create_foreign_key(
        "fk_document_templates_active_version_id", "document_templates",
        "document_template_versions", ["active_version_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_ai_tasks_template_version_id", "ai_tasks", "document_template_versions",
        ["template_version_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_ai_tasks_template_version_id", "ai_tasks", type_="foreignkey")
    op.drop_constraint("fk_document_templates_active_version_id", "document_templates", type_="foreignkey")
    op.drop_table("document_template_versions")
    op.drop_table("document_templates")
