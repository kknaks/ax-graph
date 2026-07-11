"""문서 라이브러리 요약 브랜치 read-only view (AXKG-SPEC-013, PLAN-012-T-006).

요약(`summaries/`)은 `documents` row가 없어 문서 목록으로 열거되지 않으므로, 문서 라이브러리
트리에 합류시키기 위한 읽기 전용 view를 별도로 노출한다.

경계(seam):
- **서빙 소스 = DB 요약 원본**(`sources.summary_payload` active 버전 = `active_summary_revision_id`
  포인터 revision). `summaries/` 아래 백업 md 파일은 읽지 않는다(파일시스템 접근 없음).
- 읽기 전용 — 요약 버전 히스토리(`source_summary_revisions`)·요약 파이프라인·그래프/인덱스에
  어떤 쓰기도, 어떤 영향도 주지 않는다(active 버전만 읽음).
- `name`/`path`/`markdown_full` 파생은 요약 보관 서비스(`summary_archive`)의 stem·본문 렌더
  로직을 재사용해 백업 md와 동일한 표현을 DB에서 서빙한다.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.source import (
    SourceDTO,
    SourceSummaryRevisionDTO,
    SummaryLibraryDetailDTO,
    SummaryLibraryItemDTO,
)
from axkg.repositories.sources import SourceRepository
from axkg.services.summary_archive import (
    build_summary_markdown,
    summary_archive_path,
)


class SummaryNotFoundError(Exception):
    """대상 source 없음 또는 active 요약 없음 (AXKG-SPEC-013 SUMMARY_NOT_FOUND)."""


def _summary_name(source: SourceDTO, revision: SourceSummaryRevisionDTO) -> str:
    """요약 표시명 — payload title, 없으면 source_url (보관 md 렌더 title과 정합)."""
    payload = revision.payload or {}
    return str(payload.get("title") or source.source_url)


class SummaryLibraryService:
    """요약 브랜치 목록/본문 조회 (읽기 전용)."""

    def __init__(self, session: AsyncSession) -> None:
        self._sources = SourceRepository(session)

    async def list_summaries(self) -> list[SummaryLibraryItemDTO]:
        """active 요약을 가진 source 목록 (정렬·필터·페이지네이션 없음 — 전체 반환)."""
        pairs = await self._sources.list_active_summaries()
        return [
            SummaryLibraryItemDTO(
                source_id=source.id,
                name=_summary_name(source, revision),
                path=summary_archive_path(revision),
            )
            for source, revision in pairs
        ]

    async def get_summary(self, source_id: uuid.UUID) -> SummaryLibraryDetailDTO:
        """해당 source의 active 요약 본문(`markdown_full`) — 없으면 SummaryNotFoundError."""
        source = await self._sources.get(source_id)
        if source is None or source.active_summary_revision_id is None:
            raise SummaryNotFoundError(str(source_id))
        revision = await self._sources.get_summary_revision(
            source.active_summary_revision_id
        )
        if revision is None:
            raise SummaryNotFoundError(str(source_id))
        return SummaryLibraryDetailDTO(
            source_id=source.id,
            name=_summary_name(source, revision),
            path=summary_archive_path(revision),
            markdown_full=build_summary_markdown(source, revision),
        )
