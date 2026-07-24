---
type: reference
title: "Agents vs Workflows: Why Not Both? — Sam Bhagwat (Mastra.ai) @ AI Engineer World's Fair 2025"
source: "https://youtu.be/8SUJEqQNClw"
aliases: ["Agent vs Workflow 논쟁", "Mastra.ai Sam Bhagwat 발표", "Why Not Both 발표"]
tags: ["agent", "workflow", "LLM-orchestration", "composition", "design-pattern", "agentic-patterns", "Mastra.ai", "AI-engineering", "fluent-syntax", "dynamic-tool-injection"]
up: ["에이전틱-ai"]
---

# Agents vs Workflows: Why Not Both? — Sam Bhagwat (Mastra.ai) @ AI Engineer World's Fair 2025

## 요약

Mastra.ai CEO Sam Bhagwat가 'Agent vs Workflow' 이분법이 불필요하다고 주장하며, 두 개념의 정확한 정의·트레이드오프·조합 설계 패턴을 제시한 발표다. 핵심 메시지는 Agent를 Workflow 스텝으로, Workflow를 Agent 툴로 쓰는 [[agent-workflow-조합]] 패턴이 실전에서 가장 강력하다는 것이다.

## 핵심 내용

### 발표 배경: 'Agent vs Workflow' 논쟁

- 발표자: Sam Bhagwat, Mastra.ai 공동창업자 겸 CEO. 이전 Gatsby.js 공동창업자. *Principles of AI Agents* 저자.
- 2025년 초 Twitter에서 촉발된 논쟁이 계기. Anthropic은 2024년 12월 블로그 "Building Effective Agents"에서 에이전트·워크플로우 패턴을 균형 있게 도식화해 긍정 평가를 받았으나, OpenAI의 2025년 4월 논문 말미에 그래프 기반 워크플로우 접근을 암묵적으로 비판하는 내용이 포함되어 논란이 됐다. Swyx(Latent Space)의 긴급 블로그 포스트가 이 논쟁을 정리했다.

### 핫테이크 1: "Don't Be That Guy"

대형 모델 제공사가 공개 채널에서 '유일하게 옳은 방법'을 단정적으로 주장하면 생태계 전체에 영향이 퍼진다. 발표자는 지난 10년간 일부 Google 엔지니어들이 어려운 기술을 유일한 정답으로 설교하며 사용하기 어려운 기술을 밀어붙인 사례와 비유하며, 권위 있는 제공사일수록 담론의 질을 높여야 한다고 주장한다.

### 핫테이크 2: 그래프 노드·엣지 API는 해롭다

LangChain 등 프레임워크의 노드·엣지 방식 그래프 API를 문제로 지적한다. 프로덕션 앱을 만들기 위해 팀 전체가 그래프 이론을 숙지해야 한다면 진입 장벽이 너무 높다는 것이 근거다. 발표자 자신도 Gatsby.js에서 GraphQL을 기본 데이터 페칭 방식으로 채택했다가 사용자들이 이탈한 경험을 자기반성 사례로 든다.

대안으로 **Fluent Syntax**를 제시한다. 코드를 위에서 아래로 읽으면 제어 흐름이 자연스럽게 파악되고, 무엇이 먼저 실행되는지 한눈에 보이며, 팀 협업 시 가독성을 유지한다.

### Agent와 Workflow 정의

[[에이전틱-ai]] 맥락에서 개별 Agent는 **턴 기반 게임(turn-based game)**에 비유된다. 내가 한 턴 → 에이전트가 한 턴(툴 콜 포함) → 반복. 대화 스레드·메모리 등은 메시지 누적 과정에서 발생하는 emergent property다.

Workflow는 **테크 트리(Civilization 게임)**에 비유된다. 청동기를 연구해야 철기를 연구할 수 있듯, Step A → B → C → D의 단계 간 의존 관계(dependency chain)로 구성된 데이터 파이프라인이다. 브랜칭·병렬 처리·조건·루프·일시 중단·재개·리플레이 등은 의존 관계에서 나오는 emergent property다.

Workflow가 AI 엔지니어링에서 특히 주목받는 이유는 **비결정성(non-determinism)** 이 핵심이기 때문이다. 무슨 일이 일어났는지 추적·파악하는 능력이 일반 소프트웨어 엔지니어링보다 10배 중요하다.

### 트레이드오프: 자율성 vs 제어

핵심 트레이드오프는 **Power(자율성) vs Control(제어)**다. 실용적 접근은 자율성으로 시작하고 문제가 생기는 지점에 제어를 추가하는 것이다. 예: 대용량 의료 PDF에서 12개 증상을 진단하는 에이전트 정확도가 낮을 때 → LM 콜 1개를 LM 콜 12개로 분해하는 방식으로 구조 추가. '어떤 부분의 신뢰성이 낮은가 → 어떻게 구조를 추가해 신뢰성을 높일 수 있는가'를 묻는 사고 프로세스다.

### 조합(Composition) 설계 패턴

[[agent-workflow-조합]] 패턴의 핵심 원칙:

- Agent는 툴을 가진다 → **Workflow를 Agent의 툴로** 줄 수 있다.
- Workflow는 스텝을 가진다 → **Agent를 Workflow의 스텝으로** 넣을 수 있다.
- 프리미티브는 단순하지만 조합이 만드는 가능성이 진짜 힘이다.

구체적 패턴:
- **Agent Supervisor 모델**: 오케스트레이터 에이전트가 리서치·요약 에이전트 등을 툴로 호출.
- **Workflow as Tool**: 복잡한 워크플로우(날씨 확인 → 여행 계획 등)를 에이전트에게 툴로 넘겨 반복·결정 처리.
- **Workflow를 Agent 핸드오프 메커니즘으로 활용**: 에이전트 간 전환 시 구조화된 워크플로우로 연결.
- **[[dynamic-tool-injection]]**: 에이전트에게 주는 툴 수가 두 자리 수에 가까워지면 성능 저하 가능 → 현재 수행 중인 태스크에 맞는 툴만 선택적으로 주입.
- **Nested Workflows**: 워크플로우 안에 워크플로우를 스텝으로 중첩.

### 에이전틱 패턴 공통 어휘의 부재

Christopher Alexander의 *A Pattern Language*(건축·도시계획 패턴 카탈로그)에 비유하며, 소프트웨어 디자인 패턴이 그 개념을 계승했듯 에이전틱 패턴에 대한 **공통 어휘(verbiage)와 용어집(glossary)이 아직 없다**고 주장한다. 일부 시도는 있으나 업계 합의에 이르지 못한 상태다.

### Q&A: 이론보다 실천이 빠르다

발표자는 '특정 에이전트가 20개 툴로 잘 작동하는데, 이론적으로 맞지 않더라도 그대로 써도 되는가?'라는 질문에 이렇게 답했다.

> "우리는 이론의 커뮤니티가 아니라 실천의 커뮤니티다. 에이전트가 필요한 대로 작동하고 있다면, 이론적으로 맞지 않는다는 것은 이론이 틀렸다는 뜻이지 실천이 틀렸다는 게 아니다. 이 분야는 이론보다 실천이 더 빠르게 발전하고 있다."

## 연결

- [[에이전틱-ai]] — Agent 정의(턴 기반 루프)·멀티 에이전트 패턴의 SoT; up 노드
- [[agent-workflow-조합]] — 이 발표의 핵심 주장인 Agent/Workflow 조합 설계 패턴 SoT 위임
- [[dynamic-tool-injection]] — 툴 수 증가로 인한 성능 저하 문제와 선택적 툴 주입 패턴 SoT 위임
