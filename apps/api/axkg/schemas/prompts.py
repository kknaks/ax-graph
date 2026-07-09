"""프롬프트 관리 API 요청/응답 (AXKG-SPEC-009 §4 Data Contract).

FE(WP5 Phase 4 Prompts 탭)가 이 계약으로 붙는다. 필드명은 spec Data Contract를 따른다
(`key`/`prompt_text`/`output_schema`/`version`/`is_active`/`active_version`/`updated_at`).
output_schema 내용 검증은 service의 jsonschema가 담당(여기 pydantic은 dict 타입만).
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 요청
# ---------------------------------------------------------------------------


class SavePromptRequest(BaseModel):
    """POST /prompts/{key}/versions — 본문+스키마 한 쌍으로 새 버전 저장."""

    prompt_text: str
    output_schema: dict[str, Any] = Field(default_factory=dict)


class RollbackPromptRequest(BaseModel):
    """POST /prompts/{key}/rollback — 활성으로 만들 대상 version."""

    version: int


# ---------------------------------------------------------------------------
# 응답
# ---------------------------------------------------------------------------


class PromptSummary(BaseModel):
    """GET /prompts 목록 아이템."""

    key: str
    name: str
    active_version: int | None = None
    updated_at: datetime | None = None


class PromptListResponse(BaseModel):
    prompts: list[PromptSummary]


class PromptActiveResponse(BaseModel):
    """활성 버전 view — GET /prompts/{key}, POST versions/rollback 반환."""

    key: str
    name: str
    version: int | None = None
    prompt_text: str | None = None
    output_schema: dict[str, Any] | None = None
    is_active: bool = False
    updated_at: datetime | None = None


class PromptVersionView(BaseModel):
    """GET /prompts/{key}/versions 아이템."""

    version: int
    prompt_text: str
    output_schema: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = False
    updated_at: datetime | None = None


class PromptVersionListResponse(BaseModel):
    key: str
    versions: list[PromptVersionView]
