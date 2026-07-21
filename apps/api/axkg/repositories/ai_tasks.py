"""ai_tasks repository (AXKG-SPEC-011/002).

- 실패 task는 불변: 상태 전이는 queued→running→succeeded|failed|cancelled 방향으로만.
- 재시도는 retry_of_task_id로 원 task를 참조하는 새 row (create로 만든다).
"""
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.ai import AiTaskDTO
from axkg.models import AiTask
from axkg.models.base import utcnow


def _to_dto(row: AiTask) -> AiTaskDTO:
    return AiTaskDTO(
        id=row.id,
        task_type=row.task_type,
        task_definition_id=row.task_definition_id,
        status=row.status,
        source_id=row.source_id,
        gate_id=row.gate_id,
        revision_id=row.revision_id,
        retry_of_task_id=row.retry_of_task_id,
        retry_count=row.retry_count,
        provider=row.provider,
        model=row.model,
        options=row.options or {},
        provider_options=row.provider_options or {},
        open_kknaks_task_id=row.open_kknaks_task_id,
        open_kknaks_session_id=row.open_kknaks_session_id,
        prompt_version_id=row.prompt_version_id,
        template_version_id=row.template_version_id,
        payload=row.payload or {},
        error_code=row.error_code,
        error_message=row.error_message,
        queued_at=row.queued_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


class AiTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_row(self, task_id: uuid.UUID) -> AiTask:
        row = await self._session.get(AiTask, task_id)
        if row is None:
            raise LookupError(f"ai_task not found: {task_id}")
        return row

    async def create(
        self,
        *,
        task_type: str,
        task_definition_id: uuid.UUID | None,
        provider: str,
        model: str | None,
        options: dict[str, Any],
        provider_options: dict[str, Any],
        source_id: uuid.UUID | None = None,
        gate_id: uuid.UUID | None = None,
        revision_id: uuid.UUID | None = None,
        retry_of_task_id: uuid.UUID | None = None,
        retry_count: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> AiTaskDTO:
        row = AiTask(
            task_type=task_type,
            task_definition_id=task_definition_id,
            status="queued",
            source_id=source_id,
            gate_id=gate_id,
            revision_id=revision_id,
            retry_of_task_id=retry_of_task_id,
            retry_count=retry_count,
            provider=provider,
            model=model,
            options=options,
            provider_options=provider_options,
            payload=payload or {},
            queued_at=utcnow(),
        )
        self._session.add(row)
        await self._session.flush()
        return _to_dto(row)

    async def get(self, task_id: uuid.UUID) -> AiTaskDTO | None:
        row = await self._session.get(AiTask, task_id)
        return _to_dto(row) if row is not None else None

    async def list_by_source(self, source_id: uuid.UUID) -> list[AiTaskDTO]:
        """source에 연결된 ai_task 이력을 queued_at 오름차순으로 반환 (AXKG-SPEC-003)."""
        rows = (
            await self._session.scalars(
                sa.select(AiTask)
                .where(AiTask.source_id == source_id)
                .order_by(AiTask.queued_at.asc(), AiTask.retry_count.asc())
            )
        ).all()
        return [_to_dto(row) for row in rows]

    async def list_by_gate(
        self, gate_id: uuid.UUID, task_type: str | None = None
    ) -> list[AiTaskDTO]:
        """gate에 연결된 ai_task 목록(queued_at 오름차순). plan-then-fanout fan-in 취합용.

        task_type을 주면 그 타입만(예: generate_feature_spec). 재시도 체인이 있으면 같은 gate에
        여러 row가 쌓이므로 호출측이 seq별 최신을 고른다.
        """
        query = sa.select(AiTask).where(AiTask.gate_id == gate_id)
        if task_type is not None:
            query = query.where(AiTask.task_type == task_type)
        rows = (
            await self._session.scalars(
                query.order_by(AiTask.queued_at.asc(), AiTask.retry_count.asc())
            )
        ).all()
        return [_to_dto(row) for row in rows]

    async def merge_payload(
        self, task_id: uuid.UUID, patch: dict[str, Any]
    ) -> AiTaskDTO:
        """task.payload에 patch를 병합한다(plan-then-fanout: 기능 산출물 보관 등).

        JSONB는 재대입해야 변경이 flush된다(in-place mutate는 dirty 감지 안 됨).
        """
        row = await self._get_row(task_id)
        row.payload = {**(row.payload or {}), **patch}
        await self._session.flush()
        return _to_dto(row)

    async def get_latest_failed_by_source(
        self, source_id: uuid.UUID, task_type: str
    ) -> AiTaskDTO | None:
        """재시도 기준이 될 최신 failed task (요약 재시도 retry_of_task_id 원천)."""
        row = await self._session.scalar(
            sa.select(AiTask)
            .where(
                AiTask.source_id == source_id,
                AiTask.task_type == task_type,
                AiTask.status == "failed",
            )
            .order_by(AiTask.queued_at.desc(), AiTask.retry_count.desc())
            .limit(1)
        )
        return _to_dto(row) if row is not None else None

    async def get_latest_succeeded_by_source(
        self, source_id: uuid.UUID, task_type: str
    ) -> AiTaskDTO | None:
        """최신 succeeded task — 피드백 재요약이 이어붙일 resume session 원천 (PLAN-005-T-016).

        직전 요약(v1/…/vN)을 낸 task의 `open_kknaks_session_id`를 resume 대상으로 쓴다
        (AXKG-SPEC-002 open-kknaks Session Rule의 원 task 경로).
        """
        row = await self._session.scalar(
            sa.select(AiTask)
            .where(
                AiTask.source_id == source_id,
                AiTask.task_type == task_type,
                AiTask.status == "succeeded",
            )
            .order_by(AiTask.queued_at.desc(), AiTask.retry_count.desc())
            .limit(1)
        )
        return _to_dto(row) if row is not None else None

    async def set_assembly_snapshot(
        self,
        task_id: uuid.UUID,
        *,
        prompt_version_id: uuid.UUID | None,
        template_version_id: uuid.UUID | None,
        payload: dict[str, Any],
    ) -> AiTaskDTO:
        """조립 입력 스냅샷 — fallback 실행은 버전 id를 null로 두고 payload에 기록."""
        row = await self._get_row(task_id)
        row.prompt_version_id = prompt_version_id
        row.template_version_id = template_version_id
        row.payload = payload
        await self._session.flush()
        return _to_dto(row)

    async def mark_running(self, task_id: uuid.UUID) -> AiTaskDTO:
        row = await self._get_row(task_id)
        row.status = "running"
        row.started_at = utcnow()
        await self._session.flush()
        return _to_dto(row)

    async def set_open_kknaks_refs(
        self,
        task_id: uuid.UUID,
        *,
        open_kknaks_task_id: str | None,
        open_kknaks_session_id: str | None,
    ) -> AiTaskDTO:
        row = await self._get_row(task_id)
        row.open_kknaks_task_id = open_kknaks_task_id
        row.open_kknaks_session_id = open_kknaks_session_id
        await self._session.flush()
        return _to_dto(row)

    async def mark_succeeded(self, task_id: uuid.UUID) -> AiTaskDTO:
        row = await self._get_row(task_id)
        row.status = "succeeded"
        row.finished_at = utcnow()
        await self._session.flush()
        return _to_dto(row)

    async def mark_failed(
        self, task_id: uuid.UUID, *, error_code: str, error_message: str | None
    ) -> AiTaskDTO:
        row = await self._get_row(task_id)
        row.status = "failed"
        row.error_code = error_code
        row.error_message = error_message
        row.finished_at = utcnow()
        await self._session.flush()
        return _to_dto(row)

    async def get_retry_chain(self, task_id: uuid.UUID) -> list[AiTaskDTO]:
        """task가 속한 재시도 체인 전체를 queued_at 오름차순으로 반환.

        retry_of_task_id를 따라 root까지 올라간 뒤 후손을 레벨 단위로 수집한다
        (체인은 짧다는 전제의 단순 반복 조회).
        """
        current = await self._get_row(task_id)
        while current.retry_of_task_id is not None:
            current = await self._get_row(current.retry_of_task_id)

        chain: list[AiTask] = [current]
        frontier: list[uuid.UUID] = [current.id]
        while frontier:
            rows = (
                await self._session.scalars(
                    sa.select(AiTask).where(AiTask.retry_of_task_id.in_(frontier))
                )
            ).all()
            chain.extend(rows)
            frontier = [row.id for row in rows]
        chain.sort(key=lambda row: (row.queued_at, row.retry_count))
        return [_to_dto(row) for row in chain]
