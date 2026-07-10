"""approval gates repository (AXKG-SPEC-002/001). session 접근은 여기서만.

`approval_gates`(컨테이너) / `approval_gate_revisions`(버전) / `gate_feedback` CRUD.
- 새 revision이 reviewable이 되면 직전 active revision은 superseded(SPEC-002 §5) — 전이는
  서비스가 이 repo의 update로 지시한다.
- 실패/승인 revision·feedback은 불변 감사 이력으로 보존한다(상태 전이만, 내용 덮어쓰기 없음).
- JSONB 갱신은 새 dict 재할당으로 변경을 추적한다(ORM in-place mutation 미추적 회피).
"""
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.gate import ApprovalGateDTO, ApprovalGateRevisionDTO, GateFeedbackDTO
from axkg.models import ApprovalGate, ApprovalGateRevision, GateFeedback
from axkg.models.base import utcnow


def _gate_to_dto(row: ApprovalGate) -> ApprovalGateDTO:
    return ApprovalGateDTO(
        id=row.id,
        source_id=row.source_id,
        gate_kind=row.gate_kind,
        status=row.status,
        active_revision_id=row.active_revision_id,
        approved_revision_id=row.approved_revision_id,
        last_ai_task_id=row.last_ai_task_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _revision_to_dto(row: ApprovalGateRevision) -> ApprovalGateRevisionDTO:
    return ApprovalGateRevisionDTO(
        id=row.id,
        gate_id=row.gate_id,
        version=row.version,
        status=row.status,
        payload=row.payload or {},
        form_schema_version=row.form_schema_version,
        parent_revision_id=row.parent_revision_id,
        feedback_id=row.feedback_id,
        ai_task_id=row.ai_task_id,
        open_kknaks_session_id=row.open_kknaks_session_id,
        created_at=row.created_at,
        approved_at=row.approved_at,
    )


def _feedback_to_dto(row: GateFeedback) -> GateFeedbackDTO:
    return GateFeedbackDTO(
        id=row.id,
        gate_id=row.gate_id,
        target_revision_id=row.target_revision_id,
        body=row.body,
        quick_options=row.quick_options or [],
        payload=row.payload or {},
        status=row.status,
        created_at=row.created_at,
        consumed_at=row.consumed_at,
    )


class GateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # gate
    # ------------------------------------------------------------------

    async def create_gate(
        self, *, source_id: uuid.UUID, gate_kind: str, status: str
    ) -> ApprovalGateDTO:
        row = ApprovalGate(source_id=source_id, gate_kind=gate_kind, status=status)
        self._session.add(row)
        await self._session.flush()
        return _gate_to_dto(row)

    async def get_gate(self, gate_id: uuid.UUID) -> ApprovalGateDTO | None:
        row = await self._session.get(ApprovalGate, gate_id)
        return _gate_to_dto(row) if row is not None else None

    async def get_gate_by_source_and_kind(
        self, source_id: uuid.UUID, gate_kind: str
    ) -> ApprovalGateDTO | None:
        row = await self._session.scalar(
            sa.select(ApprovalGate).where(
                ApprovalGate.source_id == source_id,
                ApprovalGate.gate_kind == gate_kind,
            )
        )
        return _gate_to_dto(row) if row is not None else None

    async def list_gates_by_source(self, source_id: uuid.UUID) -> list[ApprovalGateDTO]:
        rows = (
            await self._session.scalars(
                sa.select(ApprovalGate)
                .where(ApprovalGate.source_id == source_id)
                .order_by(ApprovalGate.created_at.asc())
            )
        ).all()
        return [_gate_to_dto(row) for row in rows]

    async def list_gates_by_kind(self, gate_kind: str) -> list[ApprovalGateDTO]:
        """특정 kind의 모든 게이트(문서화 게이트 조회 뷰 목록용)."""
        rows = (
            await self._session.scalars(
                sa.select(ApprovalGate)
                .where(ApprovalGate.gate_kind == gate_kind)
                .order_by(ApprovalGate.created_at.desc())
            )
        ).all()
        return [_gate_to_dto(row) for row in rows]

    async def list_gates_by_sources_and_kind(
        self, source_ids: list[uuid.UUID], gate_kind: str
    ) -> list[ApprovalGateDTO]:
        """여러 source의 특정 kind 게이트를 한 번에 조회(파생 라벨 batch용)."""
        if not source_ids:
            return []
        rows = (
            await self._session.scalars(
                sa.select(ApprovalGate).where(
                    ApprovalGate.source_id.in_(source_ids),
                    ApprovalGate.gate_kind == gate_kind,
                )
            )
        ).all()
        return [_gate_to_dto(row) for row in rows]

    async def update_gate(
        self,
        gate_id: uuid.UUID,
        *,
        status: str | None = None,
        active_revision_id: uuid.UUID | None = None,
        approved_revision_id: uuid.UUID | None = None,
        last_ai_task_id: uuid.UUID | None = None,
        clear_approved_revision: bool = False,
    ) -> ApprovalGateDTO:
        """게이트 포인터/상태 전이. None 인자는 '변경 없음'이며, approved_revision_id를
        명시적으로 비우려면 clear_approved_revision=True를 쓴다(재분류 재오픈 Phase 4용)."""
        row = await self._require_gate(gate_id)
        if status is not None:
            row.status = status
        if active_revision_id is not None:
            row.active_revision_id = active_revision_id
        if approved_revision_id is not None:
            row.approved_revision_id = approved_revision_id
        if clear_approved_revision:
            row.approved_revision_id = None
        if last_ai_task_id is not None:
            row.last_ai_task_id = last_ai_task_id
        await self._session.flush()
        return _gate_to_dto(row)

    # ------------------------------------------------------------------
    # revision
    # ------------------------------------------------------------------

    async def next_version(self, gate_id: uuid.UUID) -> int:
        current = await self._session.scalar(
            sa.select(sa.func.max(ApprovalGateRevision.version)).where(
                ApprovalGateRevision.gate_id == gate_id
            )
        )
        return (current or 0) + 1

    async def create_revision(
        self,
        *,
        gate_id: uuid.UUID,
        version: int,
        status: str,
        payload: dict[str, Any],
        form_schema_version: str,
        parent_revision_id: uuid.UUID | None = None,
        feedback_id: uuid.UUID | None = None,
        ai_task_id: uuid.UUID | None = None,
    ) -> ApprovalGateRevisionDTO:
        row = ApprovalGateRevision(
            gate_id=gate_id,
            version=version,
            status=status,
            payload=payload,
            form_schema_version=form_schema_version,
            parent_revision_id=parent_revision_id,
            feedback_id=feedback_id,
            ai_task_id=ai_task_id,
        )
        self._session.add(row)
        await self._session.flush()
        return _revision_to_dto(row)

    async def get_revision(
        self, revision_id: uuid.UUID
    ) -> ApprovalGateRevisionDTO | None:
        row = await self._session.get(ApprovalGateRevision, revision_id)
        return _revision_to_dto(row) if row is not None else None

    async def list_revisions_by_gate(
        self, gate_id: uuid.UUID
    ) -> list[ApprovalGateRevisionDTO]:
        rows = (
            await self._session.scalars(
                sa.select(ApprovalGateRevision)
                .where(ApprovalGateRevision.gate_id == gate_id)
                .order_by(ApprovalGateRevision.version.asc())
            )
        ).all()
        return [_revision_to_dto(row) for row in rows]

    async def list_reviewable_revisions_by_gate(
        self, gate_id: uuid.UUID
    ) -> list[ApprovalGateRevisionDTO]:
        """게이트의 reviewable revision만(형제 supersede sweep용). version 오름차순."""
        rows = (
            await self._session.scalars(
                sa.select(ApprovalGateRevision)
                .where(
                    ApprovalGateRevision.gate_id == gate_id,
                    ApprovalGateRevision.status == "reviewable",
                )
                .order_by(ApprovalGateRevision.version.asc())
            )
        ).all()
        return [_revision_to_dto(row) for row in rows]

    async def supersede_other_reviewable_revisions(
        self, gate_id: uuid.UUID, *, keep_revision_id: uuid.UUID
    ) -> int:
        """gate의 reviewable revision 중 keep을 제외한 전부를 superseded로. 전이 건수 반환.

        빠른 연속 재생성으로 형제 reviewable이 병렬 누적됐을 때 dangling(승인/supersede
        어디에도 안 잡히는 잔존 revision)을 막는다 (SPEC-002 §5/§7 OQ). drafting(실행 중)은
        대상이 아니다 — reviewable만 sweep한다.
        """
        swept = 0
        for sibling in await self.list_reviewable_revisions_by_gate(gate_id):
            if sibling.id == keep_revision_id:
                continue
            await self.update_revision(sibling.id, status="superseded")
            swept += 1
        return swept

    async def update_revision(
        self,
        revision_id: uuid.UUID,
        *,
        status: str | None = None,
        payload: dict[str, Any] | None = None,
        open_kknaks_session_id: str | None = None,
        ai_task_id: uuid.UUID | None = None,
        approved: bool = False,
    ) -> ApprovalGateRevisionDTO:
        row = await self._require_revision(revision_id)
        if status is not None:
            row.status = status
        if payload is not None:
            row.payload = dict(payload)
        if open_kknaks_session_id is not None:
            row.open_kknaks_session_id = open_kknaks_session_id
        if ai_task_id is not None:
            row.ai_task_id = ai_task_id
        if approved:
            row.approved_at = utcnow()
        await self._session.flush()
        return _revision_to_dto(row)

    # ------------------------------------------------------------------
    # feedback
    # ------------------------------------------------------------------

    async def create_feedback(
        self,
        *,
        gate_id: uuid.UUID,
        target_revision_id: uuid.UUID,
        body: str,
        quick_options: list[Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> GateFeedbackDTO:
        row = GateFeedback(
            gate_id=gate_id,
            target_revision_id=target_revision_id,
            body=body,
            quick_options=quick_options or [],
            payload=payload or {},
            status="submitted",
        )
        self._session.add(row)
        await self._session.flush()
        return _feedback_to_dto(row)

    async def get_latest_submitted_feedback(
        self, gate_id: uuid.UUID
    ) -> GateFeedbackDTO | None:
        row = await self._session.scalar(
            sa.select(GateFeedback)
            .where(
                GateFeedback.gate_id == gate_id,
                GateFeedback.status == "submitted",
            )
            .order_by(GateFeedback.created_at.desc())
            .limit(1)
        )
        return _feedback_to_dto(row) if row is not None else None

    async def consume_feedback(self, feedback_id: uuid.UUID) -> GateFeedbackDTO:
        row = await self._session.get(GateFeedback, feedback_id)
        if row is None:
            raise LookupError(f"gate_feedback not found: {feedback_id}")
        row.status = "consumed"
        row.consumed_at = utcnow()
        await self._session.flush()
        return _feedback_to_dto(row)

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    async def _require_gate(self, gate_id: uuid.UUID) -> ApprovalGate:
        row = await self._session.get(ApprovalGate, gate_id)
        if row is None:
            raise LookupError(f"approval_gate not found: {gate_id}")
        return row

    async def _require_revision(self, revision_id: uuid.UUID) -> ApprovalGateRevision:
        row = await self._session.get(ApprovalGateRevision, revision_id)
        if row is None:
            raise LookupError(f"approval_gate_revision not found: {revision_id}")
        return row
