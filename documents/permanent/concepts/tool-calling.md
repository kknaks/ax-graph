---
type: concept
title: "Tool Calling"
aliases: ["툴 콜링", "전통적 Tool Calling", "LLM 도구 호출"]
tags: ["Tool Calling", "LLM", "도구 정의", "실시간 데이터", "AI"]
up: ["에이전틱-ai"]
---

# Tool Calling

## 정의

LLM이 외부 도구(API·데이터베이스·코드 인터프리터 등)의 정의 목록을 전달받아 어떤 도구를 어떻게 호출할지 추천하고, 클라이언트 애플리케이션이 실제 실행 후 결과를 LLM에 반환하는 사이클로 작동하는 LLM-외부 시스템 연결 기법.

## 맥락

[[에이전틱-ai]] 시스템에서 LLM이 텍스트 생성을 넘어 실제 외부 액션을 수행하는 핵심 메커니즘이다. 도구 정의는 이름(name) · 설명(description) · 입력 파라미터(input parameters)로 구성되며, LLM은 description을 보고 어떤 도구를 언제 호출할지 스스로 결정한다.

전통적 Tool Calling 흐름: (1) 클라이언트가 메시지 + 도구 정의 목록을 LLM에 전송 → (2) LLM이 호출할 도구를 추천 → (3) 클라이언트가 도구를 실행하고 결과를 LLM에 반환 → (4) LLM이 최종 답변 생성.

클라이언트가 도구 실행 주체이므로 LLM이 **잘못된 도구 호출**을 추천하거나 **환각(hallucination)**을 일으킬 위험이 있다. 이를 구조적으로 해소하는 발전형이 [[embedded-tool-calling]]이다. VoltAgent에서는 `createTool()`로 Zod 타입 안전 도구를 정의하고 에이전트 `tools` 배열에 주입하는 방식으로 구현한다([[voltagent-tools-도구-생성-실행-제어-가이드]] 참조).

LangChain에서는 `@tool` 데코레이터로 일반 Python 함수를 도구 객체로 변환한다. 모델에 전달되는 정보는 **함수 이름·docstring·타입 힌트(인자 스키마)**뿐이며 내부 실행 로직은 전달되지 않는다. `bind_tools`로 도구 스키마를 모델 컨텍스트에 등록하면 모델이 `tool_calls` 필드로 호출 의사를 표현하고, 외부 루프([[react-패턴]] 참조)가 실제 도구를 실행한 뒤 결과를 ToolMessage로 반환한다. 이때 `tool_call_id` 매핑이 필수다 — 여러 도구를 동시 또는 순차 호출할 때 모델이 어떤 호출의 결과인지 식별하는 유일한 키이기 때문이다([[langchain-tool-bind-tools-react-루프-실습]] 참조).

## 근거 출처

- [[tool-calling-embedded-tool-calling-llm-실시간데이터-ibm-technology]] — IBM Technology Roy Derks가 전통적 Tool Calling 구조·흐름·한계를 예시와 함께 설명한 1차 출처
- [[voltagent-tools-도구-생성-실행-제어-가이드]] — VoltAgent에서의 Tool Calling 구현 레퍼런스
- [[langchain-tool-bind-tools-react-루프-실습]] — LangChain @tool 데코레이터·bind_tools·tool_call_id 매핑의 구체적 구현 실습 출처
