---
type: reference
title: "Mastra Workflows 개요 — 구조화 워크플로우 엔진 공식 문서"
source: "https://mastra.ai/docs/workflows/overview"
aliases: ["Mastra 워크플로우 개요", "createStep createWorkflow", "Mastra workflow engine", "Mastra 워크플로우 실행", "cloneWorkflow", "Mastra stateSchema"]
tags: ["Mastra", "workflow", "workflow-engine", "createStep", "createWorkflow", "suspend-resume", "streaming", "docs"]
up: ["agent-workflow-조합"]
---

# Mastra Workflows 개요 — 구조화 워크플로우 엔진 공식 문서

## 요약

Mastra 워크플로우 엔진 공식 문서로, `createStep()`·`createWorkflow()` API를 중심으로 구조화 단계 기반 태스크 시퀀스를 정의·실행하는 방법을 다룬다. suspend/resume·스트리밍·워크플로우 상태(stateSchema)·중첩·복제 등 핵심 합성 패턴을 포괄하는 레퍼런스다.

## 핵심 내용

### 워크플로우란 무엇인가

[[agent-workflow-조합]] 패턴에서 워크플로우는 단일 에이전트 추론 대신 **명확하고 구조화된 단계(step)**로 복잡한 태스크 시퀀스를 정의하는 메커니즘이다. 태스크 분해 방식, 단계 간 데이터 흐름, 실행 시점을 완전히 제어할 수 있다.

**사용 시점**: 사전에 명확히 정의된 태스크, 특정 실행 순서가 필요한 다단계 작업, 단계 간 데이터 흐름·변환과 각 단계의 primitive 호출을 세밀하게 제어해야 할 때.

기본 내장 실행 엔진 또는 **Inngest** 같은 외부 workflow runner에 배포 가능하다. [[에이전틱-ai]] 맥락에서 워크플로우는 비결정적 실행을 추적·제어하는 핵심 구조로 기능한다.

### 핵심 원칙 — createStep · createWorkflow

**`createStep()`** 으로 스텝 정의:
- `inputSchema`·`outputSchema`로 입출력 데이터 형태 선언
- 스키마는 Zod, Valibot, ArkType 등 Standard JSON Schema 호환 라이브러리 모두 지원
- `execute` 함수에서 코드베이스 내 함수, 외부 API, 에이전트, 툴 호출 가능

```ts
const step1 = createStep({
  id: 'step-1',
  inputSchema: z.object({ message: z.string() }),
  outputSchema: z.object({ formatted: z.string() }),
  execute: async ({ inputData }) => {
    return { formatted: inputData.message.toUpperCase() }
  },
})
```

**`createWorkflow()`** 로 스텝 합성:
- `.then(step)`으로 스텝 추가, `.commit()`으로 완성

```ts
export const testWorkflow = createWorkflow({
  id: 'test-workflow',
  inputSchema: z.object({ message: z.string() }),
  outputSchema: z.object({ output: z.string() }),
})
  .then(step1)
  .commit();
```

### 워크플로우 상태 (Workflow State)

스텝 간 값을 `inputSchema`/`outputSchema` 체인을 거치지 않고 공유하는 별도 채널이다. 진행 추적·결과 누적·전체 공유 설정에 활용한다.

스텝 정의 시 `stateSchema`를 추가하고 `execute`에서 `state`·`setState`를 사용한다:

```ts
stateSchema: z.object({ counter: z.number() }),
execute: async ({ inputData, state, setState }) => {
  setState({ ...state, counter: state.counter + 1 })
  return { formatted: inputData.message.toUpperCase() }
}
```

`suspend`/`resume` 시에도 상태가 유지되며 중첩 워크플로우에서도 사용 가능하다.

### 워크플로우 합성 패턴

[[agent-workflow-조합]]의 Nested Workflows 패턴에 해당한다. 워크플로우를 스텝처럼 사용해 더 큰 합성 내에서 로직을 재사용할 수 있다:

```ts
const childWorkflow = createWorkflow({ id: 'child-workflow', ... })
  .then(step1).then(step2).commit();

const testWorkflow = createWorkflow({ id: 'test-workflow', ... })
  .then(childWorkflow).commit();
```

**`cloneWorkflow()`**: 워크플로우 로직을 재사용하되 새 ID로 독립 추적한다. 각 클론은 독립 실행되며 로그·옵저버빌리티 도구에서 별도 워크플로우로 표시된다. Nested Workflows가 계층적 합성이라면, cloneWorkflow는 동일 로직의 병렬·독립 인스턴싱이다.

### 워크플로우 등록 및 참조

- **등록**: `new Mastra({ workflows: { testWorkflow } })`로 인스턴스에 등록 → 에이전트·툴에서 호출 가능, 로깅·옵저버빌리티 공유 자원 접근
- **참조**: `mastra.getWorkflow('testWorkflow')` 권장 — 직접 import보다 Mastra 인스턴스 설정(logger, telemetry, storage) 접근 + TypeScript 타입 추론 제공
  - `getWorkflow()`는 **등록 키**로 조회; `getWorkflowById()`는 id 프로퍼티로 조회하지만 타입 추론 수준이 낮음

### 워크플로우 실행 — .start() · .stream()

**.start() 모드**: `createRun()` → `.start({ inputData })` 호출. 모든 스텝 완료 후 최종 결과 반환.

```ts
const run = await testWorkflow.createRun()
const result = await run.start({ inputData: { message: 'Hello world' } })
if (result.status === 'success') { console.log(result.result) }
```

**.stream() 모드**: `createRun()` → `.stream({ inputData })` 호출. `fullStream`으로 진행 이벤트 순차 처리, `stream.result`로 최종 결과 획득. 스텝 execute 내에서 에이전트의 `textStream`을 `writer`로 pipe해 에이전트 usage를 워크플로우 실행에 자동 집계할 수 있다.

### 워크플로우 결과 타입

`run.start()`와 `stream.result` 모두 `status` 기반 discriminated union을 반환한다. 공통 접근 가능 필드: `result.status`, `result.input`, `result.steps`, `result.state`(선택).

| status | 고유 프로퍼티 | 설명 |
|---|---|---|
| `success` | `result` | 워크플로우 출력 데이터 |
| `failed` | `error` | 실패 원인 에러 |
| `tripwire` | `reason`, `retry?`, `metadata?`, `processorId?` | — |
| `suspended` | `suspendPayload`, `suspended` | 중단 데이터 및 중단된 스텝 경로 배열 |
| `paused` | (없음) | 공통 프로퍼티만 사용 가능 |

`suspended` 상태 처리와 `resume()` 상세는 [[mastra-workflows-suspend-and-resume]] 참조. [[hitl-승인-패턴]]의 Mastra 구현 기반이 된다.

### 스트리밍 중단 재개

스트림 연결이 끊기면 `run.resumeStream()`으로 새 ReadableStream을 획득해 재개한다. 워크플로우가 `suspended` 상태면 `resumeStream({ resumeData: { ... } })`으로 재개 데이터를 함께 전달한다.

### 활성 워크플로우 실행 재시작

서버 연결이 끊길 경우 마지막 활성 스텝부터 재시작 가능:

- **`restartAllActiveWorkflowRuns()`**: 워크플로우의 모든 활성 실행 일괄 재시작
- **`run.restart()`**: 특정 실행을 마지막 활성 스텝부터 재시작
- 로컬 Mastra 서버 기동 시 모든 활성 워크플로우 실행이 자동 재시작됨
- 활성 실행 식별: status `running` 또는 `waiting`; `workflow.listActiveWorkflowRuns()`로 조회

### RequestContext 활용

`requestContext.get('key')`으로 요청별 값에 접근해 동작을 조건부 조정한다(예: 사용자 티어별 결과 수 제한):

```ts
execute: async ({ requestContext }) => {
  const userTier = requestContext.get('user-tier') as UserTier['user-tier']
  const maxResults = userTier === 'enterprise' ? 1000 : 50
  return { maxResults }
}
```

타입 안전한 RequestContext 스키마 검증은 Schema Validation 페이지 참조.

### Studio 시각화 도구

- **Graph view**: 워크플로우의 스텝과 실행 흐름 시각화
- **Input form**: `inputSchema`에서 폼 자동 생성 및 실행
- **Live status**: 실행 중 각 스텝 상태 실시간 업데이트; 입력·출력·상태·로그 표시
- **Time travel**: 실행 완료 후 개별 스텝 재실행·검사

## 연결

- [[agent-workflow-조합]] — 워크플로우의 개념적 위치(Nested Workflows, cloneWorkflow, Workflow as Tool 등 합성 패턴)의 SoT; up 노드
- [[에이전틱-ai]] — 에이전틱 시스템 맥락에서 워크플로우의 역할(비결정성 추적·제어 구조)
- [[mastra-workflows-suspend-and-resume]] — suspend/resume API 상세 레퍼런스 (suspended 결과 타입 처리 위임)
- [[hitl-승인-패턴]] — Mastra suspend/resume 기반 HITL 승인 패턴 SoT
- [[hitl-approval-placement-patterns-mastra]] — 에이전트·워크플로우 조합 구조에서 HITL 승인 위치 결정 패턴