"""graph chat repository (AXKG-SPEC-006). session / message / run DB 접근. WP4 Phase 1.

- session은 user-scoped 조회(get_session에 user_id 필수), soft delete(deleted_at) 제외.
- run 상태 전이(set_run_status)는 Phase 2(T-012)가 호출할 순수 DB 전이 메서드다.
- commit은 하지 않는다 — DI(get_session)/route가 커밋한다. 기존 레포 컨벤션과 동일.
"""
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.chat import ChatMessageDTO, ChatRunDTO, ChatSessionDTO
from axkg.models.chat import GraphChatMessage, GraphChatRun, GraphChatSession


def _session_dto(row: GraphChatSession) -> ChatSessionDTO:
    return ChatSessionDTO(
        id=row.id,
        user_id=row.user_id,
        title=row.title,
        status=row.status,
        selected_document_id=row.selected_document_id,
        last_open_kknaks_session_id=row.last_open_kknaks_session_id,
        metadata=row.metadata_ or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_message_at=row.last_message_at,
        deleted_at=row.deleted_at,
    )


def _message_dto(row: GraphChatMessage) -> ChatMessageDTO:
    return ChatMessageDTO(
        id=row.id,
        session_id=row.session_id,
        role=row.role,
        content=row.content,
        sequence_no=row.sequence_no,
        run_id=row.run_id,
        selected_document_id=row.selected_document_id,
        evidence=row.evidence or {},
        metadata=row.metadata_ or {},
        created_at=row.created_at,
    )


def _run_dto(row: GraphChatRun) -> ChatRunDTO:
    return ChatRunDTO(
        id=row.id,
        session_id=row.session_id,
        user_message_id=row.user_message_id,
        assistant_message_id=row.assistant_message_id,
        ai_task_id=row.ai_task_id,
        status=row.status,
        open_kknaks_session_id=row.open_kknaks_session_id,
        selected_document_id=row.selected_document_id,
        filters=row.filters or {},
        retrieval_context=row.retrieval_context or {},
        result_payload=row.result_payload or {},
        error_code=row.error_code,
        error_message=row.error_message,
        queued_at=row.queued_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # session
    # ------------------------------------------------------------------

    async def create_session(
        self,
        *,
        user_id: uuid.UUID,
        title: str,
        selected_document_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatSessionDTO:
        row = GraphChatSession(
            user_id=user_id,
            title=title,
            status="active",
            selected_document_id=selected_document_id,
            metadata_=metadata or {},
        )
        self._session.add(row)
        await self._session.flush()
        return _session_dto(row)

    async def list_sessions(self, user_id: uuid.UUID) -> list[ChatSessionDTO]:
        """내 활성 세션 목록 (soft delete 제외, 최근 활동 순)."""
        rows = (
            await self._session.scalars(
                sa.select(GraphChatSession)
                .where(
                    GraphChatSession.user_id == user_id,
                    GraphChatSession.deleted_at.is_(None),
                )
                .order_by(
                    sa.func.coalesce(
                        GraphChatSession.last_message_at, GraphChatSession.created_at
                    ).desc(),
                    GraphChatSession.created_at.desc(),
                )
            )
        ).all()
        return [_session_dto(row) for row in rows]

    async def get_session(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatSessionDTO | None:
        """user-scoped 조회 — 타인 소유/soft delete면 None (라우터에서 404)."""
        row = await self._get_session_row(session_id, user_id)
        return _session_dto(row) if row is not None else None

    async def get_session_by_id(self, session_id: uuid.UUID) -> ChatSessionDTO | None:
        """owner 스코프 없이 세션을 읽는다 (background 실행 전용 — 요청 user 컨텍스트 밖).

        route 폴링/목록은 user-scoped `get_session`을 쓴다. 이 경로는 run_id로 이미
        스코프가 좁혀진 background executor(`execute_graph_chat`)만 호출한다.
        """
        row = await self._session.get(GraphChatSession, session_id)
        return _session_dto(row) if row is not None else None

    async def touch_session(
        self, session_id: uuid.UUID, last_message_at: datetime
    ) -> None:
        row = await self._session.get(GraphChatSession, session_id)
        if row is not None:
            row.last_message_at = last_message_at
            await self._session.flush()

    async def set_last_open_kknaks_session(
        self, session_id: uuid.UUID, open_kknaks_session_id: str
    ) -> None:
        """다음 턴 resume 원천 — 성공 run의 open-kknaks session을 세션에 새긴다 (SPEC-002)."""
        row = await self._session.get(GraphChatSession, session_id)
        if row is not None:
            row.last_open_kknaks_session_id = open_kknaks_session_id
            await self._session.flush()

    async def soft_delete_session(
        self, session_id: uuid.UUID, user_id: uuid.UUID, *, deleted_at: datetime
    ) -> ChatSessionDTO | None:
        row = await self._get_session_row(session_id, user_id)
        if row is None:
            return None
        row.status = "deleted"
        row.deleted_at = deleted_at
        await self._session.flush()
        return _session_dto(row)

    async def _get_session_row(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> GraphChatSession | None:
        return await self._session.scalar(
            sa.select(GraphChatSession).where(
                GraphChatSession.id == session_id,
                GraphChatSession.user_id == user_id,
                GraphChatSession.deleted_at.is_(None),
            )
        )

    # ------------------------------------------------------------------
    # message
    # ------------------------------------------------------------------

    async def add_message(
        self,
        *,
        session_id: uuid.UUID,
        role: str,
        content: str,
        sequence_no: int,
        run_id: uuid.UUID | None = None,
        selected_document_id: uuid.UUID | None = None,
        evidence: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessageDTO:
        row = GraphChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            sequence_no=sequence_no,
            run_id=run_id,
            selected_document_id=selected_document_id,
            evidence=evidence or {},
            metadata_=metadata or {},
        )
        self._session.add(row)
        await self._session.flush()
        return _message_dto(row)

    async def list_messages(self, session_id: uuid.UUID) -> list[ChatMessageDTO]:
        rows = (
            await self._session.scalars(
                sa.select(GraphChatMessage)
                .where(GraphChatMessage.session_id == session_id)
                .order_by(GraphChatMessage.sequence_no.asc())
            )
        ).all()
        return [_message_dto(row) for row in rows]

    async def get_message(self, message_id: uuid.UUID) -> ChatMessageDTO | None:
        """message id로 단건 조회 (run 폴링이 assistant_message를 실을 때)."""
        row = await self._session.get(GraphChatMessage, message_id)
        return _message_dto(row) if row is not None else None

    async def next_sequence_no(self, session_id: uuid.UUID) -> int:
        current = await self._session.scalar(
            sa.select(sa.func.max(GraphChatMessage.sequence_no)).where(
                GraphChatMessage.session_id == session_id
            )
        )
        return (current or 0) + 1

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    async def create_run(
        self,
        *,
        session_id: uuid.UUID,
        user_message_id: uuid.UUID,
        selected_document_id: uuid.UUID | None,
        filters: dict[str, Any] | None,
        queued_at: datetime,
    ) -> ChatRunDTO:
        """queued run 생성. AI 실행 배선은 Phase 2(T-012)."""
        row = GraphChatRun(
            session_id=session_id,
            user_message_id=user_message_id,
            status="queued",
            selected_document_id=selected_document_id,
            filters=filters or {},
            queued_at=queued_at,
        )
        self._session.add(row)
        await self._session.flush()
        return _run_dto(row)

    async def get_run_by_id(self, run_id: uuid.UUID) -> ChatRunDTO | None:
        """run id로 단건 조회 (background 실행이 session_id 없이 run을 집어들 때)."""
        row = await self._session.get(GraphChatRun, run_id)
        return _run_dto(row) if row is not None else None

    async def get_run(
        self, session_id: uuid.UUID, run_id: uuid.UUID
    ) -> ChatRunDTO | None:
        row = await self._session.scalar(
            sa.select(GraphChatRun).where(
                GraphChatRun.id == run_id, GraphChatRun.session_id == session_id
            )
        )
        return _run_dto(row) if row is not None else None

    async def set_run_status(
        self,
        run_id: uuid.UUID,
        status: str,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        assistant_message_id: uuid.UUID | None = None,
        ai_task_id: uuid.UUID | None = None,
        open_kknaks_session_id: str | None = None,
        result_payload: dict[str, Any] | None = None,
        retrieval_context: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> ChatRunDTO:
        """run 상태 전이 (queued→running→succeeded/failed/cancelled).

        Phase 2(T-012)가 실행 결과를 여기로 flush한다. None 인자는 기존 값을 보존한다
        (부분 갱신). Phase 1은 서비스/레포 레벨 전이 테스트로만 커버한다.
        """
        row = await self._session.get(GraphChatRun, run_id)
        if row is None:
            raise LookupError(f"chat run not found: {run_id}")
        row.status = status
        if started_at is not None:
            row.started_at = started_at
        if finished_at is not None:
            row.finished_at = finished_at
        if assistant_message_id is not None:
            row.assistant_message_id = assistant_message_id
        if ai_task_id is not None:
            row.ai_task_id = ai_task_id
        if open_kknaks_session_id is not None:
            row.open_kknaks_session_id = open_kknaks_session_id
        if result_payload is not None:
            row.result_payload = dict(result_payload)
        if retrieval_context is not None:
            row.retrieval_context = dict(retrieval_context)
        if error_code is not None:
            row.error_code = error_code
        if error_message is not None:
            row.error_message = error_message
        await self._session.flush()
        return _run_dto(row)
