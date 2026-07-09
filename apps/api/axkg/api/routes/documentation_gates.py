"""documentation-gates 라우트 (AXKG-SPEC-004 조회 전용 뷰). 계약은 스펙 API Contract를 따른다.

- GET /documentation-gates                                  : 문서화 게이트 목록(뷰)
- GET /documentation-gates/{source_id}/drafts/{version}/markdown : 초안 `.md` 전문 조회

액션(feedback/regenerate/retry/approve)은 공통 게이트 API(`/gates/{id}/*`)를 쓴다 —
여기엔 없다. 권한은 main.py Bearer dependency로 일괄 적용(owner).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.core.database import get_session
from axkg.schemas.documentation_gates import (
    DocumentationGateListResponse,
    DocumentationGateResponse,
    DraftMarkdownResponse,
)
from axkg.services.gates import DraftMarkdownNotFoundError, GateService

router = APIRouter(prefix="/documentation-gates", tags=["documentation-gates"])


@router.get("", response_model=DocumentationGateListResponse)
async def list_documentation_gates(
    session: AsyncSession = Depends(get_session),
) -> DocumentationGateListResponse:
    views = await GateService(session).list_documentation_gates()
    return DocumentationGateListResponse(
        documentation_gates=[
            DocumentationGateResponse.from_view(v) for v in views
        ]
    )


@router.get(
    "/{source_id}/drafts/{draft_version}/markdown",
    response_model=DraftMarkdownResponse,
)
async def get_draft_markdown(
    source_id: uuid.UUID,
    draft_version: int,
    session: AsyncSession = Depends(get_session),
) -> DraftMarkdownResponse:
    try:
        markdown = await GateService(session).get_documentation_draft_markdown(
            source_id, draft_version
        )
    except DraftMarkdownNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "DRAFT_MARKDOWN_NOT_FOUND",
                "message": "초안 전문을 불러오지 못했습니다.",
            },
        )
    return DraftMarkdownResponse(
        source_id=source_id, draft_version=draft_version, markdown=markdown
    )
