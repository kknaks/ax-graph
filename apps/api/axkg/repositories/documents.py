"""documents / document_edges repository (AXKG-SPEC-005). session 접근은 여기서만.

`documents`(인덱스) / `document_edges`(rebuildable graph cache) CRUD.
- 문서는 path가 upsert 키다(같은 파일=같은 row, id 안정 → 엣지 FK 보존).
- stem/alias resolve는 전체 인덱스를 메모리 맵으로 올려 처리한다(dialect별 JSON contains
  회피, MVP 규모). rebuild도 어차피 전체를 로드하므로 비용 동일.
- 엣지는 from_document_id(소유 문서)가 단위다 — 문서 rebuild 시 그 문서의 엣지만 지우고
  다시 만든다(엣지 단일 소스=문서 Markdown, SPEC-005 §5).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.document import DocumentDTO, DocumentEdgeDTO
from axkg.models import Document, DocumentEdge


def _doc_to_dto(row: Document) -> DocumentDTO:
    return DocumentDTO(
        id=row.id,
        path=row.path,
        stem=row.stem,
        document_type=row.document_type,
        title=row.title,
        aliases=list(row.aliases or []),
        tags=list(row.tags or []),
        source_url=row.source_url,
        frontmatter=row.frontmatter or {},
        content_hash=row.content_hash,
        indexed_at=row.indexed_at,
        status=row.status,
        version=row.version,
        producing_revision_id=row.producing_revision_id,
        source_id=row.source_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _edge_to_dto(row: DocumentEdge) -> DocumentEdgeDTO:
    return DocumentEdgeDTO(
        id=row.id,
        from_document_id=row.from_document_id,
        to_document_id=row.to_document_id,
        to_target=row.to_target,
        edge_type=row.edge_type,
        source_syntax=row.source_syntax,
        label=row.label,
        is_broken=row.is_broken,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # documents index
    # ------------------------------------------------------------------

    async def get(self, document_id: uuid.UUID) -> DocumentDTO | None:
        row = await self._session.get(Document, document_id)
        return _doc_to_dto(row) if row is not None else None

    async def get_by_path(self, path: str) -> DocumentDTO | None:
        row = await self._session.scalar(
            sa.select(Document).where(Document.path == path)
        )
        return _doc_to_dto(row) if row is not None else None

    async def get_by_stem(self, stem: str) -> DocumentDTO | None:
        row = await self._session.scalar(
            sa.select(Document).where(Document.stem == stem)
        )
        return _doc_to_dto(row) if row is not None else None

    async def list_all(self) -> list[DocumentDTO]:
        rows = (
            await self._session.scalars(
                sa.select(Document).order_by(Document.stem.asc())
            )
        ).all()
        return [_doc_to_dto(row) for row in rows]

    async def list_by_types(
        self,
        *,
        exclude_types: tuple[str, ...] = (),
        include_superseded: bool = False,
    ) -> list[DocumentDTO]:
        """document_type 제외 필터 + 기본적으로 superseded 문서 제외 (SPEC-005).

        superseded 문서는 박제 보존은 하되 최신 그래프/조회에서 빠진다(`source`·`deleted`와
        동일 기준). 전체 인덱스가 필요한 rebuild/resolver는 `list_all`을 쓴다.
        """
        stmt = sa.select(Document)
        if exclude_types:
            stmt = stmt.where(Document.document_type.notin_(exclude_types))
        if not include_superseded:
            stmt = stmt.where(Document.status != "superseded")
        stmt = stmt.order_by(Document.stem.asc())
        rows = (await self._session.scalars(stmt)).all()
        return [_doc_to_dto(row) for row in rows]

    async def get_current_main_by_source(
        self, source_id: uuid.UUID
    ) -> DocumentDTO | None:
        """같은 source 계보의 현재 유효 main 문서(재문서화 supersede 판단 기준, SPEC-004).

        current 계보에는 최대 1건만 존재한다 — 재문서화가 옛 것을 superseded로 내리고 새 것을
        current로 세우기 때문. 파생 concept도 producing source_id를 스탬프하므로(T-027 D),
        main 계보 판단에서 concept를 제외한다 — main은 reference/permanent/baseline이다.
        """
        row = await self._session.scalar(
            sa.select(Document).where(
                Document.source_id == source_id,
                Document.status == "current",
                Document.document_type != "concept",
            )
        )
        return _doc_to_dto(row) if row is not None else None

    async def set_main_lifecycle(
        self,
        *,
        path: str,
        version: int,
        producing_revision_id: uuid.UUID | None,
        source_id: uuid.UUID,
    ) -> DocumentDTO:
        """main 문서(path 기준)에 lifecycle을 스탬프한다: current + version + producing 링크.

        upsert(rebuild)가 만든 row 위에 얹는다 — upsert는 lifecycle을 건드리지 않으므로
        일반 재인덱스(startup scan)에는 영향이 없다.
        """
        return await self._stamp_lifecycle(
            path=path,
            version=version,
            producing_revision_id=producing_revision_id,
            source_id=source_id,
        )

    async def set_derived_lifecycle(
        self,
        *,
        path: str,
        version: int,
        producing_revision_id: uuid.UUID | None,
        source_id: uuid.UUID,
    ) -> DocumentDTO:
        """파생 문서(concept/baseline)에 lifecycle을 스탬프한다(SPEC-004 D, T-027).

        create=version 1 / supplement(overwrite)=version++. stem·경로 불변이고, 옛 버전 본문은
        게이트 revision payload(draft_markdown)가 박제한다 — 별도 스냅샷 테이블을 만들지 않는다.
        main과 동일 스탬프지만 재문서화 main 판단(`get_current_main_by_source`)은 concept 제외.
        """
        return await self._stamp_lifecycle(
            path=path,
            version=version,
            producing_revision_id=producing_revision_id,
            source_id=source_id,
        )

    async def _stamp_lifecycle(
        self,
        *,
        path: str,
        version: int,
        producing_revision_id: uuid.UUID | None,
        source_id: uuid.UUID,
    ) -> DocumentDTO:
        row = await self._session.scalar(
            sa.select(Document).where(Document.path == path)
        )
        if row is None:
            raise LookupError(f"document not found for lifecycle: {path}")
        row.status = "current"
        row.version = version
        row.producing_revision_id = producing_revision_id
        row.source_id = source_id
        await self._session.flush()
        return _doc_to_dto(row)

    async def supersede_document(self, document_id: uuid.UUID) -> DocumentDTO | None:
        """옛 문서를 superseded로 마킹(박제 보존). row/엣지는 감사·비교용으로 남긴다."""
        row = await self._session.get(Document, document_id)
        if row is None:
            return None
        row.status = "superseded"
        await self._session.flush()
        return _doc_to_dto(row)

    async def upsert(
        self,
        *,
        path: str,
        stem: str,
        document_type: str,
        title: str,
        aliases: list[str],
        tags: list[str],
        source_url: str | None,
        frontmatter: dict[str, Any],
        content_hash: str,
        indexed_at: datetime,
    ) -> DocumentDTO:
        """path 기준 upsert. 기존 row가 있으면 필드를 갱신(id 유지)."""
        row = await self._session.scalar(
            sa.select(Document).where(Document.path == path)
        )
        if row is None:
            row = Document(path=path)
            self._session.add(row)
        row.stem = stem
        row.document_type = document_type
        row.title = title
        row.aliases = list(aliases)
        row.tags = list(tags)
        row.source_url = source_url
        row.frontmatter = dict(frontmatter)
        row.content_hash = content_hash
        row.indexed_at = indexed_at
        await self._session.flush()
        return _doc_to_dto(row)

    async def delete_by_path(self, path: str) -> uuid.UUID | None:
        """path의 문서를 인덱스에서 제거하고 그 id를 반환(없으면 None)."""
        row = await self._session.scalar(
            sa.select(Document).where(Document.path == path)
        )
        if row is None:
            return None
        document_id = row.id
        await self._session.delete(row)
        await self._session.flush()
        return document_id

    # ------------------------------------------------------------------
    # document_edges (rebuildable cache)
    # ------------------------------------------------------------------

    async def add_edge(
        self,
        *,
        from_document_id: uuid.UUID,
        to_document_id: uuid.UUID | None,
        to_target: str,
        edge_type: str,
        source_syntax: str,
        label: str | None,
        is_broken: bool,
    ) -> DocumentEdgeDTO:
        row = DocumentEdge(
            from_document_id=from_document_id,
            to_document_id=to_document_id,
            to_target=to_target,
            edge_type=edge_type,
            source_syntax=source_syntax,
            label=label,
            is_broken=is_broken,
        )
        self._session.add(row)
        await self._session.flush()
        return _edge_to_dto(row)

    async def delete_edges_from(self, from_document_id: uuid.UUID) -> None:
        """문서가 소유한(outgoing) 엣지를 모두 제거 — 그 문서 rebuild 전에 호출."""
        await self._session.execute(
            sa.delete(DocumentEdge).where(
                DocumentEdge.from_document_id == from_document_id
            )
        )
        await self._session.flush()

    async def delete_all_edges(self) -> None:
        await self._session.execute(sa.delete(DocumentEdge))
        await self._session.flush()

    async def list_all_edges(self) -> list[DocumentEdgeDTO]:
        rows = (await self._session.scalars(sa.select(DocumentEdge))).all()
        return [_edge_to_dto(row) for row in rows]

    async def list_edges_from(self, from_document_id: uuid.UUID) -> list[DocumentEdgeDTO]:
        rows = (
            await self._session.scalars(
                sa.select(DocumentEdge).where(
                    DocumentEdge.from_document_id == from_document_id
                )
            )
        ).all()
        return [_edge_to_dto(row) for row in rows]

    async def list_edges_to_document(
        self, to_document_id: uuid.UUID
    ) -> list[DocumentEdgeDTO]:
        """이 문서를 가리키는(resolved) 백링크 엣지."""
        rows = (
            await self._session.scalars(
                sa.select(DocumentEdge).where(
                    DocumentEdge.to_document_id == to_document_id
                )
            )
        ).all()
        return [_edge_to_dto(row) for row in rows]

    async def resolve_edges_to_target(
        self, *, to_target: str, to_document_id: uuid.UUID
    ) -> None:
        """target stem을 가리키던 미해결/깨진 엣지를 이 문서로 연결(inbound heal).

        외부(Obsidian/git) 편집으로 나중에 문서가 추가/이름변경돼 stem이 생기면, 그 stem을
        참조하던 기존 엣지가 이제 resolve된다(is_broken 해제).
        """
        await self._session.execute(
            sa.update(DocumentEdge)
            .where(DocumentEdge.to_target == to_target)
            .values(to_document_id=to_document_id, is_broken=False)
        )
        await self._session.flush()

    async def break_edges_to_document(self, to_document_id: uuid.UUID) -> None:
        """문서가 제거되면 그 문서를 가리키던 엣지를 깨진 것으로 표시(사후 발견)."""
        await self._session.execute(
            sa.update(DocumentEdge)
            .where(DocumentEdge.to_document_id == to_document_id)
            .values(to_document_id=None, is_broken=True)
        )
        await self._session.flush()
