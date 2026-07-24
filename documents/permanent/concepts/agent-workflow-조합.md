---
type: concept
title: "Agent-Workflow 조합 패턴"
aliases: ["Agent Workflow Composition", "에이전트 워크플로우 조합", "Workflow as Tool", "Agent as Step"]
tags: ["agent", "workflow", "LLM-orchestration", "composition", "design-pattern", "agentic-patterns"]
up: ["에이전틱-ai"]
---

# Agent-Workflow 조합 패턴

## 정의

Agent를 Workflow의 스텝으로, Workflow를 Agent의 툴로 상호 조합하는 LLM 오케스트레이션 설계 원칙; 두 프리미티브는 상호 배타적이지 않고 중첩 가능하다.

## 맥락

[[에이전틱-ai]] 설계에서 Agent와 Workflow를 각각 독립 프리미티브로 정의한 뒤 조합하면 단일 접근법보다 훨씬 넓은 설계 공간이 열린다. Sam Bhagwat(Mastra.ai)는 이 원칙을 다음과 같이 정리한다.

- **Agent는 툴을 가진다** → Workflow를 Agent의 툴로 줄 수 있다.
- **Workflow는 스텝을 가진다** → Agent를 Workflow의 스텝으로 넣을 수 있다.
- 프리미티브 자체는 단순하지만 조합이 만드는 가능성이 진짜 힘이다.

구체적 패턴 목록:

| 패턴 | 구조 | 언제 쓰나 |
|---|---|---|
| Agent Supervisor | 오케스트레이터 에이전트가 하위 에이전트들을 툴로 호출 | 도메인별 특화 에이전트가 필요할 때 |
| Workflow as Tool | 복잡한 다단계 워크플로우를 에이전트의 툴로 등록 | 반복·결정이 필요한 복잡 플로우를 에이전트에게 위임할 때 |
| Agent as Step | 에이전트를 워크플로우 특정 스텝으로 삽입 | 파이프라인 일부에만 자율성이 필요할 때 |
| Agent 핸드오프 | 에이전트 간 전환 시 구조화된 워크플로우로 연결 | 멀티 에이전트 협업에서 전환 신뢰성을 높일 때 |
| Nested Workflows | 워크플로우 안에 워크플로우를 스텝으로 중첩 | 재사용 가능한 하위 파이프라인이 필요할 때 |
| cloneWorkflow | 동일 워크플로우 로직을 새 ID로 독립 인스턴싱 | 동일 로직을 별도 추적·로그 단위로 병렬 운영할 때 |

**cloneWorkflow 상세**: `cloneWorkflow()`는 워크플로우 로직을 복사하되 새 ID를 부여해 독립 실행 단위로 만든다. 각 클론은 로그·옵저버빌리티 도구에서 별도 워크플로우로 표시된다. Nested Workflows가 계층적 합성이라면, cloneWorkflow는 동일 로직의 수평 복제다(Mastra 공식 문서).

자율성(Power) vs 제어(Control) 트레이드오프를 다루는 실용적 접근은 자율성으로 시작하고, 신뢰성이 낮은 지점을 찾아 Workflow 스텝 분해 등 구조를 추가하는 것이다. [[dynamic-tool-injection]]은 이 조합 패턴에서 에이전트의 툴 집합을 동적으로 관리하는 보완 기법이다.

조합 구조에 Human-in-the-Loop(HITL) 승인을 삽입할 때는 "어디에" 넣을지가 핵심 설계 결정이 된다. 에이전트가 진입점일 때는 툴 호출 전(툴 레벨)이나 워크플로 스텝 내부(워크플로 레벨) 중 하나를 선택하고, 워크플로가 진입점일 때는 스텝 내에서 `agent.generate()`를 호출하거나 `createStep(agent)`으로 에이전트를 명시적 스텝으로 삽입한 뒤 직전 승인 스텝에서 `suspend()`를 쓰는 방식을 택한다. 패턴 선택 기준은 (1) 위험이 어디에 있는가, (2) 사람이 합리적으로 판단할 수 있는 시점이 언제인가다. 상세는 [[hitl-승인-패턴]] 참조.

## 근거 출처

- [[agents-vs-workflows-why-not-both-sam-bhagwat-mastra]] — Sam Bhagwat(Mastra.ai)가 AI Engineer World's Fair 2025에서 조합 패턴을 체계적으로 정리한 발표
- [[hitl-approval-placement-patterns-mastra]] — 조합 구조에서 HITL 승인을 어디에 삽입할지 패턴별로 상세히 다룬 Mastra 공식 블로그
- [[mastra-workflows-overview]] — cloneWorkflow() 패턴 및 Nested Workflows 구현 예시 출처(Mastra 공식 문서)
