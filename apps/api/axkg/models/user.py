"""users / auth_tokens (AXKG-SPEC-008). token은 hash로만 저장한다."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from axkg.models.base import Base, created_at_col, updated_at_col, uuid_pk


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(sa.Text(), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    display_name: Mapped[str | None] = mapped_column(sa.Text())
    # AXKG-SPEC-008: role 2값(admin/staff, 기본 staff), is_active=false면 로그인 차단.
    role: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="staff")
    is_active: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(sa.Text(), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
