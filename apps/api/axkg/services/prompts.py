"""프롬프트 동적 관리 service (AXKG-SPEC-009). WP5 Phase 2.

경계:
- 목록/버전/저장(텍스트+스키마 쌍 → 새 버전 + 활성)/롤백(포인터 이동)까지.
- AI 실행 시 활성 버전 로드는 `pipeline._load_active_prompt`가 담당 — 건드리지 않는다.
- Templates(Phase 3)·FE(Phase 4)는 이 service 밖이다.

저장은 항상 **새 버전**을 만든다(기존 버전 불변). 롤백은 기존 버전으로 active 포인터만 옮긴다.
output_schema는 유효한 JSON Schema여야 실행 파이프라인의 구조화 출력 계약으로 쓸 수 있다.
"""
from __future__ import annotations

import uuid
from typing import Any

import jsonschema
from jsonschema.validators import validator_for
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.repositories.prompts import PromptRepository


class PromptNotFoundError(Exception):
    """존재하지 않는 프롬프트 key (Case Matrix: PROMPT_NOT_FOUND)."""

    def __init__(self, key: str) -> None:
        super().__init__(f"prompt not found: {key}")
        self.key = key


class EmptyPromptBodyError(Exception):
    """prompt_text 공백 (Case Matrix: EMPTY_PROMPT_BODY)."""


class InvalidOutputSchemaError(Exception):
    """output_schema가 유효한 JSON Schema가 아님 (Case Matrix: INVALID_OUTPUT_SCHEMA)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"invalid output schema: {reason}")
        self.reason = reason


class PromptVersionNotFoundError(Exception):
    """롤백 대상 버전 없음 (Case Matrix: PROMPT_VERSION_NOT_FOUND)."""

    def __init__(self, key: str, version: int) -> None:
        super().__init__(f"prompt version not found: {key} v{version}")
        self.key = key
        self.version = version


class PromptSaveError(Exception):
    """버전 저장 실패 (Case Matrix: PROMPT_SAVE_FAILED)."""


class PromptService:
    def __init__(self, session: AsyncSession) -> None:
        self._prompts = PromptRepository(session)

    async def list(self) -> list[dict[str, Any]]:
        return await self._prompts.list_prompts()

    async def get(self, key: str) -> dict[str, Any]:
        view = await self._prompts.get_prompt(key)
        if view is None:
            raise PromptNotFoundError(key)
        return view

    async def versions(self, key: str) -> list[dict[str, Any]]:
        views = await self._prompts.list_versions(key)
        if views is None:
            raise PromptNotFoundError(key)
        return views

    async def save(
        self,
        key: str,
        *,
        prompt_text: str,
        output_schema: dict[str, Any],
        created_by: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """새 버전 저장 + 활성화. 본문/스키마 검증 → key 확인 순."""
        if not (prompt_text or "").strip():
            raise EmptyPromptBodyError
        self._validate_output_schema(output_schema)
        try:
            view = await self._prompts.create_version(
                key,
                prompt_text=prompt_text,
                output_schema=output_schema,
                created_by=created_by,
            )
        except Exception as exc:  # noqa: BLE001 — 저장 실패는 코드로 표면화
            raise PromptSaveError(str(exc)) from exc
        if view is None:
            raise PromptNotFoundError(key)
        return view

    async def rollback(self, key: str, version: int) -> dict[str, Any]:
        """지정 버전으로 active 포인터를 옮긴다(새 row 없음)."""
        if await self._prompts.get_prompt(key) is None:
            raise PromptNotFoundError(key)
        if await self._prompts.get_version(key, version) is None:
            raise PromptVersionNotFoundError(key, version)
        view = await self._prompts.set_active(key, version)
        if view is None:  # 경합 등으로 사라진 경우 방어
            raise PromptVersionNotFoundError(key, version)
        return view

    @staticmethod
    def _validate_output_schema(output_schema: Any) -> None:
        """output_schema 자체가 유효한 JSON Schema인지 검사(파싱/메타스키마)."""
        if not isinstance(output_schema, dict):
            raise InvalidOutputSchemaError("object가 아닙니다")
        try:
            validator_cls = validator_for(output_schema)
            validator_cls.check_schema(output_schema)
        except jsonschema.SchemaError as exc:
            raise InvalidOutputSchemaError(exc.message) from exc
        except Exception as exc:  # noqa: BLE001 — 어떤 파싱 실패든 무효 스키마로 표면화
            raise InvalidOutputSchemaError(str(exc)) from exc
