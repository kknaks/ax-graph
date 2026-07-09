"""documents API 요청/응답 (AXKG-SPEC-005 Interface Contract).

FE Phase 4(그래프 뷰)가 이 계약을 소비한다 — 응답 스키마를 임의로 바꾸지 않는다.
- Document 조회: 인덱스 필드(본문 body는 Markdown SoT라 응답에 싣지 않는다).
- Links: wikilink(assoc out) / up(lineage out) / backlink(incoming) 3분할.
- Link Preview: 생성 경로 검증(BROKEN_WIKILINK/UP_WITHOUT_BODY_LINK/DUPLICATE_STEM).
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from axkg.dto.document import DocumentDTO
from axkg.services.documents import DocumentLinks, LinkView
from axkg.services.graph import LinkIssue, LinkPreview, LinkPreviewEntry


class DocumentResponse(BaseModel):
    id: uuid.UUID
    path: str
    stem: str
    document_type: str
    title: str
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_url: str | None = None
    content_hash: str
    indexed_at: datetime
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dto(cls, dto: DocumentDTO) -> "DocumentResponse":
        return cls(
            id=dto.id,
            path=dto.path,
            stem=dto.stem,
            document_type=dto.document_type,
            title=dto.title,
            aliases=dto.aliases,
            tags=dto.tags,
            source_url=dto.source_url,
            content_hash=dto.content_hash,
            indexed_at=dto.indexed_at,
            created_at=dto.created_at,
            updated_at=dto.updated_at,
        )


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]


class LinkResponse(BaseModel):
    """단일 링크 뷰 (wikilink/up/backlink 공용)."""

    target: str
    label: str | None = None
    edge_type: str
    source_syntax: str
    is_broken: bool = False
    document_id: uuid.UUID | None = None
    title: str | None = None
    stem: str | None = None

    @classmethod
    def from_view(cls, view: LinkView) -> "LinkResponse":
        return cls(
            target=view.target,
            label=view.label,
            edge_type=view.edge_type,
            source_syntax=view.source_syntax,
            is_broken=view.is_broken,
            document_id=view.document_id,
            title=view.title,
            stem=view.stem,
        )


class DocumentLinksResponse(BaseModel):
    """문서 링크 조회 (SPEC-005 U-2): 참조/상류(up)/백링크."""

    wikilinks: list[LinkResponse]
    up: list[LinkResponse]
    backlinks: list[LinkResponse]

    @classmethod
    def from_links(cls, links: DocumentLinks) -> "DocumentLinksResponse":
        return cls(
            wikilinks=[LinkResponse.from_view(v) for v in links.wikilinks],
            up=[LinkResponse.from_view(v) for v in links.up],
            backlinks=[LinkResponse.from_view(v) for v in links.backlinks],
        )


class LinkPreviewRequest(BaseModel):
    """draft markdown에서 연결 preview (POST /documents/{id}/link-preview).

    stem 생략 시 path의 문서 stem을 쓴다(기존 문서 편집). 신규 draft는 stem을 실어 보내면
    DUPLICATE_STEM 충돌까지 검증한다.
    """

    markdown: str = Field(min_length=1)
    stem: str | None = None


class LinkErrorResponse(BaseModel):
    error_code: str
    target: str

    @classmethod
    def from_issue(cls, issue: LinkIssue) -> "LinkErrorResponse":
        return cls(error_code=issue.error_code, target=issue.target)


class LinkPreviewEntryResponse(BaseModel):
    target: str
    label: str | None = None
    edge_type: str
    source_syntax: str
    resolved: bool
    document_id: uuid.UUID | None = None
    title: str | None = None
    stem: str | None = None

    @classmethod
    def from_entry(cls, entry: LinkPreviewEntry) -> "LinkPreviewEntryResponse":
        return cls(
            target=entry.target,
            label=entry.label,
            edge_type=entry.edge_type,
            source_syntax=entry.source_syntax,
            resolved=entry.resolved,
            document_id=entry.document_id,
            title=entry.title,
            stem=entry.stem,
        )


class LinkPreviewResponse(BaseModel):
    links: list[LinkPreviewEntryResponse]
    backlinks: list[LinkPreviewEntryResponse]
    errors: list[LinkErrorResponse]

    @classmethod
    def from_preview(cls, preview: LinkPreview) -> "LinkPreviewResponse":
        return cls(
            links=[LinkPreviewEntryResponse.from_entry(e) for e in preview.links],
            backlinks=[
                LinkPreviewEntryResponse.from_entry(e) for e in preview.backlinks
            ],
            errors=[LinkErrorResponse.from_issue(i) for i in preview.errors],
        )
