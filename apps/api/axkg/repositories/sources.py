"""sources repository (AXKG-SPEC-003). Source Inbox lifecycle DB 접근.

- normalized_url로 중복을 조회한다(soft delete 제외).
- metadata.slack_events[] 누적·duplicate_candidate 표시는 database README 규약을 따른다.
- JSONB 갱신은 새 dict를 재할당해 변경을 추적한다(ORM in-place mutation 미추적 회피).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.source import SourceDTO, SourceSummaryRevisionDTO
from axkg.models import Source, SourceSummaryRevision
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
        active_summary_revision_id=row.active_summary_revision_id,
        destination_type=row.destination_type,
        approved_classification_gate_id=row.approved_classification_gate_id,
        documented_at=row.documented_at,
        deleted_at=row.deleted_at,
        metadata=row.metadata_ or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_summary_revision_dto(row: SourceSummaryRevision) -> SourceSummaryRevisionDTO:
    return SourceSummaryRevisionDTO(
        id=row.id,
        source_id=row.source_id,
        version=row.version,
        status=row.status,
        payload=row.payload or {},
        parent_revision_id=row.parent_revision_id,
        ai_task_id=row.ai_task_id,
        open_kknaks_session_id=row.open_kknaks_session_id,
        created_at=row.created_at,
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

    async def set_classification_destination(
        self,
        source_id: uuid.UUID,
        *,
        destination_type: str,
        gate_id: uuid.UUID,
        archived: bool,
    ) -> SourceDTO:
        """분류 승인 부수효과 (AXKG-SPEC-001 U-3): destination 확정 + 승인 게이트 포인터.

        destination=archive면 source를 `archived`로 종료(Inbox에서 숨김). 그 외
        (project/area/resource)는 `summarized` 유지 — 문서화 게이트가 이어진다.
        """
        row = await self._require_row(source_id)
        row.destination_type = destination_type
        row.approved_classification_gate_id = gate_id
        if archived:
            row.status = "archived"
            row.visible_in_inbox = False
        await self._session.flush()
        return _to_dto(row)

    async def reset_classification(self, source_id: uuid.UUID) -> SourceDTO:
        """재분류 재오픈 시 destination 확정을 리셋한다 (AXKG-SPEC-002 §5).

        `destination_type`·`approved_classification_gate_id`를 null로 되돌린다. status는
        건드리지 않는다 — source는 `summarized` 그대로 두고 분류 게이트만 다시 regenerating이
        된다(분류 내내 summarized 유지, SPEC-001 매핑표).
        """
        row = await self._require_row(source_id)
        row.destination_type = None
        row.approved_classification_gate_id = None
        await self._session.flush()
        return _to_dto(row)

    async def mark_documented(self, source_id: uuid.UUID) -> SourceDTO:
        """문서화 게이트 승인 apply 완료 시 source를 documented로 종료한다 (SPEC-001 상태도).

        Inbox에서 숨기고(visible_in_inbox=False) documented_at을 남긴다. 멱등: 이미
        documented면 그대로 둔다.
        """
        row = await self._require_row(source_id)
        if row.status != "documented":
            row.status = "documented"
            row.visible_in_inbox = False
            row.documented_at = utcnow()
            await self._session.flush()
        return _to_dto(row)

    async def set_summary(
        self,
        source_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        ai_task_id: uuid.UUID | None = None,
        open_kknaks_session_id: str | None = None,
    ) -> SourceDTO:
        """요약 성공 시 새 버전을 immutable 박제로 남기고 active 포인터를 갱신한다.

        AXKG-SPEC-002/003 C · DEC-005 C (PLAN-009-T-012): 요약 draft 버전을 게이트 revision과
        **same-format**으로 별도 테이블(`source_summary_revisions`)에 박제한다. 최초 요약은 v1,
        피드백 재요약은 직전 active(reviewable) 버전을 `superseded`로 read-only 보존하고
        새 버전(vN+1, `parent`=직전)을 append한다 — **직전 버전을 덮어쓰지 않는다**(비덮어쓰기).

        `sources.summary_payload`는 active 버전 payload의 비정규 미러(FE 소비 계약 유지)이고,
        `active_summary_revision_id`가 현재 버전을 가리킨다. 버전 이력의 SoT는 revision 테이블이다
        (종전 `metadata.summary_versions[]` 배열 아카이브를 대체 — SPEC-003 §7 OQ (나) 별도 테이블).
        """
        row = await self._require_row(source_id)

        prior_active = await self._get_active_summary_revision_row(source_id)
        version = await self._next_summary_version(source_id)
        new_rev = SourceSummaryRevision(
            source_id=source_id,
            version=version,
            status="reviewable",
            payload=dict(payload),
            parent_revision_id=prior_active.id if prior_active else None,
            ai_task_id=ai_task_id,
            open_kknaks_session_id=open_kknaks_session_id,
        )
        self._session.add(new_rev)
        await self._session.flush()
        if prior_active is not None:
            prior_active.status = "superseded"

        row.summary_payload = dict(payload)
        row.active_summary_revision_id = new_rev.id
        row.status = "summarized"
        row.visible_in_inbox = True
        await self._session.flush()
        return _to_dto(row)

    # ------------------------------------------------------------------
    # 요약 draft 버전 박제 (source_summary_revisions) — 조회
    # ------------------------------------------------------------------

    async def _next_summary_version(self, source_id: uuid.UUID) -> int:
        current = await self._session.scalar(
            sa.select(sa.func.max(SourceSummaryRevision.version)).where(
                SourceSummaryRevision.source_id == source_id
            )
        )
        return (current or 0) + 1

    async def _get_active_summary_revision_row(
        self, source_id: uuid.UUID
    ) -> SourceSummaryRevision | None:
        return await self._session.scalar(
            sa.select(SourceSummaryRevision).where(
                SourceSummaryRevision.source_id == source_id,
                SourceSummaryRevision.status == "reviewable",
            )
        )

    async def get_active_summary_revision(
        self, source_id: uuid.UUID
    ) -> SourceSummaryRevisionDTO | None:
        """현재 active(reviewable) 요약 버전. 요약 초안 카드/재요약이 읽는 버전이다."""
        row = await self._get_active_summary_revision_row(source_id)
        return _to_summary_revision_dto(row) if row is not None else None

    async def get_summary_revision(
        self, revision_id: uuid.UUID
    ) -> SourceSummaryRevisionDTO | None:
        row = await self._session.get(SourceSummaryRevision, revision_id)
        return _to_summary_revision_dto(row) if row is not None else None

    async def list_summary_revisions(
        self, source_id: uuid.UUID
    ) -> list[SourceSummaryRevisionDTO]:
        """source의 요약 버전 목록(버전 오름차순, 박제 이력)."""
        rows = (
            await self._session.scalars(
                sa.select(SourceSummaryRevision)
                .where(SourceSummaryRevision.source_id == source_id)
                .order_by(SourceSummaryRevision.version.asc())
            )
        ).all()
        return [_to_summary_revision_dto(row) for row in rows]

    async def _require_row(self, source_id: uuid.UUID) -> Source:
        row = await self._get_row(source_id)
        if row is None:
            raise LookupError(f"source not found: {source_id}")
        return row
