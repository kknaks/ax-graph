---
type: concept
title: "Slack 서명검증"
aliases: ["Slack Signature Verification", "Slack HMAC 서명검증", "v0 서명 방식"]
tags: ["Slack", "서명검증", "HMAC-SHA256", "보안", "inbound", "replay-attack"]
up: []
---

# Slack 서명검증

## 정의

Slack이 모든 inbound 요청에 첨부하는 `X-Slack-Signature` 헤더를 v0 HMAC-SHA256 방식으로 검증해 요청의 진위와 신선도를 확인하는 보안 절차.

## 맥락

Slack은 모든 inbound 요청(슬래시 커맨드, 이벤트 API 등)에 `X-Slack-Signature`와 `X-Slack-Request-Timestamp` 두 헤더를 붙인다. 수신 서버는 **어떤 처리보다 먼저** 이 서명을 검증해야 하며, 실패 시 401을 반환한다.

검증의 네 핵심 규칙:

1. **v0 방식**: `basestring = "v0:{timestamp}:{raw_body}"`, `expected = "v0=" + hmac_sha256(signing_secret, basestring)`
2. **raw body(파싱 전 bytes)로만** 검증 — form 파싱 후 재직렬화 시 서명이 깨진다
3. **replay 윈도우 ±5분(300초)**: `abs(now - timestamp) > 300`이면 만료 요청으로 거부한다
4. **constant-time 비교**: `hmac.compare_digest` 사용 — 타이밍 공격(timing attack)을 방지한다

서명 검증으로 보호되는 라우트는 Bearer 인증 대상에서 제외한다(Slack은 Bearer 헤더를 붙이지 않는다). 인증 미들웨어에서 해당 경로만 열어준다.

## 근거 출처

- [[slack-연동-참조-구현-서명검증-슬래시커맨드-outbound-봇-멱등성]] — ax-graph 구현에서 정제한 v0 검증 로직·코드 예시·적용 규칙의 원문 출처
- [[voltops-slack-trigger-설정-가이드]] — VoltOps가 Signing Secret으로 자동 서명 검증을 수행하는 플랫폼 적용 사례
