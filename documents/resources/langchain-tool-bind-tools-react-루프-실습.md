---
type: reference
title: "LangChain @tool·bind_tools로 수동 ReAct 루프 직접 구현 실습"
source: "https://m.youtube.com/watch?v=OqSiCQKT1nU&ra=m"
aliases: ["LangChain ReAct 루프 실습", "LangChain @tool 데코레이터 실습", "수동 ReAct 루프 구현", "bind_tools 실습"]
tags: ["LangChain", "ReAct 패턴", "@tool 데코레이터", "bind_tools", "tool_calls", "Tavily", "에이전트 구현", "수동 툴콜링"]
up: ["tool-calling", "에이전틱-ai"]
---

# LangChain @tool·bind_tools로 수동 ReAct 루프 직접 구현 실습

## 요약

LangChain의 `@tool` 데코레이터와 `bind_tools`로 사내 업무 시뮬레이션 도구 5종·Tavily 웹검색을 모델에 등록하고, `tool_calls` 응답을 직접 읽어 수동 ReAct 루프를 약 30줄로 구현하는 실습 강의다. 도구 호출 판단·실행·결과 반환의 사이클이 [[react-패턴|ReAct 패턴]]의 구체적 구현임을 실증하며, `tool_call_id` 매핑의 중요성과 모델 성능에 따른 도구 호출 품질 차이를 함께 확인한다.

## 핵심 내용

### LLM과 도구의 관계

이 강의는 LLM을 '두뇌', 도구(Tool)를 '손발'로 비유한다. LLM 단독으로는 실시간 정보 조회·사내 시스템 연동·계산이 불가능하므로, [[tool-calling]]을 통해 외부 기능에 연결해 능력을 확장한다. 개념 상세는 [[tool-calling]] 참조.

### @tool 데코레이터 — 함수를 도구 객체로

`@tool` 데코레이터는 일반 Python 함수를 LangChain 도구 객체로 변환하는 가장 단순하고 실무 빈도가 높은 방법이다. 모델에 전달되는 정보는 함수 이름·docstring·타입 힌트(인자 스키마)뿐이며, 내부 실행 로직은 전달되지 않는다.

| 전달됨 | 전달 안 됨 |
|---|---|
| 함수 이름, docstring, 타입 힌트 | 함수 내부 실행 로직 |

모델이 도구를 호출할지·어떤 인자로 호출할지는 **함수 정의부(이름·docstring·타입힌트)에만 의존**하므로, docstring에 도구 용도와 입력 형식(날짜 포맷 등)을 충분히 기재하는 것이 중요하다. 도구 스키마는 `name`·`description`·`args_schema`(타입 힌트 기반 JSON Schema 자동 생성)로 구성되며, `.invoke({"인자명": 값})` 형태로 직접 실행할 수 있다.

### bind_tools — 모델에 도구 스키마 등록

`bind_tools`는 정의된 도구들의 **스키마 정보**를 모델 컨텍스트에 포함시키는 메소드다. 실제 도구 실행은 `bind_tools`가 하지 않는다 — 모델이 `tool_calls` 필드로 호출 의사를 표현할 뿐이며, 실제 실행은 외부 코드(루프)가 담당한다.

동작 흐름:
1. `model.bind_tools(tools)` → 도구 스키마가 모델 컨텍스트에 포함
2. `model.invoke(messages)` → 모델 응답에 `tool_calls` 포함 가능
3. `tool_calls`가 있으면 외부 루프가 실제 도구를 실행하고 결과를 ToolMessage로 반환

### ReAct 패턴 — Reasoning·Act·Observe 사이클

[[react-패턴|ReAct 패턴]]은 **Re**asoning(추론) + **Act**(행동) + **Obs**erve(관찰)의 반복 사이클로, [[에이전틱-ai]] 에이전트가 복잡한 작업을 처리할 때 사용하는 핵심 아키텍처 패턴이다. 개념 상세는 [[react-패턴]] 참조.

사이클:
1. **Reasoning**: 현재 보유 정보로 답변 가능한지 판단, 필요한 도구 결정
2. **Act**: 도구 선택 후 `tool_calls`로 호출 의사 표현 → 외부 코드 실행
3. **Observe**: 도구 실행 결과(ToolMessage)를 메시지 히스토리에 추가, 모델이 결과 확인
4. 반복 — `tool_calls`가 비어 있을 때 최종 텍스트 응답 출력

강사(판다스 스튜디오) 직접 인용: "리즈닝(추론)하고 액트(행동)하고 — 행동은 도구를 호출하는 과정 — 옵저브는 도구를 실행한 결과 호출 결과를 확인하는 것. 이 사이클을 ReAct 패턴이라고 이야기한다."

### 사내 업무 도구 5종

모두 하드코딩 시뮬레이션 데이터로 구현(실습 목적):

1. **일정 조회** — 날짜 문자열 입력 → 해당 날짜 일정 리스트 반환 (4월 15일 2건, 4월 16일 1건)
2. **휴가일수 계산** — 시작일·종료일 입력 → 주말 제외 영업일 기준 일수 반환
3. **연차 조회** — 사원번호 입력 → 남은 연차일수 반환 (3명 데이터 하드코딩)
4. **Slack 공지 발송** — 채널(`team-dev`, `announcements`)·메시지 입력 → 로그 출력 후 결과 반환 (실제 Slack API 미구현)
5. **IT 헬프데스크 검색** — 키워드 입력 → 관련 작업 내용 반환 (하드코딩)

### 외부 API 도구 — Tavily 웹검색

Tavily API 키를 `.env`에 설정 후 초기화(최대 3개 결과, 일반 검색 모드). API 키 없을 시 하드코딩 목업 데이터를 반환하는 폴백 패턴을 적용하며, 사내 도구 5종과 함께 모델에 바인딩한다.

### 수동 ReAct 루프 구현 (~30줄)

**사전 준비**: `{"도구이름": 도구객체}` 딕셔너리 생성 — 이름으로 도구를 빠르게 조회하기 위함.

**루프 구조**:
1. 메시지 리스트 초기화(사용자 질문 포함)
2. `model_with_tools.invoke(messages)` → AIMessage 반환, 메시지 리스트에 추가
3. `response.tool_calls`가 비어 있으면 루프 종료, `response.content` 출력
4. `tool_calls`가 있으면: `name`·`args`·`id` 추출 → 도구 `.invoke(args)` 실행 → **ToolMessage**로 감싸 메시지 리스트에 추가 → 반복

**`tool_call_id` 매핑의 중요성**: 모델은 여러 도구를 동시에 또는 순차 호출할 수 있다. ToolMessage에 `tool_call_id`가 없거나 잘못 매핑되면 모델이 어떤 호출의 결과인지 파악 불가 → 잘못된 추론 또는 오류 발생.

### 테스트 시나리오 3종

**시나리오 1 — 단일 도구 호출**: "4월 15일 일정 알려줘" → `schedule` 도구 1회 호출 → 일정 2건 반환 → 최종 답변. 정상 동작 확인.

**시나리오 2 — 다중 도구 호출(복합 질문)**: 특정 직원이 4월 21~24일 휴가 시 남은 연차 계산. 이상적 호출 순서는 ① 연차 조회 → ② 영업일수 계산 → ③ 공휴일 확인이나, Q1 32B 모델은 ①②만 호출(③ 누락). 강사 코멘트: "상용 모델인 OpenAI나 Gemini 이런 모델들 한번 사용해보시면 결과가 달라질 수 있으니까" — **동일한 ReAct 루프라도 모델 성능에 따라 도구 호출 횟수·정확도가 달라짐**을 실증.

**시나리오 3 — 이종 도구 순차 호출**: LangChain 최신 변경점 웹검색 후 Slack team-dev 채널 공지. ① Tavily 검색 → ② 결과 요약 → ③ `send_notification`으로 발송. 업무 성격이 다른 두 도구의 순차 처리 정확성 확인.

### 수동 루프의 한계와 다음 단계

수동 ReAct 루프는 루프 제어·예외 처리 구현이 복잡하다. 다음 강의(5강)에서 LangChain의 `create_agent` 함수를 활용해 동일 과정을 더 간결하게 구현 예정이다.

## 연결

- [[tool-calling]] — @tool 데코레이터·bind_tools·tool_calls 메커니즘이 Tool Calling 개념의 구체적 LangChain 구현 사례; up 노드
- [[에이전틱-ai]] — 수동 ReAct 루프 구현이 에이전틱 AI의 턴 기반 루프 구조를 직접 실습한 사례; up 노드
- [[react-패턴]] — 이 실습의 핵심 아키텍처 패턴; SoT 위임 대상(이 제안에서 신규 생성)
- [[dynamic-tool-injection]] — bind_tools로 도구 집합을 모델에 등록하는 흐름이 동적 툴 주입 패턴과 인접; 개념 참조
