---
type: summary
title: VoltOps Slack Trigger 설정 가이드
source_url: https://voltagent.dev/docs/triggers/slack/
tags:
- Slack Trigger
- VoltOps
- Events API
- webhook
- Slack app
- bot token
- signing secret
- event subscriptions
- agent
- integration
summarized_at: '2026-07-11T03:08:55.695014+00:00'
---

## 개요

**Slack Trigger**는 Slack Events API 웹훅을 리슨하여, 메시지·반응·채널 활동이 발생할 때 **VoltOps**가 에이전트를 실행할 수 있게 한다.
- VoltOps는 Slack의 **URL 인증 챌린지(url_verification)**를 자동으로 처리한다.
- **Signing Secret**을 이용해 요청 서명 검증도 자동으로 수행한다.
- 상세한 트리거 설정·사용법은 별도 Usage Guide를 참조한다(원문 링크 제공).

## 주요 유스케이스

- 앱 멘션을 캡처하여 에이전트로 라우팅
- 새 채널 메시지 요약 또는 분류(triage)
- 이모지 시그널에 반응 (예: 특정 이모지 → 리뷰 요청, 완료 표시)
- 파일 공유 감지 후 다른 곳으로 문서 동기화
- 새 팀원 합류 또는 채널 생성 시 알림

## 자격증명(Credential) 설정 절차

1. [api.slack.com/apps](https://api.slack.com/apps)에서 Slack 앱을 **From scratch**로 생성하고 워크스페이스를 선택한다.
2. **OAuth & Permissions**에서 이벤트 처리에 필요한 봇 스코프를 추가한다.
   - 권장 스코프: `channels:read`, `channels:history`, `groups:history`, `im:history`, `mpim:history`, `reactions:read`, `chat:write`, `files:read`, `files:write`, `users:read`
3. 앱을 워크스페이스에 설치하고 **Bot User OAuth Token** (`xoxb-...`)을 복사한다.
4. **Basic Information**에서 **Signing Secret**을 복사한다. VoltOps는 이를 사용해 Slack 요청 서명을 검증한다.
5. **VoltOps 콘솔 Step 1 (Connection)**에서 Slack 자격증명을 생성하고 아래 값을 입력한다.
   - **Access Token**: `xoxb-` 봇 토큰
   - **Signing Secret**: 서명 검증용(권장). 환경변수 `SLACK_SIGNING_SECRET` 또는 `SLACK_APP_SIGNING_SECRET`으로도 설정 가능.

## 이벤트 구독(Event Subscriptions) 활성화 절차

1. Slack 앱 설정의 **Features → Event Subscriptions**에서 **Enable Events**를 켠다.
2. VoltOps에서 Slack 트리거 생성 시 표시되는 **Request URL**을 붙여넣는다.
   - Slack이 해당 URL로 `url_verification` 요청을 전송하며, VoltOps가 자동으로 응답한다.

> 원문이 설정 절차 도중에 끊겨 있어, 이후 단계(구독할 이벤트 타입 선택 등)는 원문에 포함되지 않음.
