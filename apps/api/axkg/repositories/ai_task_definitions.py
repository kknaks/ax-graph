"""ai_task_definitions repository (AXKG-SPEC-007/011). key로 정의를 해석한다."""
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.ai import AiTaskDefinitionDTO
from axkg.models import AiTaskDefinition


def _to_dto(row: AiTaskDefinition) -> AiTaskDefinitionDTO:
    return AiTaskDefinitionDTO(
        id=row.id,
        key=row.key,
        display_name=row.display_name,
        handler_kind=row.handler_kind,
        prompt_key=row.prompt_key,
        template_key=row.template_key,
        default_provider=row.default_provider,
        default_model=row.default_model,
        default_options=row.default_options or {},
        default_provider_options=row.default_provider_options or {},
        enabled=row.enabled,
    )


class AiTaskDefinitionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_key(self, key: str) -> AiTaskDefinitionDTO | None:
        row = await self._session.scalar(
            sa.select(AiTaskDefinition).where(AiTaskDefinition.key == key)
        )
        return _to_dto(row) if row is not None else None
