"""settings repository (AXKG-SPEC-007). keyed JSONB 설정 조회."""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.models import Setting


class SettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_value(self, key: str) -> dict[str, Any] | None:
        row = await self._session.get(Setting, key)
        return row.value if row is not None else None
