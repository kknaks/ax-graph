"""AXKG-SPEC-006 S-4 / WORK-009 — 채팅④ 방안 → Source Inbox push (PLAN-013-T-008).

커버(계약 SSOT: SPEC-006 §4·S-4, SPEC-003 §5 chat 데이터 계약, SPEC-008 push 경계):
- 정상 push(admin·staff 모두 허용 — 단일 쓰기 액션)
- 본인 아닌 chat 403/404(owner 스코프)
- 빈 대화 422(EMPTY_PUSH_TEXT)
- source 필드 계약(source_channel=chat / source_url·normalized_url null / slack_message_ts null /
  raw_text 대화 전부 / chat_push provenance)
- 서버 조립(§7 OQ 확정): assistant 방안 메시지 포함, role heading 직렬화
- 요약 파이프라인 합류(received → start_summary → summarizing + collect_source_summary task)
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.core.security import hash_password
from axkg.dto.chat import ChatMessageDTO
from axkg.models import User
from axkg.models.base import utcnow
from axkg.repositories.chat import ChatRepository
from axkg.services.chat import ChatService, serialize_conversation
from axkg.services.sources import EmptyPushTextError, SourceService

ADMIN_EMAIL = "kknaks@medisolveai.com"
STAFF_EMAIL = "dr.jinlee@kakao.com"
SEED_PASSWORD = "1234"


async def _auth(client: AsyncClient, email: str = ADMIN_EMAIL) -> dict[str, str]:
    res = await client.post("/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


async def _start_chat(client: AsyncClient, headers: dict[str, str], question: str) -> dict:
    res = await client.post("/graph/chats", json={"question": question}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def _user_id(factory: async_sessionmaker[AsyncSession], email: str) -> uuid.UUID:
    async with factory() as s:
        return await s.scalar(select(User.id).where(User.email == email))


# ---------------------------------------------------------------------------
# 정상 push — admin·staff 모두 허용 (SPEC-008 push 행)
# ---------------------------------------------------------------------------


async def test_push_creates_chat_source_admin(client: AsyncClient) -> None:
    headers = await _auth(client, ADMIN_EMAIL)
    chat = await _start_chat(client, headers, "이 개념으로 뭘 해볼 수 있을까?")

    res = await client.post(
        f"/graph/chats/{chat['chat_id']}/push-to-inbox",
        json={"run_id": chat["run_id"]},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "received"
    assert body["source_id"]


async def test_push_allowed_for_staff(client: AsyncClient) -> None:
    """push는 채팅 접근이 되는 staff도 쓸 수 있는 단일 쓰기 액션 (SPEC-008)."""
    headers = await _auth(client, STAFF_EMAIL)
    chat = await _start_chat(client, headers, "staff가 던지는 아이디어")

    res = await client.post(
        f"/graph/chats/{chat['chat_id']}/push-to-inbox", headers=headers
    )
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "received"


async def test_push_requires_auth(client: AsyncClient) -> None:
    res = await client.post(
        f"/graph/chats/{uuid.uuid4()}/push-to-inbox", json={}
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# owner 스코프 — 본인 아닌 chat push 금지
# ---------------------------------------------------------------------------


async def test_push_other_users_chat_404(client: AsyncClient) -> None:
    owner = await _auth(client, ADMIN_EMAIL)
    chat = await _start_chat(client, owner, "내 채팅")

    intruder = await _auth(client, STAFF_EMAIL)
    res = await client.post(
        f"/graph/chats/{chat['chat_id']}/push-to-inbox", headers=intruder
    )
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "CHAT_SESSION_NOT_FOUND"


# ---------------------------------------------------------------------------
# source 필드 계약 (SPEC-003 §5 chat 데이터 계약)
# ---------------------------------------------------------------------------


async def test_push_source_field_contract(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _auth(client, ADMIN_EMAIL)
    chat = await _start_chat(client, headers, "방안을 달라")
    submitter = await _user_id(session_factory, ADMIN_EMAIL)

    res = await client.post(
        f"/graph/chats/{chat['chat_id']}/push-to-inbox",
        json={"run_id": chat["run_id"]},
        headers=headers,
    )
    source_id = res.json()["source_id"]

    async with session_factory() as s:
        source = await SourceService(s).get(uuid.UUID(source_id))
    assert source.source_channel == "chat"
    assert source.source_url is None
    assert source.normalized_url is None
    assert source.slack_message_ts is None
    assert source.status == "received"
    assert source.submitted_by == submitter
    assert "방안을 달라" in source.raw_text  # push 시점까지의 대화 내용 전부
    # push provenance: chat_id + run_id
    provenance = source.metadata["chat_push"]
    assert provenance["chat_id"] == chat["chat_id"]
    assert provenance["run_id"] == chat["run_id"]


async def test_push_includes_assistant_answer(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """서버 조립(§7 OQ 확정): user 질문 + assistant 방안이 모두 raw_text에 담긴다."""
    headers = await _auth(client, ADMIN_EMAIL)
    chat = await _start_chat(client, headers, "생각을 발전시켜줘")

    # 방안(assistant 메시지)을 세션에 박제 (실전 Graph RAG 실행 결과를 대체).
    async with session_factory() as s:
        await ChatRepository(s).add_message(
            session_id=uuid.UUID(chat["chat_id"]),
            role="assistant",
            content="제시된 방안: 이 개념을 X에 적용해 보라.",
            sequence_no=2,
        )
        await s.commit()

    res = await client.post(
        f"/graph/chats/{chat['chat_id']}/push-to-inbox", headers=headers
    )
    source_id = res.json()["source_id"]
    async with session_factory() as s:
        source = await SourceService(s).get(uuid.UUID(source_id))
    assert "## User" in source.raw_text
    assert "생각을 발전시켜줘" in source.raw_text
    assert "## Assistant" in source.raw_text
    assert "제시된 방안" in source.raw_text


# ---------------------------------------------------------------------------
# 빈 대화 → EMPTY_PUSH_TEXT (endpoint)
# ---------------------------------------------------------------------------


async def test_push_empty_conversation_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # content가 공백뿐인 세션을 repo로 만든다(직렬화 시 잡음 제거 → 빈 raw_text).
    email = "emptypush@medisolveai.com"
    async with session_factory() as s:
        user = User(email=email, password_hash=hash_password(SEED_PASSWORD))
        s.add(user)
        await s.flush()
        chat_session = await ChatRepository(s).create_session(
            user_id=user.id, title="빈 대화"
        )
        await ChatRepository(s).add_message(
            session_id=chat_session.id, role="user", content="   ", sequence_no=1
        )
        await s.commit()
        chat_id = chat_session.id

    headers = await _auth(client, email)
    res = await client.post(
        f"/graph/chats/{chat_id}/push-to-inbox", headers=headers
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "EMPTY_PUSH_TEXT"


# ---------------------------------------------------------------------------
# 서비스/유닛 — 직렬화·cutoff·빈 텍스트·파이프라인 합류
# ---------------------------------------------------------------------------


def test_serialize_conversation_format() -> None:
    now = utcnow()

    def _msg(role: str, content: str, seq: int) -> ChatMessageDTO:
        return ChatMessageDTO(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            role=role,
            content=content,
            sequence_no=seq,
            created_at=now,
        )

    text = serialize_conversation(
        [_msg("user", "질문", 1), _msg("assistant", " 답변 ", 2), _msg("system", "  ", 3)]
    )
    # role heading + 빈 줄 구분, 공백뿐인 메시지는 제외.
    assert text == "## User\n질문\n\n## Assistant\n답변"


async def test_create_chat_push_empty_text_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        service = SourceService(s)
        raised = False
        try:
            await service.create_chat_push(
                raw_text="   ",
                submitted_by=None,
                chat_id=uuid.uuid4(),
                run_id=None,
            )
        except EmptyPushTextError:
            raised = True
        assert raised


async def test_chat_source_joins_summary_pipeline(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """chat source가 slack/manual과 동일한 received→요약 파이프라인에 합류한다 (C-4)."""
    async with session_factory() as s:
        service = SourceService(s)
        source = await service.create_chat_push(
            raw_text="## User\n뭘 해볼까\n\n## Assistant\n방안 A",
            submitted_by=None,
            chat_id=uuid.uuid4(),
            run_id=None,
        )
        assert source.status == "received"
        assert source.source_channel == "chat"

        triggered = await service.start_summary(source.id)
        assert triggered.source.status == "summarizing"
        assert triggered.ai_task.task_type == "collect_source_summary"
        await s.commit()


async def test_push_run_id_cutoff_excludes_later_messages(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """cutoff_run_id는 그 run의 응답까지만 담고 이후 턴은 제외한다 (push 시점 경계)."""
    async with session_factory() as s:
        user = User(email="cutoff@medisolveai.com", password_hash=hash_password("x"))
        s.add(user)
        await s.flush()
        service = ChatService(s)
        chat, _msg1, run1 = await service.start_chat(
            user_id=user.id, question="첫 질문"
        )
        # 이후 턴(제외 대상)
        await service.add_message(
            user_id=user.id, session_id=chat.id, question="두 번째 질문"
        )
        await s.commit()

        full = await service.assemble_conversation_for_push(user.id, chat.id)
        assert "첫 질문" in full and "두 번째 질문" in full

        cut = await service.assemble_conversation_for_push(
            user.id, chat.id, cutoff_run_id=run1.id
        )
        assert "첫 질문" in cut
        assert "두 번째 질문" not in cut
