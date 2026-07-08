"""SourceMaterial — 수집 adapter의 정규화 출력 (AXKG-SPEC-012 §2 SourceMaterial 계약).

요약 스테이지(AXKG-SPEC-011 ①)의 입력 컨텍스트. `adapter`(수집 방식)와
`source_type`(콘텐츠 유형, SPEC-001/002)은 다른 어휘다 — 섞지 않는다.
"""
from typing import Any

from pydantic import BaseModel, Field


class SourceMaterial(BaseModel):
    source_url: str
    canonical_url: str
    adapter: str  # youtube | static_web | dynamic_web
    title: str | None = None
    author: str | None = None
    published_at: str | None = None  # YYYY-MM-DD or None
    duration_seconds: int | None = None
    content_text: str
    content_format: str  # transcript | video_description | page_text
    fetch_method: str  # youtube_transcript_api | youtube_metadata | static_html | playwright_chrome
    fetched_at: str  # ISO-8601
    external_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
