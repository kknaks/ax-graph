"""문서 템플릿 관리 API 요청/응답 (AXKG-SPEC-010 §4 Data Contract).

FE(WP5 Phase 4 Templates 탭)가 이 계약으로 붙는다. 필드명은 spec Data Contract를 따른다
(`key`/`body`/`version`/`is_active`/`active_version`/`updated_at`). Prompt와 달리
output_schema가 없다(템플릿은 md `body`만).
"""
from datetime import datetime

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# 요청
# ---------------------------------------------------------------------------


class SaveTemplateRequest(BaseModel):
    """POST /templates/{key}/versions — 새 body로 새 버전 저장."""

    body: str


class RollbackTemplateRequest(BaseModel):
    """POST /templates/{key}/rollback — 활성으로 만들 대상 version."""

    version: int


# ---------------------------------------------------------------------------
# 응답
# ---------------------------------------------------------------------------


class TemplateSummary(BaseModel):
    """GET /templates 목록 아이템."""

    key: str
    name: str
    active_version: int | None = None
    updated_at: datetime | None = None


class TemplateListResponse(BaseModel):
    templates: list[TemplateSummary]


class TemplateActiveResponse(BaseModel):
    """활성 버전 view — GET /templates/{key}, POST versions/rollback 반환."""

    key: str
    name: str
    version: int | None = None
    body: str | None = None
    is_active: bool = False
    updated_at: datetime | None = None


class TemplateVersionView(BaseModel):
    """GET /templates/{key}/versions 아이템."""

    version: int
    body: str
    is_active: bool = False
    updated_at: datetime | None = None


class TemplateVersionListResponse(BaseModel):
    key: str
    versions: list[TemplateVersionView]
