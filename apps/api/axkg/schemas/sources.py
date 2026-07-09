"""sources API 요청/응답 (AXKG-SPEC-003 Interface Contract).

FE(profile-fe)가 이 계약으로 병렬 작업 중이다(`apps/web/lib/api-client/sources.ts`).
- 리소스 응답은 봉투 없이 Source 자체를 반환한다(FE `createManualSource`/`getSource`/
  `queueCollection`이 `Promise<Source>`를 기대).
- 중복은 Case Matrix `DUPLICATE_SOURCE` 에러로 신호한다(FE는 error_code로 분기).
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from axkg.dto.ai import AiTaskDTO
from axkg.dto.source import SourceDTO


class SourceResponse(BaseModel):
    """Source Data Contract (AXKG-SPEC-003 Data Contract 표).

    FE Source 인터페이스의 상위집합 — 추가 필드(normalized_url/metadata/타임스탬프)는
    FE가 무시한다. error_message는 상세(U-2)에서 최신 실패 task 사유를 실어 보낸다.
    """

    id: uuid.UUID
    source_url: str
    normalized_url: str
    source_channel: str
    submitted_by: uuid.UUID | None = None
    submitted_at: datetime
    slack_message_ts: str | None = None
    raw_text: str | None = None
    status: str
    visible_in_inbox: bool
    summary_payload: dict[str, Any] = Field(default_factory=dict)
    destination_type: str | None = None
    approved_classification_gate_id: uuid.UUID | None = None
    # Inbox 큐 파생 라벨(classify_pending/regenerating/approved) — DB 미저장, 게이트 상태 조합
    # (AXKG-SPEC-001 매핑표). 게이트가 없거나 매핑 밖이면 None.
    inbox_label: str | None = None
    documented_at: datetime | None = None
    deleted_at: datetime | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dto(
        cls,
        dto: SourceDTO,
        *,
        error_message: str | None = None,
        inbox_label: str | None = None,
    ) -> "SourceResponse":
        return cls(
            id=dto.id,
            source_url=dto.source_url,
            normalized_url=dto.normalized_url,
            source_channel=dto.source_channel,
            submitted_by=dto.submitted_by,
            submitted_at=dto.submitted_at,
            slack_message_ts=dto.slack_message_ts,
            raw_text=dto.raw_text,
            status=dto.status,
            visible_in_inbox=dto.visible_in_inbox,
            summary_payload=dto.summary_payload,
            destination_type=dto.destination_type,
            approved_classification_gate_id=dto.approved_classification_gate_id,
            inbox_label=inbox_label,
            documented_at=dto.documented_at,
            deleted_at=dto.deleted_at,
            error_message=error_message,
            metadata=dto.metadata,
            created_at=dto.created_at,
            updated_at=dto.updated_at,
        )


class ManualSourceRequest(BaseModel):
    source_url: str = Field(min_length=1)
    raw_text: str | None = None


class QueueCollectionRequest(BaseModel):
    """요약 재시도 시 메모(note) 첨부 — 메모 저장 + 재요약을 단건 호출로 (PLAN-005-T-013).

    note 생략/None이면 메모를 건드리지 않고 순수 재시도. 있으면 raw_text를 갱신해 원문 수집이
    또 실패해도 user_note fallback으로 요약되게 한다(FE T-014가 이 계약을 소비).
    """

    note: str | None = None


class SummaryFeedbackRequest(BaseModel):
    """요약 피드백 재요약 입력 (PLAN-005-T-016 / SPEC-003 개정 예정 · FE T-017 공유 계약).

    summarized source에만 허용. feedback으로 직전 요약 세션을 resume해 v2를 만든다
    (원문 재전송 없음). 빈/공백 feedback은 EMPTY_FEEDBACK으로 거부한다(min_length가 1차 방어).
    """

    feedback: str = Field(min_length=1)


class SourceListResponse(BaseModel):
    sources: list[SourceResponse]


class AiTaskResponse(BaseModel):
    """source 연결 AI task 이력 (AXKG-SPEC-003 GET /sources/{id}/ai-tasks)."""

    id: uuid.UUID
    task_type: str
    status: str
    source_id: uuid.UUID | None = None
    retry_of_task_id: uuid.UUID | None = None
    retry_count: int
    provider: str
    model: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def from_dto(cls, dto: AiTaskDTO) -> "AiTaskResponse":
        return cls(
            id=dto.id,
            task_type=dto.task_type,
            status=dto.status,
            source_id=dto.source_id,
            retry_of_task_id=dto.retry_of_task_id,
            retry_count=dto.retry_count,
            provider=dto.provider,
            model=dto.model,
            error_code=dto.error_code,
            error_message=dto.error_message,
            queued_at=dto.queued_at,
            started_at=dto.started_at,
            finished_at=dto.finished_at,
        )


class SourceAiTasksResponse(BaseModel):
    ai_tasks: list[AiTaskResponse]
