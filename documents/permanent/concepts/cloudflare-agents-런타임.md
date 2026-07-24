---
type: concept
title: "Cloudflare Agents SDK 런타임"
aliases: ["Agents SDK Runtime", "Cloudflare Agents 런타임", "durable agent runtime"]
tags: ["Cloudflare Agents", "Agents SDK", "durable agent", "에이전트 런타임", "WebSocket", "스케줄링"]
up: ["에이전틱-ai"]
---

# Cloudflare Agents SDK 런타임

## 정의

Cloudflare Agents SDK가 제공하는 지속 가능한 에이전트 실행 인프라 — `Agent` 클래스, 상태, 세션, 라우팅, WebSockets, 스케줄링, 파이버, 옵저버빌리티로 구성된다.

## 맥락

[[에이전틱-ai]] 시스템을 실제로 호스팅하는 인프라 층이다. Cloudflare 글로벌 네트워크 위에서 실행되며, 에이전트 인스턴스마다 **지속적 ID(durable identity)**·로컬 SQL 스토리지·실시간 연결·예약 작업·복구 가능한 실행을 보장한다. 별도의 인프라 관리, 세션 재구성, 외부 상태 저장 없이 수천만 개의 인스턴스로 확장할 수 있다.

구성 요소:

| 구성 요소 | 역할 |
|---|---|
| `Agent` 클래스 | 에이전트 인스턴스의 기본 단위 |
| 상태(state) | 세션 간 지속되는 에이전트 상태 |
| 세션(sessions) | 대화 단위로 격리된 실행 컨텍스트 |
| 라우팅(routing) | 채널별 요청을 에이전트로 연결 |
| WebSockets | 실시간 양방향 통신 |
| 스케줄링(scheduling) | 예약 작업 실행 |
| 파이버(fibers) | 복구 가능한 비동기 실행 단위 |
| 옵저버빌리티 | 에이전트 실행 추적·모니터링 |

[[루프-엔지니어링]] 스택 관점에서 이 런타임은 에이전트 하네스(루프 정의)를 구동하는 하위 인프라 층이다. 스케줄링 구성 요소는 루프 엔지니어링의 '자동화(Automations)' 요소와 직접 대응하며, WebSocket은 실시간 연결 채널을 담당한다.

## 근거 출처

- [[build-agents-on-cloudflare]] — Cloudflare 공식 문서에서 Agents SDK 런타임 구성 요소를 소개한 출처
