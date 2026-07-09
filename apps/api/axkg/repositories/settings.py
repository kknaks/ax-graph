"""settings repository (AXKG-SPEC-007). keyed JSONB 설정 조회/저장."""
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.models import Setting


class SettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_value(self, key: str) -> dict[str, Any] | None:
        row = await self._session.get(Setting, key)
        return row.value if row is not None else None

    async def get(self, key: str) -> Setting | None:
        return await self._session.get(Setting, key)

    async def set_value(
        self,
        key: str,
        value: dict[str, Any],
        *,
        updated_by: uuid.UUID | None = None,
    ) -> Setting:
        """key 설정을 upsert한다(전체 value 교체). commit은 DI/route가 한다.

        value는 새 dict로 재할당해 JSONB 변경이 감지되게 한다(부분 mutate 금지).
        """
        row = await self._session.get(Setting, key)
        if row is None:
            row = Setting(key=key, value=value, updated_by=updated_by)
            self._session.add(row)
        else:
            row.value = value
            row.updated_by = updated_by
        await self._session.flush()
        return row
