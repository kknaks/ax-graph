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
    active_summary_revision_id: uuid.UUID | None = None
    destination_type: str | None = None
    approved_classification_gate_id: uuid.UUID | None = None
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


class SourceSummaryRevisionDTO(BaseModel):
    """요약 draft 버전 박제 스냅샷 (AXKG-SPEC-002/003 C). 게이트 revision과 same-format.

    status는 reviewable(active)·superseded 뿐이다(요약은 approve/lock 없음). 버전 이력의
    SoT이며 immutable — 재요약은 새 버전을 append하고 직전 버전을 superseded로 보존한다.
    """

    id: uuid.UUID
    source_id: uuid.UUID
    version: int
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_revision_id: uuid.UUID | None = None
    ai_task_id: uuid.UUID | None = None
    open_kknaks_session_id: str | None = None
    created_at: datetime
