"""source 내부 DTO (AXKG-SPEC-003). 서비스 계층 입출력 전용."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SourceDTO(BaseModel):
    """Source Inbox row 스냅샷 — Data Contract 필드 + metadata/normalized_url."""

    id: uuid.UUID
    source_url: str
    normalized_url: str
    source_channel: str
    submitted_by: uuid.UUID | None = None
    submitted_at: datetime
    raw_text: str | None = None
    status: str
    visible_in_inbox: bool = True
    summary_payload: dict[str, Any] = Field(default_factory=dict)
    destination_type: str | None = None
    documented_at: datetime | None = None
    deleted_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @property
    def slack_message_ts(self) -> str | None:
        """Slack 메시지 timestamp. 수동 입력이면 metadata에 없어 None (Data Contract)."""
        value = self.metadata.get("slack_message_ts")
        return str(value) if value is not None else None
