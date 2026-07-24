---
type: concept
title: "Dynamic Tool Injection"
aliases: ["동적 툴 주입", "선택적 툴 주입"]
tags: ["agent", "LLM-orchestration", "design-pattern", "dynamic-tool-injection", "agentic-patterns"]
up: ["에이전틱-ai"]
---

# Dynamic Tool Injection

## 정의

에이전트에게 주는 툴 집합을 고정하지 않고, 현재 수행 중인 태스크에 맞는 툴만 선택적으로 주입하는 LLM 에이전트 설계 패턴이다.

## 맥락

[[에이전틱-ai]] 시스템에서 에이전트에게 제공하는 툴 수가 두 자리 수에 가까워지면 모델이 올바른 툴을 선택하는 정확도가 저하될 수 있다. Dynamic Tool Injection은 이 문제를 완화하기 위해 전체 툴 목록 중 현재 태스크 컨텍스트와 관련 있는 툴만 동적으로 선별해 에이전트에게 건넨다.

이 패턴은 [[agent-workflow-조합]] 패턴과 함께 쓰인다: Workflow 스텝 진입 시점에 해당 스텝에 필요한 툴만 에이전트에게 주입하면, 에이전트의 툴 선택 부담을 낮추면서도 전체 워크플로우는 풍부한 툴 생태계를 유지할 수 있다.

VoltAgent는 이 패턴의 두 가지 API를 제공한다:
- **런타임 추가**: `agent.addTools([calculatorTool])` — 에이전트 생성 후 전체 레퍼토리에 툴을 추가
- **요청별 주입**: `agent.generateText("...", { tools: [calculatorTool] })` — 특정 인터랙션에서만 노출 툴을 한정해 선택 정확도를 높임

두 방식은 목적이 다르다: 런타임 추가는 에이전트가 사용할 수 있는 툴 풀을 넓히고, 요청별 주입은 특정 요청에서 노출 범위를 좁혀 [[dynamic-tool-injection]] 효과를 극대화한다.

Mastra에서는 `Agent` 생성 시 `tools` 옵션을 **함수**로 선언해 [[mastra-request-context]]의 런타임 값에 따라 주입 툴을 동적으로 결정한다:

```ts
export const agent = new Agent({
  tools: ({ requestContext }) => {
    const tier = requestContext.get('user-tier')
    return tier === 'enterprise' ? enterpriseTools : basicTools
  },
})
```

이 방식은 요청마다 requestContext 값을 읽어 툴 집합을 교체하므로, 동일 에이전트 인스턴스가 테넌트·역할·상태에 따라 서로 다른 툴 노출 범위를 갖는다.

## 근거 출처

- [[agents-vs-workflows-why-not-both-sam-bhagwat-mastra]] — Sam Bhagwat(Mastra.ai)가 두 자리 수 툴 성능 저하 문제와 선택적 주입 패턴을 언급한 AI Engineer World's Fair 2025 발표
- [[voltagent-tools-도구-생성-실행-제어-가이드]] — VoltAgent의 `addTools`·per-request tools API로 런타임/요청별 두 가지 동적 주입 모드를 구체화
- [[mastra-server-request-context]] — Mastra에서 `tools: ({ requestContext }) => {}` 함수 선언으로 requestContext 기반 동적 툴 주입을 구현하는 패턴
