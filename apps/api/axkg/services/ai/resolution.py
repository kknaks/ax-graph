"""실행 설정 해석 (AXKG-SPEC-007).

병합 순서(SPEC-007 "open-kknaks Task Mapping"):

    global AIProviderSettings
      + AITaskDefinition.default_model/default_options/default_provider_options
      + AIProviderSettings.task_overrides[task_key]
      = ai_tasks.model/options/provider_options snapshot

- task_overrides는 model/options/provider_options만 바꾼다(provider는 못 바꾼다).
- 초기 설정이 없으면 SPEC-007 MVP 기본값을 쓴다.
"""
from typing import Any

from axkg.dto.ai import AiTaskDefinitionDTO, ResolvedExecutionConfigDTO

# SPEC-007 MVP 기본값 — settings.ai_provider seed와 동일한 값의 코드 소유 사본.
DEFAULT_PROVIDER = "claude"
DEFAULT_OPTIONS: dict[str, Any] = {"timeout_sec": 300, "resume": False}
DEFAULT_PROVIDER_OPTIONS: dict[str, Any] = {"max_turns": 3, "effort": "medium"}


def _merge(*layers: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for layer in layers:
        if layer:
            merged.update(layer)
    return merged


def resolve_execution_config(
    global_settings: dict[str, Any] | None,
    definition: AiTaskDefinitionDTO,
) -> ResolvedExecutionConfigDTO:
    """global settings → task definition defaults → task_overrides[task_key] 병합."""
    gs = global_settings or {}
    overrides: dict[str, Any] = (gs.get("task_overrides") or {}).get(definition.key) or {}

    provider = definition.default_provider or gs.get("provider") or DEFAULT_PROVIDER
    model = overrides.get("model") or definition.default_model or gs.get("model")
    options = _merge(
        DEFAULT_OPTIONS,
        gs.get("options"),
        definition.default_options,
        overrides.get("options"),
    )
    provider_options = _merge(
        DEFAULT_PROVIDER_OPTIONS,
        gs.get("provider_options"),
        definition.default_provider_options,
        overrides.get("provider_options"),
    )
    return ResolvedExecutionConfigDTO(
        provider=provider,
        model=model,
        options=options,
        provider_options=provider_options,
    )
