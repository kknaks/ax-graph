---
type: summary
title: OpenAI Agents SDK — Human-in-the-Loop 승인 흐름 가이드
source_url: https://openai.github.io/openai-agents-js/guides/human-in-the-loop/
tags:
- human-in-the-loop
- OpenAI Agents SDK
- interruptions
- RunState
- needsApproval
- tool approval
- agent.asTool
- serialization
- streaming
- handoff
summarized_at: '2026-07-10T12:01:35.865056+00:00'
---

## 개요

- **대상**: OpenAI Agents JS SDK의 승인 기반 HITL(human-in-the-loop) 흐름
- 툴 호출에 승인이 필요하면 SDK가 실행을 **일시 중지**하고 `interruptions`를 반환, 이후 동일한 `RunState`에서 재개 가능
- 승인 범위는 run 전체 — 현재 에이전트뿐 아니라 **handoff**로 도달한 에이전트, 중첩된 `agent.asTool()` 실행 내부 툴도 포함
- `agent.asTool()` 케이스에서는 두 레이어에서 승인이 발생할 수 있음:
  1. `asTool({ needsApproval })`로 에이전트 툴 자체에 승인 요구
  2. 중첩 run 시작 후 내부 툴이 자체 승인 요구
  - 두 경우 모두 **외부 run의 interruption 흐름**으로 처리됨

---

## 승인 흐름 (Approval Flow)

### 툴 정의

`needsApproval` 옵션으로 승인 필요 여부를 지정:

- **항상 승인 필요**: `needsApproval: true`
- **조건부 승인**: `needsApproval: async (context, args) => boolean` 형태의 비동기 함수

```ts
// 항상 승인 필요
const sensitiveTool = tool({
  name: 'cancelOrder',
  needsApproval: true,
  execute: async ({ orderId }, args) => { /* ... */ },
});

// 조건부 승인 (제목에 'spam' 포함 시만)
const sendEmail = tool({
  name: 'sendEmail',
  needsApproval: async (_context, { subject }) => subject.includes('spam'),
  execute: async ({ to, subject, body }, args) => { /* ... */ },
});
```

### 흐름 단계

1. 툴 호출 직전 SDK가 `needsApproval` 규칙 평가
2. 승인 필요 + 결정 미저장 → 툴 미실행, **`RunToolApprovalItem`** 기록
3. 해당 턴 종료 시 run 일시 중지, `result.interruptions` 배열로 보류 항목 반환
4. 각 항목을 `result.state.approve(interruption)` 또는 `result.state.reject(interruption)`으로 결정
   - `{ alwaysApprove: true }` / `{ alwaysReject: true }`: 해당 run 전체에서 동일 툴 고정 결정
   - `{ message: '...' }`: 거절 시 모델에 전달할 메시지 커스터마이즈
5. `runner.run(agent, state)`로 재개 — `agent`는 **원래 최상위 에이전트**

### 부분 처리

- 모든 보류 항목을 한 번에 해결할 필요 없음
- 일부만 승인·거절 후 재실행하면 해결된 항목은 계속 진행, 미해결 항목은 다음 `interruptions`에 재등장

---

## 입력 가드레일과 승인의 관계

- 기본 동작: 함수 툴의 입력 가드레일은 **승인 후**, 툴 실행 직전에 실행
- 선택적 동작: `run()` 또는 `Runner`에 `toolExecution: { preApprovalInputGuardrails: true }` 전달 시 승인 전에도 가드레일 실행
  - 가드레일이 **거절** → approval interruption 대신 가드레일 메시지가 툴 출력으로 모델에 전달
  - 가드레일이 **허용** → run은 여전히 승인을 위해 일시 중지, 승인 후 가드레일 재실행(대기 중 안전성 변화 대비)

---

## 자동 승인 결정 (Automatic Approval Decisions)

수동 interruption 외에 코드에서 즉시 결정하는 방식:

| 툴 타입 | 방법 |
|---|---|
| 로컬 `shellTool()`, `applyPatchTool()` | `onApproval` 콜백 사용 |
| 호스팅 MCP 툴 | `requireApproval` + `onApproval` 조합 |
| 일반 함수 툴 | 수동 interruption 흐름만 지원 |

- 콜백이 결정을 반환하면 run이 일시 중지 없이 계속 진행
- Realtime/voice 세션은 별도의 voice agents 가이드 참고

---

## 스트리밍 및 세션 통합

- 스트리밍 run에서도 동일한 interruption 흐름 적용
- 흐름:
  1. 스트리밍 run 일시 중지 → `stream.completed` 대기
  2. `stream.interruptions` 읽기
  3. 항목 해결
  4. `run(agent, state, { stream: true })`로 재개(스트리밍 유지)
- **세션(session)** 사용 시: `RunState`에서 재개할 때도 동일 `session` 전달 필요
  - 재개 턴이 세션 메모리에 추가되며 입력 재준비 불필요

---

## 예제: 터미널 승인 + 상태 파일 저장

**시나리오**: Oakland와 San Francisco의 날씨 질의, SF 조회 시 승인 필요

**구조**:
- `getWeatherTool`: `location === 'San Francisco'`일 때만 `needsApproval: true`
- `dataAgentTwo`: 날씨 전문 에이전트, `getWeatherTool` 보유
- `agent`: 최상위 에이전트, `dataAgentTwo`에 handoff

**처리 흐름**:
1. `run(agent, 'What is the weather in Oakland and San Francisco?')` 실행
2. `result.interruptions` 존재 시:
   - `result.state`를 `result.json` 파일로 직렬화 저장
   - `RunState.fromString(agent, storedState)`로 복원
   - 각 interruption에 대해 터미널에서 y/n 질의
   - `state.approve()` / `state.reject()` 호출
   - `run(agent, state)`로 재개
3. `result.finalOutput` 출력

---

## 장기 보류 처리 (Longer Approval Times)

- 서버를 종료하고 나중에 재개 가능한 설계
- **직렬화**: `result.state.toString()` 또는 `JSON.stringify(result.state)`
- **역직렬화**: `RunState.fromString(agent, serializedState)` — `agent`는 전체 run을 시작한 최상위 에이전트
- SDK는 직렬화 시 안정적인 에이전트 ID를 기록 → 같은 이름을 가진 에이전트들도 구분 가능
- `sticky decisions`(`alwaysApprove/alwaysReject`)는 직렬화 상태에 유지됨

### 에이전트 그래프 재구성

- 역직렬화 시 SDK가 `agent`의 handoffs 및 `Agent.asTool()` 참조를 순회하여 모든 직렬화된 에이전트 참조를 재구성 그래프에 매핑
- **대체 그래프로 재개** 필요 시:
  1. 원래 그래프로 역직렬화
  2. 다시 직렬화
  3. 대체 루트 에이전트로 재역직렬화
  - ⚠️ `state.setCurrentAgent(agent)`는 활성 에이전트만 변경, 역직렬화 중 이미 해결된 중첩 참조는 변경 불가

### 컨텍스트 주입

재개 프로세스에 새 컨텍스트 객체가 필요할 때:
`RunState.fromStringWithContext(agent, serializedState, context, { contextStrategy })`

| `contextStrategy` | 동작 |
|---|---|
| `'merge'` (기본) | 제공된 `RunContext` 유지, 직렬화된 승인 상태 병합, 새 컨텍스트에 없는 `toolInput` 복원 |
| `'replace'` | 제공된 `RunContext`를 그대로 사용하여 run 재구성 |

### 보안 주의사항

- 직렬화된 상태에는 앱 컨텍스트 + SDK 런타임 메타데이터(승인, 사용량, 중첩 toolInput 등) 포함
- `runContext.context`는 영속 데이터로 취급 — 의도하지 않은 한 비밀값 저장 금지
- 기본적으로 **tracing API 키는 직렬화 상태에서 제외** (보안)
  - 포함하려면: `result.state.toString({ includeTracingApiKey: true })`

---

## Computer 툴 Interruption 특이사항

- GA 모델에서 `computer_call` 하나가 여러 액션 배치를 나타낼 수 있음
- SDK는 **액션별로** `needsApproval` 평가 → 하나의 보류 승인이 move + click 같은 시퀀스를 커버 가능
- `interruption.rawItem` 검사 시 GA `actions` 배열과 레거시 단일 `action` 필드 **모두 처리** 필요
- 직렬화된 `RunState`는 `computer` 툴명과 레거시 `computer_use_preview`명 모두에서 computer 승인을 보존 → preview→GA 마이그레이션 중에도 재개 가능

---

## 버전 관리 (Versioning Pending Tasks)

> **주의**: 직렬화된 상태를 장기간 저장하면서 에이전트 정의나 SDK 버전을 변경할 계획이 있을 때 해당

- 현재 권장 방법: **패키지 별칭(package aliases)**을 사용해 두 버전의 Agents SDK를 병렬 설치
- 자체 코드에 버전 번호를 부여하고, 직렬화된 상태와 함께 저장
- 역직렬화 시 저장된 버전 번호로 올바른 코드 버전을 분기하여 처리
