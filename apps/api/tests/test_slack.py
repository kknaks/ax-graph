"""AXKG-SPEC-003 S-1 Slack 슬래시 커맨드 intake 테스트 (WP1 Phase 4).

커버:
- 서명 검증 통과/실패(401), URL 없음→사용법 ephemeral(SLACK_URL_MISSING)
- 정상 URL→source received+slack+ack, 중복 URL→기존 병합(S-2)+ack
- 멱등(같은 trigger_id 2회→source 1건)
- 봇 아웃바운드: 앵커 post→metadata 저장, 요약 종료→앵커 스레드 회신(fake bot)
- 단위: verify_slack_signature / extract_first_url / SlackIdempotencyStore

라이브 Slack 없이 fake 서명/payload/fake bot으로 완결한다(앱 등록·env 2키는 admin 후속).
"""
import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings as app_settings
from axkg.core.database import get_session
from axkg.dto.source_material import SourceMaterial
from axkg.integrations.open_kknaks import OpenKknaksClient, OpenKknaksTaskResult
from axkg.integrations.slack import (
    SlackIdempotencyStore,
    extract_first_url,
    extract_note,
    slash_idempotency_key,
    verify_slack_signature,
)
from axkg.main import app
from axkg.models.base import utcnow
from axkg.repositories.sources import SourceRepository
from axkg.services.slack_intake import SlackSummaryNotifier, post_anchor_message
from axkg.services.sources import SourceService
from axkg.services.summary_execution import execute_source_summary

SECRET = "test-signing-secret"
COMMANDS_PATH = "/api/v1/slack/commands"

VALID_SUMMARY = {
    "title": "Graph RAG 실전 설계",
    "summary": "문서 그래프를 검색 컨텍스트로 삼는 RAG 설계 요약.",
    "keywords": ["graph-rag"],
    "source_type": "article",
    "body_markdown": "## 배경\n문서 그래프를 검색 컨텍스트로 삼는다.",
}


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _slack_state(monkeypatch: pytest.MonkeyPatch):
    """서명 secret 주입 + app.state 격리(멱등 집합·봇·factory·client 리셋)."""
    monkeypatch.setattr(app_settings, "axkg_slack_signing_secret", SECRET)
    app.state.slack_idempotency = SlackIdempotencyStore()
    app.state.slack_bot_client = None
    app.state.open_kknaks_client = None
    if hasattr(app.state, "session_factory"):
        delattr(app.state, "session_factory")
    yield
    app.state.slack_idempotency = SlackIdempotencyStore()
    app.state.slack_bot_client = None
    app.state.open_kknaks_client = None
    if hasattr(app.state, "session_factory"):
        delattr(app.state, "session_factory")


class FakeBot:
    """SlackBotClient 대역 — chat.postMessage 호출을 기록하고 증가 ts를 반환한다."""

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self._n = 0

    async def chat_post_message(self, channel: str, text: str, thread_ts: str | None = None) -> dict:
        self._n += 1
        ts = f"1720000000.00000{self._n}"
        self.posts.append(
            {"channel": channel, "text": text, "thread_ts": thread_ts, "ts": ts}
        )
        return {"ok": True, "ts": ts}

    async def aclose(self) -> None:  # pragma: no cover - 대역 편의
        pass


def _signed_headers(body: str, *, ts: int | None = None, secret: str = SECRET) -> dict[str, str]:
    timestamp = str(int(time.time()) if ts is None else ts)
    basestring = f"v0:{timestamp}:{body}".encode()
    sig = "v0=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()
    return {
        "X-Slack-Signature": sig,
        "X-Slack-Request-Timestamp": timestamp,
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _command_body(
    *,
    text: str,
    command: str = "/axkg",
    channel_id: str = "C123",
    user_id: str = "U123",
    team_id: str = "T123",
    trigger_id: str = "TR123",
) -> str:
    return urlencode(
        {
            "command": command,
            "text": text,
            "channel_id": channel_id,
            "user_id": user_id,
            "team_id": team_id,
            "trigger_id": trigger_id,
        }
    )


async def _post_command(client: AsyncClient, body: str, **header_kw):
    return await client.post(COMMANDS_PATH, content=body, headers=_signed_headers(body, **header_kw))


# ---------------------------------------------------------------------------
# 서명 검증 (단위)
# ---------------------------------------------------------------------------


def test_verify_signature_roundtrip() -> None:
    body = "text=hi"
    ts = str(int(time.time()))
    base = f"v0:{ts}:{body}".encode()
    sig = "v0=" + hmac.new(SECRET.encode(), base, hashlib.sha256).hexdigest()
    assert verify_slack_signature(body.encode(), ts, sig, SECRET) is True
    # 다른 secret / 빈 secret / 헤더 누락 / 만료 timestamp → False
    assert verify_slack_signature(body.encode(), ts, sig, "other") is False
    assert verify_slack_signature(body.encode(), ts, sig, "") is False
    assert verify_slack_signature(body.encode(), None, sig, SECRET) is False
    old = str(int(time.time()) - 600)
    old_sig = "v0=" + hmac.new(
        SECRET.encode(), f"v0:{old}:{body}".encode(), hashlib.sha256
    ).hexdigest()
    assert verify_slack_signature(body.encode(), old, old_sig, SECRET) is False


@pytest.mark.parametrize(
    "text,expected",
    [
        ("https://example.com/a", "https://example.com/a"),
        ("보세요 <https://example.com/b>", "https://example.com/b"),
        ("<https://example.com/c|라벨>", "https://example.com/c"),
        ("메모 https://example.com/d 끝", "https://example.com/d"),
        ("링크 없음", None),
        ("ftp://example.com/x", None),
        ("", None),
    ],
)
def test_extract_first_url(text: str, expected: str | None) -> None:
    assert extract_first_url(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("https://example.com/a", None),  # URL만 → 메모 없음
        ("https://example.com/a << 이 글 핵심 메모 >>", "이 글 핵심 메모"),  # URL+메모
        ("<< 메모만 >> https://example.com/a", "메모만"),  # 순서 무관
        ("https://example.com/a <<   >>", None),  # 공백뿐 → 메모 없음
        ("링크 없음", None),
        ("", None),
    ],
)
def test_extract_note(text: str, expected: str | None) -> None:
    assert extract_note(text) == expected


def test_idempotency_store_marks_once() -> None:
    store = SlackIdempotencyStore(ttl_seconds=300)
    key = slash_idempotency_key("T", "C", "U", "TR", "text")
    assert store.mark(key, now=0.0) is True
    assert store.mark(key, now=1.0) is False  # 중복
    # TTL 경과 후 재수신은 다시 새로 취급
    assert store.mark(key, now=400.0) is True
    # 다른 키는 독립
    other = slash_idempotency_key("T", "C", "U", "TR2", "text")
    assert store.mark(other, now=1.0) is True


# ---------------------------------------------------------------------------
# 라우트 — 서명/URL/멱등/중복
# ---------------------------------------------------------------------------


async def test_invalid_signature_returns_401(client: AsyncClient) -> None:
    body = _command_body(text="https://example.com/a")
    res = await client.post(
        COMMANDS_PATH,
        content=body,
        headers={
            "X-Slack-Signature": "v0=deadbeef",
            "X-Slack-Request-Timestamp": str(int(time.time())),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    assert res.status_code == 401
    assert res.json()["error"] == "invalid_signature"


async def test_missing_url_returns_usage_ephemeral(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    res = await _post_command(client, _command_body(text="URL 없이 텍스트만"))
    assert res.status_code == 200
    payload = res.json()
    assert payload["response_type"] == "ephemeral"
    assert "사용법" in payload["text"]

    # source가 저장되지 않았다
    async with session_factory() as session:
        assert await SourceRepository(session).list(status="received") == []


async def test_valid_url_creates_received_slack_source(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    res = await _post_command(
        client, _command_body(text="이거 봐 https://example.com/ax-article")
    )
    assert res.status_code == 200
    assert res.json()["response_type"] == "ephemeral"
    assert "접수" in res.json()["text"]

    async with session_factory() as session:
        sources = await SourceRepository(session).list(status="received")
        assert len(sources) == 1
        src = sources[0]
        assert src.source_channel == "slack"
        assert src.source_url == "https://example.com/ax-article"
        assert src.status == "received"
        assert src.submitted_by is None  # Slack user는 metadata에 산다
        assert src.metadata["slack_channel"] == "C123"
        assert src.metadata["slack_user"] == "U123"
        assert src.metadata["slack_trigger_key"].startswith("slash:")
        events = src.metadata["slack_events"]
        assert len(events) == 1
        assert events[0]["channel"] == "slack"
        assert events[0]["user"] == "U123"


async def test_idempotent_double_submit_same_trigger(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    body = _command_body(text="https://example.com/idem", trigger_id="TR-SAME")
    first = await _post_command(client, body)
    assert "접수" in first.json()["text"]
    second = await _post_command(client, body)  # 같은 trigger_id 재전송
    assert second.status_code == 200
    assert "이미 접수" in second.json()["text"]

    async with session_factory() as session:
        sources = await SourceRepository(session).list(status="received")
        assert len(sources) == 1  # 재생성 없음


async def test_duplicate_url_links_to_existing(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # 서로 다른 trigger_id지만 같은(정규화 동일) URL → S-2 병합
    first = await _post_command(
        client, _command_body(text="https://example.com/dup", trigger_id="TR-A")
    )
    assert "접수" in first.json()["text"]
    second = await _post_command(
        client, _command_body(text="https://Example.com/dup/", trigger_id="TR-B", user_id="U999")
    )
    assert second.status_code == 200
    assert "이미 받은 URL" in second.json()["text"]

    async with session_factory() as session:
        sources = await SourceRepository(session).list(status="received")
        assert len(sources) == 1  # 새 row 없음
        events = sources[0].metadata["slack_events"]
        assert len(events) == 2  # 최초 + 재수신 누적
        assert events[1]["user"] == "U999"


async def test_slack_note_stored_as_raw_text(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # `<< >>` 메모가 source.raw_text(메모)로 저장돼 user_note fallback 입력이 된다.
    res = await _post_command(
        client,
        _command_body(text="https://example.com/medium-x << 핵심: 전이 비용이 지배적 >>"),
    )
    assert "접수" in res.json()["text"]
    async with session_factory() as session:
        sources = await SourceRepository(session).list(status="received")
        assert len(sources) == 1
        assert sources[0].raw_text == "핵심: 전이 비용이 지배적"


async def test_slack_no_note_leaves_raw_text_none(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # 메모 표식이 없으면 raw_text None → 수집 실패 시 collection_failed(메모로 구제 안 함).
    res = await _post_command(client, _command_body(text="https://example.com/no-note"))
    assert "접수" in res.json()["text"]
    async with session_factory() as session:
        sources = await SourceRepository(session).list(status="received")
        assert len(sources) == 1
        assert sources[0].raw_text is None


# ---------------------------------------------------------------------------
# 봇 아웃바운드 — 앵커 저장 + 요약 스레드 회신 (fake bot)
# ---------------------------------------------------------------------------


async def _new_slack_source(
    session_factory: async_sessionmaker[AsyncSession], *, channel: str = "C123"
) -> uuid.UUID:
    async with session_factory() as session:
        result = await SourceService(session).create_slack(
            source_url="https://example.com/a",
            raw_text="https://example.com/a",
            slack_user_id="U1",
            channel_id=channel,
            trigger_key="slash:abc",
        )
        await session.commit()
        return result.source.id


async def test_post_anchor_stores_ts_in_metadata(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _new_slack_source(session_factory)
    bot = FakeBot()

    await post_anchor_message(source_id, "C123", bot, session_factory)

    # 봇이 채널에 앵커를 post(스레드 아님)했다
    assert len(bot.posts) == 1
    assert bot.posts[0]["channel"] == "C123"
    assert bot.posts[0]["thread_ts"] is None
    anchor_ts = bot.posts[0]["ts"]

    async with session_factory() as session:
        src = await SourceRepository(session).get(source_id)
        assert src.metadata["slack_anchor"] == {"channel": "C123", "ts": anchor_ts}
        assert src.metadata["slack_message_ts"] == anchor_ts
        assert src.slack_message_ts == anchor_ts


class _FakeOpenKknaks(OpenKknaksClient):
    """execute_source_summary용 최소 open-kknaks 대역(run_task는 베이스 편의 경로 사용)."""

    def __init__(self, *, result_text: str | None, status: str = "done") -> None:
        self._result_text = result_text
        self._status = status

    async def submit_task(self, request) -> str:  # noqa: ANN001
        return "okk-1"

    async def get_task_status(self, task_id: str) -> str | None:
        return self._status

    async def wait_result(self, task_id: str, *, timeout_sec=None) -> OpenKknaksTaskResult:  # noqa: ANN001
        return OpenKknaksTaskResult(
            task_id=task_id,
            status=self._status,  # type: ignore[arg-type]
            result_text=self._result_text,
            session_id="sess-1",
        )


async def _collect_ok(url: str, *, user_note: str | None = None) -> SourceMaterial:
    return SourceMaterial(
        source_url=url,
        canonical_url=url,
        adapter="static_web",
        title="예시",
        content_text="본문 " * 200,
        content_format="page_text",
        fetch_method="static_html",
        fetched_at="2026-07-08T00:00:00+00:00",
        metadata={"page_kind": "article"},
    )


async def _arm_summary(
    session_factory: async_sessionmaker[AsyncSession], source_id: uuid.UUID
) -> uuid.UUID:
    """slack source에 앵커를 심고 start_summary로 queued task를 만든다."""
    async with session_factory() as session:
        await SourceRepository(session).set_slack_anchor(source_id, "C123", "1720000000.000009")
        result = await SourceService(session).start_summary(source_id)
        await session.commit()
        return result.ai_task.id


async def test_notifier_replies_on_summarized(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _new_slack_source(session_factory)
    task_id = await _arm_summary(session_factory, source_id)

    bot = FakeBot()
    done = await execute_source_summary(
        task_id,
        source_id,
        client=_FakeOpenKknaks(result_text=json.dumps(VALID_SUMMARY)),
        session_factory=session_factory,
        collect=_collect_ok,
        notifier=SlackSummaryNotifier(bot),
    )
    assert done.status == "succeeded"

    # 앵커 스레드(thread_ts=앵커 ts)로 요약 결과가 회신됐다
    assert len(bot.posts) == 1
    reply = bot.posts[0]
    assert reply["channel"] == "C123"
    assert reply["thread_ts"] == "1720000000.000009"
    assert "요약 완료" in reply["text"]
    assert VALID_SUMMARY["title"] in reply["text"]


async def test_notifier_replies_on_collection_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _new_slack_source(session_factory)
    task_id = await _arm_summary(session_factory, source_id)

    bot = FakeBot()
    # 스키마 불일치 → collection_failed
    done = await execute_source_summary(
        task_id,
        source_id,
        client=_FakeOpenKknaks(result_text=json.dumps({"title": "T"})),
        session_factory=session_factory,
        collect=_collect_ok,
        notifier=SlackSummaryNotifier(bot),
    )
    assert done.status == "failed"

    async with session_factory() as session:
        src = await SourceRepository(session).get(source_id)
        assert src.status == "collection_failed"

    assert len(bot.posts) == 1
    assert bot.posts[0]["thread_ts"] == "1720000000.000009"
    assert "요약 실패" in bot.posts[0]["text"]


async def test_notifier_skips_manual_source(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """manual 유입 source는 요약이 끝나도 Slack 회신하지 않는다."""
    async with session_factory() as session:
        src = await SourceRepository(session).create(
            source_url="https://example.com/manual",
            normalized_url="https://example.com/manual",
            source_channel="manual",
            submitted_by=None,
            submitted_at=utcnow(),
            raw_text=None,
        )
        result = await SourceService(session).start_summary(src.id)
        await session.commit()
        source_id = src.id
        task_id = result.ai_task.id

    bot = FakeBot()
    done = await execute_source_summary(
        task_id,
        source_id,
        client=_FakeOpenKknaks(result_text=json.dumps(VALID_SUMMARY)),
        session_factory=session_factory,
        collect=_collect_ok,
        notifier=SlackSummaryNotifier(bot),
    )
    assert done.status == "succeeded"
    assert bot.posts == []  # manual → 무회신
