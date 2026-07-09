"""분류 게이트 ② 실행 오케스트레이션 (AXKG-SPEC-011 / SPEC-002). WP3 Phase 1.

queued `generate_classification_gate`/`regenerate_classification_gate` task 하나를 자체
session에서 실행한다(`execute_source_summary` 미러링):
- `ClassificationGateContextBuilder`(session 바인딩)를 등록한 registry로 AiExecutionService 구동.
- 성공: builder.handle_result가 envelope 저장 + revision reviewable + gate review_pending.
- 실패(수집 없음/실행/파싱/스키마): task는 failed로 보존되고, 대상 revision은 `failed`,
  gate는 `failed`(+error_code/message)로 표면화한다. 실패 task/revision은 감사 이력으로 남는다.

api 요청 핸들러는 이 함수를 FastAPI BackgroundTask로 스케줄링한다. open-kknaks는 별도
worker가 소비하는 비동기 실행이다.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.core.database import get_session_factory
from axkg.dto.ai import AiTaskDTO
from axkg.integrations.open_kknaks import OpenKknaksClient
from axkg.repositories.gates import GateRepository
from axkg.services.ai import AiExecutionService, ContextBuilderRegistry
from axkg.services.ai.classification_gate import (
    HANDLER_KIND,
    ClassificationGateContextBuilder,
)

logger = logging.getLogger("axkg.classification_gate_execution")


async def execute_classification_gate(
    task_id: uuid.UUID,
    gate_id: uuid.UUID,
    revision_id: uuid.UUID,
    *,
    client: OpenKknaksClient,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AiTaskDTO:
    """queued 분류 task를 실행하고 성공/실패를 gate/revision 상태에 반영한 뒤 commit한다."""
    factory = session_factory or get_session_factory()
    try:
        async with factory() as session:
            builder = ClassificationGateContextBuilder(session)
            registry = ContextBuilderRegistry()
            registry.register(HANDLER_KIND, builder)
            service = AiExecutionService(session, client=client, registry=registry)

            done = await service.execute_task(task_id)
            if done.status != "succeeded":
                # 실행/파싱/스키마 실패 — 실패 task는 불변 보존, revision/gate만 표면화.
                await _surface_failure(
                    session,
                    gate_id=gate_id,
                    revision_id=revision_id,
                    error_code=done.error_code,
                    error_message=done.error_message,
                )
            await session.commit()
        return done
    except Exception:
        # 예기치 못한 인프라 오류로 gate가 generating/regenerating에 갇히지 않게 별도 session에서
        # failed로 표면화한다(실패 task 기록은 execute_task가 이미 남겼을 수 있다).
        async with factory() as session:
            await _surface_failure(
                session,
                gate_id=gate_id,
                revision_id=revision_id,
                error_code="CLASSIFICATION_EXECUTION_FAILED",
                error_message="분류 실행 중 예기치 못한 오류가 발생했습니다.",
            )
            await session.commit()
        raise


async def _surface_failure(
    session: AsyncSession,
    *,
    gate_id: uuid.UUID,
    revision_id: uuid.UUID,
    error_code: str | None,
    error_message: str | None,
) -> None:
    """대상 revision을 failed, gate를 failed로 전이한다(감사 이력 보존)."""
    gates = GateRepository(session)
    revision = await gates.get_revision(revision_id)
    if revision is not None and revision.status == "drafting":
        await gates.update_revision(revision_id, status="failed")
    gate = await gates.get_gate(gate_id)
    if gate is not None and gate.status != "failed":
        await gates.update_gate(gate_id, status="failed")
    logger.warning(
        "classification gate failed gate_id=%s revision_id=%s code=%s",
        gate_id,
        revision_id,
        error_code,
    )
