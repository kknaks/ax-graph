"""step 15: Initial Seeds — seed user / ai_provider settings / prompts / templates / task definitions.

seed 본문은 axkg.seeds가 SSOT (idempotent, 테스트와 공유).
"""
import sqlalchemy as sa
from alembic import op

from axkg import seeds
from axkg.models import (
    AiTaskDefinition,
    AuthToken,
    DocumentTemplate,
    DocumentTemplateVersion,
    Prompt,
    PromptVersion,
    Setting,
    User,
)

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    seeds.seed_all(op.get_bind())


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.delete(AiTaskDefinition).where(
            AiTaskDefinition.key.in_([d["key"] for d in seeds.TASK_DEFINITION_SEEDS])
        )
    )

    template_keys = [t["key"] for t in seeds.TEMPLATE_SEEDS]
    conn.execute(
        sa.update(DocumentTemplate)
        .where(DocumentTemplate.key.in_(template_keys))
        .values(active_version_id=None)
    )
    conn.execute(
        sa.delete(DocumentTemplateVersion).where(
            DocumentTemplateVersion.template_id.in_(
                sa.select(DocumentTemplate.id).where(DocumentTemplate.key.in_(template_keys))
            )
        )
    )
    conn.execute(sa.delete(DocumentTemplate).where(DocumentTemplate.key.in_(template_keys)))

    prompt_keys = [p["key"] for p in seeds.PROMPT_SEEDS]
    conn.execute(
        sa.update(Prompt).where(Prompt.key.in_(prompt_keys)).values(active_version_id=None)
    )
    conn.execute(
        sa.delete(PromptVersion).where(
            PromptVersion.prompt_id.in_(
                sa.select(Prompt.id).where(Prompt.key.in_(prompt_keys))
            )
        )
    )
    conn.execute(sa.delete(Prompt).where(Prompt.key.in_(prompt_keys)))

    conn.execute(sa.delete(Setting).where(Setting.key == "ai_provider"))
    conn.execute(
        sa.delete(AuthToken).where(
            AuthToken.user_id.in_(
                sa.select(User.id).where(User.email == seeds.SEED_USER_EMAIL)
            )
        )
    )
    conn.execute(sa.delete(User).where(User.email == seeds.SEED_USER_EMAIL))


