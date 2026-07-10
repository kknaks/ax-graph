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

# SPEC-007 MVP 기본값 — settings.ai_provider seed(AI_PROVIDER_DEFAULT)와 동일한 값의
# 코드 소유 사본(ai_provider row 부재 시 fallback). PLAN-010-T-012로 운영값 정합.
DEFAULT_PROVIDER = "claude"
DEFAULT_OPTIONS: dict[str, Any] = {"timeout_sec": 300, "resume": True}
DEFAULT_PROVIDER_OPTIONS: dict[str, Any] = {"max_turns": 20, "effort": "medium"}


def is_resume_session(options: dict[str, Any] | None) -> bool:
    """options.resume가 **실제 세션 resume**인가 (open-kknaks claude executor 계약).

    executor는 resume가 `{"mode": "session", "session_id": ...}` dict일 때만 `--resume`한다
    (`gates.py _enqueue_task`가 배선하는 유일한 형태). 글로벌 설정에서 스냅샷된 bare `True`나
    `False`/`None`은 **새 세션**이므로 feedback-only 컨텍스트를 조립하면 안 된다 — 그 조합에서
    원문/요약 없이 feedback 블록만 공급되는 조용한 컨텍스트 유실을 막는다(PLAN-010-T-008).
    """
    resume = (options or {}).get("resume")
    return (
        isinstance(resume, dict)
        and resume.get("mode") == "session"
        and bool(resume.get("session_id"))
    )


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
