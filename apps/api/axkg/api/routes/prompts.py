"""prompts 라우트 (AXKG-SPEC-009 §4 API Contract). owner 스코프.

- GET  /prompts                       : 프롬프트 목록(각 활성 버전 포함)
- GET  /prompts/{key}                 : 단일 프롬프트 활성 버전
- GET  /prompts/{key}/versions        : 버전 목록
- POST /prompts/{key}/versions        : 본문+스키마 저장(새 버전 생성 + 활성화)
- POST /prompts/{key}/rollback        : 지정 버전으로 활성 전환(포인터 이동)

전역 Bearer 인증은 main.py의 _PROTECTED_ROUTERS(get_current_auth)가 건다. 여기서는
get_current_user로 요청 user를 확보(created_by 기록 + owner 명시). AI 실행 시 활성 버전
로드는 pipeline 소관이라 이 라우터에서 다루지 않는다.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.core.database import get_session
from axkg.core.security import get_current_user
from axkg.dto.auth import UserDTO
from axkg.schemas.prompts import (
    PromptActiveResponse,
    PromptListResponse,
    PromptSummary,
    PromptVersionListResponse,
    PromptVersionView,
    RollbackPromptRequest,
    SavePromptRequest,
)
from axkg.services.prompts import (
    EmptyPromptBodyError,
    InvalidOutputSchemaError,
    PromptNotFoundError,
    PromptSaveError,
    PromptService,
    PromptVersionNotFoundError,
)

router = APIRouter(prefix="/prompts", tags=["prompts"])


def _error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error_code": error_code, "message": message}
    )


def _not_found(key: str) -> HTTPException:
    return _error(404, "PROMPT_NOT_FOUND", f"프롬프트를 찾을 수 없습니다: {key}")


@router.get("", response_model=PromptListResponse)
async def list_prompts(
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PromptListResponse:
    prompts = await PromptService(session).list()
    return PromptListResponse(prompts=[PromptSummary(**p) for p in prompts])


@router.get("/{key}", response_model=PromptActiveResponse)
async def get_prompt(
    key: str,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PromptActiveResponse:
    try:
        view = await PromptService(session).get(key)
    except PromptNotFoundError:
        raise _not_found(key)
    return PromptActiveResponse(**view)


@router.get("/{key}/versions", response_model=PromptVersionListResponse)
async def list_prompt_versions(
    key: str,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PromptVersionListResponse:
    try:
        versions = await PromptService(session).versions(key)
    except PromptNotFoundError:
        raise _not_found(key)
    return PromptVersionListResponse(
        key=key, versions=[PromptVersionView(**v) for v in versions]
    )


@router.post("/{key}/versions", response_model=PromptActiveResponse, status_code=201)
async def save_prompt_version(
    key: str,
    body: SavePromptRequest,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PromptActiveResponse:
    try:
        view = await PromptService(session).save(
            key,
            prompt_text=body.prompt_text,
            output_schema=body.output_schema,
            created_by=user.id,
        )
    except EmptyPromptBodyError:
        raise _error(422, "EMPTY_PROMPT_BODY", "프롬프트 본문을 입력해 주세요.")
    except InvalidOutputSchemaError:
        raise _error(422, "INVALID_OUTPUT_SCHEMA", "출력 형식(JSON schema)이 올바르지 않습니다.")
    except PromptNotFoundError:
        raise _not_found(key)
    except PromptSaveError:
        raise _error(500, "PROMPT_SAVE_FAILED", "프롬프트를 저장하지 못했습니다. 다시 시도해 주세요.")
    return PromptActiveResponse(**view)


@router.post("/{key}/rollback", response_model=PromptActiveResponse)
async def rollback_prompt(
    key: str,
    body: RollbackPromptRequest,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PromptActiveResponse:
    try:
        view = await PromptService(session).rollback(key, body.version)
    except PromptNotFoundError:
        raise _not_found(key)
    except PromptVersionNotFoundError:
        raise _error(404, "PROMPT_VERSION_NOT_FOUND", "롤백할 버전을 찾을 수 없습니다.")
    return PromptActiveResponse(**view)
