---
type: summary
title: VoltAgent Workflow Suspend & Resume & Cancellation
source_url: https://voltagent.dev/docs/workflows/suspend-resume/
tags:
- VoltAgent
- workflow
- suspend
- resume
- cancellation
- createWorkflowChain
- resumeSchema
- time travel
- crash recovery
- REST API
summarized_at: '2026-07-10T11:58:08.968692+00:00'
---

## 개요

**VoltAgent** 워크플로우에서 실행을 일시정지하고 나중에 재개하는 기능. 인간 승인, 외부 이벤트, 시간이 걸리는 비동기 작업에 적합하다.

---

## Quick Start — 기본 suspend & resume

```ts
import VoltAgent, { createWorkflowChain } from "@voltagent/core";
import { z } from "zod";

const simpleApprovalChain = createWorkflowChain({
  id: "simple-approval",
  input: z.object({ item: z.string() }),
  result: z.object({ approved: z.boolean() }),
})
.andThen({
  id: "wait-for-approval",
  execute: async ({ data, suspend, resumeData }) => {
    if (resumeData) return { approved: resumeData.approved };
    await suspend("Waiting for approval");
  },
});

const simpleApproval = simpleApprovalChain.toWorkflow();
new VoltAgent({ workflows: { simpleApproval } });

const execution = await simpleApproval.run({ item: "New laptop" });
console.log(execution.status); // "suspended"

const result = await execution.resume({ approved: true });
console.log(result.result); // { approved: true }
```

- `createWorkflowChain`은 빌더를 반환하므로 `.toWorkflow()`로 변환 후 **동일 인스턴스**를 `VoltAgent`에 등록해야 suspend/resume 상태 추적이 가능하다.

---

## 동작 원리

**Suspend 시**
- 현재 스텝 상태가 자동 저장됨
- 워크플로우 status → `"suspended"`
- `resume()` 메서드가 포함된 execution 객체 반환

**Resume 시**
- 일시정지된 스텝이 처음부터 다시 실행됨
- `resumeData`에 새 데이터가 담김
- 이후 스텝들이 순서대로 계속 실행됨

---

## 타입 안전 Resume Schema

워크플로우 정의 시 `resumeSchema`를 지정해 `resume()`가 받는 데이터를 TypeScript로 타입 체크할 수 있다.

```ts
const approvalWorkflow = createWorkflowChain({
  id: "document-approval",
  input: z.object({ documentId: z.string(), authorId: z.string() }),
  resumeSchema: z.object({
    approved: z.boolean(),
    reviewerId: z.string(),
    comments: z.string().optional(),
  }),
  result: z.object({ status: z.enum(["approved", "rejected"]), reviewedBy: z.string() }),
})
.andThen({
  id: "review-document",
  execute: async ({ data, suspend, resumeData }) => {
    if (resumeData) {
      return { status: resumeData.approved ? "approved" : "rejected", reviewedBy: resumeData.reviewerId };
    }
    await suspend("Document needs review");
  },
});
```

---

## 스텝별 Resume Schema

각 스텝에 독립적인 `resumeSchema`를 지정할 수 있다.

```ts
.andThen({
  id: "manager-approval",
  resumeSchema: z.object({ approved: z.boolean(), managerId: z.string() }),
  execute: async ({ data, suspend, resumeData }) => {
    if (resumeData) return { ...data, managerApproved: resumeData.approved };
    await suspend("Needs manager approval");
  },
})
.andThen({
  id: "finance-approval",
  resumeSchema: z.object({ approved: z.boolean(), financeId: z.string(), budgetCode: z.string() }),
  execute: async ({ data, suspend, resumeData }) => {
    if (resumeData) return { ...data, financeApproved: resumeData.approved, budgetCode: resumeData.budgetCode };
    if (data.amount > 1000) await suspend("Needs finance approval");
    return data;
  },
})
```

---

## 실전 예제: 사용자 이메일 인증

- **suspendSchema**: suspend 시 저장할 데이터 타입 (`verificationCode`, `expiresAt`)
- **resumeSchema**: resume 시 받을 데이터 타입 (`code`)
- `suspendData`로 저장된 코드와 만료시간을 resume 스텝에서 참조해 검증

```ts
// suspend 스텝: 코드 생성 후 이메일 발송, suspend에 코드 저장
await suspend("Waiting for verification", { verificationCode: code, expiresAt });

// verify 스텝: suspendData로 만료 확인 & 코드 비교
if (new Date(suspendData.expiresAt) < new Date()) return { verified: false };
if (resumeData.code === suspendData.verificationCode) return { verified: true, verifiedAt: ... };
```

---

## 특정 스텝에서 Resume

```ts
// 기본: 일시정지된 스텝에서 재개
await exec.resume({ approved: true });

// stepId 지정: 특정 스텝으로 점프
await exec2.resume({ approved: true }, { stepId: "step-2-finance" });
```

---

## 주요 변수

| 변수 | 설명 |
|---|---|
| `data` | 이전 모든 스텝의 누적 데이터 |
| `suspend` | 워크플로우를 일시정지하는 함수 |
| `resumeData` | resume 시 전달된 데이터 (첫 실행 시 undefined) |
| `suspendData` | suspend 시 저장된 데이터 |
| `getInitData` | 원본 워크플로우 입력값 반환 함수 (여러 transform/resume 후에도 안정적) |

---

## 공통 패턴

### Auto-Approve 패턴
- 소액(`amount < 100`)은 자동 승인, 고액은 `suspend`로 수동 승인 대기

### Timeout 패턴
- `suspendData`에 `expiresAt` 저장
- resume 시 현재 시각과 비교해 만료 여부 판단 → `"expired"` / `"completed"` / `"cancelled"` 반환

---

## 베스트 프랙티스

1. **항상 `resumeData` 먼저 확인** — resume 케이스를 먼저 처리하고, 아니면 suspend
2. **명확한 스키마 필드명** — `approved`, `approvedBy`, `rejectionReason` 등 의미 명확한 이름 사용
3. **타임아웃 처리** — `suspendData.expiresAt`으로 만료 감지

---

## Restart & Crash Recovery

실행 중(`running` 상태) 워크플로우가 크래시된 경우 마지막 체크포인트에서 재시작.

```ts
// 단일 execution 재시작
const restarted = await workflow.restart("exec_1234567890_abc123");

// 해당 워크플로우의 모든 active 실행 재시작
const summary = await workflow.restartAllActive();
console.log(summary.restarted); // 성공한 executionId 목록
console.log(summary.failed);    // [{ executionId, error }]

// 레지스트리를 통해 모든 등록 워크플로우의 active 실행 재시작
import { WorkflowRegistry } from "@voltagent/core";
const registry = WorkflowRegistry.getInstance();
const summary = await registry.restartAllActiveWorkflowRuns();
```

- restart는 `running` 상태에서만 동작 (suspended와 다름)
- 체크포인트된 데이터·상태·context·usage를 복원 후 계속 실행
- **스텝은 가능하면 멱등(idempotent)하게 작성** — 크래시 전에 외부 사이드 이펙트가 이미 발생했을 수 있음

---

## Time Travel & Deterministic Replay

완료/일시정지/취소/에러 상태의 execution을 **특정 과거 스텝부터 새 execution으로 재실행**.

> `restart`는 running 실행을 이어가는 것, `timeTravel`은 과거 상태에서 새 execution을 만드는 것.

```ts
// 기본 재실행
const replay = await workflow.timeTravel({
  executionId: original.executionId,
  stepId: "step-2",
});
console.log(replay.executionId); // 새 execution ID

// 오버라이드 재실행
const replay = await workflow.timeTravel({
  executionId: original.executionId,
  stepId: "approval-step",
  inputData: { amount: 2500 },
  resumeData: { approved: true, approvedBy: "ops-user-1" },
  workflowStateOverride: { replayReason: "incident-1234" },
});

// 스트리밍 재실행
const stream = workflow.timeTravelStream({ executionId, stepId: "step-2" });
for await (const event of stream) { console.log(event.type, event.from); }
const replayResult = await stream.result;
```

**Lineage 메타데이터**: replay execution에는 `replayedFromExecutionId`, `replayFromStepId` 필드가 저장되어 추적 가능.

---

## 외부에서 Suspend (createSuspendController)

워크플로우 외부(UI 버튼 등)에서 제어할 때 사용.

```ts
import { createWorkflowChain, createSuspendController } from "@voltagent/core";

const controller = createSuspendController();
const execution = await workflow.run(input, { suspendController: controller });

// 3초 후 외부에서 일시정지
setTimeout(() => controller.suspend("User clicked pause"), 3000);

if (execution.status === "suspended") {
  const result = await execution.resume();
}
```

---

## 워크플로우 취소 (Cancellation)

### Option 1: stream handle에서 직접 취소
```ts
const execution = simpleApproval.stream(input, { suspendController: controller });
execution.cancel("No longer needed");
const status = await execution.status; // "cancelled"
```
- `execution.cancel()`은 내부적으로 동일 `suspendController`로 전달됨

### Option 2: suspend controller로 취소
```ts
controller.cancel("User requested stop");
```

### REST API로 취소
```bash
curl -X POST "https://your-app/api/workflows/<workflowId>/executions/<executionId>/cancel" \
  -H "Content-Type: application/json" \
  -d '{"reason": "User requested stop"}'
```

---

## REST API

### Suspend
- **Endpoint**: `POST /workflows/{id}/executions/{executionId}/suspend`
- **Request**: `{ "reason": "..." }` (optional)
- **Response**: `{ success, data: { executionId, status: "suspended", suspension: { suspendedAt, reason } } }`

### Resume
- **Endpoint**: `POST /workflows/{id}/executions/{executionId}/resume`
- **Request**: `{ "resumeData": {...}, "options": { "stepId": "step-2" } }` (stepId optional)
- **Response**: `{ success, data: { executionId, status, result } }`

### 에러 코드
| 코드 | 의미 |
|---|---|
| 404 | execution 미존재 또는 suspended 상태 아님 |
| 400 | 잘못된 상태에서 suspend 시도 / 스키마 검증 실패 |
| 500 | 서버 에러 |
- 에러 응답 형식: `{ "success": false, "error": "..." }`

---

## Quick Reference

**함수**
- `suspend(reason?, data?)` — 워크플로우 일시정지
- `execution.resume(data?, options?)` — 워크플로우 재개

**Resume options**
```ts
await execution.resume({ approved: true });                        // 일시정지 스텝에서 재개
await execution.resume({ approved: true }, { stepId: "step-2" }); // 특정 스텝으로 점프
```
