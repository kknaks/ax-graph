"""gates 라우트 (AXKG-SPEC-002 공통 게이트 액션). 계약은 스펙 API Contract를 따른다.

- POST /gates/{id}/approve    : active revision 승인 → 분류 destination 확정 (WP3 Phase 1)
- POST /gates/{id}/feedback   : 피드백 저장 (review_pending→feedback_pending)
- POST /gates/{id}/regenerate : 피드백 기반 새 버전(v2) 생성 + 재생성 실행 스케줄링
- POST /gates/{id}/retry      : 실패한 게이트 생성/재생성 AI task 재실행

feedback은 AI를 돌리지 않고 저장만 한다. regenerate/retry는 queued task를 commit한 뒤
background(execute_classification_gate)로 실행을 연결한다(open-kknaks 미구성 시 큐만 남긴다).
에러 계약은 SPEC-002 Case Matrix.
"""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.core.database import get_session
from axkg.integrations.open_kknaks import OpenKknaksClient
from axkg.schemas.gates import ApproveRequest, FeedbackRequest, GateResponse
from axkg.services.classification_gate_execution import execute_classification_gate
from axkg.services.documentation_gate_execution import execute_documentation_gate
from axkg.services.gates import (
    GATE_KIND_DOCUMENTATION,
    FeedbackTooShortError,
    GateAlreadyApprovedError,
    GateNotFoundError,
    GateRetryNotAllowedError,
    GateService,
    GateTaskResult,
    NotThisDestinationReasonMissingError,
    ReclassificationNotAllowedError,
    StaleGateVersionError,
)
from axkg.workers.apply_executor import ApplyValidationError

# apply 검증 실패 코드 → HTTP status (SPEC-004 Case Matrix). 기본 409.
_APPLY_ERROR_STATUS = {"DRAFT_NOT_READY": 409, "PATH_NOT_ALLOWED": 422}
_APPLY_ERROR_MESSAGE = {
    "BROKEN_WIKILINK": "연결할 문서를 찾지 못했습니다.",
    "UP_WITHOUT_BODY_LINK": "계보 링크는 본문 링크도 필요합니다.",
    "DUPLICATE_STEM": "같은 파일 식별자가 이미 있습니다.",
    "PATH_NOT_ALLOWED": "허용되지 않은 문서 경로입니다.",
    "DRAFT_NOT_READY": "초안이 아직 준비되지 않았습니다.",
}

router = APIRouter(prefix="/gates", tags=["gates"])


def _open_kknaks_client(request: Request) -> OpenKknaksClient | None:
    return getattr(request.app.state, "open_kknaks_client", None)


def _session_factory(request: Request):
    return getattr(request.app.state, "session_factory", None)


def _error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error_code": error_code, "message": message}
    )


def _not_found(gate_id: uuid.UUID) -> HTTPException:
    return _error(404, "GATE_NOT_FOUND", f"게이트 없음: {gate_id}")


async def _gate_response(service: GateService, gate) -> GateResponse:
    active = await service.get_active_revision(gate)
    return GateResponse.from_dto(gate, active_revision=active)


def _schedule_execution(
    request: Request, background: BackgroundTasks, result: GateTaskResult
) -> None:
    """queued 생성/재생성/재시도 task를 background 실행에 연결한다(client 구성 시).

    gate_kind로 올바른 오케스트레이터를 고른다(classification vs documentation). 호출측이
    먼저 session.commit()해야 background(별도 session)가 task/revision을 본다.
    """
    client = _open_kknaks_client(request)
    if client is None:
        return
    executor = (
        execute_documentation_gate
        if result.gate.gate_kind == GATE_KIND_DOCUMENTATION
        else execute_classification_gate
    )
    background.add_task(
        executor,
        result.ai_task.id,
        result.gate.id,
        result.revision.id,
        client=client,
        session_factory=_session_factory(request),
    )


@router.post("/{gate_id}/approve", response_model=GateResponse)
async def approve_gate(
    gate_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    body: ApproveRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> GateResponse:
    service = GateService(session)
    try:
        result = await service.approve(
            gate_id, expected_revision_id=body.revision_id if body else None
        )
    except GateNotFoundError:
        raise _not_found(gate_id)
    except GateAlreadyApprovedError:
        raise _error(
            409,
            "GATE_ALREADY_APPROVED",
            "승인된 게이트는 변경할 수 없습니다. 새 revision을 만들어 주세요.",
        )
    except StaleGateVersionError:
        raise _error(409, "STALE_GATE_VERSION", "최신 상태를 다시 확인해 주세요.")
    except ApplyValidationError as exc:
        # 문서화 승인 apply 검증 실패 — 확정 문서를 만들지 않고 거부(SPEC-004 Case Matrix).
        code = exc.primary_code
        raise _error(
            _APPLY_ERROR_STATUS.get(code, 409),
            code,
            _APPLY_ERROR_MESSAGE.get(code, "초안을 확정할 수 없습니다."),
        )
    # 분류 승인(비-archive)은 문서화 게이트를 generating으로 만들고 초안 task를 큐잉한다.
    # background가 커밋된 task를 읽도록 먼저 커밋한 뒤 문서화 실행을 연결한다(Phase 2).
    if result.documentation_task is not None and _open_kknaks_client(request) is not None:
        await session.commit()
        _schedule_execution(request, background, result.documentation_task)
    return await _gate_response(service, result.gate)


@router.post("/{gate_id}/feedback", response_model=GateResponse)
async def feedback_gate(
    gate_id: uuid.UUID,
    body: FeedbackRequest,
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> GateResponse:
    service = GateService(session)
    # 문서화 게이트 "이 destination이 아님" → 분류 게이트 재오픈(SPEC-002 §5 / SPEC-004 S-3).
    if body.not_this_destination:
        try:
            reopen = await service.request_reclassification(
                gate_id, reason=body.not_this_destination_reason or ""
            )
        except GateNotFoundError:
            raise _not_found(gate_id)
        except NotThisDestinationReasonMissingError:
            raise _error(
                400,
                "MISSING_NOT_THIS_DESTINATION_REASON",
                "이 destination이 아닌 이유를 입력해 주세요.",
            )
        except GateAlreadyApprovedError:
            raise _error(
                409,
                "GATE_ALREADY_APPROVED",
                "승인된 게이트는 변경할 수 없습니다. 새 revision을 만들어 주세요.",
            )
        except ReclassificationNotAllowedError:
            raise _error(
                409,
                "RECLASSIFICATION_NOT_ALLOWED",
                "재분류할 수 없는 상태입니다. 승인된 분류 게이트의 문서화 초안에서만 가능합니다.",
            )
        # 재오픈된 분류 게이트 재생성 task를 background로 스케줄링(먼저 commit).
        if _open_kknaks_client(request) is not None:
            await session.commit()
            _schedule_execution(request, background, reopen.classification_task)
        # POST 대상(문서화 게이트, 이제 cancelled=reclassification_requested)을 반환한다.
        return await _gate_response(service, reopen.documentation_gate)

    try:
        result = await service.submit_feedback(gate_id, body=body.body or "")
    except GateNotFoundError:
        raise _not_found(gate_id)
    except GateAlreadyApprovedError:
        raise _error(
            409,
            "GATE_ALREADY_APPROVED",
            "승인된 게이트는 변경할 수 없습니다. 새 revision을 만들어 주세요.",
        )
    except FeedbackTooShortError:
        raise _error(
            400, "FEEDBACK_TOO_SHORT", "원하는 수정 방향을 조금 더 구체적으로 적어 주세요."
        )
    except StaleGateVersionError:
        raise _error(409, "STALE_GATE_VERSION", "최신 상태를 다시 확인해 주세요.")
    return await _gate_response(service, result.gate)


@router.post("/{gate_id}/regenerate", response_model=GateResponse)
async def regenerate_gate(
    gate_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> GateResponse:
    service = GateService(session)
    try:
        result = await service.regenerate(gate_id)
    except GateNotFoundError:
        raise _not_found(gate_id)
    except GateAlreadyApprovedError:
        raise _error(
            409,
            "GATE_ALREADY_APPROVED",
            "승인된 게이트는 변경할 수 없습니다. 새 revision을 만들어 주세요.",
        )
    except StaleGateVersionError:
        raise _error(409, "STALE_GATE_VERSION", "최신 상태를 다시 확인해 주세요.")
    # background가 커밋된 queued task를 읽도록 먼저 커밋한다(yield-teardown보다 먼저 실행됨).
    if _open_kknaks_client(request) is not None:
        await session.commit()
        _schedule_execution(request, background, result)
    return await _gate_response(service, result.gate)


@router.post("/{gate_id}/retry", response_model=GateResponse)
async def retry_gate(
    gate_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> GateResponse:
    service = GateService(session)
    try:
        result = await service.retry(gate_id)
    except GateNotFoundError:
        raise _not_found(gate_id)
    except GateRetryNotAllowedError:
        raise _error(
            409, "RETRY_NOT_ALLOWED", "현재 상태에서는 재시도할 수 없습니다."
        )
    if _open_kknaks_client(request) is not None:
        await session.commit()
        _schedule_execution(request, background, result)
    return await _gate_response(service, result.gate)
