"""SQLAlchemy engine/session. 스키마 SoT는 40-architecture/database README. WP0 Phase 3.

SQLAlchemy 2.0 async (postgresql+psycopg, psycopg3 async).
session lifecycle은 여기(DI)가 소유한다: 요청 성공 시 commit, 예외 시 rollback.
repository만 session을 만진다 — service/route는 session을 repository로 전달만 한다.
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from axkg.config import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.axkg_database_url)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI DI용 request-scoped session. 테스트는 이 dependency를 override한다."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
