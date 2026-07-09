"""prompts / prompt_versions repository (AXKG-SPEC-009).

- 실행측(pipeline)은 `get_active_version`으로 활성 버전만 로드한다(건드리지 않음).
- 관리 API(WP5 Phase 2)는 목록/버전/저장(새 버전+활성 포인터 이동)/롤백(포인터 이동)을 쓴다.
- 활성 여부는 `PromptVersion` 컬럼이 아니라 `Prompt.active_version_id` 포인터로 판별한다
  (버전 row는 불변 — 저장은 새 버전, 롤백은 포인터만 이동, 복사 없음).
- commit은 DI/route가 한다. 기존 레포 컨벤션과 동일.
"""
import uuid
from typing import Any

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

    # ------------------------------------------------------------------
    # 관리 API용 조회
    # ------------------------------------------------------------------

    async def list_prompts(self) -> list[dict[str, Any]]:
        """프롬프트 목록 + 각 활성 버전 번호(key asc)."""
        prompts = (
            await self._session.scalars(sa.select(Prompt).order_by(Prompt.key.asc()))
        ).all()
        result: list[dict[str, Any]] = []
        for prompt in prompts:
            active = await self._active_version_row(prompt)
            result.append(
                {
                    "key": prompt.key,
                    "name": prompt.name,
                    "active_version": active.version if active is not None else None,
                    "updated_at": prompt.updated_at,
                }
            )
        return result

    async def get_prompt(self, key: str) -> dict[str, Any] | None:
        """단일 프롬프트의 활성 버전 view. 프롬프트가 없으면 None."""
        prompt = await self._prompt_row(key)
        if prompt is None:
            return None
        return self._active_view(prompt, await self._active_version_row(prompt))

    async def list_versions(self, key: str) -> list[dict[str, Any]] | None:
        """버전 목록(version desc, is_active 표시). 프롬프트가 없으면 None."""
        prompt = await self._prompt_row(key)
        if prompt is None:
            return None
        versions = (
            await self._session.scalars(
                sa.select(PromptVersion)
                .where(PromptVersion.prompt_id == prompt.id)
                .order_by(PromptVersion.version.desc())
            )
        ).all()
        return [self._version_view(prompt, v) for v in versions]

    async def get_version(self, key: str, version: int) -> dict[str, Any] | None:
        """특정 버전 view. 프롬프트/버전 없으면 None."""
        prompt = await self._prompt_row(key)
        if prompt is None:
            return None
        row = await self._version_row(prompt.id, version)
        return self._version_view(prompt, row) if row is not None else None

    # ------------------------------------------------------------------
    # 관리 API용 변경
    # ------------------------------------------------------------------

    async def create_version(
        self,
        key: str,
        *,
        prompt_text: str,
        output_schema: dict[str, Any],
        created_by: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """새 버전(version=max+1) 생성 + 활성 포인터 이동. 프롬프트 없으면 None. 기존 버전 불변."""
        prompt = await self._prompt_row(key)
        if prompt is None:
            return None
        current_max = await self._session.scalar(
            sa.select(sa.func.max(PromptVersion.version)).where(
                PromptVersion.prompt_id == prompt.id
            )
        )
        row = PromptVersion(
            prompt_id=prompt.id,
            version=(current_max or 0) + 1,
            prompt_text=prompt_text,
            output_schema=output_schema,
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.flush()
        prompt.active_version_id = row.id
        await self._session.flush()
        return self._active_view(prompt, row)

    async def set_active(self, key: str, version: int) -> dict[str, Any] | None:
        """롤백 — 대상 버전으로 active 포인터만 이동(복사 없음). 프롬프트/버전 없으면 None."""
        prompt = await self._prompt_row(key)
        if prompt is None:
            return None
        target = await self._version_row(prompt.id, version)
        if target is None:
            return None
        prompt.active_version_id = target.id
        await self._session.flush()
        return self._active_view(prompt, target)

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    async def _prompt_row(self, key: str) -> Prompt | None:
        return await self._session.scalar(sa.select(Prompt).where(Prompt.key == key))

    async def _version_row(
        self, prompt_id: uuid.UUID, version: int
    ) -> PromptVersion | None:
        return await self._session.scalar(
            sa.select(PromptVersion).where(
                PromptVersion.prompt_id == prompt_id,
                PromptVersion.version == version,
            )
        )

    async def _active_version_row(self, prompt: Prompt) -> PromptVersion | None:
        if prompt.active_version_id is None:
            return None
        return await self._session.get(PromptVersion, prompt.active_version_id)

    @staticmethod
    def _active_view(prompt: Prompt, version: PromptVersion | None) -> dict[str, Any]:
        if version is None:
            return {
                "key": prompt.key,
                "name": prompt.name,
                "version": None,
                "prompt_text": None,
                "output_schema": None,
                "is_active": False,
                "updated_at": prompt.updated_at,
            }
        return {
            "key": prompt.key,
            "name": prompt.name,
            "version": version.version,
            "prompt_text": version.prompt_text,
            "output_schema": version.output_schema,
            "is_active": True,
            "updated_at": version.created_at,
        }

    @staticmethod
    def _version_view(prompt: Prompt, version: PromptVersion) -> dict[str, Any]:
        return {
            "version": version.version,
            "prompt_text": version.prompt_text,
            "output_schema": version.output_schema,
            "is_active": version.id == prompt.active_version_id,
            "updated_at": version.created_at,
        }
