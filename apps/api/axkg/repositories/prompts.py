"""prompts / prompt_versions repository (AXKG-SPEC-009). 실행측은 활성 버전 로드만."""
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.ai import PromptVersionDTO
from axkg.models import Prompt, PromptVersion


class PromptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_version(self, prompt_key: str) -> PromptVersionDTO | None:
        """prompt_key의 활성 버전. 프롬프트가 없거나 active_version_id가 비면 None."""
        stmt = (
            sa.select(Prompt, PromptVersion)
            .join(PromptVersion, PromptVersion.id == Prompt.active_version_id)
            .where(Prompt.key == prompt_key)
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return None
        prompt, version = row
        return PromptVersionDTO(
            id=version.id,
            prompt_id=prompt.id,
            prompt_key=prompt.key,
            version=version.version,
            prompt_text=version.prompt_text,
            output_schema=version.output_schema,
        )
