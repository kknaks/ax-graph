"""auth 서비스 (AXKG-SPEC-008). 로그인/토큰 검증/로그아웃/본인 비밀번호 변경."""
import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.config import settings
from axkg.core.security import generate_token, hash_token, verify_password
from axkg.dto.auth import LoginResultDTO, UserDTO
from axkg.models.base import utcnow
from axkg.repositories.auth_tokens import AuthTokenRepository
from axkg.repositories.users import UserRepository


class InvalidCredentialsError(Exception):
    """email/password 불일치 (Case Matrix: INVALID_CREDENTIALS)."""


class InactiveAccountError(Exception):
    """is_active=false 계정 로그인 시도 (Case Matrix: INACTIVE_ACCOUNT)."""


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)
        self._tokens = AuthTokenRepository(session)

    async def login(self, email: str, password: str) -> LoginResultDTO:
        credentials = await self._users.get_credentials_by_email(email)
        if credentials is None or not verify_password(password, credentials.password_hash):
            raise InvalidCredentialsError
        if not credentials.is_active:
            raise InactiveAccountError
        token = generate_token()
        expires_at = utcnow() + timedelta(days=settings.axkg_auth_token_ttl_days)
        await self._tokens.create(credentials.id, hash_token(token), expires_at)
        return LoginResultDTO(
            token=token,
            expires_at=expires_at,
            user=UserDTO(
                id=credentials.id,
                email=credentials.email,
                display_name=credentials.display_name,
                role=credentials.role,
            ),
        )

    async def resolve_token(self, token: str) -> UserDTO | None:
        """유효(미만료·미회수) token의 사용자. 없으면 None (INVALID_TOKEN 소관은 호출측)."""
        return await self._tokens.get_user_by_active_token_hash(hash_token(token), utcnow())

    async def logout(self, token: str) -> None:
        await self._tokens.revoke_by_hash(hash_token(token), utcnow())

    async def change_password(
        self, user_id: uuid.UUID, current_password: str, new_password: str
    ) -> None:
        """본인 비밀번호 변경 — 현재 비번 검증 후 교체 (강제 아님, AXKG-SPEC-008 BE-4)."""
        from axkg.core.security import hash_password

        stored = await self._users.get_password_hash(user_id)
        if stored is None or not verify_password(current_password, stored):
            raise InvalidCredentialsError
        await self._users.update_password(user_id, hash_password(new_password))
