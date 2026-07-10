"""document_stale_marks repository (AXKG-SPEC-004 §E). session 접근은 여기서만.

concept 개정 → 참조 permanent stale 배지의 CRUD. (document_id, concept_stem)당 한 행을
유지한다 — 재감지는 in-place 갱신(active로 되살림), 해제는 status=dismissed 전이.
목록은 active만, 감사 이력은 dismissed 행으로 보존한다(row 삭제 없음).
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.document import DocumentStaleMarkDTO
from axkg.models import DocumentStaleMark
from axkg.models.base import utcnow


def _to_dto(row: DocumentStaleMark) -> DocumentStaleMarkDTO:
    return DocumentStaleMarkDTO(
        id=row.id,
        document_id=row.document_id,
        concept_stem=row.concept_stem,
        concept_path=row.concept_path,
        change_summary=row.change_summary,
        triggering_revision_id=row.triggering_revision_id,
        status=row.status,
        marked_at=row.marked_at,
        dismissed_at=row.dismissed_at,
    )


class StaleMarkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def mark(
        self,
        *,
        document_id: uuid.UUID,
        concept_stem: str,
        concept_path: str | None,
        change_summary: str | None,
        triggering_revision_id: uuid.UUID | None,
    ) -> DocumentStaleMarkDTO:
        """(document_id, concept_stem)당 한 행을 upsert 한다(재감지=in-place 갱신).

        이미 dismissed였다면 active로 되살리고 변경 요지·유발 revision·시각을 새로 스탬프한다.
        """
        row = await self._session.scalar(
            sa.select(DocumentStaleMark).where(
                DocumentStaleMark.document_id == document_id,
                DocumentStaleMark.concept_stem == concept_stem,
            )
        )
        now = utcnow()
        if row is None:
            row = DocumentStaleMark(
                document_id=document_id,
                concept_stem=concept_stem,
            )
            self._session.add(row)
        row.concept_path = concept_path
        row.change_summary = change_summary
        row.triggering_revision_id = triggering_revision_id
        row.status = "active"
        row.marked_at = now
        row.dismissed_at = None
        await self._session.flush()
        return _to_dto(row)

    async def list_active(self) -> list[DocumentStaleMarkDTO]:
        rows = (
            await self._session.scalars(
                sa.select(DocumentStaleMark)
                .where(DocumentStaleMark.status == "active")
                .order_by(DocumentStaleMark.marked_at.desc())
            )
        ).all()
        return [_to_dto(row) for row in rows]

    async def list_active_for_document(
        self, document_id: uuid.UUID
    ) -> list[DocumentStaleMarkDTO]:
        rows = (
            await self._session.scalars(
                sa.select(DocumentStaleMark)
                .where(
                    DocumentStaleMark.document_id == document_id,
                    DocumentStaleMark.status == "active",
                )
                .order_by(DocumentStaleMark.marked_at.desc())
            )
        ).all()
        return [_to_dto(row) for row in rows]

    async def dismiss_document(self, document_id: uuid.UUID) -> int:
        """그 문서의 active 배지를 모두 dismissed로 내린다. 멱등(0건이면 no-op). 해제 수 반환."""
        rows = (
            await self._session.scalars(
                sa.select(DocumentStaleMark).where(
                    DocumentStaleMark.document_id == document_id,
                    DocumentStaleMark.status == "active",
                )
            )
        ).all()
        now = utcnow()
        for row in rows:
            row.status = "dismissed"
            row.dismissed_at = now
        await self._session.flush()
        return len(rows)
