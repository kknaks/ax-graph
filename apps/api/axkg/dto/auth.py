"""auth 내부 DTO (AXKG-SPEC-008)."""
import uuid
from datetime import datetime

from pydantic import BaseModel


class UserDTO(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None = None
    role: str = "staff"


class UserCredentialsDTO(BaseModel):
    """로그인 검증용 — repository 밖으로는 password_hash를 노출하지 않는다."""

    id: uuid.UUID
    email: str
    display_name: str | None = None
    role: str = "staff"
    is_active: bool = True
    password_hash: str


class UserAdminDTO(BaseModel):
    """유저 관리(admin) 조회용 — password_hash는 노출하지 않는다 (AXKG-SPEC-008 §3)."""

    id: uuid.UUID
    email: str
    display_name: str | None = None
    role: str
    is_active: bool


class LoginResultDTO(BaseModel):
    token: str
    expires_at: datetime
    user: UserDTO


class AuthContextDTO(BaseModel):
    """Bearer 검증 dependency 결과 — user + 요청에 실려온 raw token."""

    user: UserDTO
    token: str
