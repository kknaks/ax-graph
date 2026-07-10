"""유저 관리 서비스 (AXKG-SPEC-008 §3, admin 전용). WP6 BE-3.

- 생성: 기본 비밀번호 `1234`(운영 보안 기준 아님). 공개 가입 없음.
- 역할 변경/활성 토글: admin 전용(라우트 authz가 강제).
권한 경계 자체는 라우터 include의 require_admin이 소유한다.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.core.security import hash_password
from axkg.dto.auth import UserAdminDTO
from axkg.repositories.users import UserRepository

# AXKG-SPEC-008: admin이 유저 생성 시 기본 비밀번호. 최초 로그인 강제 변경은 하지 않는다.
DEFAULT_NEW_USER_PASSWORD = "1234"
VALID_ROLES = ("admin", "staff")


class EmailExistsError(Exception):
    """이미 존재하는 email로 유저 생성 시도."""


class UserNotFoundError(Exception):
    """대상 유저가 없음."""


class InvalidRoleError(Exception):
    """role이 admin/staff가 아님."""


class UserManagementService:
    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)

    async def list_users(self) -> list[UserAdminDTO]:
        return await self._users.list_all()

    async def create_user(
        self, email: str, display_name: str | None, role: str
    ) -> UserAdminDTO:
        if role not in VALID_ROLES:
            raise InvalidRoleError
        if await self._users.email_exists(email):
            raise EmailExistsError
        return await self._users.create(
            email=email,
            display_name=display_name,
            role=role,
            password_hash=hash_password(DEFAULT_NEW_USER_PASSWORD),
        )

    async def change_role(self, user_id: uuid.UUID, role: str) -> UserAdminDTO:
        if role not in VALID_ROLES:
            raise InvalidRoleError
        dto = await self._users.set_role(user_id, role)
        if dto is None:
            raise UserNotFoundError
        return dto

    async def set_active(self, user_id: uuid.UUID, is_active: bool) -> UserAdminDTO:
        dto = await self._users.set_active(user_id, is_active)
        if dto is None:
            raise UserNotFoundError
        return dto
