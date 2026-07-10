"""auth API 요청/응답 (AXKG-SPEC-008 API Contract)."""
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserResponse(BaseModel):
    email: str
    display_name: str | None = None
    role: str


class LoginResponse(BaseModel):
    token: str
    user: UserResponse


class MeResponse(BaseModel):
    user: UserResponse


class LogoutResponse(BaseModel):
    ok: bool = True


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


class ChangePasswordResponse(BaseModel):
    ok: bool = True
