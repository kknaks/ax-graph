"""settings 라우트 (AXKG-SPEC-007 §4 API Contract). owner 스코프.

- GET    /settings/ai-provider                              : 현재 AI provider 설정 조회
- PUT    /settings/ai-provider                              : 전역 provider/default options 저장
- PUT    /settings/ai-provider/task-overrides/{task_key}    : task override 추가/수정
- DELETE /settings/ai-provider/task-overrides/{task_key}    : task override 삭제
- GET    /settings/ai-provider/health                       : Claude/Codex provider 상태

전역 Bearer 인증은 main.py의 _PROTECTED_ROUTERS(get_current_auth)가 건다. 여기서는
get_current_user로 요청 user를 확보해 updated_by 기록 + owner 스코프를 명시한다.
POST /ai/tasks(internal)는 파이프라인 소관이라 이 라우터에서 만들지 않는다.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.core.database import get_session
from axkg.core.security import get_current_user
from axkg.dto.auth import UserDTO
from axkg.schemas.settings import (
    AIProviderSettingsRequest,
    AIProviderSettingsResponse,
    ProviderHealth,
    ProviderHealthResponse,
    TaskOverrideRequest,
)
from axkg.services.settings import (
    InvalidExecutionLimitError,
    SettingsService,
    UnknownTaskDefinitionError,
    UnsupportedProviderError,
)

router = APIRouter(prefix="/settings", tags=["settings"])


def _error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error_code": error_code, "message": message}
    )


@router.get("/ai-provider", response_model=AIProviderSettingsResponse)
async def get_ai_provider(
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AIProviderSettingsResponse:
    value = await SettingsService(session).get_ai_provider()
    return AIProviderSettingsResponse.from_value(value)


@router.put("/ai-provider", response_model=AIProviderSettingsResponse)
async def put_ai_provider(
    body: AIProviderSettingsRequest,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AIProviderSettingsResponse:
    try:
        value = await SettingsService(session).put_ai_provider(
            provider=body.provider,
            model=body.model,
            options=body.options,
            provider_options=body.provider_options,
            updated_by=user.id,
        )
    except UnsupportedProviderError:
        raise _error(422, "UNSUPPORTED_PROVIDER", "지원하지 않는 provider입니다.")
    except InvalidExecutionLimitError:
        raise _error(422, "INVALID_EXECUTION_LIMIT", "실행 한도 값을 확인해 주세요.")
    return AIProviderSettingsResponse.from_value(value)


@router.put(
    "/ai-provider/task-overrides/{task_key}", response_model=AIProviderSettingsResponse
)
async def put_task_override(
    task_key: str,
    body: TaskOverrideRequest,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AIProviderSettingsResponse:
    try:
        value = await SettingsService(session).put_task_override(
            task_key,
            model=body.model,
            options=body.options,
            provider_options=body.provider_options,
            updated_by=user.id,
        )
    except UnknownTaskDefinitionError:
        raise _error(
            404, "UNKNOWN_TASK_DEFINITION", "등록되지 않았거나 비활성인 작업입니다."
        )
    except InvalidExecutionLimitError:
        raise _error(422, "INVALID_EXECUTION_LIMIT", "실행 한도 값을 확인해 주세요.")
    return AIProviderSettingsResponse.from_value(value)


@router.delete(
    "/ai-provider/task-overrides/{task_key}", response_model=AIProviderSettingsResponse
)
async def delete_task_override(
    task_key: str,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AIProviderSettingsResponse:
    value = await SettingsService(session).delete_task_override(
        task_key, updated_by=user.id
    )
    return AIProviderSettingsResponse.from_value(value)


@router.get("/ai-provider/health", response_model=ProviderHealthResponse)
async def get_ai_provider_health(
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProviderHealthResponse:
    health = await SettingsService(session).get_health()
    return ProviderHealthResponse(providers=[ProviderHealth(**h) for h in health])
