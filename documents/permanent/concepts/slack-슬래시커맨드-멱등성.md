---
type: concept
title: "Slack 슬래시 커맨드 멱등성"
aliases: ["슬래시 커맨드 멱등키", "trigger_id 합성 멱등키", "Slack idempotency"]
tags: ["Slack", "멱등성", "슬래시커맨드", "trigger_id", "in-memory TTL", "Redis"]
up: []
---

# Slack 슬래시 커맨드 멱등성

## 정의

Slack 슬래시 커맨드가 `event_id`를 제공하지 않는 구조적 특성 때문에, `trigger_id` 기반 합성 멱등키와 TTL 저장소로 중복 처리를 차단하는 패턴.

## 맥락

Slack 이벤트 API(메시지 이벤트 등)는 `event_id`를 제공해 이를 멱등키로 직접 쓸 수 있다. 그러나 **슬래시 커맨드에는 `event_id`가 없다**. Slack은 3초 내 응답이 없으면 같은 요청을 재전송하므로, 중복 처리 방지 장치가 없으면 동일 커맨드가 두 번 실행될 수 있다.

권장 패턴:

- **합성 멱등키 형식**: `slash:{sha256(team_id:channel_id:user_id:trigger_id:text)}`
- **저장소**: in-memory TTL 집합 (TTL 300초) — 프로세스 단일 인스턴스 환경에서 유효
- **스케일아웃 시**: 프로세스 여러 개(워커 스케일아웃)이면 in-memory 대신 **Redis TTL**로 승격한다

처리 흐름에서 멱등키 확인은 서명 검증 직후, 도메인 처리 전에 수행한다. 중복 요청이면 재처리 없이 ack만 반환한다.

## 근거 출처

- [[slack-연동-참조-구현-서명검증-슬래시커맨드-outbound-봇-멱등성]] — ax-graph `SlackIdempotencyStore` 구현과 trigger_id 합성키 설계의 원문 출처
