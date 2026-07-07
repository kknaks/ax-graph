"""AI 실행 파이프라인 내부 DTO (AXKG-SPEC-011/007). WP0 Phase 5.

- ResolvedExecutionConfigDTO: SPEC-007 병합 순서(global → definition defaults →
  task_overrides)의 결과 스냅샷.
- AssembledInputDTO: 블록 조립 결과. 변수 치환이 아니라 블록을 쌓는다
  (AXKG-SPEC-011 Assembly Contract).
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AiTaskDefinitionDTO(BaseModel):
    id: uuid.UUID
    key: str
    display_name: str
    handler_kind: str
    prompt_key: str
    template_key: str | None = None
    default_provider: str | None = None
    default_model: str | None = None
    default_options: dict[str, Any] = Field(default_factory=dict)
    default_provider_options: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class PromptVersionDTO(BaseModel):
    id: uuid.UUID
    prompt_id: uuid.UUID
    prompt_key: str
    version: int
    prompt_text: str
    output_schema: dict[str, Any]


class TemplateVersionDTO(BaseModel):
    id: uuid.UUID
    template_id: uuid.UUID
    template_key: str
    version: int
    body: str


class ResolvedExecutionConfigDTO(BaseModel):
    """SPEC-007 실행 설정 병합 결과 — ai_tasks에 생성 시점 스냅샷된다."""

    provider: str
    model: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    provider_options: dict[str, Any] = Field(default_factory=dict)


class AssembledBlockDTO(BaseModel):
    """조립 입력의 문자열 블록 하나.

    kind: ``prompt``(지시) / ``template_frame``(코드 프레임+템플릿 body) /
    ``data``(handler가 준 데이터) / ``output_contract``(코드 프레임+output_schema).
    """

    kind: str
    label: str
    text: str


class AssembledInputDTO(BaseModel):
    """블록 조립 결과 + 사용 버전 스냅샷 + fallback 관찰 기록."""

    blocks: list[AssembledBlockDTO] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    prompt_version_id: uuid.UUID | None = None
    template_version_id: uuid.UUID | None = None
    # Case Matrix 관찰 코드: PROMPT_FALLBACK_USED / TEMPLATE_FALLBACK_USED
    fallback_codes: list[str] = Field(default_factory=list)

    def render_prompt(self) -> str:
        """블록을 순서대로 쌓아 open-kknaks ``Task.prompt`` 텍스트를 만든다."""
        return "\n\n---\n\n".join(block.text for block in self.blocks)


class AiTaskDTO(BaseModel):
    id: uuid.UUID
    task_type: str
    task_definition_id: uuid.UUID | None = None
    status: str
    source_id: uuid.UUID | None = None
    gate_id: uuid.UUID | None = None
    revision_id: uuid.UUID | None = None
    retry_of_task_id: uuid.UUID | None = None
    retry_count: int = 0
    provider: str
    model: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    provider_options: dict[str, Any] = Field(default_factory=dict)
    open_kknaks_task_id: str | None = None
    open_kknaks_session_id: str | None = None
    prompt_version_id: uuid.UUID | None = None
    template_version_id: uuid.UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
