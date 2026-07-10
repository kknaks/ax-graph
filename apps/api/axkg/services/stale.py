"""stale 배지 조회/해제 (AXKG-SPEC-004 §E). WP4 후속 (T-030).

concept 개정 → 참조 permanent stale 배지의 조회 뷰와 해제. 감지(마킹)는 Apply Executor,
재생성 게이트 오픈은 GateService 소관 — 이 서비스는 목록/해제만 담당한다.

E-1: 배지는 "영향 가능성 있음" 표시일 뿐 "수정 필요" 판단이 아니다. 시스템은 판단하지 않는다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.repositories.documents import DocumentRepository
from axkg.repositories.stale import StaleMarkRepository


@dataclass(frozen=True)
class StaleMarkView:
    concept_stem: str
    change_summary: str | None
    marked_at: datetime
    concept_path: str | None = None


@dataclass(frozen=True)
class StaleDocumentView:
    document_id: uuid.UUID
    path: str
    title: str
    document_type: str
    stale_marks: list[StaleMarkView] = field(default_factory=list)


class StaleService:
    def __init__(self, session: AsyncSession) -> None:
        self._stale = StaleMarkRepository(session)
        self._docs = DocumentRepository(session)

    async def list_stale(self) -> list[StaleDocumentView]:
        """active stale 배지를 문서별로 묶어 조회한다(GET /documents/stale).

        배지가 가리키는 문서가 삭제/인덱스 이탈이면 조용히 건너뛴다(배지는 유지되지만
        표시 대상이 아님) — 목록은 현존 문서만 노출한다.
        """
        marks = await self._stale.list_active()
        if not marks:
            return []
        docs_by_id = {d.id: d for d in await self._docs.list_all()}
        grouped: dict[uuid.UUID, StaleDocumentView] = {}
        order: list[uuid.UUID] = []
        for mark in marks:
            doc = docs_by_id.get(mark.document_id)
            if doc is None:
                continue
            if mark.document_id not in grouped:
                grouped[mark.document_id] = StaleDocumentView(
                    document_id=doc.id,
                    path=doc.path,
                    title=doc.title,
                    document_type=doc.document_type,
                    stale_marks=[],
                )
                order.append(mark.document_id)
            grouped[mark.document_id].stale_marks.append(
                StaleMarkView(
                    concept_stem=mark.concept_stem,
                    concept_path=mark.concept_path,
                    change_summary=mark.change_summary,
                    marked_at=mark.marked_at,
                )
            )
        return [grouped[doc_id] for doc_id in order]

    async def dismiss(self, document_id: uuid.UUID) -> int:
        """그 문서의 active 배지를 모두 해제한다(POST /documents/{id}/stale/dismiss). 멱등.

        판단이 유효하다고 본 사용자가 배지만 내리는 경로(E-1). 해제한 배지 수를 반환한다
        (이미 없으면 0 — 200 OK 유지).
        """
        return await self._stale.dismiss_document(document_id)
