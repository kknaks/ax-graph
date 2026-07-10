"""auth_tokens repository (AXKG-SPEC-008). token_hash만 저장/조회한다."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.auth import UserDTO
from axkg.models import AuthToken, User


class AuthTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, user_id: uuid.UUID, token_hash: str, expires_at: datetime
    ) -> None:
        self._session.add(
            AuthToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        )
        await self._session.flush()

    async def get_user_by_active_token_hash(
        self, token_hash: str, now: datetime
    ) -> UserDTO | None:
        stmt = (
            sa.select(User)
            .join(AuthToken, AuthToken.user_id == User.id)
            .where(
                AuthToken.token_hash == token_hash,
                AuthToken.revoked_at.is_(None),
                AuthToken.expires_at > now,
            )
        )
        user = await self._session.scalar(stmt)
        if user is None:
            return None
        return UserDTO(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
        )

    async def revoke_by_hash(self, token_hash: str, now: datetime) -> bool:
        result = await self._session.execute(
            sa.update(AuthToken)
            .where(AuthToken.token_hash == token_hash, AuthToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await self._session.flush()
        return result.rowcount > 0
