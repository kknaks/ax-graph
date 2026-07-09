"""AXKG-SPEC-006 / SPEC-011 ④ chat 스테이지 배선 테스트 (WP4 Phase 2, T-012).

커버:
- execute_graph_chat 오케스트레이션: queued run → running → succeeded/failed
  - 정상: evidence 있는 output → assistant 메시지 저장 + run succeeded + result_payload
    (answer/evidence_documents/evidence_edges/used_paths) + retrieval_context 스냅샷
  - 근거 부족: 실제 문서로 확인되는 evidence 없음 → run succeeded + INSUFFICIENT_GRAPH_CONTEXT
    + missing_context/suggested_actions, 단정 answer(assistant 메시지) 저장 안 함
  - 실패: 파싱/스키마 실패 → run failed + error_code, 실패 ai_task 보존
  - resume: 세션 last_open_kknaks_session_id 있으면 create_task options.resume에 실리고,
    성공 후 세션 session_id가 이번 run의 open-kknaks session으로 갱신
- 폴링 조립: 성공 run GET → answer/evidence_documents 반환

fake open-kknaks client로 네트워크/redis 없이 검증한다. 문서는 tmp markdown root를
rebuild해 인덱싱한다(retriever + evidence stem 확인).
"""
import json
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings
from axkg.core.security import hash_password
from axkg.integrations.open_kknaks import (
    OpenKknaksClient,
    OpenKknaksTaskRequest,
    OpenKknaksTaskResult,
)
from axkg.models import User
from axkg.repositories.chat import ChatRepository
from axkg.services.chat import ChatService
from axkg.services.graph import GraphService
from axkg.services.graph_chat_execution import execute_graph_chat
from axkg.storage.markdown_root import MarkdownRoot

DOC_GRAPH_RAG = """---
type: concept
id: CONCEPT-GRAPH-RAG
title: Graph RAG
---
Graph RAG는 지식 그래프를 검색 컨텍스트로 삼는 RAG다. [[retriever-design]]와 함께 본다.
"""

DOC_RETRIEVER = """---
type: concept
id: CONCEPT-RETRIEVER
title: Retriever 설계
---
retriever는 keyword score와 edge distance를 함께 쓴다.
"""

VALID_OUTPUT = {
    "answer": "Graph RAG는 지식 그래프를 검색 컨텍스트로 삼는 RAG다.",
    "evidence": [
        {
            "stem": "graph-rag",
            "title": "Graph RAG",
            "excerpt": "지식 그래프를 검색 컨텍스트로",
            "reason": "정의 근거",
        },
        {
            "stem": "retriever-design",
            "title": "Retriever 설계",
            "excerpt": "keyword score와 edge distance",
            "reason": "retriever 동작 근거",
        },
    ],
    "missing_context": [],
    "suggested_actions": ["retriever-design 문서를 열어보기"],
}

# schema는 통과하지만(answer/evidence 존재) evidence stem이 그래프에 없어 근거 부족으로 귀결.
INSUFFICIENT_OUTPUT = {
    "answer": "그래프에서 근거가 되는 문서를 찾지 못했다.",
    "evidence": [{"stem": "does-not-exist", "reason": "존재하지 않는 stem"}],
    "missing_context": ["질문에 해당하는 문서가 그래프에 없음"],
    "suggested_actions": ["관련 소스를 먼저 수집하기"],
}


class FakeClient(OpenKknaksClient):
    """제출 request와 반환 session_id를 관찰 가능한 fake (resume 배선/출력 주입용)."""

    def __init__(self, *, result_text: str, status: str = "done", session_id: str = "okk-chat-1") -> None:
        self._result_text = result_text
        self._status = status
        self._session_id = session_id
        self.requests: list[OpenKknaksTaskRequest] = []

    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:
        self.requests.append(request)
        return "okk-task-1"

    async def get_task_status(self, task_id: str) -> str | None:
        return self._status

    async def wait_result(
        self, task_id: str, *, timeout_sec: float | None = None
    ) -> OpenKknaksTaskResult:
        return OpenKknaksTaskResult(
            task_id=task_id,
            status=self._status,  # type: ignore[arg-type]
            result_text=self._result_text,
            session_id=self._session_id,
        )


@pytest.fixture
def graph_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "graph-rag.md").write_text(DOC_GRAPH_RAG, "utf-8")
    (tmp_path / "retriever-design.md").write_text(DOC_RETRIEVER, "utf-8")
    monkeypatch.setattr(settings, "axkg_markdown_root", str(tmp_path))
    return tmp_path


async def _rebuild(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        graph = GraphService(session, root=MarkdownRoot(settings.axkg_markdown_root))
        await graph.rebuild_all()
        await session.commit()


async def _seed_user(session: AsyncSession, email: str = "chat@medisolveai.com") -> uuid.UUID:
    user = User(email=email, password_hash=hash_password("x"))
    session.add(user)
    await session.flush()
    return user.id


async def _start_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    question: str = "RAG란 무엇인가?",
) -> tuple[uuid.UUID, uuid.UUID]:
    """새 채팅 + 첫 질문 queued run을 만들고 (run_id, session_id)를 반환한다."""
    async with session_factory() as session:
        user_id = await _seed_user(session)
        _, _, run = await ChatService(session).start_chat(
            user_id=user_id, question=question
        )
        await session.commit()
        return run.id, run.session_id


# ---------------------------------------------------------------------------
# 정상
# ---------------------------------------------------------------------------


async def test_execute_success_saves_message_and_run(
    session_factory: async_sessionmaker[AsyncSession], graph_root: Path
) -> None:
    await _rebuild(session_factory)
    run_id, session_id = await _start_run(session_factory)

    client = FakeClient(result_text=json.dumps(VALID_OUTPUT))
    done = await execute_graph_chat(run_id, client=client, session_factory=session_factory)
    assert done.status == "succeeded"

    async with session_factory() as session:
        chats = ChatRepository(session)
        run = await chats.get_run_by_id(run_id)
        assert run.status == "succeeded"
        assert run.ai_task_id == done.id
        assert run.open_kknaks_session_id == "okk-chat-1"

        payload = run.result_payload
        assert payload["answer"] == VALID_OUTPUT["answer"]
        stems = {d["stem"] for d in payload["evidence_documents"]}
        assert stems == {"graph-rag", "retriever-design"}
        assert all("document_id" in d for d in payload["evidence_documents"])
        # graph-rag → retriever-design 엣지가 evidence_edges로 잡힌다.
        assert any(
            e["from_stem"] == "graph-rag" and e["to_stem"] == "retriever-design"
            for e in payload["evidence_edges"]
        )
        assert payload["used_paths"] == ["graph-rag", "retriever-design"]
        assert payload.get("error_code") is None
        # retrieval 스냅샷이 run에 보관된다.
        assert run.retrieval_context.get("query")
        assert "documents" in run.retrieval_context

        # assistant 메시지가 seq=2로 저장되고 run에 연결된다.
        messages = await chats.list_messages(session_id)
        assert [m.role for m in messages] == ["user", "assistant"]
        assistant = messages[1]
        assert assistant.id == run.assistant_message_id
        assert assistant.content == VALID_OUTPUT["answer"]
        assert {d["stem"] for d in assistant.evidence["documents"]} == {
            "graph-rag",
            "retriever-design",
        }

        # 세션 last_open_kknaks_session_id가 다음 턴 resume 원천으로 갱신된다.
        chat_session = await chats.get_session_by_id(session_id)
        assert chat_session.last_open_kknaks_session_id == "okk-chat-1"


# ---------------------------------------------------------------------------
# 근거 부족
# ---------------------------------------------------------------------------


async def test_execute_insufficient_surfaces_error_code(
    session_factory: async_sessionmaker[AsyncSession], graph_root: Path
) -> None:
    await _rebuild(session_factory)
    run_id, session_id = await _start_run(session_factory)

    client = FakeClient(result_text=json.dumps(INSUFFICIENT_OUTPUT))
    done = await execute_graph_chat(run_id, client=client, session_factory=session_factory)
    # ai_task 자체는 스키마를 통과했으므로 succeeded다.
    assert done.status == "succeeded"

    async with session_factory() as session:
        chats = ChatRepository(session)
        run = await chats.get_run_by_id(run_id)
        assert run.status == "succeeded"
        assert run.error_code == "INSUFFICIENT_GRAPH_CONTEXT"
        payload = run.result_payload
        assert payload["error_code"] == "INSUFFICIENT_GRAPH_CONTEXT"
        assert payload["answer"] is None
        assert payload["evidence_documents"] == []
        assert payload["missing_context"] == INSUFFICIENT_OUTPUT["missing_context"]
        assert payload["suggested_actions"] == INSUFFICIENT_OUTPUT["suggested_actions"]

        # 단정 answer(assistant 메시지)는 저장하지 않는다 — user 메시지만 남는다.
        messages = await chats.list_messages(session_id)
        assert [m.role for m in messages] == ["user"]
        assert run.assistant_message_id is None


# ---------------------------------------------------------------------------
# 실패 (파싱 / 스키마)
# ---------------------------------------------------------------------------


async def test_execute_parse_failure_marks_run_failed(
    session_factory: async_sessionmaker[AsyncSession], graph_root: Path
) -> None:
    await _rebuild(session_factory)
    run_id, session_id = await _start_run(session_factory)

    client = FakeClient(result_text="not-json {")
    done = await execute_graph_chat(run_id, client=client, session_factory=session_factory)
    assert done.status == "failed"
    assert done.error_code == "OUTPUT_PARSE_FAILED"

    async with session_factory() as session:
        chats = ChatRepository(session)
        run = await chats.get_run_by_id(run_id)
        assert run.status == "failed"
        assert run.error_code == "OUTPUT_PARSE_FAILED"
        assert run.ai_task_id == done.id
        # 실패라 assistant 메시지는 없다.
        messages = await chats.list_messages(session_id)
        assert [m.role for m in messages] == ["user"]


async def test_execute_schema_mismatch_marks_run_failed(
    session_factory: async_sessionmaker[AsyncSession], graph_root: Path
) -> None:
    await _rebuild(session_factory)
    run_id, _ = await _start_run(session_factory)

    # required("answer") 누락 → OUTPUT_SCHEMA_MISMATCH (부분 소비 금지).
    client = FakeClient(result_text=json.dumps({"evidence": []}))
    done = await execute_graph_chat(run_id, client=client, session_factory=session_factory)
    assert done.status == "failed"
    assert done.error_code == "OUTPUT_SCHEMA_MISMATCH"

    async with session_factory() as session:
        run = await ChatRepository(session).get_run_by_id(run_id)
        assert run.status == "failed"
        assert run.error_code == "OUTPUT_SCHEMA_MISMATCH"


# ---------------------------------------------------------------------------
# resume (멀티턴 세션 이어붙이기)
# ---------------------------------------------------------------------------


async def test_execute_wires_resume_session_from_previous_turn(
    session_factory: async_sessionmaker[AsyncSession], graph_root: Path
) -> None:
    await _rebuild(session_factory)
    run_id, session_id = await _start_run(session_factory)

    # 직전 턴이 남긴 세션 open-kknaks session을 심어 둔다.
    async with session_factory() as session:
        await ChatRepository(session).set_last_open_kknaks_session(session_id, "sess-prev")
        await session.commit()

    client = FakeClient(result_text=json.dumps(VALID_OUTPUT), session_id="sess-new")
    done = await execute_graph_chat(run_id, client=client, session_factory=session_factory)
    assert done.status == "succeeded"

    # submit request의 options.resume에 직전 세션이 실린다.
    submitted = client.requests[0]
    assert submitted.options["resume"] == {"mode": "session", "session_id": "sess-prev"}

    # 성공 후 세션은 이번 run의 open-kknaks session으로 갱신(다음 턴 resume 원천).
    async with session_factory() as session:
        chat_session = await ChatRepository(session).get_session_by_id(session_id)
        assert chat_session.last_open_kknaks_session_id == "sess-new"


# ---------------------------------------------------------------------------
# 폴링 조립 (route)
# ---------------------------------------------------------------------------


async def test_run_polling_returns_answer_and_evidence(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    graph_root: Path,
) -> None:
    await _rebuild(session_factory)

    # client 미구성 상태로 채팅 생성(→ queued). 로그인 유저 소유로 만들어 폴링 권한 확보.
    login = await client.post(
        "/auth/login", json={"email": "kknaks@medisolveai.com", "password": "1234"}
    )
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    created = (
        await client.post("/graph/chats", json={"question": "RAG란?"}, headers=headers)
    ).json()
    assert created["status"] == "queued"
    chat_id, run_id = created["chat_id"], created["run_id"]

    # background 대신 직접 실행(같은 엔진 DB를 공유).
    done = await execute_graph_chat(
        uuid.UUID(run_id),
        client=FakeClient(result_text=json.dumps(VALID_OUTPUT)),
        session_factory=session_factory,
    )
    assert done.status == "succeeded"

    res = await client.get(f"/graph/chats/{chat_id}/runs/{run_id}", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "succeeded"
    assert body["answer"] == VALID_OUTPUT["answer"]
    stems = {d["stem"] for d in body["evidence_documents"]}
    assert stems == {"graph-rag", "retriever-design"}
    assert body["assistant_message"]["content"] == VALID_OUTPUT["answer"]
    assert body["error_code"] is None
