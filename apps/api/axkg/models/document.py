"""documents / document_edges — 문서 인덱스·그래프 캐시 (AXKG-SPEC-005).

Markdown이 body SoT, document_edges는 rebuildable cache.
"""
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from axkg.models.base import JSONB, TEXT_ARRAY, Base, created_at_col, updated_at_col, uuid_pk
from axkg.models.enums import DOCUMENT_TYPE, EDGE_SOURCE_SYNTAX, EDGE_TYPE, check_in


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        sa.CheckConstraint(
            check_in("document_type", DOCUMENT_TYPE), name="ck_documents_document_type"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    path: Mapped[str] = mapped_column(sa.Text(), unique=True, nullable=False)
    stem: Mapped[str] = mapped_column(sa.Text(), unique=True, nullable=False)
    document_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    title: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    source_url: Mapped[str | None] = mapped_column(sa.Text())
    frontmatter: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class DocumentEdge(Base):
    __tablename__ = "document_edges"
    __table_args__ = (
        sa.UniqueConstraint(
            "from_document_id",
            "to_target",
            "edge_type",
            "source_syntax",
            name="uq_document_edges_from_target_type_syntax",
        ),
        sa.CheckConstraint(check_in("edge_type", EDGE_TYPE), name="ck_document_edges_edge_type"),
        sa.CheckConstraint(
            check_in("source_syntax", EDGE_SOURCE_SYNTAX),
            name="ck_document_edges_source_syntax",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    from_document_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("documents.id"), nullable=False
    )
    to_document_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("documents.id")
    )
    to_target: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    edge_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_syntax: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    label: Mapped[str | None] = mapped_column(sa.Text())
    is_broken: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
