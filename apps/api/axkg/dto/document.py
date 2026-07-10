"""document / document_edge 내부 DTO (AXKG-SPEC-005). 서비스 계층 입출력 전용."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocumentDTO(BaseModel):
    """documents index row 스냅샷 — Markdown이 body SoT, 이건 조회 캐시."""

    id: uuid.UUID
    path: str
    stem: str
    document_type: str
    title: str
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_url: str | None = None
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    content_hash: str
    indexed_at: datetime
    # 확정 문서 lifecycle (SPEC-004 / DEC-005 D). current/superseded, 버전, producing 링크.
    status: str = "current"
    version: int = 1
    producing_revision_id: uuid.UUID | None = None
    source_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class DocumentStaleMarkDTO(BaseModel):
    """document_stale_marks row 스냅샷 (SPEC-004 §E).

    stale 대상 permanent(document_id)에, 유발 concept(concept_stem/path)와 변경 요지
    (change_summary)를 담는다. 영향 가능성 표시일 뿐 "수정 필요" 판단이 아니다(E-1).
    """

    id: uuid.UUID
    document_id: uuid.UUID
    concept_stem: str
    concept_path: str | None = None
    change_summary: str | None = None
    triggering_revision_id: uuid.UUID | None = None
    status: str = "active"
    marked_at: datetime
    dismissed_at: datetime | None = None


class DocumentEdgeDTO(BaseModel):
    """document_edges row 스냅샷 — rebuildable graph cache.

    from_document_id가 엣지를 소유한 문서(엣지 단일 소스=그 문서의 Markdown)다.
    lineage(source_syntax=up)는 to_document가 upstream, from_document가 current(방향
    upstream→current)라는 의미 오버레이다. assoc(source_syntax=wikilink)는 방향 없음.
    """

    id: uuid.UUID
    from_document_id: uuid.UUID
    to_document_id: uuid.UUID | None = None
    to_target: str
    edge_type: str
    source_syntax: str
    label: str | None = None
    is_broken: bool = False
    created_at: datetime
    updated_at: datetime
