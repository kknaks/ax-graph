---
type: summary
title: 팔란티어 에이전트 스택과 AIP Evolve — 프로덕션 AI 에이전트의 실제 조건(DevCon 6)
source_url: https://www.youtube.com/watch?app=desktop&v=LbC2YC4YYGg
tags:
- 팔란티어
- DevCon 6
- 에이전트 스택
- AIP Evolve
- 프로덕션 에이전트
- 온톨로지
- 미션 크리티컬
- AI 최적화
- 탬파 병원
- 결정론적 함수
summarized_at: '2026-07-18T04:53:50.203441+00:00'
---

## 데모 에이전트 vs. 프로덕션 에이전트

- **DevCon 6**의 핵심 메시지: 단순히 에이전트 데모를 만드는 것과 실제 업무에 투입 가능한 **프로덕션용 에이전트**를 만드는 것은 전혀 다른 일이다.
- 현실이 너무 복잡하기 때문이며, 이것이 팔란티어가 엔지니어를 현장에 배치하는 본질적 이유다.
- 일반적으로 에이전트를 '의도대로 입력→도구 사용→결과 출력'의 일방향 흐름으로 생각하는 경향이 있으나, 실제 조직 업무는 그렇지 않다.

## 실제 환경에서의 복잡성 — 주요 문제 시나리오

- **비정상 중단 및 중복 실행**: 메모리 부족, 모델 오류, 네트워크 오류로 에이전트가 진행 중 갑자기 중단될 경우 — 예: 결제 진행 중 중단 후 재실행 시 결제가 두 번 발생하는 문제.
- **인간 실수로 인한 중단**: 다른 사용자가 실수로 중단 버튼을 누를 경우 중요한 빌드 프로세스가 멈추는 상황.
- **충돌 정보 유입**: 에이전트 입장에서 서로 반대되는 정보가 동시에 들어오는 경우.
- **장기 프로세스**: 2주 이상 지속되어야 하는 프로세스가 안정적으로 작동할 수 있는가.
- 개인 프로젝트와 달리 **미션 크리티컬** 영역(기업 핵심 프로젝트, 전쟁 현장 등)에서는 이런 문제가 큰 사고로 이어질 수 있다.

## 팔란티어 에이전트 스택 구성

팔란티어는 **온톨로지 기반**의 에이전트 운영 인프라인 **에이전트 스택(Agent Stack)**을 발표했다.

- **오케스트레이터(Orchestrator)**: 에이전트가 갑자기 멈췄을 때에 대비한 레이어.
- **에이전트 엔진(Agent Engine)**: 여러 에이전트 시스템이 동시에 참여할 때 각자의 상태와 액션을 조율하여 전체 업무를 안정적으로 작동시키는 분산 운영 시스템.
- **에이전트 SDK / 필터**: 개발 도구.
- **에이전트 매니저**: 관리·분석 도구.
- **AIP Evolve**: 에이전트 스택의 핵심 구성요소 중 하나로, 이번 DevCon에서 실제 활용 사례가 심도 있게 다뤄졌다.

## AIP Evolve — 탬파 병원(TGH) 사례

### 배경

- **탬파 병원(Tampa General Hospital, TGH)**에서 AIP Evolve 테스트 중.
- 대상 업무: **Utilization Review(진료 적정성 심사)** — 환자 입원 후 진료 내용이 적절한지, 과잉 진료는 아닌지를 검토하여 환자 본인부담금과 병원의 보험사 청구 가능 여부를 결정.
- TGH는 AIP Evolve 도입을 통해 **비용을 70% 절감**했다고 발표.

### 온톨로지 기반 복잡성 관리

> "What I'm showing you here is a utilization review's journey through the ontology as it's being manipulated by different human and AI actions. So you can see a bunch of different automations are being called. It's a mixture of deterministic and agent backed logic here."

- 작업은 왼쪽에서 오른쪽으로 갈수록 AI와 인간 간 핸드오프가 증가하며 복잡도가 높아진다.
- Utilization Review 외에도 환자 사전 승인(patient authorization), 문서 처리(documentation processing) 등 상류·하류 프로세스와 연결되어 있다.
- 하나의 노드에서 비싼 모델을 저렴한 모델로 교체할 경우 하위 의사결정에 미치는 영향을 파악하기 어렵지만, **모든 복잡성이 TGH 온톨로지에 모델링되어 있기 때문에** 이 복잡성을 추론하고 지능적인 최적화를 수행할 수 있다.

### Evolve의 최적화 사례 1 — 모델 교체

- Evolve가 시스템 내 데이터 흐름과 LLM 사용 위치를 분석한 뒤, 가장 높은 절감 가능성이 있는 부분으로 **특정 기준 매칭 에이전트(criteria matching agent)**를 지목.
- 해당 부분에서 **Claude Sonnet** 2곳을 **GPT-5 Mini**로 전면 교체 → **비용 68% 절감**.
- 단순히 "Sonnet이 GPT-5 Mini보다 비싸다"는 사실만으로 결정한 것이 아님을 강조:
  - Evolve가 **실제 온톨로지 데이터·실제 프로덕션 실행 이력**을 기반으로 다양한 복잡한 입력 케이스를 커버하는 현실적인 테스트 케이스를 자동 생성.
  - 전문가가 기존 버전과 최적화 버전의 출력을 **환자 차트·노트·검사 결과 등 실제 온톨로지 컨텍스트** 안에서 나란히 비교·피드백할 수 있는 인터페이스 구축.
  - 여러 모델 후보를 스크리닝하고, 각 모델에 맞춰 프롬프트도 별도 최적화하며 반복 개선.
  - 결과: 비용 68% 절감 + **전문가가 90%의 경우 최적화 버전을 선호**.

### Evolve의 최적화 사례 2 — AI 제거(결정론적 함수로 대체)

- Evolve가 시스템 내 AI 사용 위치를 분석하던 중, **GPT-4.1**이 사용되던 특정 지점을 발견.
- 온톨로지의 의미적 관계(semantic relationships)와 로직 내 문서 등을 분석한 결과, 해당 부분은 AI가 필요 없다고 판단.
- Evolve가 **완전한 결정론적 TypeScript 함수**를 자동으로 작성하고 평가(evaluance)로 검증한 뒤, 온톨로지에 등록하여 AIP 로직 내에서 조건부로 교체.
- 결과: **84%의 경우에서 AI(GPT) 호출을 결정론적 TypeScript로 대체** → 수십만~수백만 건의 GPT 호출 제거.

### Evolve의 핵심 철학

> "Evolve is this engine that will spawn agents to optimize for you, but it's optimizing with regards to what your actual objectives are. It wants to maximize the value that you're producing with AI. And sometimes that looks like swapping models. Sometimes that looks like optimizing prompts. But also it could mean getting rid of AI entirely because all of those are implementation details that sit below the real value that AI can deliver."

- 최적화 방향: 모델 교체, 프롬프트 최적화, **AI 자체 제거** 모두 수단이며, 목적은 실제 목표 가치 극대화.

## 팔란티어의 핵심 철학

- 팔란티어의 철학은 **뛰어난 AI 에이전트를 구축하는 데 있는 것이 아니라 문제를 해결하는 데 있다.**
