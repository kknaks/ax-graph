"""document_templates / document_template_versions — 문서 템플릿 관리 (AXKG-SPEC-010)."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from axkg.models.base import Base, created_at_col, updated_at_col, uuid_pk


class DocumentTemplate(Base):
    __tablename__ = "document_templates"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(sa.Text(), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    # 순환 FK 회피: FK 제약은 마이그레이션에서 versions 생성 후 추가.
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class DocumentTemplateVersion(Base):
    __tablename__ = "document_template_versions"
    __table_args__ = (
        sa.UniqueConstraint(
            "template_id", "version", name="uq_document_template_versions_template_id_version"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    template_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("document_templates.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()
