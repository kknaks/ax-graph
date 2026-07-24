---
type: reference
title: "Slack 연동 참조 구현 — 서명검증·슬래시 커맨드·outbound 봇·멱등성 (REF-0001)"
source: ""
aliases: ["Slack 연동 참조 구현", "REF-0001", "Slack 서명검증 레시피", "슬래시 커맨드 수신 패턴"]
tags: ["Slack", "서명검증", "HMAC-SHA256", "멱등성", "슬래시커맨드", "BackgroundTasks", "chat.postMessage", "integration-reference"]
up: ["슬랙봇-개발-방식"]
---

# Slack 연동 참조 구현 — 서명검증·슬래시 커맨드·outbound 봇·멱등성 (REF-0001)

## 요약

ax-graph 프로젝트의 Slack 연동 모듈(`slack.py`, `routes/slack.py`, `services/slack_intake.py`)을 정제한 참조 구현 문서다. inbound 슬래시 커맨드 수신, outbound 봇 메시지 발신, 서명검증, 멱등성 네 축의 구현 패턴과 체크리스트를 담아, 다른 프로젝트에 Slack을 붙일 때 바로 꺼내 쓸 수 있도록 정리한다.

## 핵심 내용

### env 설정

연동에 필요한 환경 변수는 두 가지다:

| env | 용도 |
|---|---|
| `*_SLACK_SIGNING_SECRET` | inbound 요청 서명 검증 (Slack App > Basic Information > Signing Secret) |
| `*_SLACK_BOT_TOKEN` | outbound `chat.postMessage`용 bot token (`xoxb-...`) |

ax-graph 예: `AXKG_SLACK_SIGNING_SECRET`, `AXKG_SLACK_BOT_TOKEN`.

---

### 서명 검증 (inbound 필수 선행)

Slack은 모든 inbound 요청에 `X-Slack-Signature` + `X-Slack-Request-Timestamp` 헤더를 붙인다. **검증 전에는 어떤 처리도 하지 않는다.** 실패 시 401 반환.

[[slack-서명검증]] 개념의 핵심 규칙:

- **v0 방식**: `basestring = "v0:{timestamp}:{raw_body}"`, `expected = "v0=" + hmac_sha256(signing_secret, basestring)`
- **raw body(파싱 전 bytes)만** 사용 — form 파싱 후 재직렬화 시 서명 깨짐
- **replay 윈도우 ±5분(300초)**: `abs(now - timestamp) > 300`이면 만료로 거부
- **constant-time 비교**: `hmac.compare_digest` 사용 (타이밍 공격 방지)

```python
REPLAY_WINDOW_SECONDS = 300

def verify_slack_signature(raw_body, timestamp_header, signature_header, secret, *, now=None):
    if not timestamp_header or not signature_header:
        return False
    try:
        ts = int(timestamp_header)
    except ValueError:
        return False
    if abs((now or time.time()) - ts) > REPLAY_WINDOW_SECONDS:
        return False
    basestring = b"v0:" + timestamp_header.encode() + b":" + raw_body
    digest = hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()
    expected = "v0=" + digest
    return hmac.compare_digest(expected, signature_header)
```

> 슬래시 커맨드 라우트는 signing secret으로 보호되므로 Bearer 인증 대상에서 **제외**한다(Slack은 Bearer를 붙이지 않는다). 인증 미들웨어에서 이 경로만 열어준다.

---

### Inbound — 슬래시 커맨드 라우트

- 엔드포인트: `POST /api/v1/slack/commands`
- Slack App에 등록한 Request URL과 **문자 그대로** 일치시킨다(다른 라우트의 prefix rewrite 관례에 대한 명시적 예외).

**처리 흐름** (Slack 3초 응답 제약이 지배):

1. raw body로 [[slack-서명검증]] 수행 → 실패 시 401
2. form-urlencoded 파싱 → `text`에서 URL/메모 추출. 필요한 값 없으면 사용법 **ephemeral** 응답
3. **멱등키로 더블서밋 차단** → 중복이면 재처리 없이 ack
4. 도메인 처리(예: 소스 저장)
5. **3초 내 ephemeral ack 반환.** 무거운 작업(봇 앵커 post, 요약/enrich)은 **BackgroundTasks**로 미뤄 동기 응답을 막지 않는다
   - Starlette `BackgroundTasks`는 순차 실행 → 앵커가 응답 회신보다 먼저 처리됨

```python
def _ephemeral(text: str) -> JSONResponse:
    return JSONResponse(status_code=200, content={"response_type": "ephemeral", "text": text})
```

**`text` 파싱 유틸**:
- Slack은 URL을 `<https://x>` / `<https://x|label>` 형태로 감쌈
- `extract_first_url(text)` — 첫 http/https URL, `<`·`>`·`|`·공백에서 끊고 언랩
- `extract_note(text)` — `<< ... >>`로 감싼 사용자 메모 (원문 수집 실패 시 fallback)

---

### Inbound — 멱등성

[[slack-슬래시커맨드-멱등성]] 처리 방식:

- **이벤트 API**(메시지 이벤트 등): `event_id`가 있어 그것을 멱등키로 사용
- **슬래시 커맨드는 `event_id`가 없다** → `trigger_id` 기반 합성 멱등키 생성:
  - 형식: `slash:{sha256(team_id:channel_id:user_id:trigger_id:text)}`
- Slack은 3초 내 응답 없으면 **재전송** → in-memory TTL 집합(300초)으로 중복 차단

```python
class SlackIdempotencyStore:
    def mark(self, key, *, now=None) -> bool:
        # 처음 보면 저장 후 True, 이미 있으면 False (중복)
        ...
```

> 프로세스 여러 개(워커 스케일아웃)면 in-memory 대신 **Redis TTL**로 승격한다.

---

### Outbound — 봇 메시지 (`chat.postMessage`)

- `SlackBotClient`가 bot token으로 `chat.postMessage` 호출
- 용도: 접수 **앵커 메시지**를 채널에 남기고, 이후 결과를 그 메시지의 **스레드**(`thread_ts`)로 회신
- 헤더: `Authorization: Bearer {bot_token}`
- **429 Retry-After 처리**: `Retry-After` 헤더만큼 대기 후 재시도
- 앵커 `{channel, ts}`를 저장해두고, 회신 시 `thread_ts=ts`로 스레드에 건다
- 슬래시 커맨드는 제출 메시지 ts가 없으므로 **봇 앵커 ts를 대표 ts**로 사용

---

### 저장 규약 (metadata) — 선택

ax-graph는 소스 row의 `metadata`에 Slack 맥락을 누적한다:

| 필드 | 내용 |
|---|---|
| `slack_events[]` | 수신 이벤트 누적 `{ts, channel, channel_id, user, text, received_at}` |
| `slack_channel` / `slack_user` | 최초 수신 채널 / 제출 user id |
| `slack_trigger_key` | 최초 수신 합성 멱등키 (감사용) |
| `slack_anchor` | 봇 앵커 메시지 `{channel, ts}` |
| `slack_message_ts` | 앵커 `ts` (대표 ts) |

---

### Outbound 알림 계약 패턴

mediness SPEC-119 참고. "상태가 전이될 때 다음 행동 주체에게 DM" 같은 알림 계약을 만들 때의 정석:

- 알림은 **상태 전이 이벤트**에 훅한다 (원장 상태 변경 시 `*_event` 발생 → 알림)
- "어떤 전이에서 / 누구에게 / 무엇을"만 외부 계약으로 고정
- enum·흐름·엔진 설계는 앵커 SPEC/코드가 SoT — 알림 SPEC은 **재정의하지 않고 참조**
- 수신자 매핑(`user.slack_id` 같은 컬럼)의 SoT를 명확히 한다

---

### 체크리스트 (다른 프로젝트에 붙일 때)

- [ ] `SLACK_SIGNING_SECRET` / `SLACK_BOT_TOKEN` env 설정
- [ ] 서명 검증을 **raw body**로, replay ±5분, constant-time으로 구현
- [ ] 슬래시 라우트를 **Bearer 인증 예외**로 mount, Request URL 문자 그대로 일치
- [ ] 3초 ephemeral ack + 무거운 작업 background 분리
- [ ] 멱등성 (event_id 또는 trigger_id 합성키) + TTL 중복 차단
- [ ] outbound는 앵커+스레드 회신, 429 Retry-After 처리
- [ ] 원문/URL 전문을 application log에 남기지 않기 (민감정보)

---

## 연결

- [[슬랙봇-개발-방식]] — Slack 연동 서버 구현 방식(Bolt/SDK/Webhook)의 개념 SoT; 이 레퍼런스의 상위 개념 계보
- [[슬랙봇-개념부터-개발까지-업무자동화-에어프레미아-기술세션]] — Slack Bot Token·Event Subscriptions 설정 흐름을 다루는 형제 레퍼런스; 연동 절차 비교 참조
- [[voltops-slack-trigger-설정-가이드]] — VoltOps 환경에서 Signing Secret·Bot Token을 등록하는 설정 절차; 서명 검증 개념을 공유하는 형제 레퍼런스
- [[slack-서명검증]] — HMAC-SHA256 v0 방식·raw body·replay 윈도우·constant-time 비교의 개념 SoT 위임
- [[slack-슬래시커맨드-멱등성]] — trigger_id 기반 합성 멱등키·in-memory TTL·Redis 승격 패턴의 개념 SoT 위임
