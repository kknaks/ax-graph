---
type: summary
title: Mastra Workflows — Suspend and Resume
source_url: https://mastra.ai/docs/workflows/suspend-and-resume
tags:
- Mastra
- workflow
- suspend
- resume
- human-in-the-loop
- snapshot
- resumeData
- suspendData
- createWorkflowStateReader
- sleep
summarized_at: '2026-07-10T11:58:57.251013+00:00'
---

## 개요

워크플로우는 다음 목적으로 임의의 스텝에서 일시 중단될 수 있다:
- 추가 데이터 수집
- API 콜백 대기
- 비용이 큰 작업 스로틀링
- **human-in-the-loop** 입력 요청

중단 시 현재 실행 상태가 **스냅샷(snapshot)**으로 저장된다. 이후 특정 **step ID**로부터 워크플로우를 재개하면 해당 스냅샷의 정확한 상태가 복원된다. 스냅샷은 설정된 스토리지 프로바이더에 저장되며 배포 및 애플리케이션 재시작 후에도 유지된다.

---

## suspend()로 워크플로우 일시 중단

- 스텝의 `execute` 블록 내에서 `suspend()`를 호출해 실행을 일시 중단한다.
- `resumeData` 값을 사용해 suspend 조건을 정의할 수 있다.
- 조건이 충족되지 않으면 워크플로우가 일시 중단되고 `suspend()`를 반환한다.
- 조건이 충족되면 스텝의 나머지 로직을 계속 실행한다.

**코드 예시** (`src/mastra/workflows/test-workflow.ts`):
```typescript
const step1 = createStep({
  id: 'step-1',
  inputSchema: z.object({ userEmail: z.string() }),
  outputSchema: z.object({ output: z.string() }),
  resumeSchema: z.object({ approved: z.boolean() }),
  execute: async ({ inputData, resumeData, suspend }) => {
    const { userEmail } = inputData
    const { approved } = resumeData ?? {}
    if (!approved) {
      return await suspend({})
    }
    return { output: `Email sent to ${userEmail}` }
  },
})

export const testWorkflow = createWorkflow({
  id: 'test-workflow',
  inputSchema: z.object({ userEmail: z.string() }),
  outputSchema: z.object({ output: z.string() }),
}).then(step1).commit()
```

---

## resume()로 워크플로우 재개

- `resume()`을 사용해 중단된 워크플로우를 일시 중단된 스텝에서 재시작한다.
- `resumeData`를 스텝의 `resumeSchema`에 맞게 전달하여 중단 조건을 충족시키고 실행을 계속한다.

**기본 사용 예시**:
```typescript
const workflow = mastra.getWorkflow('testWorkflow')
const run = await workflow.createRun()
await run.start({ inputData: { userEmail: 'alex@example.com' } })

const handleResume = async () => {
  const result = await run.resume({
    step: step1,           // step 객체 전달 → resumeData 타입 안전성 확보
    resumeData: { approved: true },
  })
}
```

- **step 객체** 전달 시: `resumeData`에 대한 완전한 타입 안전성 제공
- **step ID 문자열** 전달 시: 유연성 확보 (사용자 입력이나 DB에서 ID를 가져올 때 유용)

```typescript
const result = await run.resume({
  step: 'step-1',
  resumeData: { approved: true },
})
```

- 중단된 스텝이 하나뿐이면 `step` 인수를 생략 가능 → Mastra가 마지막 중단 스텝을 자동으로 재개
- **runId만으로 재개**할 경우 먼저 `createRun()`으로 run 인스턴스를 생성해야 한다:

```typescript
const workflow = mastra.getWorkflow('testWorkflow')
const run = await workflow.createRun({ runId: '123' })
const stream = run.resume({ resumeData: { approved: true } })
```

- `resume()`은 HTTP 엔드포인트, 이벤트 핸들러, 사람 입력 처리, 타이머 등 애플리케이션 어디서든 호출 가능

**타이머 예시** (자정에 자동 재개):
```typescript
const midnight = new Date()
midnight.setUTCHours(24, 0, 0, 0)
setTimeout(async () => {
  await run.resume({
    step: 'step-1',
    resumeData: { approved: true },
  })
}, midnight.getTime() - Date.now())
```

---

## suspendData로 중단 데이터 접근

- 스텝이 중단될 때 `suspend()`에 전달한 데이터를, 재개 시점에서 `suspendData` 파라미터로 접근할 수 있다.
- 이를 통해 워크플로우가 왜 중단됐는지 컨텍스트를 유지하고 재개 시 활용할 수 있다.

**코드 예시** (`src/mastra/workflows/user-approval.ts`):
```typescript
const approvalStep = createStep({
  id: 'user-approval',
  inputSchema: z.object({ requestId: z.string() }),
  resumeSchema: z.object({ approved: z.boolean() }),
  suspendSchema: z.object({
    reason: z.string(),
    requestDetails: z.string(),
  }),
  outputSchema: z.object({ result: z.string() }),
  execute: async ({ inputData, resumeData, suspend, suspendData }) => {
    const { requestId } = inputData
    const { approved } = resumeData ?? {}

    // 첫 실행 시: 컨텍스트와 함께 중단
    if (!approved) {
      return await suspend({
        reason: 'User approval required',
        requestDetails: `Request ${requestId} pending review`,
      })
    }

    // 재개 시: 원래 중단 데이터 접근
    const suspendReason = suspendData?.reason || 'Unknown'
    const details = suspendData?.requestDetails || 'No details'
    return {
      result: `${details} - ${suspendReason} - Decision: ${approved ? 'Approved' : 'Rejected'}`,
    }
  },
})
```

- `suspendData`는 재개 시 자동으로 채워지며, 최초 중단 시 `suspend()` 함수에 전달된 정확한 데이터를 담는다.

---

## 중단된 실행 식별

- 워크플로우가 중단되면 일시 중단된 스텝에서 재시작된다.
- `result.status === 'suspended'`로 중단 여부 확인 가능
- `result.suspended` 배열로 중단된 스텝 또는 중첩 워크플로우 식별 가능

```typescript
const workflow = mastra.getWorkflow('testWorkflow')
const run = await workflow.createRun()
const result = await run.start({ inputData: { userEmail: 'alex@example.com' } })

if (result.status === 'suspended') {
  console.log(result.suspended[0])
  await run.resume({
    step: result.suspended[0],
    resumeData: { approved: true },
  })
}
```

**출력 예시**:
```json
['nested-workflow', 'step-1']
```

- `suspended` 배열에는 해당 실행에서 중단된 워크플로우 및 스텝의 ID가 담긴다.
- 이 값을 `resume()`의 `step` 파라미터에 전달해 특정 중단 실행 경로를 재개할 수 있다.

---

## 중단된 실행 복구 (Recovering Suspended Runs)

- `workflow.getWorkflowRunById()`와 `createWorkflowStateReader()`를 함께 사용해 스토리지에서 중단된 실행을 복구할 수 있다.
- **`createWorkflowStateReader`**는 원시 스냅샷 형태를 직접 읽지 않고, 중단된 스텝·재개 레이블·스텝 페이로드·스텝 출력을 노출한다.

**코드 예시** (`src/mastra/workflows/recover-run.ts`):
```typescript
import { createWorkflowStateReader } from '@mastra/core/workflows'

const workflow = mastra.getWorkflow('testWorkflow')
const state = await workflow.getWorkflowRunById('run-123')

if (state?.status === 'suspended') {
  const reader = createWorkflowStateReader(state)
  const suspendedStep = reader.getSuspendedStep()
  const approvalLabel = reader.getResumeLabel('approve')

  const run = await workflow.createRun({ runId: state.runId })
  await run.resume({
    step: approvalLabel?.stepId ?? suspendedStep?.path,
    resumeData: { approved: true },
    forEachIndex: approvalLabel?.foreachIndex,
  })
}
```

- 중첩 워크플로우의 경우 `suspendedStep.path`에 재개 경로가 담긴다.
- **foreach** 중단의 경우, 일치하는 재개 레이블에 특정 반복 인덱스를 가리키는 `foreachIndex`가 포함된다.

---

## Sleep (슬립)

- **sleep 메서드**는 워크플로우 레벨에서 실행을 일시 정지하며, 상태를 `waiting`으로 설정한다.
- **`suspend()`**는 특정 스텝 내에서 실행을 일시 정지하며, 상태를 `suspended`로 설정한다. (suspend와 sleep은 다름)

사용 가능한 메서드:
- `.sleep()`: 지정한 밀리초 동안 일시 정지
- `.sleepUntil()`: 특정 날짜까지 일시 정지
