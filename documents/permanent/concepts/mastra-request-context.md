---
type: concept
title: "Mastra RequestContext"
aliases: ["RequestContext", "Mastra 런타임 컨텍스트 주입", "requestContext"]
tags: ["Mastra", "RequestContext", "런타임컨텍스트", "에이전트프레임워크", "TypeScript", "멀티테넌트"]
up: ["에이전틱-ai"]
---

# Mastra RequestContext

## 정의

Mastra 프레임워크에서 단일 요청 범위의 런타임 데이터를 에이전트·워크플로·툴·네트워크 등 모든 프리미티브에 주입하는 클래스다. `.set(key, value)` · `.get(key)` API로 값을 등록·읽으며, TypeScript 제네릭으로 타입 안전성을 보장한다.

## 맥락

[[에이전틱-ai]] 시스템에서 런타임 조건(사용자 속성·로케일·실험 변형)에 따라 에이전트의 instructions·model·tools·memory를 동적으로 분기해야 할 때 사용한다. [[agent-workflow-조합]] 구조의 모든 진입점(agent.generate, run.start, run.resume, tool.execute)에 동일 인스턴스를 전달해 프리미티브 간 컨텍스트를 공유한다.

에이전트 메모리(대화 히스토리·상태 지속)와는 별개 개념으로, 단일 요청 생명주기 내 횡단 데이터 전달이 목적이다. 서버 미들웨어에서 요청 헤더 기반으로 값을 주입하고, `requestContextSchema`(Zod 등)로 런타임 검증을 추가할 수 있다. 멀티테넌트 환경에서는 `MASTRA_RESOURCE_ID_KEY`·`MASTRA_THREAD_ID_KEY` 예약 키로 사용자 격리를 강제한다.

## 근거 출처

- [[mastra-server-request-context]] — Mastra 공식 docs: RequestContext API 전체(set/get, 프리미티브 전달, 스키마 검증, 예약 키, Dynamic Instructions 패턴)의 상세 레퍼런스
