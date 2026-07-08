"""Slack 슬래시 커맨드 intake 하부 (AXKG-SPEC-003 S-1 / WP1 Phase 4).

이 모듈은 **Slack 프로토콜 표면**만 담는다(비즈니스 로직은 services/slack_intake·sources):

- `verify_slack_signature`: v0 서명 검증(±5분 replay 윈도우, constant-time). mediness
  `slack_sig` 선례를 포팅. raw body(파싱 전 bytes)로만 검증한다 — 재직렬화 금지.
- `extract_first_url`: 슬래시 `text`에서 첫 http/https URL 추출(`<url>`·`<url|label>` 언랩).
- `slash_idempotency_key`: 슬래시엔 event_id가 없어 `trigger_id` 기반 멱등키를 합성한다.
- `SlackIdempotencyStore`: 더블서밋(3초 내 Slack 재전송) 차단용 in-memory TTL 집합.
- `SlackBotClient`: `chat.postMessage` 아웃바운드(앵커 메시지·스레드 회신). mediness 포팅.

## sources.metadata Slack 규약 (DB README 40-arch database §metadata 확장)

- `metadata.slack_events[]`: 수신 이벤트 누적 — `{ts, channel, channel_id, user, text, received_at}`.
  최초 수신 + 중복 재수신(S-2)이 여기 쌓인다. `channel`은 `slack`/`manual`/`collection_merge`.
- `metadata.slack_channel` / `metadata.slack_user`: 슬래시 최초 수신 채널·제출 Slack user id.
- `metadata.slack_trigger_key`: 최초 수신의 합성 멱등키(디버그·감사용).
- `metadata.slack_anchor`: 접수 후 봇이 채널에 post한 앵커 메시지 — `{channel, ts}`.
  요약 완료/실패 회신을 이 `ts` 스레드로 보낸다.
- `metadata.slack_message_ts`(= 앵커 `ts`): Data Contract `slack_message_ts` 소스(SPEC-003).
  슬래시 커맨드는 제출 메시지 ts가 없으므로 봇 앵커 ts를 대표 ts로 쓴다.

원문(text)/URL 전문은 application log에 남기지 않는다(Pre-deploy Check).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

# Slack 권장 replay 윈도우 = ±5분(300초). 범위 밖 timestamp는 만료로 거부.
REPLAY_WINDOW_SECONDS = 300

# 멱등키 in-memory 유지 시간(초). Slack 슬래시 재전송(3초)보다 넉넉히 크게.
IDEMPOTENCY_TTL_SECONDS = 300.0

# 슬래시 text에서 URL 추출. Slack은 URL을 `<https://x>` 또는 `<https://x|label>`로
# 감쌀 수 있어 `<`, `>`, `|`, 공백에서 끊는다.
_URL_RE = re.compile(r"https?://[^\s<>|]+")

# 슬래시 text에서 `<< ... >>`로 감싼 사용자 메모 추출. 원문 수집이 실패하면 이 메모로
# 요약하는 user_note fallback 소스가 된다(PLAN-005-T-013). 여러 줄 메모 허용(DOTALL).
_NOTE_RE = re.compile(r"<<(.+?)>>", re.DOTALL)


def verify_slack_signature(
    raw_body: bytes,
    timestamp_header: str | None,
    signature_header: str | None,
    secret: str,
    *,
    now: float | None = None,
) -> bool:
    """Slack v0 서명 검증 + timestamp replay 윈도우(±5분).

    계약(v0):
      basestring = b"v0:" + timestamp + b":" + raw_body   (파싱 이전 bytes 원본)
      signature  = "v0=" + hex(HMAC_SHA256(signing_secret, basestring))
      헤더       = X-Slack-Signature / X-Slack-Request-Timestamp

    - secret이 빈 문자열(env 미설정)이면 False — 서명 없이 열리지 않게 하는 안전망.
    - 헤더 누락/형식 불량이면 False. replay 윈도우 밖(±5분)이면 False.
    """
    if not secret:
        return False
    if not timestamp_header or not signature_header:
        return False
    if not signature_header.startswith("v0="):
        return False

    try:
        ts = int(timestamp_header)
    except (TypeError, ValueError):
        return False

    current = time.time() if now is None else now
    if abs(current - ts) > REPLAY_WINDOW_SECONDS:
        return False

    basestring = b"v0:" + timestamp_header.encode() + b":" + raw_body
    digest = hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature_header)


def extract_first_url(text: str | None) -> str | None:
    """슬래시 커맨드 `text`에서 첫 http/https URL을 추출한다(`<url|label>` 언랩).

    유효한 http/https가 없으면 None(호출측이 SLACK_URL_MISSING 사용법으로 안내).
    """
    if not text:
        return None
    match = _URL_RE.search(text)
    if match is None:
        return None
    candidate = match.group(0).rstrip(">.,)]}")
    parts = urlsplit(candidate)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return candidate


def extract_note(text: str | None) -> str | None:
    """슬래시 커맨드 `text`에서 `<< ... >>`로 감싼 사용자 메모를 추출한다(PLAN-005-T-013).

    `<<`/`>>` 표식이 없거나 감싼 내용이 공백뿐이면 None(메모 없음 → 원문 수집 실패 시
    collection_failed). 첫 `<< >>` 쌍만 사용한다. 메모 전문은 로그에 남기지 않는다.
    """
    if not text:
        return None
    match = _NOTE_RE.search(text)
    if match is None:
        return None
    note = match.group(1).strip()
    return note or None


def slash_idempotency_key(
    team_id: str, channel_id: str, user_id: str, trigger_id: str, text: str
) -> str:
    """슬래시엔 event_callback event_id가 없어 BE가 멱등키를 합성한다(mediness 선례).

    Slack은 슬래시당 고유 `trigger_id`(3초·1회용)를 주므로 그걸 기반으로 쓰되,
    누락 시 `채널+유저+본문`으로 degrade한다.
    """
    basis = trigger_id or f"{channel_id}:{user_id}:{text}"
    digest = hashlib.sha256(f"{team_id}:{basis}".encode()).hexdigest()[:24]
    return f"slash:{digest}"


class SlackIdempotencyStore:
    """슬래시 더블서밋 차단용 in-memory TTL 집합 (합성 멱등키 기준).

    Slack은 3초 내 200을 못 받으면 같은 `trigger_id`로 재전송한다. 같은 키가 이미
    보였으면 새 source를 만들지 않고 접수 ack만 반환하게 한다.

    MVP는 단일 프로세스 in-memory다(멀티 워커 공유 아님). 운영에서 다중 인스턴스가 되면
    Redis(`core/redis.py`) 기반으로 승격한다 — 현재 앱은 producer 단일 프로세스 전제.
    """

    def __init__(self, ttl_seconds: float = IDEMPOTENCY_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._seen: dict[str, float] = {}

    def mark(self, key: str, *, now: float | None = None) -> bool:
        """키를 처음 봤으면 기록하고 True, 이미 봤으면(중복) False를 반환한다."""
        current = time.monotonic() if now is None else now
        self._purge(current)
        if key in self._seen:
            return False
        self._seen[key] = current
        return True

    def _purge(self, current: float) -> None:
        expired = [k for k, seen_at in self._seen.items() if current - seen_at > self._ttl]
        for key in expired:
            del self._seen[key]


_BASE_URL = "https://slack.com/api"
_MAX_RETRIES = 3


class SlackBotClient:
    """Slack 봇 아웃바운드(`chat.postMessage`) — 앵커 메시지·스레드 회신. mediness 포팅.

    `AXKG_SLACK_BOT_TOKEN`(xoxb)으로 인증한다. 429/5xx 재시도 + `ok:false` 검사.
    """

    def __init__(self, token: str, timeout: float = 30.0) -> None:
        self._token = token
        self._http = httpx.AsyncClient(base_url=_BASE_URL, timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self._token:
            raise RuntimeError("AXKG_SLACK_BOT_TOKEN not configured")
        headers = {"Authorization": f"Bearer {self._token}"}
        attempt = 0
        while attempt < _MAX_RETRIES:
            resp = await self._http.post(path, json=body, headers=headers)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "1"))
                wait = retry_after * (2**attempt) if retry_after == 0 else retry_after
                await asyncio.sleep(wait)
                attempt += 1
                continue
            if resp.status_code >= 500:
                await asyncio.sleep(2**attempt)
                attempt += 1
                continue
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"slack {path} failed: {data.get('error')}")
            return data
        raise RuntimeError(f"Slack API exhausted retries after {_MAX_RETRIES} attempts")

    async def chat_post_message(
        self, channel: str, text: str, thread_ts: str | None = None
    ) -> dict[str, Any]:
        """chat.postMessage — thread_ts를 주면 스레드 답글. 반환 data에 `ts`가 있다."""
        body: dict[str, Any] = {"channel": channel, "text": text}
        if thread_ts:
            body["thread_ts"] = thread_ts
        return await self._post("/chat.postMessage", body)
