"""auth 라우트 (AXKG-SPEC-008). 계약은 스펙 API Contract를 따른다.

- POST /auth/login  : public. email/password → token 발급.
- GET  /auth/me     : authenticated.
- POST /auth/logout : authenticated. token revoke.
에러 계약은 스펙 Case Matrix (INVALID_CREDENTIALS / MISSING_TOKEN / INVALID_TOKEN).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.core.database import get_session
from axkg.core.security import get_current_auth
from axkg.dto.auth import AuthContextDTO
from axkg.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MeResponse,
    UserResponse,
)
from axkg.services.auth import AuthService, InvalidCredentialsError

router = APIRouter(prefix="/auth", tags=["auth"])


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
    return LoginResponse(
        token=result.token,
        user=UserResponse(email=result.user.email, display_name=result.user.display_name),
    )


@router.get("/me", response_model=MeResponse)
async def me(auth: AuthContextDTO = Depends(get_current_auth)) -> MeResponse:
    return MeResponse(
        user=UserResponse(email=auth.user.email, display_name=auth.user.display_name)
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    auth: AuthContextDTO = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
) -> LogoutResponse:
    await AuthService(session).logout(auth.token)
    return LogoutResponse()
