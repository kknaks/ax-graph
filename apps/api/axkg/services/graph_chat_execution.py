"""chat 스테이지 ④ 실행 오케스트레이션 (AXKG-SPEC-006 / SPEC-011 ④). WP4 Phase 2.

queued chat run 하나를 자체 session에서 실행한다(`execute_source_summary` 패턴):
- `GraphRagChatContextBuilder`(session 바인딩)를 등록한 registry로 AiExecutionService 구동.
- run→ai_task를 create_task(handler_kind=graph_rag_chat). 세션에 직전 open-kknaks session이
  있으면 options.resume로 이어붙인다(SPEC-002 멀티턴 컨텍스트).
- 성공: builder.handle_result가 assistant 메시지 + run 결과(result_payload/retrieval_context)를
  저장한다. 여기서 ai_task_id/open-kknaks session을 run·세션에 연결하고 세션을 touch한다.
- 실패(수집/파싱/스키마/실행): 실패 task는 불변 보존되고 run을 `failed`로 표면화한다.

api 요청 핸들러는 이 함수를 FastAPI BackgroundTask로 스케줄링한다(동기 응답을 막지 않음).
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings
from axkg.core.database import get_session_factory
from axkg.dto.ai import AiTaskDTO
from axkg.integrations.open_kknaks import OpenKknaksClient
from axkg.models.base import utcnow
from axkg.repositories.chat import ChatRepository
from axkg.services.ai import AiExecutionService, ContextBuilderRegistry
from axkg.services.ai.graph_rag_chat import HANDLER_KIND, GraphRagChatContextBuilder
from axkg.storage.markdown_root import MarkdownRoot

logger = logging.getLogger("axkg.graph_chat_execution")

CHAT_TASK_TYPE = "graph_rag_chat"
# 실행 골격 밖에서 예외가 터졌을 때 run에 남기는 실행측 코드.
ERROR_GRAPH_CHAT_EXECUTION_FAILED = "GRAPH_CHAT_EXECUTION_FAILED"


async def execute_graph_chat(
    run_id: uuid.UUID,
    *,
    client: OpenKknaksClient,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AiTaskDTO:
    """queued chat run을 실행하고 성공/실패를 run·세션 상태에 반영한 뒤 commit한다."""
    factory = session_factory or get_session_factory()
    async with factory() as session:
        chats = ChatRepository(session)
        run = await chats.get_run_by_id(run_id)
        if run is None:
            raise LookupError(f"chat run not found: {run_id}")
        chat_session = await chats.get_session_by_id(run.session_id)
        resume_session = (
            chat_session.last_open_kknaks_session_id if chat_session is not None else None
        )

        await chats.set_run_status(run_id, "running", started_at=utcnow())

        builder = GraphRagChatContextBuilder(
            session, root=MarkdownRoot(settings.axkg_markdown_root)
        )
        registry = ContextBuilderRegistry()
        registry.register(HANDLER_KIND, builder)
        service = AiExecutionService(session, client=client, registry=registry)

        options_overrides = None
        if resume_session:
            # open-kknaks claude executor 계약: options.resume={mode:session, session_id}
            # → worker가 이전 턴 세션을 이어 실행한다(멀티턴 컨텍스트, 원문 재주입 없음).
            options_overrides = {
                "resume": {"mode": "session", "session_id": resume_session}
            }
        task = await service.create_task(
            CHAT_TASK_TYPE,
            payload={
                "run_id": str(run_id),
                "session_id": str(run.session_id),
                "user_message_id": str(run.user_message_id),
                "selected_document_id": (
                    str(run.selected_document_id)
                    if run.selected_document_id is not None
                    else None
                ),
                "filters": run.filters,
            },
            options_overrides=options_overrides,
        )

        try:
            done = await service.execute_task(task.id)
        except Exception:
            # 실행 골격 밖 예외(예: handle_result) — run을 failed로 표면화하고 재전파.
            await chats.set_run_status(
                run_id,
                "failed",
                finished_at=utcnow(),
                ai_task_id=task.id,
                error_code=ERROR_GRAPH_CHAT_EXECUTION_FAILED,
                error_message="chat 실행 중 예기치 못한 오류",
                retrieval_context=builder.last_retrieval_context or None,
            )
            await session.commit()
            logger.warning("graph chat execution failed run_id=%s", run_id, exc_info=True)
            raise

        if done.status != "succeeded":
            # 수집/파싱/스키마/실행 실패 — 실패 task는 불변 보존, run만 표면화.
            await chats.set_run_status(
                run_id,
                "failed",
                finished_at=utcnow(),
                ai_task_id=task.id,
                error_code=done.error_code,
                error_message=done.error_message,
                retrieval_context=builder.last_retrieval_context or None,
            )
        else:
            # handle_result가 이미 run을 succeeded로 flush(assistant 메시지/result_payload/
            # retrieval_context). 여기선 ai_task/open-kknaks session 연결 + 세션 갱신만 한다.
            await chats.set_run_status(
                run_id,
                "succeeded",
                ai_task_id=task.id,
                open_kknaks_session_id=done.open_kknaks_session_id,
            )
            if done.open_kknaks_session_id:
                await chats.set_last_open_kknaks_session(
                    run.session_id, done.open_kknaks_session_id
                )
            await chats.touch_session(run.session_id, utcnow())
        await session.commit()
        return done
