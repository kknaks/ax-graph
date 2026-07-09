"""AXKG-SPEC-006 Graph Chat lifecycle API 테스트 (WP4 Phase 1).

커버: 세션/메시지/run 생성·조회·폴링, sequence_no 순서, owner 스코프 격리(404),
EMPTY_QUESTION/NODE_NOT_FOUND Case Matrix, run 상태 전이(service/repo 레벨).
AI 실행(Graph RAG)은 Phase 2(T-012)라 run은 queued로만 검증한다.
"""
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings
from axkg.core.database import get_session
from axkg.core.security import hash_password
from axkg.main import app
from axkg.models import User
from axkg.models.base import utcnow
from axkg.repositories.chat import ChatRepository
from axkg.services.chat import ChatService

SEED_EMAIL = "kknaks@medisolveai.com"
SEED_PASSWORD = "1234"
OTHER_EMAIL = "other@medisolveai.com"
OTHER_PASSWORD = "5678"

CONCEPT = """---
type: concept
id: CONCEPT-GRAPH-RAG
title: Graph RAG
---
Graph RAG combines retrieval with a knowledge graph.
"""


async def _auth(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


@pytest.fixture
async def other_headers(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> dict[str, str]:
    """seed 유저와 별개의 두 번째 유저 — owner 스코프 격리 검증용."""
    async with session_factory() as s:
        s.add(
            User(
                email=OTHER_EMAIL,
                password_hash=hash_password(OTHER_PASSWORD),
                display_name="Other",
            )
        )
        await s.commit()
    return await _auth(client, OTHER_EMAIL, OTHER_PASSWORD)


@pytest.fixture
def seeded_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "graph-rag.md").write_text(CONCEPT, "utf-8")
    monkeypatch.setattr(settings, "axkg_markdown_root", str(tmp_path))
    return tmp_path


async def _doc_id(client: AsyncClient, headers: dict[str, str], stem: str) -> str:
    res = await client.get("/documents", headers=headers)
    assert res.status_code == 200
    for doc in res.json()["documents"]:
        if doc["stem"] == stem:
            return doc["id"]
    raise AssertionError(f"document {stem} not found")


# ---------------------------------------------------------------------------
# 생성 / 이력
# ---------------------------------------------------------------------------


async def test_create_chat_persists_session_message_run(client: AsyncClient) -> None:
    headers = await _auth(client, SEED_EMAIL, SEED_PASSWORD)
    res = await client.post(
        "/graph/chats", json={"question": "  RAG란 무엇인가?  "}, headers=headers
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "queued"
    assert body["chat_id"] and body["run_id"] and body["user_message_id"]

    # 이력 조회 → seq=1 user 메시지 + queued run 폴링 확인.
    detail = await client.get(f"/graph/chats/{body['chat_id']}", headers=headers)
    assert detail.status_code == 200
    messages = detail.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["sequence_no"] == 1
    assert messages[0]["content"] == "RAG란 무엇인가?"  # 앞뒤 공백 trim

    run = await client.get(
        f"/graph/chats/{body['chat_id']}/runs/{body['run_id']}", headers=headers
    )
    assert run.status_code == 200
    run_body = run.json()
    assert run_body["status"] == "queued"
    assert run_body["answer"] is None
    assert run_body["chat_id"] == body["chat_id"]


async def test_add_message_increments_sequence_and_new_run(
    client: AsyncClient,
) -> None:
    headers = await _auth(client, SEED_EMAIL, SEED_PASSWORD)
    created = (
        await client.post(
            "/graph/chats", json={"question": "첫 질문"}, headers=headers
        )
    ).json()
    chat_id = created["chat_id"]

    res = await client.post(
        f"/graph/chats/{chat_id}/messages",
        json={"question": "두 번째 질문"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "queued"
    assert body["run_id"] != created["run_id"]

    detail = (await client.get(f"/graph/chats/{chat_id}", headers=headers)).json()
    seqs = [m["sequence_no"] for m in detail["messages"]]
    assert seqs == [1, 2]  # sequence_no asc
    assert detail["messages"][1]["content"] == "두 번째 질문"


async def test_list_chats_only_returns_owner_sessions(
    client: AsyncClient, other_headers: dict[str, str]
) -> None:
    headers = await _auth(client, SEED_EMAIL, SEED_PASSWORD)
    mine = (
        await client.post("/graph/chats", json={"question": "내 채팅"}, headers=headers)
    ).json()
    await client.post(
        "/graph/chats", json={"question": "남의 채팅"}, headers=other_headers
    )

    listing = await client.get("/graph/chats", headers=headers)
    assert listing.status_code == 200
    ids = {c["chat_id"] for c in listing.json()["chats"]}
    assert ids == {mine["chat_id"]}


# ---------------------------------------------------------------------------
# 검증 Case Matrix
# ---------------------------------------------------------------------------


async def test_empty_question_rejected(client: AsyncClient) -> None:
    headers = await _auth(client, SEED_EMAIL, SEED_PASSWORD)
    res = await client.post(
        "/graph/chats", json={"question": "   "}, headers=headers
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "EMPTY_QUESTION"


async def test_unknown_selected_node_rejected(client: AsyncClient) -> None:
    headers = await _auth(client, SEED_EMAIL, SEED_PASSWORD)
    res = await client.post(
        "/graph/chats",
        json={
            "question": "이 노드에 대해",
            "selected_node_id": "00000000-0000-0000-0000-000000000000",
        },
        headers=headers,
    )
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "NODE_NOT_FOUND"


async def test_valid_selected_node_accepted(
    client: AsyncClient, seeded_root: Path
) -> None:
    headers = await _auth(client, SEED_EMAIL, SEED_PASSWORD)
    assert (await client.post("/graph/rebuild", headers=headers)).status_code == 200
    node_id = await _doc_id(client, headers, "graph-rag")
    res = await client.post(
        "/graph/chats",
        json={"question": "이 개념 설명", "selected_node_id": node_id},
        headers=headers,
    )
    assert res.status_code == 201, res.text


# ---------------------------------------------------------------------------
# owner 스코프 격리 (404)
# ---------------------------------------------------------------------------


async def test_other_user_cannot_read_session_or_run(
    client: AsyncClient, other_headers: dict[str, str]
) -> None:
    headers = await _auth(client, SEED_EMAIL, SEED_PASSWORD)
    created = (
        await client.post("/graph/chats", json={"question": "비밀"}, headers=headers)
    ).json()
    chat_id, run_id = created["chat_id"], created["run_id"]

    # B가 A의 세션 상세 조회 → 404
    assert (
        await client.get(f"/graph/chats/{chat_id}", headers=other_headers)
    ).status_code == 404
    # B가 A의 run 폴링 → 404
    assert (
        await client.get(
            f"/graph/chats/{chat_id}/runs/{run_id}", headers=other_headers
        )
    ).status_code == 404
    # B가 A의 세션에 메시지 추가 → 404
    assert (
        await client.post(
            f"/graph/chats/{chat_id}/messages",
            json={"question": "끼어들기"},
            headers=other_headers,
        )
    ).status_code == 404


async def test_run_polling_unknown_run_404(client: AsyncClient) -> None:
    headers = await _auth(client, SEED_EMAIL, SEED_PASSWORD)
    created = (
        await client.post("/graph/chats", json={"question": "질문"}, headers=headers)
    ).json()
    res = await client.get(
        f"/graph/chats/{created['chat_id']}/runs/"
        "00000000-0000-0000-0000-000000000000",
        headers=headers,
    )
    assert res.status_code == 404


async def test_chat_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/graph/chats")).status_code == 401


# ---------------------------------------------------------------------------
# run 상태 전이 (service/repo 레벨 — Phase 2가 호출할 seam)
# ---------------------------------------------------------------------------


async def test_run_status_transitions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        user = User(email="tx@medisolveai.com", password_hash=hash_password("x"))
        s.add(user)
        await s.flush()
        service = ChatService(s)
        repo = ChatRepository(s)

        _, _, run = await service.start_chat(user_id=user.id, question="전이 테스트")
        assert run.status == "queued"

        now = utcnow()
        running = await repo.set_run_status(run.id, "running", started_at=now)
        assert running.status == "running"
        assert running.started_at is not None

        done = await repo.set_run_status(
            run.id,
            "succeeded",
            finished_at=now,
            result_payload={"answer": "결과", "confidence": 0.8},
        )
        assert done.status == "succeeded"
        assert done.result_payload["answer"] == "결과"
        assert done.finished_at is not None

        # 실패 전이도 가능해야 한다.
        failed = await repo.set_run_status(
            run.id, "failed", error_code="INSUFFICIENT_GRAPH_CONTEXT"
        )
        assert failed.status == "failed"
        assert failed.error_code == "INSUFFICIENT_GRAPH_CONTEXT"
        await s.commit()
