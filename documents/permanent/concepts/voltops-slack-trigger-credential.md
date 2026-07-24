---
type: concept
title: "VoltOps Slack Trigger 자격증명"
aliases: ["Slack Trigger 자격증명", "VoltOps bot token", "VoltOps signing secret"]
tags: ["VoltOps", "Slack", "bot-token", "signing-secret", "credential", "webhook"]
up: ["에이전틱-ai"]
---

# VoltOps Slack Trigger 자격증명

## 정의

VoltOps Slack Trigger가 Slack Events API 웹훅을 수신하고 요청 서명을 검증하기 위해 필요한 두 가지 자격증명 — Bot User OAuth Token(`xoxb-...`)과 Signing Secret.

## 맥락

[[에이전틱-ai]] 에이전트를 Slack 이벤트로 구동할 때, Slack 앱을 VoltOps에 연결하려면 **OAuth & Permissions**에서 봇 스코프를 부여하고 앱을 워크스페이스에 설치한 뒤, Bot Token과 Signing Secret을 VoltOps 콘솔 Connection 단계에 등록한다. Signing Secret은 VoltOps가 인입 요청이 실제 Slack에서 온 것임을 검증하는 데 사용하며, 환경변수 `SLACK_SIGNING_SECRET` 또는 `SLACK_APP_SIGNING_SECRET`으로도 설정 가능하다. VoltOps는 Slack의 `url_verification` 챌린지를 자동 처리하므로 별도 구현이 불필요하다.

## 근거 출처

- [[voltops-slack-trigger-설정-가이드]] — Bot Token·Signing Secret 등록 절차 및 봇 스코프 목록의 원문 출처
