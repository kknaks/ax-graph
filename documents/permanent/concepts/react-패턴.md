---
type: concept
title: "ReAct 패턴"
aliases: ["ReAct", "Reasoning-Act-Observe", "ReAct loop", "리즈닝-액트-옵저브"]
tags: ["ReAct", "에이전트 아키텍처", "LLM", "tool-calling", "에이전틱AI"]
up: ["에이전틱-ai"]
---

# ReAct 패턴

## 정의

LLM 에이전트가 **Re**asoning(추론) + **Act**(행동) + **Obs**erve(관찰)을 반복해 복잡한 작업을 처리하는 핵심 아키텍처 패턴이다.

## 맥락

[[에이전틱-ai]] 에이전트가 도구 호출을 포함한 다단계 추론을 수행할 때 사용하는 루프 구조다. 사이클은 다음과 같다:

1. **Reasoning(추론)**: 사용자 질문을 받아 현재 보유 정보로 답변 가능한지 판단, 필요한 도구를 결정
2. **Act(행동)**: 필요한 도구를 선택하고 `tool_calls`로 호출 의사 표현 → 외부 코드(클라이언트)가 실제 실행
3. **Observe(관찰)**: 도구 실행 결과(ToolMessage)를 메시지 히스토리에 추가 → 모델이 결과를 확인
4. 위 사이클 반복 — `tool_calls`가 비어 있을 때(충분한 정보 수집) 최종 텍스트 응답 출력

LangChain에서는 `@tool` 데코레이터로 도구를 정의하고 `bind_tools`로 모델에 등록한 뒤, `tool_calls` 응답을 직접 읽어 수동 루프를 약 30줄로 구현할 수 있다. 동일한 ReAct 루프라도 **모델 성능에 따라 도구 호출 횟수·정확도가 달라진다** — 복잡한 복합 질문에서 약한 모델은 필요한 도구 호출 중 일부를 누락할 수 있다.

[[tool-calling]]과의 관계: ReAct 패턴은 Tool Calling 메커니즘 위에서 동작하는 루프 전략이다. Tool Calling이 단일 도구 호출-실행-반환의 기본 사이클을 정의한다면, ReAct 패턴은 그 사이클을 종료 조건(빈 `tool_calls`)이 생길 때까지 반복하는 제어 구조다.

## 근거 출처

- [[langchain-tool-bind-tools-react-루프-실습]] — LangChain @tool·bind_tools로 수동 ReAct 루프를 약 30줄로 구현하는 실습 강의; ReAct 개념 정의·사이클·종료 조건·모델 성능 차이 실증 출처
