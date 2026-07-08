"""templates 라우트 (AXKG-SPEC-010 §4 API Contract). owner 스코프.

- GET  /templates                     : 템플릿 목록(각 활성 버전 포함)
- GET  /templates/{key}               : 단일 템플릿 활성 버전
- GET  /templates/{key}/versions      : 버전 목록
- POST /templates/{key}/versions      : body 저장(새 버전 생성 + 활성화)
- POST /templates/{key}/rollback      : 지정 버전으로 활성 전환(포인터 이동)

전역 Bearer 인증은 main.py의 _PROTECTED_ROUTERS(get_current_auth)가 건다. 여기서는
get_current_user로 요청 user를 확보(created_by 기록 + owner 명시). AI 실행 시 활성 버전
로드는 pipeline 소관이라 이 라우터에서 다루지 않는다. T-009 Prompts 라우트와 대칭.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.core.database import get_session
from axkg.core.security import get_current_user
from axkg.dto.auth import UserDTO
from axkg.schemas.templates import (
    RollbackTemplateRequest,
    SaveTemplateRequest,
    TemplateActiveResponse,
    TemplateListResponse,
    TemplateSummary,
    TemplateVersionListResponse,
    TemplateVersionView,
)
from axkg.services.templates import (
    EmptyTemplateBodyError,
    TemplateNotFoundError,
    TemplateSaveError,
    TemplateService,
    TemplateVersionNotFoundError,
)

router = APIRouter(prefix="/templates", tags=["templates"])


def _error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error_code": error_code, "message": message}
    )


def _not_found(key: str) -> HTTPException:
    return _error(404, "TEMPLATE_NOT_FOUND", f"템플릿을 찾을 수 없습니다: {key}")


@router.get("", response_model=TemplateListResponse)
async def list_templates(
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TemplateListResponse:
    templates = await TemplateService(session).list()
    return TemplateListResponse(templates=[TemplateSummary(**t) for t in templates])


@router.get("/{key}", response_model=TemplateActiveResponse)
async def get_template(
    key: str,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TemplateActiveResponse:
    try:
        view = await TemplateService(session).get(key)
    except TemplateNotFoundError:
        raise _not_found(key)
    return TemplateActiveResponse(**view)


@router.get("/{key}/versions", response_model=TemplateVersionListResponse)
async def list_template_versions(
    key: str,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TemplateVersionListResponse:
    try:
        versions = await TemplateService(session).versions(key)
    except TemplateNotFoundError:
        raise _not_found(key)
    return TemplateVersionListResponse(
        key=key, versions=[TemplateVersionView(**v) for v in versions]
    )


@router.post("/{key}/versions", response_model=TemplateActiveResponse, status_code=201)
async def save_template_version(
    key: str,
    body: SaveTemplateRequest,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TemplateActiveResponse:
    try:
        view = await TemplateService(session).save(
            key, body=body.body, created_by=user.id
        )
    except EmptyTemplateBodyError:
        raise _error(422, "EMPTY_TEMPLATE_BODY", "템플릿 본문을 입력해 주세요.")
    except TemplateNotFoundError:
        raise _not_found(key)
    except TemplateSaveError:
        raise _error(500, "TEMPLATE_SAVE_FAILED", "템플릿을 저장하지 못했습니다. 다시 시도해 주세요.")
    return TemplateActiveResponse(**view)


@router.post("/{key}/rollback", response_model=TemplateActiveResponse)
async def rollback_template(
    key: str,
    body: RollbackTemplateRequest,
    user: UserDTO = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TemplateActiveResponse:
    try:
        view = await TemplateService(session).rollback(key, body.version)
    except TemplateNotFoundError:
        raise _not_found(key)
    except TemplateVersionNotFoundError:
        raise _error(404, "TEMPLATE_VERSION_NOT_FOUND", "롤백할 버전을 찾을 수 없습니다.")
    return TemplateActiveResponse(**view)
