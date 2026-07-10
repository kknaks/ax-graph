"""users repository (AXKG-SPEC-008). session 접근은 이 계층에서만."""
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.auth import UserAdminDTO, UserCredentialsDTO, UserDTO
from axkg.models import User


def _to_user_dto(user: User) -> UserDTO:
    return UserDTO(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
    )


def _to_admin_dto(user: User) -> UserAdminDTO:
    return UserAdminDTO(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
    )


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
            role=user.role,
            is_active=user.is_active,
            password_hash=user.password_hash,
        )

    async def get_by_id(self, user_id: uuid.UUID) -> UserDTO | None:
        user = await self._session.get(User, user_id)
        return _to_user_dto(user) if user is not None else None

    # --- 유저 관리 (admin 전용, AXKG-SPEC-008 §3 BE-3) --------------------------

    async def list_all(self) -> list[UserAdminDTO]:
        users = await self._session.scalars(
            sa.select(User).order_by(User.created_at.asc())
        )
        return [_to_admin_dto(u) for u in users]

    async def email_exists(self, email: str) -> bool:
        found = await self._session.scalar(
            sa.select(User.id).where(User.email == email)
        )
        return found is not None

    async def create(
        self, email: str, display_name: str | None, role: str, password_hash: str
    ) -> UserAdminDTO:
        user = User(
            email=email,
            display_name=display_name,
            role=role,
            is_active=True,
            password_hash=password_hash,
        )
        self._session.add(user)
        await self._session.flush()
        return _to_admin_dto(user)

    async def set_role(self, user_id: uuid.UUID, role: str) -> UserAdminDTO | None:
        user = await self._session.get(User, user_id)
        if user is None:
            return None
        user.role = role
        await self._session.flush()
        return _to_admin_dto(user)

    async def set_active(
        self, user_id: uuid.UUID, is_active: bool
    ) -> UserAdminDTO | None:
        user = await self._session.get(User, user_id)
        if user is None:
            return None
        user.is_active = is_active
        await self._session.flush()
        return _to_admin_dto(user)

    # --- 본인 비밀번호 변경 (AXKG-SPEC-008 §3 BE-4) ---------------------------

    async def get_password_hash(self, user_id: uuid.UUID) -> str | None:
        return await self._session.scalar(
            sa.select(User.password_hash).where(User.id == user_id)
        )

    async def update_password(self, user_id: uuid.UUID, password_hash: str) -> None:
        await self._session.execute(
            sa.update(User)
            .where(User.id == user_id)
            .values(password_hash=password_hash)
        )
        await self._session.flush()
