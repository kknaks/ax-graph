---
type: summary
title: 'Agents vs Workflows: Why Not Both? — Sam Bhagwat (Mastra.ai) @ AI Engineer
  World''s Fair 2025'
source_url: https://youtu.be/8SUJEqQNClw
tags:
- agent
- workflow
- Mastra.ai
- AI engineering
- composition
- design patterns
- LLM orchestration
- graph API
- fluent syntax
- agentic patterns
summarized_at: '2026-07-10T07:43:28.045825+00:00'
---

## 발표 배경 및 논쟁 소개

- 발표자: **Sam Bhagwat**, Mastra.ai 공동창업자 겸 CEO. 이전에 **Gatsby.js** 공동창업자. *Principles of AI Agents* 저자.
- 발표 배경: 2025년 초 Twitter에서 촉발된 'Agent vs Workflow' 논쟁이 직접적 계기.
  - **Anthropic** — 2024년 12월 블로그 포스트 "Building Effective Agents": 에이전트와 다양한 워크플로우 패턴(라우팅·오케스트레이션 등)을 도식화한 좋은 글로 평가.
  - **OpenAI** — 2025년 4월 논문 발표: 기존 자료를 크게 벗어나지 않는다는 비판과 함께, 논문 말미에 **워크플로우 그래프 접근법을 암묵적으로 비판하는 내용** 포함 → Twitter에서 논란.
  - Swyx의 긴급 블로그 포스트(Latent Space)가 이 논쟁을 정리.

## 핫테이크 1: "그런 사람 되지 마라(Don't Be That Guy)"

- 특정 대형 모델 제공사가 공개 채널에서 '유일하게 옳은 방법'을 단정적으로 주장하면, 생태계 전체에 영향이 퍼진다.
- 비유: 지난 10년간 일부 Google 엔지니어들이 웹 개발의 '올바른 방식'을 설교하며 사용하기 어려운 기술을 밀어붙인 것과 유사.
- 모델 제공사는 생태계에서 높은 권위를 가지므로, 담론의 질을 높여야 한다는 것이 발표자의 바람.

## 핫테이크 2: 그래프 노드·엣지 터미널 API는 해롭다

- **LangChain** 등 프레임워크의 노드·엣지 방식 그래프 API를 문제로 지적.
- 근거: 프로덕션 애플리케이션을 만들기 위해 **그래프 이론을 배울 필요가 없어야 한다**. 팀 전체가 그래프 이론을 숙지해야 한다면 진입 장벽이 너무 높다.
- 자기반성: Gatsby.js 시절 GraphQL을 기본 데이터 페칭 방식으로 채택했던 경험 — 2017년에는 멋있었지만, 많은 사용자들이 React 메타프레임워크만 원했을 뿐 GraphQL을 원하지 않았고 결국 다른 프레임워크로 이탈.
- 대안으로 제시하는 패턴: **Fluent Syntax** (Mastra 워크플로우 예시)
  - 코드를 위에서 아래로 읽으면 제어 흐름을 자연스럽게 파악 가능.
  - 무엇이 먼저 실행되고, 그 다음 무엇이 실행되는지 한눈에 보임.
  - 팀 협업 시 가독성 유지.

## Agent와 Workflow 정의

- **Agent**: 턴 기반 게임(turn-based game)에 비유.
  - 내가 한 턴 → 에이전트가 한 턴 → 내가 한 턴 → 에이전트가 툴 콜 등 반복.
  - 대화 스레드, 메모리 등이 많은 메시지 누적에서 자연스럽게 발생하는 emergent property.
- **Workflow**: 테크 트리(tech tree)에 비유 (Civilization 게임 참조).
  - 청동기를 연구해야 철기를 연구할 수 있듯, **단계 간 의존 관계(dependency chain)** 존재.
  - Step A → B → C → D 순서로 실행되는 데이터 파이프라인.
  - 의존 관계에서 자연스럽게 나오는 emergent property: 브랜칭, 병렬 처리, 조건, 루프, 일시 중단/재개, 리플레이 등.
- Workflow가 AI 엔지니어링에서 더 주목받는 이유: **비결정성(non-determinism)** 이 핵심이기 때문. 무슨 일이 일어났는지 추적하고 파악하는 능력이 일반 소프트웨어 엔지니어링보다 10배 중요.

## 트레이드오프: 자율성 vs 제어

- 핵심 트레이드오프: **Power(자율성)** vs **Control(제어)**.
- 어느 부분에 자율성을 줄지, 어느 부분에 제어를 넣을지 선택하면 된다.
- 실용적 접근: 자율성으로 시작하고, 문제가 생기는 지점에 제어를 추가.
- 화이트보드 세션 예시:
  - 대용량 의료 PDF에서 12개 증상을 진단하는 에이전트가 정확도가 낮을 때 → LM 콜 1개를 LM 콜 12개로 분해하는 방식 제안.
  - '어떤 부분의 신뢰성이 낮은가' → '어떻게 구조를 추가해 신뢰성을 높일 수 있는가'를 묻는 사고 프로세스.

## 조합(Composition): 핵심 설계 패턴

- **조합 원칙**:
  - Agent는 툴을 가진다 → Workflow를 툴로 줄 수 있다.
  - Workflow는 스텝을 가진다 → Agent를 스텝으로 넣을 수 있다.
  - Agent를 툴로 쓸 수 있다. Workflow를 스텝으로 쓸 수 있다.
  - 프리미티브는 단순하지만, **조합이 만드는 가능성이 진짜 힘**.

- **Agent Supervisor 모델**: 오케스트레이터 에이전트가 리서치 에이전트·요약 에이전트 등 다른 에이전트를 툴로 호출.
- **Workflow as Tool**: 날씨 확인 → 여행 계획 같은 복잡한 워크플로우를 에이전트에게 툴로 넘겨 반복·결정 처리.
- **Workflow를 Agent 핸드오프 메커니즘으로 활용**: 에이전트 간 전환 시 구조화된 워크플로우로 연결.
- **Dynamic Tool Injection**: 에이전트에게 주는 툴 수가 두 자리 수에 가까워지면 성능 저하 발생 가능 → 현재 수행 중인 태스크에 맞는 툴만 선택적으로 주입.
- **Nested Workflows**: 워크플로우 안에 워크플로우를 스텝으로 중첩.

## 아직 없는 것: 에이전틱 패턴 공통 어휘

- Christopher Alexander의 *A Pattern Language* (건축·도시계획 패턴 카탈로그)에 비유: 소프트웨어 엔지니어링에서 디자인 패턴 개념으로 계승됨.
- 발표자 주장: 에이전틱 패턴에 대한 **공통 어휘(verbiage)와 용어집(glossary)이 아직 없다**. 일부 시도가 있지만 업계 합의에 이르지 못한 상태.

## Q&A 발췌

- 질문 요지: 특정 에이전트가 20개 툴로 잘 작동하는데, 이론적으로 맞지 않더라도 그대로 써도 되는가?
- 발표자 답변:
  > "우리는 이론의 커뮤니티가 아니라 실천의 커뮤니티다. 에이전트가 필요한 대로 작동하고 있다면, 이론적으로 맞지 않는다는 것은 이론이 틀렸다는 뜻이지 실천이 틀렸다는 게 아니다. 이 분야는 이론보다 실천이 더 빠르게 발전하고 있다."
- 연락처: Twitter/X 핸들 `@calcam` (calculator + sam)
- 서적 *Principles of AI Agents* 컨퍼런스 현장 배포 중.
