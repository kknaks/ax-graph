"""유저 관리 라우트 (AXKG-SPEC-008 §3, admin 전용). WP6 BE-3.

- GET   /users               : 유저 목록
- POST  /users               : 유저 생성 (기본 비밀번호 1234)
- PATCH /users/{id}/role     : 역할 변경
- PATCH /users/{id}/active   : 활성/비활성 토글

admin 전용 authz는 main.py include의 require_admin이 강제한다(staff → FORBIDDEN).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.core.database import get_session
from axkg.dto.auth import UserAdminDTO
from axkg.schemas.users import (
    ChangeRoleRequest,
    CreateUserRequest,
    ToggleActiveRequest,
    UserAdminResponse,
    UsersListResponse,
)
from axkg.services.users import (
    EmailExistsError,
    InvalidRoleError,
    UserManagementService,
    UserNotFoundError,
)

router = APIRouter(prefix="/users", tags=["users"])


def _response(dto: UserAdminDTO) -> UserAdminResponse:
    return UserAdminResponse(
        id=dto.id,
        email=dto.email,
        display_name=dto.display_name,
        role=dto.role,
        is_active=dto.is_active,
    )


def _error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error_code": error_code, "message": message}
    )


@router.get("", response_model=UsersListResponse)
async def list_users(
    session: AsyncSession = Depends(get_session),
) -> UsersListResponse:
    users = await UserManagementService(session).list_users()
    return UsersListResponse(users=[_response(u) for u in users])


@router.post("", response_model=UserAdminResponse, status_code=201)
async def create_user(
    body: CreateUserRequest,
    session: AsyncSession = Depends(get_session),
) -> UserAdminResponse:
    try:
        dto = await UserManagementService(session).create_user(
            email=body.email, display_name=body.display_name, role=body.role
        )
    except EmailExistsError:
        raise _error(409, "EMAIL_EXISTS", "이미 존재하는 이메일입니다.")
    except InvalidRoleError:
        raise _error(422, "INVALID_ROLE", "role은 admin 또는 staff여야 합니다.")
    return _response(dto)


@router.patch("/{user_id}/role", response_model=UserAdminResponse)
async def change_role(
    user_id: uuid.UUID,
    body: ChangeRoleRequest,
    session: AsyncSession = Depends(get_session),
) -> UserAdminResponse:
    try:
        dto = await UserManagementService(session).change_role(user_id, body.role)
    except UserNotFoundError:
        raise _error(404, "USER_NOT_FOUND", "대상 유저를 찾을 수 없습니다.")
    except InvalidRoleError:
        raise _error(422, "INVALID_ROLE", "role은 admin 또는 staff여야 합니다.")
    return _response(dto)


@router.patch("/{user_id}/active", response_model=UserAdminResponse)
async def toggle_active(
    user_id: uuid.UUID,
    body: ToggleActiveRequest,
    session: AsyncSession = Depends(get_session),
) -> UserAdminResponse:
    try:
        dto = await UserManagementService(session).set_active(user_id, body.is_active)
    except UserNotFoundError:
        raise _error(404, "USER_NOT_FOUND", "대상 유저를 찾을 수 없습니다.")
    return _response(dto)
