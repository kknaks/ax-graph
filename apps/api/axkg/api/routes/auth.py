"""auth 라우트 (AXKG-SPEC-008). 계약은 스펙 API Contract를 따른다.

- POST /auth/login    : public. email/password → token 발급 (+ user.role).
- GET  /auth/me       : authenticated. email·role 반환.
- POST /auth/logout   : authenticated. token revoke.
- POST /auth/password : authenticated(본인). 현재 비번 검증 후 교체 (강제 아님, BE-4).
에러 계약은 스펙 Case Matrix
(INVALID_CREDENTIALS / INACTIVE_ACCOUNT / MISSING_TOKEN / INVALID_TOKEN).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.core.database import get_session
from axkg.core.security import get_current_auth
from axkg.dto.auth import AuthContextDTO
from axkg.schemas.auth import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MeResponse,
    UserResponse,
)
from axkg.services.auth import (
    AuthService,
    InactiveAccountError,
    InvalidCredentialsError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_response(user) -> UserResponse:
    return UserResponse(
        email=user.email, display_name=user.display_name, role=user.role
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest, session: AsyncSession = Depends(get_session)
) -> LoginResponse:
    try:
        result = await AuthService(session).login(body.email, body.password)
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "INVALID_CREDENTIALS", "message": "email/password 불일치"},
        )
    except InactiveAccountError:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "INACTIVE_ACCOUNT",
                "message": "비활성화된 계정입니다. 관리자에게 문의하세요.",
            },
        )
    return LoginResponse(token=result.token, user=_user_response(result.user))


@router.get("/me", response_model=MeResponse)
async def me(auth: AuthContextDTO = Depends(get_current_auth)) -> MeResponse:
    return MeResponse(user=_user_response(auth.user))


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    auth: AuthContextDTO = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
) -> LogoutResponse:
    await AuthService(session).logout(auth.token)
    return LogoutResponse()


@router.post("/password", response_model=ChangePasswordResponse)
async def change_password(
    body: ChangePasswordRequest,
    auth: AuthContextDTO = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
) -> ChangePasswordResponse:
    try:
        await AuthService(session).change_password(
            auth.user.id, body.current_password, body.new_password
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "INVALID_CREDENTIALS",
                "message": "현재 비밀번호가 올바르지 않습니다.",
            },
        )
    return ChangePasswordResponse()
