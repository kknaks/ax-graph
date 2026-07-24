---
type: reference
title: "VoltOps Slack Trigger 설정 가이드 (Events API 웹훅 연동)"
source: "https://voltagent.dev/docs/triggers/slack/"
aliases: ["VoltOps Slack Trigger", "Slack Events API 웹훅 연동", "VoltOps Slack 연동"]
tags: ["VoltOps", "Slack", "Events API", "webhook", "integration", "trigger", "docs", "bot-token", "signing-secret"]
up: ["에이전틱-ai"]
---

# VoltOps Slack Trigger 설정 가이드 (Events API 웹훅 연동)

## 요약

VoltOps의 Slack Trigger를 이용해 Slack Events API 웹훅을 수신하고, 메시지·반응·채널 활동 발생 시 에이전트를 실행하는 설정 절차를 단계별로 다룬 공식 docs다. Slack 앱 생성부터 Bot OAuth Token·Signing Secret 등록, 이벤트 구독 활성화까지의 흐름이 핵심이다.

## 핵심 내용

### 개요 및 동작 방식

**Slack Trigger**는 Slack Events API 웹훅을 리슨하여, 메시지·반응·채널 활동이 발생할 때 [[에이전틱-ai]] 에이전트를 실행할 수 있게 한다.

- VoltOps는 Slack의 **URL 인증 챌린지(`url_verification`)**를 자동으로 처리한다.
- **Signing Secret**을 이용한 요청 서명 검증도 자동으로 수행한다.

### 주요 유스케이스

- 앱 멘션을 캡처하여 에이전트로 라우팅
- 새 채널 메시지 요약 또는 분류(triage)
- 이모지 시그널에 반응 (예: 특정 이모지 → 리뷰 요청, 완료 표시)
- 파일 공유 감지 후 다른 곳으로 문서 동기화
- 새 팀원 합류 또는 채널 생성 시 알림

### 자격증명(Credential) 설정 절차

[[voltops-slack-trigger-credential]]에서 개념을 다룬다. 절차 요약:

1. [api.slack.com/apps](https://api.slack.com/apps)에서 Slack 앱을 **From scratch**로 생성하고 워크스페이스를 선택한다.
2. **OAuth & Permissions**에서 봇 스코프를 추가한다.
   - 권장 스코프: `channels:read`, `channels:history`, `groups:history`, `im:history`, `mpim:history`, `reactions:read`, `chat:write`, `files:read`, `files:write`, `users:read`
3. 앱을 워크스페이스에 설치하고 **Bot User OAuth Token** (`xoxb-...`)을 복사한다.
4. **Basic Information**에서 **Signing Secret**을 복사한다.
5. **VoltOps 콘솔 Step 1 (Connection)**에서 Slack 자격증명을 생성하고 아래 값을 입력한다.
   - **Access Token**: `xoxb-` 봇 토큰
   - **Signing Secret**: 서명 검증용(권장). 환경변수 `SLACK_SIGNING_SECRET` 또는 `SLACK_APP_SIGNING_SECRET`으로도 설정 가능.

### 이벤트 구독(Event Subscriptions) 활성화 절차

1. Slack 앱 설정의 **Features → Event Subscriptions**에서 **Enable Events**를 켠다.
2. VoltOps에서 Slack 트리거 생성 시 표시되는 **Request URL**을 붙여넣는다.
   - Slack이 해당 URL로 `url_verification` 요청을 전송하며, VoltOps가 자동으로 응답한다.

> 원문이 설정 절차 도중에 끊겨 있어, 이후 단계(구독할 이벤트 타입 선택 등)는 원문에 포함되지 않음.

## 연결

- [[에이전틱-ai]] — Slack Trigger가 실행하는 에이전트 실행 모델의 개념 SoT; up 노드
- [[voltops-slack-trigger-credential]] — Slack Trigger 자격증명(Bot Token·Signing Secret) 설정 절차의 SoT 위임
