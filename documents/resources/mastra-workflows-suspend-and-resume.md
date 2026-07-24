---
type: reference
title: "Mastra Workflows — Suspend and Resume (일시 중단·재개)"
source: "https://mastra.ai/docs/workflows/suspend-and-resume"
aliases: ["Mastra suspend resume", "Mastra 워크플로우 일시 중단", "Mastra 워크플로우 재개", "createWorkflowStateReader", "Mastra snapshot"]
tags: ["Mastra", "workflow", "suspend-resume", "human-in-the-loop", "snapshot", "docs"]
up: ["hitl-승인-패턴"]
---

# Mastra Workflows — Suspend and Resume (일시 중단·재개)

## 요약

Mastra 워크플로우에서 임의의 스텝을 일시 중단하고 나중에 재개하는 메커니즘의 공식 레퍼런스다. `suspend()`/`resume()` API, 중단 시 스냅샷 영속화, `suspendData`를 통한 컨텍스트 보존, `createWorkflowStateReader()`를 이용한 중단 실행 복구까지 포괄한다. [[hitl-승인-패턴]]의 Mastra 구현 레퍼런스로 활용한다.

## 핵심 내용

### 중단 목적과 스냅샷 영속화

워크플로우는 다음 목적으로 임의의 스텝에서 일시 중단될 수 있다: 추가 데이터 수집, API 콜백 대기, 비용이 큰 작업 스로틀링, **human-in-the-loop** 입력 요청.

중단 시 현재 실행 상태가 **스냅샷(snapshot)**으로 저장된다. 스냅샷은 설정된 스토리지 프로바이더에 영속적으로 보관되며, 배포 및 애플리케이션 재시작 후에도 유지된다. 이후 특정 step ID로부터 재개하면 해당 스냅샷의 정확한 상태가 복원된다.

### suspend()로 일시 중단

스텝의 `execute` 블록 안에서 `suspend()`를 호출해 실행을 멈춘다. `resumeData` 값으로 resume 조건을 정의하고, 조건이 충족되지 않으면 `suspend()`가 반환되며 워크플로우가 중단된다.

```typescript
const step1 = createStep({
  id: 'step-1',
  inputSchema: z.object({ userEmail: z.string() }),
  outputSchema: z.object({ output: z.string() }),
  resumeSchema: z.object({ approved: z.boolean() }),
  execute: async ({ inputData, resumeData, suspend }) => {
    const { approved } = resumeData ?? {}
    if (!approved) {
      return await suspend({})
    }
    return { output: `Email sent to ${inputData.userEmail}` }
  },
})
```

### resume()로 재개

`resume()`은 중단된 워크플로우를 일시 중단된 스텝에서 재시작한다. `resumeData`를 스텝의 `resumeSchema`에 맞게 전달해 중단 조건을 충족시킨다.

- **step 객체** 전달: `resumeData`에 대한 완전한 타입 안전성 확보
- **step ID 문자열** 전달: 사용자 입력이나 DB에서 ID를 가져올 때 유용
- **step 생략**: 중단된 스텝이 하나뿐이면 Mastra가 마지막 중단 스텝을 자동 재개

`runId`만으로 재개할 경우 먼저 `createRun({ runId })`로 run 인스턴스를 생성한 뒤 `resume()`을 호출한다.

`resume()`은 HTTP 엔드포인트, 이벤트 핸들러, 타이머 등 애플리케이션 어디서든 호출 가능하다. 타이머 예시:

```typescript
const midnight = new Date()
midnight.setUTCHours(24, 0, 0, 0)
setTimeout(async () => {
  await run.resume({ step: 'step-1', resumeData: { approved: true } })
}, midnight.getTime() - Date.now())
```

### suspendData로 중단 컨텍스트 보존

`suspend(data)`에 전달한 데이터를 재개 시점에서 `suspendData` 파라미터로 접근할 수 있다. 워크플로우가 왜 중단됐는지 컨텍스트를 유지하고 재개 시 활용하는 데 쓰인다.

```typescript
// 중단 시: 컨텍스트 저장
return await suspend({
  reason: 'User approval required',
  requestDetails: `Request ${requestId} pending review`,
})

// 재개 시: 원래 중단 데이터 접근
const suspendReason = suspendData?.reason || 'Unknown'
```

`suspendData`는 재개 시 자동으로 채워지며, 최초 중단 시 `suspend()`에 전달된 정확한 데이터를 담는다. `suspendSchema`(Zod)로 타입을 선언할 수 있다.

### 중단된 실행 식별

워크플로우 실행 결과에서 `result.status === 'suspended'`로 중단 여부를 확인하고, `result.suspended` 배열로 중단된 스텝 또는 중첩 워크플로우를 식별한다.

```typescript
const result = await run.start({ inputData: { userEmail: 'alex@example.com' } })

if (result.status === 'suspended') {
  console.log(result.suspended[0])   // 예: ['nested-workflow', 'step-1']
  await run.resume({
    step: result.suspended[0],
    resumeData: { approved: true },
  })
}
```

`suspended` 배열의 값을 `resume()`의 `step` 파라미터에 직접 전달해 특정 중단 경로를 재개할 수 있다.

### 중단 실행 복구 (createWorkflowStateReader)

`workflow.getWorkflowRunById()`와 `createWorkflowStateReader()`를 함께 사용해 스토리지에서 중단된 실행을 복구한다. `createWorkflowStateReader`는 원시 스냅샷을 직접 파싱하지 않고 중단 스텝·재개 레이블·스텝 페이로드·스텝 출력을 노출하는 추상 API다.

```typescript
import { createWorkflowStateReader } from '@mastra/core/workflows'

const state = await workflow.getWorkflowRunById('run-123')
if (state?.status === 'suspended') {
  const reader = createWorkflowStateReader(state)
  const suspendedStep = reader.getSuspendedStep()
  const approvalLabel = reader.getResumeLabel('approve')

  const run = await workflow.createRun({ runId: state.runId })
  await run.resume({
    step: approvalLabel?.stepId ?? suspendedStep?.path,
    resumeData: { approved: true },
    forEachIndex: approvalLabel?.foreachIndex,   // foreach 중단 시 특정 반복 인덱스
  })
}
```

중첩 워크플로우의 경우 `suspendedStep.path`에 재개 경로가 담기며, foreach 중단에서는 `foreachIndex`로 특정 반복을 지목한다.

### sleep vs suspend 구분

| 구분 | 메서드 | 적용 레벨 | 상태 값 |
|---|---|---|---|
| 시간 기반 대기 | `.sleep(ms)` / `.sleepUntil(date)` | 워크플로우 레벨 | `waiting` |
| 외부 입력 대기 | `suspend()` | 스텝 레벨 | `suspended` |

`sleep`/`sleepUntil`은 지정한 시간이 지나면 자동 재개되며, `suspend()`는 명시적 `resume()` 호출이 있어야 재개된다.

## 연결

- [[hitl-승인-패턴]] — 이 문서가 다루는 suspend/resume 메커니즘의 개념 SoT; up 노드
- [[hitl-approval-placement-patterns-mastra]] — 동일 Mastra 생태계에서 suspend/resume를 HITL 승인 위치 패턴에 적용하는 가이드; 형제 레퍼런스
- [[voltagent-워크플로우-suspend-resume-cancellation]] — VoltAgent에서의 동일 suspend/resume 패턴 구현; 프레임워크 간 비교 참조
