---
type: reference
title: "VoltAgent 워크플로우 Suspend·Resume·Cancellation 메커니즘"
source: "https://voltagent.dev/docs/workflows/suspend-resume/"
aliases: ["VoltAgent suspend resume", "VoltAgent 워크플로우 일시정지 재개", "VoltAgent cancellation", "createWorkflowChain suspend"]
tags: ["VoltAgent", "workflow", "suspend-resume", "human-in-the-loop", "time-travel", "crash-recovery", "typescript", "agent-framework"]
up: ["에이전틱-ai"]
---

# VoltAgent 워크플로우 Suspend·Resume·Cancellation 메커니즘

## 요약

VoltAgent에서 워크플로우 실행을 특정 스텝에서 일시정지하고 인간 승인·외부 이벤트 후 재개하는 메커니즘의 공식 레퍼런스다. `suspend()`/`resume()` 기본 흐름부터 타입 안전 `resumeSchema`, 크래시 복구(`restart`), time travel 재실행, REST API까지 한 문서에 포괄한다.

## 핵심 내용

### 기본 suspend & resume 흐름

`createWorkflowChain`으로 빌더를 만들고 `.toWorkflow()`로 변환한 뒤 **동일 인스턴스**를 `VoltAgent`에 등록해야 suspend/resume 상태 추적이 가능하다. 스텝 `execute` 함수 안에서 `await suspend(reason?)` 호출 시 워크플로우 status가 `"suspended"`로 전환되며, 호출자가 받은 execution 객체의 `resume(data?)` 메서드로 재개한다.

**Suspend 시**: 현재 스텝 상태 자동 저장 → status `"suspended"` → `resume()` 포함 execution 반환  
**Resume 시**: 일시정지된 스텝이 처음부터 재실행 → `resumeData`에 새 데이터 담김 → 이후 스텝 순서대로 계속

스텝 내 핵심 변수:

| 변수 | 설명 |
|---|---|
| `data` | 이전 모든 스텝의 누적 데이터 |
| `suspend` | 워크플로우를 일시정지하는 함수 |
| `resumeData` | resume 시 전달된 데이터 (첫 실행 시 undefined) |
| `suspendData` | suspend 시 저장된 데이터 |
| `getInitData` | 원본 입력값 반환 함수 (여러 transform/resume 후에도 안정적) |

베스트 프랙티스: **`resumeData`를 먼저 확인**해 resume 케이스를 처리하고 아니면 `suspend` 호출.

### 타입 안전 resumeSchema

[[hitl-승인-패턴]]의 워크플로 스텝 승인을 구현할 때 `resumeSchema`(Zod 스키마)를 워크플로우 정의에 지정하면 `resume()` 호출 시 받는 데이터를 TypeScript 레벨에서 타입 체크한다. 각 스텝에도 **독립적인 `resumeSchema`**를 달 수 있어, 다단계 승인 워크플로우(매니저 승인 → 재무 승인)에서 스텝마다 다른 입력 타입을 강제할 수 있다.

이메일 인증 예제에서는 `suspend(reason, { verificationCode, expiresAt })`로 코드와 만료 시각을 `suspendData`에 저장하고, resume 스텝에서 `suspendData.expiresAt` 비교 + 코드 일치 검증 후 결과를 반환한다.

### 공통 패턴

- **Auto-Approve 패턴**: 소액(`amount < 100`)은 조건 분기로 즉시 반환, 고액만 `await suspend()`로 수동 승인 대기
- **Timeout 패턴**: `suspendData.expiresAt` 저장 → resume 시 `new Date(suspendData.expiresAt) < new Date()` 비교 → `"expired"` / `"completed"` / `"cancelled"` 분기
- **특정 스텝 jump**: `execution.resume(data, { stepId: "step-2" })`로 일시정지 스텝 대신 특정 스텝으로 점프 가능

### 외부에서 Suspend — createSuspendController

UI 버튼 등 워크플로우 외부에서 제어할 때 `createSuspendController()`로 컨트롤러를 만들어 `workflow.run(input, { suspendController: controller })`에 주입한다. 이후 `controller.suspend(reason)` 또는 `controller.cancel(reason)`으로 외부 트리거가 가능하다. stream handle의 `execution.cancel(reason)`은 내부적으로 동일 suspendController로 위임된다.

### Restart & Crash Recovery

`running` 상태에서 크래시된 execution을 마지막 체크포인트의 데이터·상태·context·usage를 복원해 재시작한다(`suspended` 상태와 다름).

```ts
await workflow.restart("exec_1234567890_abc123");       // 단일 재시작
await workflow.restartAllActive();                       // 해당 워크플로우 전체
await WorkflowRegistry.getInstance().restartAllActiveWorkflowRuns(); // 등록된 모든 워크플로우
```

스텝은 **멱등(idempotent)하게** 작성해야 한다 — 크래시 전에 외부 사이드 이펙트가 이미 발생했을 수 있기 때문이다.

### Time Travel & Deterministic Replay

완료·일시정지·취소·에러 상태의 execution을 **특정 과거 스텝부터 새 execution으로 재실행**한다. `restart`(running 실행을 이어가는 것)와 달리 `timeTravel`은 과거 상태에서 새 execution을 만든다.

```ts
// 오버라이드 재실행 예
const replay = await workflow.timeTravel({
  executionId: original.executionId,
  stepId: "approval-step",
  inputData: { amount: 2500 },
  resumeData: { approved: true, approvedBy: "ops-user-1" },
});
```

replay execution에는 `replayedFromExecutionId`·`replayFromStepId` lineage 메타데이터가 자동 저장되어 추적 가능하다. `timeTravelStream()`으로 스트리밍 재실행도 지원한다.

### REST API

| 동작 | Endpoint | 주요 Request 필드 |
|---|---|---|
| Suspend | `POST /workflows/{id}/executions/{executionId}/suspend` | `reason` (optional) |
| Resume | `POST /workflows/{id}/executions/{executionId}/resume` | `resumeData`, `options.stepId` (optional) |
| Cancel | `POST /workflows/{id}/executions/{executionId}/cancel` | `reason` |

에러 코드: 404(execution 미존재 또는 suspended 아님), 400(잘못된 상태 / 스키마 검증 실패), 500(서버 에러). 에러 응답 형식: `{ "success": false, "error": "..." }`

## 연결

- [[에이전틱-ai]] — 워크플로우 suspend/resume이 놓이는 에이전틱 시스템 패러다임 상위 개념; up 노드
- [[hitl-승인-패턴]] — 워크플로 스텝 내 `suspend()`가 HITL 승인 게이트의 구현 메커니즘; 이 문서가 그 구현 상세 레퍼런스
- [[agent-workflow-조합]] — VoltAgent `createWorkflowChain`이 agent-workflow 조합 구조에서 쓰이는 워크플로우 빌더 패턴의 구체적 구현
- [[hitl-approval-placement-patterns-mastra]] — Mastra에서 동일한 suspend/resume 패턴으로 HITL을 구현하는 형제 레퍼런스
