"""documents index / resolve / 조회 (AXKG-SPEC-005). WP2.

경계(범위):
- 이 서비스는 **읽기/인덱스/resolve/조회**만 담당한다. Markdown 파일 쓰기(create/patch)는
  WP3 Apply Executor 소관 — 여기서 파일을 쓰지 않는다.
- 엣지 생성/rebuild/retriever는 `services/graph.py`(GraphService). 이 서비스는 인덱스 upsert와
  stem/alias resolve, 그리고 문서/링크 조회 응답 조립까지다.

핵심 규칙(SPEC-005):
- stem = 파일명(확장자 제외). 제품 그래프 안에서 stem은 유일해야 한다(duplicate 거부).
- target resolve 우선순위: 파일명 stem → alias → frontmatter id (Obsidian 규칙과 동일).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.document import DocumentDTO, DocumentEdgeDTO
from axkg.models.base import utcnow
from axkg.repositories.documents import DocumentRepository
from axkg.storage.markdown_parser import ParsedDocument


class DocumentNotFoundError(Exception):
    def __init__(self, document_id: uuid.UUID) -> None:
        super().__init__(f"document not found: {document_id}")
        self.document_id = document_id


class DuplicateStemError(Exception):
    """같은 stem이 다른 path에 이미 존재 (Case Matrix: DUPLICATE_STEM)."""

    def __init__(self, stem: str, path: str, existing_path: str) -> None:
        super().__init__(
            f"duplicate stem {stem!r}: {path} conflicts with {existing_path}"
        )
        self.stem = stem
        self.path = path
        self.existing_path = existing_path


class InvalidDocumentError(Exception):
    """frontmatter `type`이 없어 인덱싱 불가 (SPEC-005 Required Frontmatter)."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"invalid document {path}: {reason}")
        self.path = path
        self.reason = reason


@dataclass(frozen=True)
class IndexSnapshotEntry:
    """연결 후보 컨텍스트(WP3 Phase 2)와 link-preview가 소비하는 유효 target 목록 항목."""

    stem: str
    title: str
    document_type: str
    aliases: tuple[str, ...] = ()


class DocumentResolver:
    """stem/alias/id → DocumentDTO 매핑 (SPEC-005 target resolve 규칙).

    한 rebuild/preview 패스 동안 전체 인덱스를 한 번 올려 재사용한다.
    """

    def __init__(self, documents: list[DocumentDTO]) -> None:
        self._by_stem: dict[str, DocumentDTO] = {}
        self._by_alias: dict[str, DocumentDTO] = {}
        for doc in documents:
            self._by_stem.setdefault(doc.stem, doc)
            for alias in doc.aliases:
                self._by_alias.setdefault(alias, doc)
            frontmatter_id = doc.frontmatter.get("id")
            if frontmatter_id is not None:
                self._by_alias.setdefault(str(frontmatter_id), doc)

    def resolve(self, target: str) -> DocumentDTO | None:
        return self._by_stem.get(target) or self._by_alias.get(target)


@dataclass(frozen=True)
class LinkView:
    """단일 링크(wikilink/up/backlink) 조회 뷰."""

    target: str
    label: str | None
    edge_type: str
    source_syntax: str
    is_broken: bool
    document_id: uuid.UUID | None = None
    title: str | None = None
    stem: str | None = None


@dataclass(frozen=True)
class DocumentLinks:
    wikilinks: list[LinkView] = field(default_factory=list)
    up: list[LinkView] = field(default_factory=list)
    backlinks: list[LinkView] = field(default_factory=list)


def stem_from_path(path: str) -> str:
    """상대 경로에서 stem(파일명, 확장자 제외)을 뽑는다."""
    return PurePosixPath(path).stem


class DocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self._docs = DocumentRepository(session)

    # ------------------------------------------------------------------
    # 인덱스 (upsert / resolve)
    # ------------------------------------------------------------------

    async def build_resolver(self) -> DocumentResolver:
        return DocumentResolver(await self._docs.list_all())

    async def index_document(
        self,
        *,
        path: str,
        parsed: ParsedDocument,
        content_hash: str,
        indexed_at: datetime | None = None,
    ) -> DocumentDTO:
        """파싱된 문서를 documents 인덱스에 upsert 한다.

        - stem = 파일명. duplicate stem(다른 path)이면 `DuplicateStemError`.
        - frontmatter `type` 필수 — 없으면 `InvalidDocumentError`.
        - title 없으면 stem을 fallback.
        """
        document_type = parsed.document_type
        if not document_type:
            raise InvalidDocumentError(path, "frontmatter 'type' 누락")
        stem = stem_from_path(path)
        existing = await self._docs.get_by_stem(stem)
        if existing is not None and existing.path != path:
            raise DuplicateStemError(stem, path, existing.path)
        return await self._docs.upsert(
            path=path,
            stem=stem,
            document_type=document_type,
            title=parsed.title or stem,
            aliases=parsed.aliases,
            tags=parsed.tags,
            source_url=parsed.source_url,
            frontmatter=parsed.frontmatter,
            content_hash=content_hash,
            indexed_at=indexed_at or utcnow(),
        )

    async def index_snapshot(
        self, *, exclude_types: tuple[str, ...] = ("source",)
    ) -> list[IndexSnapshotEntry]:
        """유효 stem/alias/title 목록 — 연결 후보 컨텍스트 2단의 원천(WP3 Phase 2 소비).

        기본적으로 `source`(raw record)는 링크 target이 아니므로 제외한다.
        """
        docs = await self._docs.list_by_types(exclude_types=exclude_types)
        return [
            IndexSnapshotEntry(
                stem=doc.stem,
                title=doc.title,
                document_type=doc.document_type,
                aliases=tuple(doc.aliases),
            )
            for doc in docs
        ]

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------

    async def list_documents(
        self, *, exclude_types: tuple[str, ...] = ()
    ) -> list[DocumentDTO]:
        return await self._docs.list_by_types(exclude_types=exclude_types)

    async def get_document(self, document_id: uuid.UUID) -> DocumentDTO:
        doc = await self._docs.get(document_id)
        if doc is None:
            raise DocumentNotFoundError(document_id)
        return doc

    async def get_links(self, document_id: uuid.UUID) -> DocumentLinks:
        """문서의 wikilink/up/backlink 조회 (SPEC-005 U-2)."""
        doc = await self.get_document(document_id)
        docs_by_id = {d.id: d for d in await self._docs.list_all()}

        outgoing = await self._docs.list_edges_from(doc.id)
        wikilinks: list[LinkView] = []
        up: list[LinkView] = []
        for edge in outgoing:
            view = self._edge_out_view(edge, docs_by_id)
            if edge.source_syntax == "up":
                up.append(view)
            else:
                wikilinks.append(view)

        incoming = await self._docs.list_edges_to_document(doc.id)
        backlinks = [self._edge_in_view(edge, docs_by_id) for edge in incoming]
        return DocumentLinks(wikilinks=wikilinks, up=up, backlinks=backlinks)

    @staticmethod
    def _edge_out_view(
        edge: DocumentEdgeDTO, docs_by_id: dict[uuid.UUID, DocumentDTO]
    ) -> LinkView:
        target_doc = (
            docs_by_id.get(edge.to_document_id) if edge.to_document_id else None
        )
        return LinkView(
            target=edge.to_target,
            label=edge.label,
            edge_type=edge.edge_type,
            source_syntax=edge.source_syntax,
            is_broken=edge.is_broken,
            document_id=target_doc.id if target_doc else None,
            title=target_doc.title if target_doc else None,
            stem=target_doc.stem if target_doc else None,
        )

    @staticmethod
    def _edge_in_view(
        edge: DocumentEdgeDTO, docs_by_id: dict[uuid.UUID, DocumentDTO]
    ) -> LinkView:
        from_doc = docs_by_id.get(edge.from_document_id)
        return LinkView(
            target=from_doc.stem if from_doc else str(edge.from_document_id),
            label=edge.label,
            edge_type=edge.edge_type,
            source_syntax=edge.source_syntax,
            is_broken=edge.is_broken,
            document_id=from_doc.id if from_doc else edge.from_document_id,
            title=from_doc.title if from_doc else None,
            stem=from_doc.stem if from_doc else None,
        )
