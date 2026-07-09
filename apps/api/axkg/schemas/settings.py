"""AI Provider 설정 API 요청/응답 (AXKG-SPEC-007 §4 Data Contract).

FE(WP5 Phase 4)가 이 계약으로 붙는다. 필드명은 spec Data Contract를 정확히 따른다.
값 범위 검증(timeout_sec/max_turns/effort/provider)은 정확한 error_code를 내기 위해
service 계층에서 수행한다(여기 pydantic은 타입만 강제).
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AIProviderSettingsRequest(BaseModel):
    """PUT /settings/ai-provider — 전역 provider/default options 저장.

    task_overrides는 이 요청으로 건드리지 않는다(별도 엔드포인트에서 관리, 저장 시 보존).
    """

    provider: str
    model: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    provider_options: dict[str, Any] = Field(default_factory=dict)


class TaskOverrideRequest(BaseModel):
    """PUT /settings/ai-provider/task-overrides/{task_key} — task별 override.

    provider는 override 대상이 아니다(SPEC-007: model/options/provider_options만).
    """

    model: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    provider_options: dict[str, Any] = Field(default_factory=dict)


class AIProviderSettingsResponse(BaseModel):
    provider: str
    model: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    provider_options: dict[str, Any] = Field(default_factory=dict)
    task_overrides: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime | None = None

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "AIProviderSettingsResponse":
        return cls(
            provider=value.get("provider", "claude"),
            model=value.get("model"),
            options=value.get("options") or {},
            provider_options=value.get("provider_options") or {},
            task_overrides=value.get("task_overrides") or {},
            updated_at=value.get("updated_at"),
        )


class ProviderHealth(BaseModel):
    provider: str
    status: str  # available | unavailable | unknown
    message: str | None = None


class ProviderHealthResponse(BaseModel):
    providers: list[ProviderHealth]
