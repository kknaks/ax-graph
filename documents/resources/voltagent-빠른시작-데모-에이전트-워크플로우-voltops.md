---
type: reference
title: "VoltAgent 빠른 시작 데모 — AI 에이전트·워크플로우 구축과 VoltOps 옵저버빌리티"
source: "https://www.youtube.com/watch?v=4v1ZFACsiRs"
aliases: ["VoltAgent 빠른 시작", "VoltAgent quickstart demo", "VoltOps 모니터링 데모", "VoltAgent Nati 데모"]
tags: ["VoltAgent", "VoltOps", "AI-에이전트", "워크플로우", "Human-in-the-Loop", "LLM-옵저버빌리티", "TypeScript", "suspend-resume"]
up: ["에이전틱-ai", "hitl-승인-패턴", "agent-workflow-조합"]
---

# VoltAgent 빠른 시작 데모 — AI 에이전트·워크플로우 구축과 VoltOps 옵저버빌리티

## 요약

VoltAgent 공동창업자 Nati가 CLI 부트스트랩부터 날씨 에이전트 동작, $500 임계값 기반 Human-in-the-Loop 비용 승인 워크플로우, VoltOps 실시간 모니터링까지 전체 흐름을 데모로 소개한 영상이다. VoltAgent(오픈소스 TypeScript 프레임워크)와 VoltOps(LLM 옵저버빌리티 플랫폼)의 핵심 개념을 빠르게 파악하는 데 적합한 입문 자료다.

## 핵심 내용

### 프로젝트 부트스트랩 — CLI 한 줄

- Getting Started 가이드의 npm 명령어 하나로 VoltAgent 앱을 즉시 부트스트랩한다.
- 설정 단계에서 AI 프로바이더 선택(데모: OpenAI); `.env`에 OpenAI API 키만 추가하면 준비 완료.
- `npm run` 으로 서버를 올리면 **VoltOps 플랫폼에 자동 연결**된다.

### 기본 에이전트 — 날씨 에이전트

부트스트랩 프로젝트에는 날씨 질문에 답하는 에이전트가 내장되어 있다. 에이전트 코드는 instructions(지시사항), 모델(`GPT-4o mini` 교체 가능), 도구(Tool) 배열로 구성되며, 도구가 에이전트를 단순 텍스트 생성이 아닌 **실제 액션**(날씨 조회, DB 검색, 이메일 발송 등)을 수행하는 주체로 만든다. 도구 시스템 상세는 [[voltagent-tools-도구-생성-실행-제어-가이드]] 참조.

VoltOps 콘솔에서 실행 즉시 확인 가능한 항목:
- **Input**: 사용자가 입력한 정확한 질문
- **Messages**: LLM에 전송된 전체 내용(시스템 프롬프트 포함)
- **Output**: 사용자 통계가 담긴 최종 응답

### 워크플로우 — 비용 승인 (Expense Approval)

[[agent-workflow-조합]] 관점에서 VoltAgent 워크플로우는 `createWorkflowChain`으로 단계를 체인으로 연결하며, 각 단계가 결과를 다음 단계로 전달한다.

비용 승인 워크플로우는 [[hitl-승인-패턴]]의 Auto-Approve + Suspend/Resume 조합으로 구현된다:

| 금액 조건 | 동작 |
|---|---|
| $500 미만 | 자동 승인 → 워크플로우 계속 진행 |
| $500 초과 | `suspend()` 호출 → 매니저 승인 대기 |

**데모 시나리오 1 — $250**: 한도 이하 → Check Approval 단계 자동 승인 → Process Decision → 완료.

**데모 시나리오 2 — $750**: 한도 초과 → 워크플로우 일시정지(`suspended`) → 매니저 응답 없이 진행 불가 → `resume()` 후 Process Decision → 완료. VoltOps 타임라인에서 이벤트를 단계별로 확인하여 디버깅 효율을 높인다.

코드 구조:
- **Step 1**: 금액 분기 — $500 미만이면 즉시 반환, 초과면 `suspend(비용 상세 정보)`로 일시정지
- **Step 2**: 결정 확정(finalize) 및 결과 로깅

`suspend()`/`resume()` 메커니즘 상세는 [[voltagent-워크플로우-suspend-resume-cancellation]] 참조.

### 프로덕션 모드와 VoltOps 옵저버빌리티

Enable 버튼 클릭으로 프로덕션 모드 활성화 시 대시보드에서 실시간 추적:
- **트레이스(traces)**: 사용자가 받은 결과와 그 이유를 단계별로 파악 → 프로덕션 이슈 디버깅
- **과거 실행(past runs)**: 입력·출력·**비용(costs)** 조회, 특정 실행 클릭 시 단계별 상세 흐름 확인
- **에이전트 상태(health)**: 전반적인 상태·효율성 개요

[[에이전틱-ai]] 시스템을 프로덕션에서 운영할 때 이 옵저버빌리티 레이어가 신뢰성 확보의 핵심이다.

### 확장 방향

- 더 많은 에이전트 추가
- 조건부 로직 추가
- Human-in-the-Loop 승인 단계 추가
- GitHub: `https://github.com/VoltAgent/voltagent`
- 빠른 시작 문서: `https://voltagent.dev/docs/quick-start/`

## 연결

- [[에이전틱-ai]] — VoltAgent 프레임워크가 구현하는 에이전틱 AI 패러다임(도구·워크플로우·자율 실행)의 상위 개념; up 노드
- [[hitl-승인-패턴]] — $500 임계값 비용 승인 워크플로우가 Auto-Approve + Suspend/Resume HITL 패턴의 구체적 구현 사례; up 노드
- [[agent-workflow-조합]] — `createWorkflowChain` 단계 체인이 에이전트-워크플로우 조합 패턴에 해당; up 노드
- [[voltagent-워크플로우-suspend-resume-cancellation]] — 데모에서 사용한 suspend/resume 메커니즘의 공식 레퍼런스; 형제 레퍼런스
- [[voltagent-tools-도구-생성-실행-제어-가이드]] — 날씨 에이전트의 도구(Tool) 시스템 상세 레퍼런스; 형제 레퍼런스
