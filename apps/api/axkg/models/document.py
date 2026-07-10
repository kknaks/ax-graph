"""documents / document_edges — 문서 인덱스·그래프 캐시 (AXKG-SPEC-005).

Markdown이 body SoT, document_edges는 rebuildable cache.
"""
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from axkg.models.base import (
    JSONB,
    TEXT_ARRAY,
    Base,
    created_at_col,
    updated_at_col,
    utcnow,
    uuid_pk,
)
from axkg.models.enums import (
    DOCUMENT_STATUS,
    DOCUMENT_TYPE,
    EDGE_SOURCE_SYNTAX,
    EDGE_TYPE,
    STALE_MARK_STATUS,
    check_in,
)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        sa.CheckConstraint(
            check_in("document_type", DOCUMENT_TYPE), name="ck_documents_document_type"
        ),
        sa.CheckConstraint(
            check_in("status", DOCUMENT_STATUS), name="ck_documents_status"
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
    # 확정 문서 lifecycle (SPEC-004 Document Lifecycle / SPEC-005 / DEC-005 D, T-012).
    # current=최신 유효본 / superseded=옛 버전 박제 보존(그래프 기본 노출 제외). 재문서화 apply가
    # 같은 source 계보의 옛 문서를 superseded로 마킹하고 새 문서를 current로 세운다.
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="current")
    version: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=1)
    # 이 문서를 산출한 문서화 게이트 revision / source (producing 링크). 순환 FK 회피로 제약은
    # 마이그레이션에서 추가하지 않고 컬럼만 둔다(approved_classification_gate_id와 동일 관례).
    producing_revision_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    source_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
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


class DocumentStaleMark(Base):
    """concept 개정 → 그 concept를 `[[ ]]`로 참조하는 permanent에 붙는 stale 배지
    (AXKG-SPEC-004 Document Lifecycle §E / DEC-005 E).

    "영향 가능성 있음" 표시일 뿐 "수정 필요" 판단이 아니다(E-1). backlink 쿼리로 감지하며
    (E-2, AI 없음), 어떤 자동 실행도 트리거하지 않는다. (document_id, concept_stem)당 한 행을
    유지해 재감지 시 in-place 갱신하고, 배지 해제/재생성 승인 반영 시 dismissed로 내린다.
    """

    __tablename__ = "document_stale_marks"
    __table_args__ = (
        sa.UniqueConstraint(
            "document_id",
            "concept_stem",
            name="uq_document_stale_marks_document_concept",
        ),
        sa.CheckConstraint(
            check_in("status", STALE_MARK_STATUS),
            name="ck_document_stale_marks_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # stale 대상(영향 가능성 있는 permanent 종합 노트).
    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("documents.id"), nullable=False
    )
    # stale을 유발한 concept — stem(그래프 식별자)과 경로.
    concept_stem: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    concept_path: Mapped[str | None] = mapped_column(sa.Text())
    # concept 변경 요지(유발 supplement suggestion의 diff_preview 재사용, E-2 배지 동봉).
    change_summary: Mapped[str | None] = mapped_column(sa.Text())
    # 유발 문서화 게이트 revision(어느 concept 개정이 이 배지를 붙였는지 추적).
    triggering_revision_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="active")
    marked_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
