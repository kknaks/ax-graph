"""open-kknaks task 실행/폴링, 출력·실패 저장 (AXKG-SPEC-011). WP0 Phase 5.

worker는 얇다: session을 열고 AiExecutionService.execute_task에 위임한다.
실행 모드(inline FastAPI background task vs Redis worker)는 아직 열려 있어서
(40-architecture Open Items) 여기서는 session 단위 실행 함수만 제공한다.
스테이지 트리거가 이 함수를 부르는 배선은 각 도메인 WP 소관이다.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.core.database import get_session_factory
from axkg.dto.ai import AiTaskDTO
from axkg.integrations.open_kknaks import OpenKknaksClient
from axkg.services.ai import AiExecutionService, ContextBuilderRegistry


async def run_ai_task(
    task_id: uuid.UUID,
    *,
    client: OpenKknaksClient,
    registry: ContextBuilderRegistry,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AiTaskDTO:
    """queued ai_task 하나를 자체 session에서 실행하고 commit한다.

    실행 실패는 예외가 아니라 ai_tasks.status=failed(+error_code)로 남는다 —
    예외는 인프라 오류(세션/알 수 없는 정의 등)일 때만 전파된다.
    """
    factory = session_factory or get_session_factory()
    async with factory() as session:
        try:
            service = AiExecutionService(session, client=client, registry=registry)
            task = await service.execute_task(task_id)
            await session.commit()
            return task
        except Exception:
            await session.rollback()
            raise
