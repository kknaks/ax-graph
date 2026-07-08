"""요약 스테이지 실행 오케스트레이션 (AXKG-SPEC-011 ① / SPEC-003). WP1 Phase 3.

queued `collect_source_summary` task 하나를 자체 session에서 실행한다:
- `SourceSummaryContextBuilder`(session 바인딩)를 등록한 registry로 AiExecutionService 구동.
- 성공: builder.handle_result가 summary_payload 저장 + source `summarized` 전이.
- 실패(수집/파싱/스키마/실행): task는 failed로 보존되고 source를 `collection_failed`로 표면화.

api 요청 핸들러는 이 함수를 FastAPI BackgroundTask로 스케줄링한다(동기 응답을 막지 않음).
open-kknaks는 별도 worker가 소비하는 비동기 실행이다.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.core.database import get_session_factory
from axkg.dto.ai import AiTaskDTO
from axkg.dto.source import SourceDTO
from axkg.integrations.open_kknaks import OpenKknaksClient
from axkg.integrations.source_collection import collect_source
from axkg.repositories.sources import SourceRepository
from axkg.services.ai import AiExecutionService, ContextBuilderRegistry
from axkg.services.ai.source_summary import (
    HANDLER_KIND,
    CollectFn,
    SourceSummaryContextBuilder,
)

logger = logging.getLogger("axkg.summary_execution")

# 요약 종료 후 회신 훅(AXKG-SPEC-003 S-1 Slack 아웃바운드). slack 유입 source에만 호출한다.
SummaryNotifier = Callable[[SourceDTO, AiTaskDTO], Awaitable[None]]


async def execute_source_summary(
    task_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    client: OpenKknaksClient,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    collect: CollectFn = collect_source,
    notifier: SummaryNotifier | None = None,
) -> AiTaskDTO:
    """queued 요약 task를 실행하고 성공/실패를 source 상태에 반영한 뒤 commit한다.

    notifier가 주어지고 source가 slack 유입이면 종료 상태(summarized/collection_failed)를
    앵커 스레드에 회신한다(SPEC-003 S-1). manual 유입은 회신하지 않는다. 아웃바운드 실패는
    요약 task 성패에 영향을 주지 않도록 여기서 삼킨다.
    """
    factory = session_factory or get_session_factory()
    try:
        async with factory() as session:
            builder = SourceSummaryContextBuilder(session, collect=collect)
            registry = ContextBuilderRegistry()
            registry.register(HANDLER_KIND, builder)
            service = AiExecutionService(session, client=client, registry=registry)

            done = await service.execute_task(task_id)
            if done.status != "succeeded":
                # 수집/실행/파싱/스키마 실패 — 실패 task는 불변 보존, source만 표면화.
                await SourceRepository(session).set_status(source_id, "collection_failed")
            # 커밋 전(같은 session)에 최종 source 스냅샷을 읽어 회신 입력으로 쓴다.
            final_source = await SourceRepository(session).get(source_id)
            await session.commit()
        if notifier is not None and final_source is not None and (
            final_source.source_channel == "slack"
        ):
            try:
                await notifier(final_source, done)
            except Exception:
                logger.warning(
                    "slack summary notify failed source_id=%s", source_id, exc_info=True
                )
        return done
    except Exception:
        # 예기치 못한 인프라 오류로도 source가 summarizing에 갇히지 않게 별도 session에서
        # collection_failed로 표면화한다(실패 task 기록은 execute_task가 이미 남겼을 수 있다).
        async with factory() as session:
            await SourceRepository(session).set_status(source_id, "collection_failed")
            await session.commit()
        raise
