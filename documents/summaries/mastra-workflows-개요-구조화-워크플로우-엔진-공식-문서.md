---
type: summary
title: Mastra Workflows 개요 — 구조화 워크플로우 엔진 공식 문서
source_url: https://mastra.ai/docs/workflows/overview
tags:
- Mastra
- workflow
- createStep
- createWorkflow
- step
- suspend
- resume
- streaming
- workflow state
- RequestContext
summarized_at: '2026-07-10T11:59:58.172696+00:00'
---

## 워크플로우란

- 단일 에이전트 추론 대신 **명확하고 구조화된 단계(step)**로 복잡한 태스크 시퀀스를 정의하는 메커니즘
- 태스크 분해 방식, 단계 간 데이터 흐름, 실행 시점을 완전히 제어할 수 있음
- 기본 내장 실행 엔진 사용 또는 **Inngest** 같은 외부 workflow runner에 배포 가능

## 사용 시점

- 사전에 명확히 정의된 태스크, 특정 실행 순서가 필요한 다단계 작업에 적합
- 단계 간 데이터 흐름·변환, 각 단계에서 호출할 primitive를 세밀하게 제어해야 할 때

## 핵심 원칙

1. **`createStep()`** 으로 스텝 정의 — inputSchema·outputSchema 및 비즈니스 로직 지정
2. **`createWorkflow()`** 로 스텝 합성 — 실행 흐름 정의
3. 워크플로우 **실행** — 일시 중단·재개·스트리밍 결과를 기본 지원

## 워크플로우 스텝 생성

- `createStep()`으로 생성; `inputSchema`와 `outputSchema`로 입출력 데이터 정의
- 스키마는 **Zod**, **Valibot**, **ArkType** 등 Standard JSON Schema 호환 라이브러리 모두 지원
- `execute` 함수에서 코드베이스 내 함수, 외부 API, 에이전트, 툴 호출 가능
- 스텝은 등록된 에이전트나 툴을 직접 호출할 수도 있음

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

## 워크플로우 생성

- `createWorkflow()`로 생성; `inputSchema`·`outputSchema` 지정
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

## 제어 흐름(Control Flow)

- 워크플로우는 여러 합성 방식으로 구성 가능하며, 선택한 방식에 따라 각 스텝의 스키마 구조가 달라짐
- 상세 내용은 별도 Control Flow 페이지 참조

## Studio (시각화 도구)

- **Graph view**: 워크플로우의 스텝과 실행 흐름을 시각화
- **Input form**: `inputSchema`에서 폼을 자동 생성, 실행 가능
- **Live status**: 실행 중 각 스텝 상태를 실시간 업데이트; 입력·출력·상태·로그 표시
- **Time travel**: 실행 완료 후 개별 스텝 재실행·검사 가능

## 워크플로우 상태(Workflow State)

- 모든 스텝의 inputSchema/outputSchema를 거치지 않고도 스텝 간 값 공유 가능
- 진행 추적, 결과 누적, 전체 워크플로우 공유 설정에 활용
- 스텝 정의 시 `stateSchema` 추가, `execute`에서 `state`·`setState` 사용

```ts
stateSchema: z.object({ counter: z.number() }),
execute: async ({ inputData, state, setState }) => {
  setState({ ...state, counter: state.counter + 1 })
  return { formatted: inputData.message.toUpperCase() }
}
```

- suspend/resume 시에도 상태 유지, 중첩 워크플로우에서도 사용 가능

## 워크플로우를 스텝으로 사용 (Workflows as Steps)

- 워크플로우를 스텝처럼 사용해 더 큰 합성 내에서 로직 재사용 가능
- 입출력은 Core principles의 스키마 규칙을 동일하게 따름

```ts
const childWorkflow = createWorkflow({ id: 'child-workflow', ... })
  .then(step1).then(step2).commit();

const testWorkflow = createWorkflow({ id: 'test-workflow', ... })
  .then(childWorkflow).commit();
```

## 워크플로우 복제 (cloneWorkflow)

- `cloneWorkflow()`로 워크플로우 로직은 재사용하되 새 ID로 독립 추적
- 각 클론은 독립 실행되며 로그·옵저버빌리티 도구에서 별도 워크플로우로 표시

## 워크플로우 등록 및 참조

- **등록**: `new Mastra({ workflows: { testWorkflow } })`로 인스턴스에 등록 → 에이전트·툴에서 호출 가능, 로깅·옵저버빌리티 공유 자원 접근
- **참조**: `mastra.getWorkflow('testWorkflow')` 사용 권장
  - 직접 import보다 선호하는 이유: Mastra 인스턴스 설정(logger, telemetry, storage 등) 접근 + TypeScript 타입 추론 제공
  - `getWorkflow()`는 **등록 키(registration key)** 로 조회; `getWorkflowById()`는 id 프로퍼티로 조회하지만 타입 추론 수준이 낮음

## 워크플로우 실행

### `.start()` 모드
- `createRun()` → `.start({ inputData })` 호출
- 모든 스텝 완료 후 최종 결과 반환

```ts
const run = await testWorkflow.createRun()
const result = await run.start({ inputData: { message: 'Hello world' } })
if (result.status === 'success') { console.log(result.result) }
```

### `.stream()` 모드
- `createRun()` → `.stream({ inputData })` 호출
- `fullStream`으로 진행 이벤트 순차 처리, `stream.result`로 최종 결과 획득

```ts
const stream = run.stream({ inputData: { message: 'Hello world' } })
for await (const chunk of stream.fullStream) { console.log(chunk) }
const result = await stream.result
```

## 워크플로우 결과 타입

- `run.start()`와 `stream.result` 모두 `status` 기반 discriminated union 반환
- 공통 접근 가능 필드: `result.status`, `result.input`, `result.steps`, `result.state`(선택)

| status | 고유 프로퍼티 | 설명 |
|---|---|---|
| `success` | `result` | 워크플로우 출력 데이터 |
| `failed` | `error` | 실패 원인 에러 |
| `tripwire` | `reason`, `retry?`, `metadata?`, `processorId?` | — |
| `suspended` | `suspendPayload`, `suspended` | 중단 데이터 및 중단된 스텝 경로 배열 |
| `paused` | (없음) | 공통 프로퍼티만 사용 가능 |

## 스트리밍 상세

### 스트림 페이로드 검사
- 스트림에 기록된 이벤트는 방출된 청크에 포함됨
- 청크에서 이벤트 타입, 중간 값, 스텝별 데이터 등 커스텀 필드 접근 가능

### 중단된 워크플로우 스트림 재개
- 스트림 연결이 끊기면 `run.resumeStream()`으로 새 ReadableStream 획득 후 재개
- 워크플로우가 `suspended` 상태면 `resumeStream({ resumeData: { ... } })`으로 재개 데이터 전달

### 에이전트와 함께 스트리밍
- 스텝 execute 내에서 에이전트의 `textStream`을 `writer`로 pipe 가능
- Mastra가 에이전트 usage를 워크플로우 실행에 자동 집계

```ts
execute: async ({ inputData, mastra, writer }) => {
  const stream = await mastra?.getAgent('testAgent')?.stream(`What is the weather in ${inputData.city}?`)
  await stream!.textStream.pipeTo(writer!)
  return { value: await stream!.text }
}
```

## 활성 워크플로우 실행 재시작

- 서버 연결이 끊길 경우 마지막 활성 스텝부터 재시작 가능
- **`restartAllActiveWorkflowRuns()`**: 워크플로우의 모든 활성 실행을 일괄 재시작
- **`run.restart()`**: 특정 실행을 마지막 활성 스텝부터 재시작
- 활성 실행 식별: status가 `running` 또는 `waiting`인 실행; `workflow.listActiveWorkflowRuns()`로 조회
- 로컬 Mastra 서버 기동 시 모든 활성 워크플로우 실행이 자동 재시작됨

## RequestContext 활용

- `requestContext.get('key')`으로 요청별 값 접근
- 요청 컨텍스트에 따라 동작을 조건부로 조정 가능 (예: 사용자 티어별 결과 수 제한)

```ts
execute: async ({ requestContext }) => {
  const userTier = requestContext.get('user-tier') as UserTier['user-tier']
  const maxResults = userTier === 'enterprise' ? 1000 : 50
  return { maxResults }
}
```

- 타입 안전한 RequestContext 스키마 검증은 Schema Validation 페이지 참조
