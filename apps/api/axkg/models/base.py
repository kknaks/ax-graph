"""ORM 공통 Base·타입 헬퍼. 스키마 SoT는 40-architecture/database README.

- PG 전용 타입(JSONB, TEXT[])은 variant로 선언해 테스트(sqlite+aiosqlite)의
  ``create_all``에서도 동작하게 한다. 실제 PG 스키마는 alembic 마이그레이션이 SSOT다.
- 순환 FK(gates↔revisions, feedback↔revisions, tasks↔revisions,
  messages↔runs, sources→gates, prompts/templates→versions)는 모델에서는
  plain uuid 컬럼으로 두고, FK 제약은 마이그레이션에서만 건다
  (README "Recommended Migration Order" 순환 회피 규칙).
- 인덱스는 마이그레이션에서만 정의한다(partial/GIN 포함). 모델은
  PK/FK/unique/CHECK 제약까지만 가진다.
"""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# PG에서는 JSONB, 그 외(테스트 sqlite)에서는 JSON.
JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
# PG에서는 TEXT[], 그 외에서는 JSON 배열.
TEXT_ARRAY = sa.JSON().with_variant(postgresql.ARRAY(sa.Text()), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(sa.DateTime(timezone=True), nullable=False, default=utcnow)


def updated_at_col() -> Mapped[datetime]:
    return mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
