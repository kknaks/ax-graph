"""AI Provider 설정 service (AXKG-SPEC-007). WP5 Phase 1.

경계:
- 이 Phase는 AI Provider 전역 설정 조회/갱신 + task override CRUD + health까지다.
- 실행 설정 **병합**은 재구현하지 않는다 — `services/ai/resolution.py`의
  `resolve_execution_config`가 task 생성 시점에 소유한다. 이 service는 그 위에 API만 얹는다.
- 설정 변경 비소급: resolution이 task 생성 시점 snapshot만 쓰므로 기존 queued/running
  ai_tasks에는 영향이 없다(구조적 보장, 테스트로 못박음).
- Prompts(SPEC-009 Phase 2)·Templates(Phase 3)는 이 service 밖이다.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.repositories.ai_task_definitions import AiTaskDefinitionRepository
from axkg.repositories.settings import SettingRepository
from axkg.seeds import AI_PROVIDER_DEFAULT

AI_PROVIDER_KEY = "ai_provider"
SUPPORTED_PROVIDERS = ("claude", "codex")
VALID_EFFORTS = ("low", "medium", "high")
# 응답에서 제외할 credential류 키(SPEC-007 Pre-deploy — 값을 밖으로 내지 않는다).
_SENSITIVE_KEYS = ("api_key", "apikey", "token", "secret", "credential", "credentials", "password")


class UnsupportedProviderError(Exception):
    """provider ∉ {claude, codex} (Case Matrix: UNSUPPORTED_PROVIDER)."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"unsupported provider: {provider}")
        self.provider = provider


class InvalidExecutionLimitError(Exception):
    """실행 한도 범위/타입 오류 (Case Matrix: INVALID_EXECUTION_LIMIT)."""

    def __init__(self, field: str, reason: str = "") -> None:
        super().__init__(f"invalid execution limit: {field} {reason}".strip())
        self.field = field


class UnknownTaskDefinitionError(Exception):
    """override 대상 task_key가 미등록이거나 enabled=false (task_overrides 규칙 위반)."""

    def __init__(self, task_key: str) -> None:
        super().__init__(f"unknown or disabled task definition: {task_key}")
        self.task_key = task_key


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self._settings = SettingRepository(session)
        self._definitions = AiTaskDefinitionRepository(session)

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------

    async def get_ai_provider(self) -> dict[str, Any]:
        """현재 AI provider 설정. 없으면 SPEC-007 MVP 기본값(claude)."""
        row = await self._settings.get(AI_PROVIDER_KEY)
        if row is None:
            return self._sanitize(dict(AI_PROVIDER_DEFAULT))
        value = self._sanitize(dict(row.value))
        value["updated_at"] = row.updated_at
        return value

    async def get_health(self) -> list[dict[str, Any]]:
        """Claude/Codex provider 상태 (MVP 최소).

        open-kknaks client에 health 개념이 없어(과설계 금지) 설정된 provider는 `available`,
        그 외 지원 provider는 `unknown`으로 시작한다. 실제 worker 연결 probe는 후속.
        """
        current = await self.get_ai_provider()
        configured = current.get("provider")
        health: list[dict[str, Any]] = []
        for provider in SUPPORTED_PROVIDERS:
            if provider == configured:
                health.append(
                    {"provider": provider, "status": "available", "message": "설정된 provider"}
                )
            else:
                health.append(
                    {
                        "provider": provider,
                        "status": "unknown",
                        "message": "worker 연결 상태 미확인",
                    }
                )
        return health

    # ------------------------------------------------------------------
    # 갱신 — 전역
    # ------------------------------------------------------------------

    async def put_ai_provider(
        self,
        *,
        provider: str,
        model: str | None,
        options: dict[str, Any],
        provider_options: dict[str, Any],
        updated_by: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """전역 provider/model/options/provider_options 저장(task_overrides는 보존)."""
        self._validate_provider(provider)
        self._validate_limits(options, provider_options)

        current = await self._settings.get_value(AI_PROVIDER_KEY) or dict(AI_PROVIDER_DEFAULT)
        value = {
            "provider": provider,
            "model": model,
            "options": dict(options),
            "provider_options": dict(provider_options),
            "task_overrides": current.get("task_overrides") or {},
        }
        return await self._save(value, updated_by)

    # ------------------------------------------------------------------
    # 갱신 — task override
    # ------------------------------------------------------------------

    async def put_task_override(
        self,
        task_key: str,
        *,
        model: str | None,
        options: dict[str, Any],
        provider_options: dict[str, Any],
        updated_by: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """등록+enabled task definition에만 override를 저장한다(provider는 override 불가)."""
        definition = await self._definitions.get_by_key(task_key)
        if definition is None or not definition.enabled:
            raise UnknownTaskDefinitionError(task_key)
        self._validate_limits(options, provider_options)

        current = await self._settings.get_value(AI_PROVIDER_KEY) or dict(AI_PROVIDER_DEFAULT)
        overrides = dict(current.get("task_overrides") or {})
        override: dict[str, Any] = {
            "options": dict(options),
            "provider_options": dict(provider_options),
        }
        if model is not None:
            override["model"] = model
        overrides[task_key] = override

        value = {
            "provider": current.get("provider", AI_PROVIDER_DEFAULT["provider"]),
            "model": current.get("model"),
            "options": current.get("options") or {},
            "provider_options": current.get("provider_options") or {},
            "task_overrides": overrides,
        }
        return await self._save(value, updated_by)

    async def delete_task_override(
        self, task_key: str, *, updated_by: uuid.UUID | None = None
    ) -> dict[str, Any]:
        """task override를 제거한다(없으면 no-op — 멱등)."""
        current = await self._settings.get_value(AI_PROVIDER_KEY) or dict(AI_PROVIDER_DEFAULT)
        overrides = dict(current.get("task_overrides") or {})
        overrides.pop(task_key, None)
        value = {
            "provider": current.get("provider", AI_PROVIDER_DEFAULT["provider"]),
            "model": current.get("model"),
            "options": current.get("options") or {},
            "provider_options": current.get("provider_options") or {},
            "task_overrides": overrides,
        }
        return await self._save(value, updated_by)

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    async def _save(
        self, value: dict[str, Any], updated_by: uuid.UUID | None
    ) -> dict[str, Any]:
        row = await self._settings.set_value(AI_PROVIDER_KEY, value, updated_by=updated_by)
        saved = self._sanitize(dict(row.value))
        saved["updated_at"] = row.updated_at
        return saved

    @staticmethod
    def _validate_provider(provider: str) -> None:
        if provider not in SUPPORTED_PROVIDERS:
            raise UnsupportedProviderError(provider)

    def _validate_limits(
        self, options: dict[str, Any], provider_options: dict[str, Any]
    ) -> None:
        """존재하는 실행 한도 필드만 범위/타입 검증한다(부분 override 허용)."""
        timeout = options.get("timeout_sec")
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, int) or not (
                30 <= timeout <= 3600
            ):
                raise InvalidExecutionLimitError("timeout_sec", "30~3600")

        resume = options.get("resume")
        if resume is not None and not isinstance(resume, bool):
            raise InvalidExecutionLimitError("resume", "boolean")

        max_turns = provider_options.get("max_turns")
        if max_turns is not None:
            if isinstance(max_turns, bool) or not isinstance(max_turns, int) or not (
                1 <= max_turns <= 20
            ):
                raise InvalidExecutionLimitError("max_turns", "1~20")

        effort = provider_options.get("effort")
        if effort is not None and effort not in VALID_EFFORTS:
            raise InvalidExecutionLimitError("effort", "low|medium|high")

    @classmethod
    def _sanitize(cls, value: dict[str, Any]) -> dict[str, Any]:
        """응답서 credential류 키를 제거한다(options/provider_options/task_overrides 재귀)."""
        value["options"] = cls._strip_sensitive(value.get("options") or {})
        value["provider_options"] = cls._strip_sensitive(value.get("provider_options") or {})
        overrides = value.get("task_overrides") or {}
        value["task_overrides"] = {
            key: cls._sanitize_override(dict(ov)) for key, ov in overrides.items()
        }
        return value

    @classmethod
    def _sanitize_override(cls, override: dict[str, Any]) -> dict[str, Any]:
        if "options" in override:
            override["options"] = cls._strip_sensitive(override["options"] or {})
        if "provider_options" in override:
            override["provider_options"] = cls._strip_sensitive(
                override["provider_options"] or {}
            )
        return override

    @staticmethod
    def _strip_sensitive(obj: dict[str, Any]) -> dict[str, Any]:
        return {
            k: v for k, v in obj.items() if k.lower() not in _SENSITIVE_KEYS
        }
