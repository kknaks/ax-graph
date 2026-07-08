"""Slack 슬래시 커맨드 라우트 (AXKG-SPEC-003 S-1 / WP1 Phase 4).

`POST /api/v1/slack/commands` — Slack 등록 Request URL과 **문자 그대로** 일치한다(다른
라우트의 무prefix 관례에 대한 명시적 예외, rewrite 없음). 토큰 로그인(AXKG-SPEC-008)
대상이 아니라 Slack signing secret 검증으로 보호하므로 main.py에서 Bearer 없이 mount한다.

흐름(SPEC-003 §5 Implementation Rules):
1. raw body로 v0 서명 검증 → 실패면 401(서명 없이 열리지 않음, Pre-deploy Check).
2. form-urlencoded 파싱 → `text`에서 URL 추출. 없으면 SLACK_URL_MISSING 사용법 ephemeral.
3. `trigger_id` 합성 멱등키로 더블서밋 차단(같은 키 재수신 → source 재생성 없이 ack).
4. Source Inbox에 received·source_channel=slack 저장(중복은 S-2 규칙 재사용).
5. 3초 내 접수 ephemeral ack 반환. 앵커 post·요약 실행은 background(동기 응답을 막지 않음).

봇 아웃바운드(앵커 메시지·요약 스레드 회신)와 요약 실행은 background에 **순차** 등록한다.
Starlette BackgroundTasks는 순차 실행이라 앵커 저장이 요약 회신보다 먼저 끝난다.
"""
from __future__ import annotations

import uuid
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.config import settings as app_settings
from axkg.core.database import get_session, get_session_factory
from axkg.integrations.open_kknaks import OpenKknaksClient
from axkg.integrations.slack import (
    SlackBotClient,
    SlackIdempotencyStore,
    extract_first_url,
    extract_note,
    slash_idempotency_key,
    verify_slack_signature,
)
from axkg.services.slack_intake import SlackSummaryNotifier, post_anchor_message
from axkg.services.sources import InvalidUrlError, SourceService
from axkg.services.summary_execution import execute_source_summary

router = APIRouter(tags=["slack"])

# SPEC-003 Case Matrix: SLACK_URL_MISSING 프론트 출력(사용법 ephemeral).
_USAGE_TEXT = "사용법: `/커맨드 <URL>` 형식으로 링크를 함께 보내주세요."


def _ephemeral(text: str) -> JSONResponse:
    """호출자에게만 보이는 3초 ack/안내(Slack ephemeral 규약)."""
    return JSONResponse(status_code=200, content={"response_type": "ephemeral", "text": text})


def _open_kknaks_client(request: Request) -> OpenKknaksClient | None:
    return getattr(request.app.state, "open_kknaks_client", None)


def _bot_client(request: Request) -> SlackBotClient | None:
    return getattr(request.app.state, "slack_bot_client", None)


def _session_factory(request: Request):
    return getattr(request.app.state, "session_factory", None) or get_session_factory()


def _idempotency_store(request: Request) -> SlackIdempotencyStore:
    """앱 수명에 붙는 in-memory 멱등 집합 (lifespan 미실행 테스트 대비 lazy 생성)."""
    store = getattr(request.app.state, "slack_idempotency", None)
    if store is None:
        store = SlackIdempotencyStore()
        request.app.state.slack_idempotency = store
    return store


@router.post("/api/v1/slack/commands")
async def slack_commands(
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    raw_body = await request.body()

    # 1. 서명 검증 (서명 없이 열리지 않음). raw body 원본으로만 검증.
    if not verify_slack_signature(
        raw_body,
        request.headers.get("x-slack-request-timestamp"),
        request.headers.get("x-slack-signature"),
        app_settings.axkg_slack_signing_secret,
    ):
        return JSONResponse(status_code=401, content={"error": "invalid_signature"})

    # 2. 슬래시 payload = application/x-www-form-urlencoded (command 무관, text의 URL로 동작).
    fields = {k: v[0] for k, v in parse_qs(raw_body.decode()).items()}
    text = (fields.get("text") or "").strip()
    channel_id = fields.get("channel_id") or ""
    user_id = fields.get("user_id") or ""
    team_id = fields.get("team_id", "")
    trigger_id = fields.get("trigger_id", "")

    url = extract_first_url(text)
    if url is None:
        # text에 유효한 URL 없음 → 저장하지 않고 사용법 안내 (SLACK_URL_MISSING).
        return _ephemeral(_USAGE_TEXT)

    # 3. 멱등 — 합성 키로 우발적 더블서밋(3초 재전송) 차단.
    key = slash_idempotency_key(team_id, channel_id, user_id, trigger_id, text)
    if not _idempotency_store(request).mark(key):
        return _ephemeral("이미 접수된 요청입니다.")

    # 4. Source Inbox 저장 (received·slack, S-2 중복 재사용).
    # `<< ... >>` 메모를 raw_text(메모)로 넣는다 — 원문 수집이 실패하면 이 메모로 요약하는
    # user_note fallback 소스가 된다(PLAN-005-T-013). 메모 표식이 없으면 None.
    note = extract_note(text)
    service = SourceService(session)
    try:
        result = await service.create_slack(
            source_url=url,
            raw_text=note,
            slack_user_id=user_id,
            channel_id=channel_id,
            trigger_key=key,
        )
    except InvalidUrlError:
        # extract_first_url가 이미 http/https를 보장하므로 사실상 도달하지 않는다(방어).
        return _ephemeral(_USAGE_TEXT)

    if result.duplicate_kind is not None:
        # 중복 — 새 source·앵커·요약 없이 기존 항목에 연결하고 접수만 알린다 (S-2).
        await session.commit()
        return _ephemeral("이미 받은 URL이에요. 기존 항목에 연결했습니다.")

    source_id = result.source.id
    # 5. received → 자동 요약 트리거(구성 시). 실행은 background 비동기.
    client = _open_kknaks_client(request)
    triggered = None
    if client is not None:
        triggered = await service.start_summary(source_id)

    # background가 커밋된 source/task를 읽도록 먼저 커밋한다(yield-teardown보다 먼저 실행됨).
    await session.commit()

    factory = _session_factory(request)
    bot = _bot_client(request)
    # 순차 등록: 앵커 저장 → (요약 실행 + 스레드 회신). 앵커가 회신보다 먼저 끝난다.
    if bot is not None:
        background.add_task(post_anchor_message, source_id, channel_id, bot, factory)
    if client is not None and triggered is not None:
        background.add_task(
            execute_source_summary,
            triggered.ai_task.id,
            source_id,
            client=client,
            session_factory=factory,
            notifier=SlackSummaryNotifier(bot) if bot is not None else None,
        )

    return _ephemeral("🔖 접수했습니다. 요약이 끝나면 이 스레드로 알려드릴게요.")
