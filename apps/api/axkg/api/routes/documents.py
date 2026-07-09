"""documents 라우트 (AXKG-SPEC-005). 계약은 스펙 API Contract를 따른다.

- GET  /documents                     : 문서 인덱스 목록
- GET  /documents/{id}                : 문서 상세(인덱스 필드)
- GET  /documents/{id}/links          : wikilink/up/backlink (U-2)
- POST /documents/{id}/link-preview   : draft markdown 연결 preview (U-1, 생성 경로 검증)

권한은 main.py에서 Bearer dependency로 일괄 적용(owner). 조회는 읽기 전용이다.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.config import settings
from axkg.core.database import get_session
from axkg.schemas.documents import (
    DocumentLinksResponse,
    DocumentListResponse,
    DocumentResponse,
    LinkPreviewRequest,
    LinkPreviewResponse,
)
from axkg.services.documents import DocumentNotFoundError, DocumentService
from axkg.services.graph import GraphService
from axkg.storage.markdown_root import MarkdownRoot

router = APIRouter(prefix="/documents", tags=["documents"])


def _not_found(document_id: uuid.UUID) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error_code": "DOCUMENT_NOT_FOUND",
            "message": f"문서 없음: {document_id}",
        },
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    session: AsyncSession = Depends(get_session),
) -> DocumentListResponse:
    docs = await DocumentService(session).list_documents()
    return DocumentListResponse(
        documents=[DocumentResponse.from_dto(d) for d in docs]
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> DocumentResponse:
    try:
        doc = await DocumentService(session).get_document(document_id)
    except DocumentNotFoundError:
        raise _not_found(document_id)
    return DocumentResponse.from_dto(doc)


@router.get("/{document_id}/links", response_model=DocumentLinksResponse)
async def get_document_links(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> DocumentLinksResponse:
    try:
        links = await DocumentService(session).get_links(document_id)
    except DocumentNotFoundError:
        raise _not_found(document_id)
    return DocumentLinksResponse.from_links(links)


@router.post("/{document_id}/link-preview", response_model=LinkPreviewResponse)
async def link_preview(
    document_id: uuid.UUID,
    body: LinkPreviewRequest,
    session: AsyncSession = Depends(get_session),
) -> LinkPreviewResponse:
    """draft markdown에서 연결 preview를 만든다 (SPEC-005 U-1).

    resolve 불가 wikilink는 BROKEN_WIKILINK, 본문 없는 up은 UP_WITHOUT_BODY_LINK,
    stem 충돌은 DUPLICATE_STEM으로 errors에 표면화(생성 경로 거부용).
    """
    try:
        await DocumentService(session).get_document(document_id)
    except DocumentNotFoundError:
        raise _not_found(document_id)
    graph = GraphService(session, root=MarkdownRoot(settings.axkg_markdown_root))
    preview = await graph.preview_links(
        markdown=body.markdown, stem=body.stem, document_id=document_id
    )
    return LinkPreviewResponse.from_preview(preview)
