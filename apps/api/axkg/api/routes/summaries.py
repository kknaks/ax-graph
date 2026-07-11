"""summaries 라우트 — 문서 라이브러리 요약 브랜치 read-only API (AXKG-SPEC-013 §4).

- GET /summaries              : active 요약을 가진 source 목록 (요약 브랜치 소스)
- GET /summaries/{source_id}  : 해당 source의 active 요약 본문(`markdown_full`)

권한은 main.py에서 Bearer dependency로 일괄 적용(staff·admin — 문서 라이브러리 경계 상속,
AXKG-SPEC-008 §4). 서빙 소스는 DB 요약 원본이며 파일시스템을 읽지 않는다.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.core.database import get_session
from axkg.schemas.summaries import (
    SummaryDetailResponse,
    SummaryListItem,
    SummaryListResponse,
)
from axkg.services.summaries import SummaryLibraryService, SummaryNotFoundError

router = APIRouter(prefix="/summaries", tags=["summaries"])


@router.get("", response_model=SummaryListResponse)
async def list_summaries(
    session: AsyncSession = Depends(get_session),
) -> SummaryListResponse:
    items = await SummaryLibraryService(session).list_summaries()
    return SummaryListResponse(items=[SummaryListItem.from_dto(i) for i in items])


@router.get("/{source_id}", response_model=SummaryDetailResponse)
async def get_summary(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> SummaryDetailResponse:
    try:
        detail = await SummaryLibraryService(session).get_summary(source_id)
    except SummaryNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SUMMARY_NOT_FOUND",
                "message": f"요약 없음: {source_id}",
            },
        )
    return SummaryDetailResponse.from_dto(detail)
