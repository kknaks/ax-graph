"""apply_plans repository (AXKG-SPEC-004/002). session 접근은 여기서만.

문서화 게이트 revision당 apply_plan 1건(unique gate_revision_id). Apply Executor가
검증 결과·실행 상태를 여기 기록한다(감사 이력 = sources→gates→revisions→apply_plans→documents).
"""
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.apply_plan import ApplyPlanDTO
from axkg.models import ApplyPlan
from axkg.models.base import utcnow


def _to_dto(row: ApplyPlan) -> ApplyPlanDTO:
    return ApplyPlanDTO(
        id=row.id,
        gate_revision_id=row.gate_revision_id,
        status=row.status,
        validation_status=row.validation_status,
        db_actions=list(row.db_actions or []),
        file_actions=list(row.file_actions or []),
        validation_errors=list(row.validation_errors or []),
        applied_at=row.applied_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ApplyPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_revision(self, revision_id: uuid.UUID) -> ApplyPlanDTO | None:
        row = await self._session.scalar(
            sa.select(ApplyPlan).where(ApplyPlan.gate_revision_id == revision_id)
        )
        return _to_dto(row) if row is not None else None

    async def upsert(
        self,
        *,
        gate_revision_id: uuid.UUID,
        status: str,
        validation_status: str,
        db_actions: list[Any],
        file_actions: list[Any],
        validation_errors: list[Any],
        applied: bool = False,
    ) -> ApplyPlanDTO:
        """gate_revision_id 기준 upsert(revision당 1건). applied=True면 applied_at 기록."""
        row = await self._session.scalar(
            sa.select(ApplyPlan).where(ApplyPlan.gate_revision_id == gate_revision_id)
        )
        if row is None:
            row = ApplyPlan(gate_revision_id=gate_revision_id)
            self._session.add(row)
        row.status = status
        row.validation_status = validation_status
        row.db_actions = list(db_actions)
        row.file_actions = list(file_actions)
        row.validation_errors = list(validation_errors)
        if applied:
            row.applied_at = utcnow()
        await self._session.flush()
        return _to_dto(row)
