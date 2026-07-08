"""sources repository (AXKG-SPEC-003). Source Inbox lifecycle DB 접근.

- normalized_url로 중복을 조회한다(soft delete 제외).
- metadata.slack_events[] 누적·duplicate_candidate 표시는 database README 규약을 따른다.
- JSONB 갱신은 새 dict를 재할당해 변경을 추적한다(ORM in-place mutation 미추적 회피).
"""
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.source import SourceDTO
from axkg.models import Source
from axkg.models.base import utcnow

# 기본 Inbox 목록에서 숨기는 상태 (visible_in_inbox=False로 저장되는 상태).
_HIDDEN_STATUSES = ("documented", "archived", "deleted")


def _to_dto(row: Source) -> SourceDTO:
    return SourceDTO(
        id=row.id,
        source_url=row.source_url,
        normalized_url=row.normalized_url,
        source_channel=row.source_channel,
        submitted_by=row.submitted_by,
        submitted_at=row.submitted_at,
        raw_text=row.raw_text,
        status=row.status,
        visible_in_inbox=row.visible_in_inbox,
        summary_payload=row.summary_payload or {},
        destination_type=row.destination_type,
        documented_at=row.documented_at,
        deleted_at=row.deleted_at,
        metadata=row.metadata_ or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_row(self, source_id: uuid.UUID) -> Source | None:
        return await self._session.get(Source, source_id)

    async def create(
        self,
        *,
        source_url: str,
        normalized_url: str,
        source_channel: str,
        submitted_by: uuid.UUID | None,
        submitted_at: datetime,
        raw_text: str | None,
        status: str = "received",
        metadata: dict[str, Any] | None = None,
    ) -> SourceDTO:
        row = Source(
            source_url=source_url,
            normalized_url=normalized_url,
            source_channel=source_channel,
            submitted_by=submitted_by,
            submitted_at=submitted_at,
            raw_text=raw_text,
            status=status,
            visible_in_inbox=status not in _HIDDEN_STATUSES,
            metadata_=metadata or {},
        )
        self._session.add(row)
        await self._session.flush()
        return _to_dto(row)

    async def get(self, source_id: uuid.UUID) -> SourceDTO | None:
        row = await self._get_row(source_id)
        return _to_dto(row) if row is not None else None

    async def get_active_by_normalized_url(self, normalized_url: str) -> SourceDTO | None:
        """soft delete를 제외한 같은 normalized_url source 중 최신 1건 (중복 판정용)."""
        row = await self._session.scalar(
            sa.select(Source)
            .where(Source.normalized_url == normalized_url, Source.status != "deleted")
            .order_by(Source.created_at.desc())
            .limit(1)
        )
        return _to_dto(row) if row is not None else None

    async def list(self, *, status: str | None = None) -> list[SourceDTO]:
        """status 지정 시 해당 상태만, 없으면 기본 Inbox(visible_in_inbox=True) 목록.

        수신 시각 내림차순으로 정렬한다.
        """
        stmt = sa.select(Source)
        if status is not None:
            stmt = stmt.where(Source.status == status)
        else:
            stmt = stmt.where(Source.visible_in_inbox.is_(True))
        stmt = stmt.order_by(Source.submitted_at.desc(), Source.created_at.desc())
        rows = (await self._session.scalars(stmt)).all()
        return [_to_dto(row) for row in rows]

    async def append_intake_event(
        self, source_id: uuid.UUID, event: dict[str, Any]
    ) -> SourceDTO:
        """중복 재수신 이벤트를 metadata.slack_events[]에 누적 (database README S-2)."""
        row = await self._require_row(source_id)
        metadata = dict(row.metadata_ or {})
        events = list(metadata.get("slack_events", []))
        events.append(event)
        metadata["slack_events"] = events
        row.metadata_ = metadata
        await self._session.flush()
        return _to_dto(row)

    async def set_slack_anchor(
        self, source_id: uuid.UUID, channel: str, ts: str | None
    ) -> SourceDTO:
        """접수 후 봇 앵커 메시지(channel·ts)를 metadata에 저장 (AXKG-SPEC-003 S-1).

        `slack_anchor`(요약 회신 스레드 기준) + `slack_message_ts`(Data Contract 대표 ts).
        """
        row = await self._require_row(source_id)
        metadata = dict(row.metadata_ or {})
        metadata["slack_anchor"] = {"channel": channel, "ts": ts}
        metadata["slack_message_ts"] = ts
        row.metadata_ = metadata
        await self._session.flush()
        return _to_dto(row)

    async def mark_duplicate_candidate(self, source_id: uuid.UUID) -> SourceDTO:
        """이미 documented인 source에 중복 재수신 시 duplicate_candidate=true 표시."""
        row = await self._require_row(source_id)
        metadata = dict(row.metadata_ or {})
        metadata["duplicate_candidate"] = True
        row.metadata_ = metadata
        await self._session.flush()
        return _to_dto(row)

    async def set_normalized_url(
        self, source_id: uuid.UUID, normalized_url: str
    ) -> SourceDTO:
        """수집 성공 시 canonical 기준으로 normalized_url 갱신 (AXKG-SPEC-012)."""
        row = await self._require_row(source_id)
        row.normalized_url = normalized_url
        await self._session.flush()
        return _to_dto(row)

    async def get_active_duplicate(
        self, normalized_url: str, exclude_id: uuid.UUID
    ) -> SourceDTO | None:
        """normalized_url이 같은 다른 active source(중복 재검사용, 자기 자신·soft delete 제외)."""
        row = await self._session.scalar(
            sa.select(Source)
            .where(
                Source.normalized_url == normalized_url,
                Source.id != exclude_id,
                Source.status != "deleted",
            )
            .order_by(Source.created_at.asc())
            .limit(1)
        )
        return _to_dto(row) if row is not None else None

    async def set_raw_text(
        self, source_id: uuid.UUID, raw_text: str | None
    ) -> SourceDTO:
        """메모(raw_text) 갱신 — collection_failed 재시도 시 메모 추가/수정 (PLAN-005-T-013)."""
        row = await self._require_row(source_id)
        row.raw_text = raw_text
        await self._session.flush()
        return _to_dto(row)

    async def set_status(self, source_id: uuid.UUID, status: str) -> SourceDTO:
        row = await self._require_row(source_id)
        row.status = status
        row.visible_in_inbox = status not in _HIDDEN_STATUSES
        if status == "deleted":
            row.deleted_at = utcnow()
        await self._session.flush()
        return _to_dto(row)

    async def set_summary(
        self, source_id: uuid.UUID, payload: dict[str, Any]
    ) -> SourceDTO:
        """요약 성공 시 직전 payload를 read-only 아카이브하고 새 payload로 갱신한다.

        AXKG-SPEC-011 ① 최초 요약(직전 payload 없음)은 그대로 저장한다. 피드백 재요약
        (PLAN-005-T-016)은 직전 요약(v1/…/vN)을 `metadata.summary_versions[]`에 append해
        불변 보존하고(SPEC-002 버전 규칙: 직전 버전 read-only) `summary_payload`를 최신(vN+1)로
        덮어쓴다. FE가 소비하는 `summary_payload` 계약(title/summary/keywords/…)은 항상 최신
        버전만 담아 그대로 유지한다 — 버전 이력은 metadata에만 둔다.

        NOTE: 버전 이력 저장 위치/형태는 curator T-015의 SPEC-002/011 개정본과 최종 정합
        예정(PLAN-005-T-016). 현재는 metadata.summary_versions[]로 자기완결 보존한다.
        """
        row = await self._require_row(source_id)
        prior = row.summary_payload or {}
        if prior:
            metadata = dict(row.metadata_ or {})
            versions = list(metadata.get("summary_versions", []))
            versions.append({"payload": prior, "archived_at": utcnow().isoformat()})
            metadata["summary_versions"] = versions
            row.metadata_ = metadata
        row.summary_payload = dict(payload)
        row.status = "summarized"
        row.visible_in_inbox = True
        await self._session.flush()
        return _to_dto(row)

    async def _require_row(self, source_id: uuid.UUID) -> Source:
        row = await self._get_row(source_id)
        if row is None:
            raise LookupError(f"source not found: {source_id}")
        return row
