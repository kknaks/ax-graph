"""documents 라우트 (AXKG-SPEC-005). 계약은 스펙 API Contract를 따른다.

- GET  /documents                     : 문서 인덱스 목록
- GET  /documents/{id}                : 문서 상세(인덱스 필드)
- GET  /documents/{id}/links          : wikilink/up/backlink (U-2)
- POST /documents/{id}/link-preview   : draft markdown 연결 preview (U-1, 생성 경로 검증)

권한은 main.py에서 Bearer dependency로 일괄 적용(owner). 조회는 읽기 전용이다.
"""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.config import settings
from axkg.core.database import get_session
from axkg.integrations.open_kknaks import OpenKknaksClient
from axkg.schemas.documents import (
    DocumentLinksResponse,
    DocumentListResponse,
    DocumentResponse,
    LinkPreviewRequest,
    LinkPreviewResponse,
    StaleDismissResponse,
    StaleDocumentResponse,
    StaleListResponse,
)
from axkg.schemas.gates import GateResponse
from axkg.services.documentation_gate_execution import execute_documentation_gate
from axkg.services.documents import DocumentNotFoundError, DocumentService
from axkg.services.gates import (
    GateService,
    GateTaskResult,
    StaleDocumentNotFoundError,
    StaleRegenerationNotAllowedError,
)
from axkg.services.graph import GraphService
from axkg.services.stale import StaleService
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


def _read_markdown_full(path: str) -> str | None:
    """단건 상세 read-through: markdown root에서 현재 파일 전문(frontmatter+본문)을 읽는다.

    md=SoT(DEC-002)라 본문은 DB에 저장하지 않고 요청 시점에 파일에서 읽는다. 파일이 없거나
    root 밖/접근 불가면 null을 돌려준다(상세는 여전히 인덱스 필드로 응답).
    """
    root = MarkdownRoot(settings.axkg_markdown_root)
    if not root.exists(path):
        return None
    try:
        return root.read_text(path)
    except OSError:
        return None


def _open_kknaks_client(request: Request) -> OpenKknaksClient | None:
    return getattr(request.app.state, "open_kknaks_client", None)


def _session_factory(request: Request):
    return getattr(request.app.state, "session_factory", None)


def _schedule_documentation_execution(
    request: Request, background: BackgroundTasks, result: GateTaskResult
) -> None:
    """queued 재생성 task를 문서화 오케스트레이터에 연결한다(gates 라우트 미러링).

    client 미구성이면 큐만 남긴다. 호출측이 먼저 commit해야 background(별도 session)가 본다.
    """
    client = _open_kknaks_client(request)
    if client is None:
        return
    background.add_task(
        execute_documentation_gate,
        result.ai_task.id,
        result.gate.id,
        result.revision.id,
        client=client,
        session_factory=_session_factory(request),
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    session: AsyncSession = Depends(get_session),
) -> DocumentListResponse:
    docs = await DocumentService(session).list_documents()
    return DocumentListResponse(
        documents=[DocumentResponse.from_dto(d) for d in docs]
    )


@router.get("/stale", response_model=StaleListResponse)
async def list_stale_documents(
    session: AsyncSession = Depends(get_session),
) -> StaleListResponse:
    """concept 개정으로 영향 가능성이 표시된 permanent 목록 (SPEC-004 §E, GET /documents/stale).

    "영향 가능성 있음" 표시일 뿐 "수정 필요" 판단이 아니다(E-1). 라우트 순서상 `/{document_id}`
    보다 먼저 선언해 'stale'이 UUID로 파싱되지 않게 한다.
    """
    views = await StaleService(session).list_stale()
    return StaleListResponse(
        documents=[StaleDocumentResponse.from_view(v) for v in views]
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
    return DocumentResponse.from_dto(
        doc, markdown_full=_read_markdown_full(doc.path)
    )


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


@router.post("/{document_id}/stale/dismiss", response_model=StaleDismissResponse)
async def dismiss_stale(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> StaleDismissResponse:
    """stale 배지 해제 (SPEC-004 §E-1, POST /documents/{id}/stale/dismiss). 멱등.

    판단이 유효하다고 본 사용자가 배지만 내린다. active 배지가 없어도 200(dismissed_count=0).
    """
    dismissed = await StaleService(session).dismiss(document_id)
    return StaleDismissResponse(document_id=document_id, dismissed_count=dismissed)


@router.post("/{document_id}/regenerate", response_model=GateResponse)
async def regenerate_stale_document(
    document_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> GateResponse:
    """stale permanent 재생성 게이트 오픈 + 재생성 task 큐잉 (SPEC-004 §E-3/E-4).

    그 permanent의 producing source 문서화 게이트 재문서화 경로(v++)를 재사용하고, stale 3입력
    (대상 전문 + 바뀐 concept 전문 + 변경 요지)을 주입한다. 이후 리뷰/승인은 기존 게이트 계약
    (GET /sources/{id}/gates 폴링, /gates/{id}/approve|feedback|regenerate) 그대로다.
    """
    service = GateService(session)
    try:
        result = await service.open_stale_regeneration(document_id)
    except StaleDocumentNotFoundError:
        raise _not_found(document_id)
    except StaleRegenerationNotAllowedError:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "STALE_REGENERATION_NOT_ALLOWED",
                "message": "재생성할 수 없는 문서입니다. producing source가 있는 permanent에서만 가능합니다.",
            },
        )
    # background가 커밋된 queued task를 읽도록 먼저 커밋한 뒤 문서화 실행을 연결한다.
    if _open_kknaks_client(request) is not None:
        await session.commit()
        _schedule_documentation_execution(request, background, result)
    active = await service.get_active_revision(result.gate)
    return GateResponse.from_dto(result.gate, active_revision=active)
