"""prompts / prompt_versions — 프롬프트 동적 관리 (AXKG-SPEC-009)."""
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from axkg.models.base import JSONB, Base, created_at_col, updated_at_col, uuid_pk


class Prompt(Base):
    __tablename__ = "prompts"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(sa.Text(), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text())
    # 순환 FK 회피: FK 제약은 마이그레이션에서 prompt_versions 생성 후 추가.
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        sa.UniqueConstraint("prompt_id", "version", name="uq_prompt_versions_prompt_id_version"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("prompts.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    prompt_text: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()
