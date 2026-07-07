"""users repository (AXKG-SPEC-008)."""
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.auth import UserCredentialsDTO, UserDTO
from axkg.models import User


def _to_user_dto(user: User) -> UserDTO:
    return UserDTO(id=user.id, email=user.email, display_name=user.display_name)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_credentials_by_email(self, email: str) -> UserCredentialsDTO | None:
        user = await self._session.scalar(sa.select(User).where(User.email == email))
        if user is None:
            return None
        return UserCredentialsDTO(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            password_hash=user.password_hash,
        )

    async def get_by_id(self, user_id: uuid.UUID) -> UserDTO | None:
        user = await self._session.get(User, user_id)
        return _to_user_dto(user) if user is not None else None
