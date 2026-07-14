"""graph chat lifecycle (AXKG-SPEC-006). session/message/run 생성·조회·상태 전이. WP4 Phase 1.

경계:
- 이 Phase는 채팅 세션/메시지/run 의 lifecycle·영속·폴링 골격까지다.
- run은 `queued`로 생성되고 **AI 실행은 배선하지 않는다**. Graph RAG context builder·retriever
  호출·open-kknaks 실행·응답 파싱·evidence 저장·INSUFFICIENT_GRAPH_CONTEXT 는 Phase 2(T-012).
  run 상태 전이(set_run_status)는 그때 이 서비스/레포를 통해 채워진다.
"""
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.chat import ChatMessageDTO, ChatRunDTO, ChatSessionDTO
from axkg.models.base import utcnow
from axkg.repositories.chat import ChatRepository
from axkg.services.documents import DocumentNotFoundError, DocumentService

# 세션 제목은 첫 질문 앞부분을 잘라 만든다(사용자 지정 제목은 이후 개선 항목).
MAX_TITLE_LENGTH = 80

# 대화 push 직렬화 role 라벨 (AXKG-SPEC-006 §7 OQ 확정: 서버 조립 + role heading 형식).
# 요약①(LLM)이 raw_text로 소비하므로 role 구분이 명확한 markdown heading으로 박제한다.
_PUSH_ROLE_LABELS = {"user": "User", "assistant": "Assistant", "system": "System"}


def serialize_conversation(messages: list[ChatMessageDTO]) -> str:
    """채팅 대화 이력을 push용 raw_text로 직렬화한다 (AXKG-SPEC-006 §7 OQ 확정).

    각 메시지를 ``## {Role}\\n{content}`` 블록으로, 블록 사이는 빈 줄로 구분한다. 빈/공백
    content 메시지는 건너뛴다(잡음 제거). role 라벨은 User/Assistant/System로 고정한다.
    """
    blocks: list[str] = []
    for message in messages:
        content = (message.content or "").strip()
        if not content:
            continue
        label = _PUSH_ROLE_LABELS.get(message.role, message.role)
        blocks.append(f"## {label}\n{content}")
    return "\n\n".join(blocks)


class EmptyQuestionError(Exception):
    """빈/공백 질문 (Case Matrix: EMPTY_QUESTION)."""


class NodeNotFoundError(Exception):
    """selected_node_id가 그래프(documents)에 없음 (Case Matrix: NODE_NOT_FOUND)."""

    def __init__(self, node_id: uuid.UUID) -> None:
        super().__init__(f"graph node not found: {node_id}")
        self.node_id = node_id


class ChatSessionNotFoundError(Exception):
    """세션이 없거나 타인 소유 (owner 스코프 → 404)."""

    def __init__(self, session_id: uuid.UUID) -> None:
        super().__init__(f"chat session not found: {session_id}")
        self.session_id = session_id


def _title_from_question(question: str) -> str:
    text = " ".join(question.split())
    if len(text) <= MAX_TITLE_LENGTH:
        return text
    return text[: MAX_TITLE_LENGTH - 1].rstrip() + "…"


class ChatService:
    def __init__(self, session: AsyncSession) -> None:
        self._chats = ChatRepository(session)
        self._documents = DocumentService(session)

    # ------------------------------------------------------------------
    # 생성 (run은 queued — 실행은 Phase 2)
    # ------------------------------------------------------------------

    async def start_chat(
        self,
        *,
        user_id: uuid.UUID,
        question: str,
        selected_node_id: uuid.UUID | None = None,
        filters: dict[str, Any] | None = None,
    ) -> tuple[ChatSessionDTO, ChatMessageDTO, ChatRunDTO]:
        """새 채팅 세션 + 첫 사용자 메시지(seq=1) + queued run 생성 (SPEC-006 POST /graph/chats)."""
        text = self._require_question(question)
        await self._require_node(selected_node_id)

        session = await self._chats.create_session(
            user_id=user_id,
            title=_title_from_question(text),
            selected_document_id=selected_node_id,
        )
        message, run = await self._append_turn(
            session_id=session.id,
            question=text,
            sequence_no=1,
            selected_node_id=selected_node_id,
            filters=filters,
        )
        return session, message, run

    async def add_message(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        question: str,
        selected_node_id: uuid.UUID | None = None,
        filters: dict[str, Any] | None = None,
    ) -> tuple[ChatMessageDTO, ChatRunDTO]:
        """기존 채팅에 질문 추가 + 새 queued run (SPEC-006 POST /graph/chats/{id}/messages)."""
        session = await self._require_session(user_id, session_id)
        text = self._require_question(question)
        await self._require_node(selected_node_id)

        sequence_no = await self._chats.next_sequence_no(session.id)
        return await self._append_turn(
            session_id=session.id,
            question=text,
            sequence_no=sequence_no,
            selected_node_id=selected_node_id,
            filters=filters,
        )

    async def _append_turn(
        self,
        *,
        session_id: uuid.UUID,
        question: str,
        sequence_no: int,
        selected_node_id: uuid.UUID | None,
        filters: dict[str, Any] | None,
    ) -> tuple[ChatMessageDTO, ChatRunDTO]:
        """사용자 메시지 + queued run 을 짝으로 남기고 세션 last_message_at을 갱신한다."""
        now = utcnow()
        message = await self._chats.add_message(
            session_id=session_id,
            role="user",
            content=question,
            sequence_no=sequence_no,
            selected_document_id=selected_node_id,
        )
        run = await self._chats.create_run(
            session_id=session_id,
            user_message_id=message.id,
            selected_document_id=selected_node_id,
            filters=filters,
            queued_at=now,
        )
        # run 생성 직후 user 메시지에 run_id를 역참조로 채운다 — FE가 세션 재개 시 응답이
        # 아직 없는 user 메시지의 run_id로 진행 중 run 폴링을 잇는다 (SPEC-006, T-013).
        message = await self._chats.set_message_run_id(message.id, run.id) or message
        await self._chats.touch_session(session_id, now)
        # queued run 생성까지가 이 서비스의 책임이다. Graph RAG 실행 트리거는 route가
        # background(`execute_graph_chat`)로 배선한다(T-012). 서비스는 실행 client를
        # 소유하지 않으므로(요약 intake와 동일) 여기서 실행을 호출하지 않는다.
        return message, run

    # ------------------------------------------------------------------
    # 조회 (owner 스코프)
    # ------------------------------------------------------------------

    async def list_sessions(self, user_id: uuid.UUID) -> list[ChatSessionDTO]:
        return await self._chats.list_sessions(user_id)

    async def get_session_detail(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> tuple[ChatSessionDTO, list[ChatMessageDTO]]:
        session = await self._require_session(user_id, session_id)
        messages = await self._chats.list_messages(session.id)
        return session, messages

    async def get_run(
        self, user_id: uuid.UUID, session_id: uuid.UUID, run_id: uuid.UUID
    ) -> ChatRunDTO:
        session = await self._require_session(user_id, session_id)
        run = await self._chats.get_run(session.id, run_id)
        if run is None:
            raise ChatSessionNotFoundError(session_id)
        return run

    async def get_run_detail(
        self, user_id: uuid.UUID, session_id: uuid.UUID, run_id: uuid.UUID
    ) -> tuple[ChatRunDTO, ChatMessageDTO | None]:
        """폴링용 — run + (성공 run이면) 연결된 assistant 메시지를 함께 반환한다 (SPEC-006 §4)."""
        run = await self.get_run(user_id, session_id, run_id)
        assistant_message: ChatMessageDTO | None = None
        if run.assistant_message_id is not None:
            assistant_message = await self._chats.get_message(run.assistant_message_id)
        return run, assistant_message

    # ------------------------------------------------------------------
    # 방안 push — 대화 조립 (AXKG-SPEC-006 S-4, WORK-009)
    # ------------------------------------------------------------------

    async def assemble_conversation_for_push(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        cutoff_run_id: uuid.UUID | None = None,
    ) -> str:
        """push 시점까지의 대화 내용 전부를 서버가 조립해 raw_text로 돌려준다 (S-4).

        조립 위치는 **서버**로 확정한다(AXKG-SPEC-006 §7 OQ) — 채팅 이력의 SoT가 서버이므로
        클라이언트 직렬화를 신뢰하지 않고 서버가 `session_id`로 대화를 authoritative하게 조립한다.
        owner 스코프를 강제한다(타인/삭제 세션은 404). `cutoff_run_id`가 주어지면 그 run의
        응답(assistant, 없으면 user)까지를 컷오프로 삼아 "push 시점까지"를 경계 짓는다.
        run_id가 없으면 세션의 모든 메시지를 담는다.
        """
        await self._require_session(user_id, session_id)
        messages = await self._chats.list_messages(session_id)
        if cutoff_run_id is not None:
            cutoff_seq = await self._resolve_cutoff_sequence(session_id, cutoff_run_id)
            if cutoff_seq is not None:
                messages = [m for m in messages if m.sequence_no <= cutoff_seq]
        return serialize_conversation(messages)

    async def _resolve_cutoff_sequence(
        self, session_id: uuid.UUID, run_id: uuid.UUID
    ) -> int | None:
        """push 컷오프 run의 마지막 메시지 sequence_no — assistant 응답(없으면 user 질문) 기준."""
        run = await self._chats.get_run(session_id, run_id)
        if run is None:
            return None
        target_id = run.assistant_message_id or run.user_message_id
        if target_id is None:
            return None
        message = await self._chats.get_message(target_id)
        return message.sequence_no if message is not None else None

    # ------------------------------------------------------------------
    # 검증 helper
    # ------------------------------------------------------------------

    @staticmethod
    def _require_question(question: str) -> str:
        text = (question or "").strip()
        if not text:
            raise EmptyQuestionError
        return text

    async def _require_node(self, selected_node_id: uuid.UUID | None) -> None:
        if selected_node_id is None:
            return
        try:
            await self._documents.get_document(selected_node_id)
        except DocumentNotFoundError as exc:
            raise NodeNotFoundError(selected_node_id) from exc

    async def _require_session(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> ChatSessionDTO:
        session = await self._chats.get_session(session_id, user_id)
        if session is None:
            raise ChatSessionNotFoundError(session_id)
        return session
