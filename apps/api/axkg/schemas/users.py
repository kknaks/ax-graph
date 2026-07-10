"""유저 관리 API 요청/응답 (AXKG-SPEC-008 §3, admin 전용). WP6 BE-3."""
import uuid
from typing import Literal

from pydantic import BaseModel, Field

RoleLiteral = Literal["admin", "staff"]


class UserAdminResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None = None
    role: str
    is_active: bool


class UsersListResponse(BaseModel):
    users: list[UserAdminResponse]


class CreateUserRequest(BaseModel):
    email: str = Field(min_length=1)
    display_name: str | None = None
    role: RoleLiteral = "staff"


class ChangeRoleRequest(BaseModel):
    role: RoleLiteral


class ToggleActiveRequest(BaseModel):
    is_active: bool
