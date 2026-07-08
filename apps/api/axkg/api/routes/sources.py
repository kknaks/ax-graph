"""sources 라우트 (AXKG-SPEC-003). 계약은 스펙 API Contract + FE 클라이언트를 따른다.

- POST /sources/manual              : 페이지 직접 입력 → received (S-3), 중복 처리 (S-2)
- GET  /sources                     : Inbox 목록 (status 필터, U-1)
- GET  /sources/{id}                : Source 상세 (U-2, collection_failed면 error_message)
- POST /sources/{id}/queue-collection : collection_failed 요약 재시도 큐잉 → summarizing
- GET  /sources/{id}/ai-tasks       : source 연결 AI task 이력

응답은 Source 자체를 반환하고(FE `Promise<Source>` 계약), 중복은 Case Matrix
`DUPLICATE_SOURCE`로 신호한다. 중복 링크/후보 표시는 부수효과로 커밋되어야 하므로
예외가 아니라 `JSONResponse`로 409를 반환한다(예외 반환은 session rollback을 유발).
에러 계약: INVALID_URL / DUPLICATE_SOURCE / MANUAL_NOTE_TOO_LONG / COLLECTION_RETRY_NOT_ALLOWED.
"""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.core.database import get_session
from axkg.core.security import get_current_user
from axkg.dto.auth import UserDTO
from axkg.integrations.open_kknaks import OpenKknaksClient
from axkg.schemas.sources import (
    AiTaskResponse,
    ManualSourceRequest,
    QueueCollectionRequest,
    SourceAiTasksResponse,
    SourceListResponse,
    SourceResponse,
    SummaryFeedbackRequest,
)
from axkg.services.sources import (
    CollectionRetryNotAllowedError,
    EmptyFeedbackError,
    InvalidUrlError,
    ManualNoteTooLongError,
    SourceNotFoundError,
    SummaryFeedbackNotAllowedError,
    SourceService,
)
from axkg.services.summary_execution import execute_source_summary

router = APIRouter(prefix="/sources", tags=["sources"])


def _open_kknaks_client(request: Request) -> OpenKknaksClient | None:
    """앱 수명에 바인딩된 open-kknaks client (미구성 시 None → 요약 트리거 생략)."""
    return getattr(request.app.state, "open_kknaks_client", None)


def _summary_session_factory(request: Request):
    """background 요약 실행이 쓸 session factory (미설정 시 runner 기본값 사용)."""
    return getattr(request.app.state, "session_factory", None)


def _error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error_code": error_code, "message": message}
    )


def _not_found(source_id: uuid.UUID) -> HTTPException:
    return _error(404, "SOURCE_NOT_FOUND", f"source 없음: {source_id}")


@router.post("/manual", response_model=SourceResponse, status_code=201)
async def create_manual(
    body: ManualSourceRequest,
    response: Response,
    request: Request,
    background: BackgroundTasks,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SourceResponse | JSONResponse:
    service = SourceService(session)
    try:
        result = await service.create_manual(
            source_url=body.source_url,
            raw_text=body.raw_text,
            submitted_by=user.id,
        )
    except InvalidUrlError:
        raise _error(400, "INVALID_URL", "올바른 URL이 아닙니다.")
    except ManualNoteTooLongError:
        raise _error(400, "MANUAL_NOTE_TOO_LONG", "메모는 2000자 이하로 입력해 주세요.")

    if result.duplicate_kind is not None:
        # 중복 링크/후보 표시(부수효과)는 정상 반환으로 커밋되게 두고 409로 신호한다.
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "error_code": "DUPLICATE_SOURCE",
                    "message": "이미 받은 URL입니다. 기존 항목에 연결했습니다.",
                }
            },
        )

    response.status_code = 201
    source_dto = result.source
    # SPEC-011 S-1: received → 자동 요약 트리거. 실행(수집·AI)은 background(비동기 worker).
    # open-kknaks 미구성 시엔 트리거하지 않고 received로 둔다.
    client = _open_kknaks_client(request)
    if client is not None:
        triggered = await service.start_summary(result.source.id)
        source_dto = triggered.source
        # background task는 get_session yield-teardown 커밋보다 먼저 실행되므로,
        # 여기서 명시적으로 커밋해 background(별도 session)가 source/task를 볼 수 있게 한다.
        await session.commit()
        background.add_task(
            execute_source_summary,
            triggered.ai_task.id,
            result.source.id,
            client=client,
            session_factory=_summary_session_factory(request),
        )
    return SourceResponse.from_dto(source_dto)


@router.get("", response_model=SourceListResponse)
async def list_sources(
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> SourceListResponse:
    sources = await SourceService(session).list(status=status)
    return SourceListResponse(sources=[SourceResponse.from_dto(s) for s in sources])


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> SourceResponse:
    try:
        source, error_message = await SourceService(session).get_detail(source_id)
    except SourceNotFoundError:
        raise _not_found(source_id)
    return SourceResponse.from_dto(source, error_message=error_message)


@router.post("/{source_id}/queue-collection", response_model=SourceResponse)
async def queue_collection(
    source_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    body: QueueCollectionRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> SourceResponse:
    try:
        result = await SourceService(session).queue_collection(
            source_id, note=body.note if body else None
        )
    except SourceNotFoundError:
        raise _not_found(source_id)
    except ManualNoteTooLongError:
        raise _error(400, "MANUAL_NOTE_TOO_LONG", "메모는 2000자 이하로 입력해 주세요.")
    except CollectionRetryNotAllowedError:
        raise _error(
            409,
            "COLLECTION_RETRY_NOT_ALLOWED",
            "현재 상태에서는 요약을 재시도할 수 없습니다.",
        )
    # 재시도 큐잉은 Phase 1이 동기로 끝냄 → 실제 실행을 background로 연결(구성 시).
    client = _open_kknaks_client(request)
    if client is not None:
        # background가 커밋된 queued task를 읽도록 먼저 커밋한다(yield-teardown보다 먼저 실행됨).
        await session.commit()
        background.add_task(
            execute_source_summary,
            result.ai_task.id,
            source_id,
            client=client,
            session_factory=_summary_session_factory(request),
        )
    return SourceResponse.from_dto(result.source)


@router.post("/{source_id}/summary-feedback", response_model=SourceResponse)
async def summary_feedback(
    source_id: uuid.UUID,
    body: SummaryFeedbackRequest,
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> SourceResponse:
    """summarized source에 피드백을 주면 직전 요약 세션을 resume해 재요약한다 (PLAN-005-T-016).

    FE(T-017)와 공유하는 계약. 흐름은 queue-collection과 동일하게 동기 큐잉(summarizing 전이)
    후 실제 실행을 background(execute_source_summary)로 연결한다. resume(원문 재전송 없음)는
    ai_task.options.resume 배선으로 worker까지 전달된다.
    """
    try:
        result = await SourceService(session).submit_summary_feedback(
            source_id, feedback=body.feedback
        )
    except SourceNotFoundError:
        raise _not_found(source_id)
    except EmptyFeedbackError:
        raise _error(400, "EMPTY_FEEDBACK", "피드백 내용을 입력해 주세요.")
    except SummaryFeedbackNotAllowedError:
        raise _error(
            409,
            "SUMMARY_FEEDBACK_NOT_ALLOWED",
            "요약이 완료된 항목에만 피드백으로 재요약할 수 있습니다.",
        )
    client = _open_kknaks_client(request)
    if client is not None:
        # background가 커밋된 queued task를 읽도록 먼저 커밋한다(yield-teardown보다 먼저 실행됨).
        await session.commit()
        background.add_task(
            execute_source_summary,
            result.ai_task.id,
            source_id,
            client=client,
            session_factory=_summary_session_factory(request),
        )
    return SourceResponse.from_dto(result.source)


@router.post("/{source_id}/classification-gates", response_model=SourceResponse)
async def classification_gates(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> SourceResponse:
    """[분류] 게이트 진입 트리거 자리 (SPEC-001 §4 · FE T-017 호출 계약).

    분류 AI 실행·md 변환은 WP3 범위다 — 이 스텁은 계약 표면(경로/전제조건)만 고정하고
    실제 분류를 실행하지 않는다. summarized source에서만 진입 가능함을 검증한 뒤 아직
    미구현(WP3)임을 CLASSIFICATION_NOT_IMPLEMENTED로 신호한다. 과구현 금지.
    """
    try:
        source = await SourceService(session).get(source_id)
    except SourceNotFoundError:
        raise _not_found(source_id)
    if source.status != "summarized":
        raise _error(
            409,
            "CLASSIFICATION_NOT_ALLOWED",
            "요약이 완료된 항목만 분류를 시작할 수 있습니다.",
        )
    raise _error(
        501,
        "CLASSIFICATION_NOT_IMPLEMENTED",
        "분류 실행은 아직 준비 중입니다(WP3).",
    )


@router.get("/{source_id}/ai-tasks", response_model=SourceAiTasksResponse)
async def list_source_ai_tasks(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> SourceAiTasksResponse:
    try:
        tasks = await SourceService(session).list_ai_tasks(source_id)
    except SourceNotFoundError:
        raise _not_found(source_id)
    return SourceAiTasksResponse(ai_tasks=[AiTaskResponse.from_dto(t) for t in tasks])
