---
type: reference
title: "OpenAI Agents JS SDK — Human-in-the-Loop 승인 흐름 가이드"
source: "https://openai.github.io/openai-agents-js/guides/human-in-the-loop/"
aliases: ["OpenAI Agents JS HITL", "OpenAI Agents SDK 승인 흐름", "RunState 승인 재개"]
tags: ["human-in-the-loop", "openai-agents-sdk", "tool-approval", "runstate", "serialization", "streaming", "docs"]
up: ["hitl-승인-패턴"]
---

# OpenAI Agents JS SDK — Human-in-the-Loop 승인 흐름 가이드

## 요약

OpenAI Agents JS SDK에서 툴 호출 전 사람 승인을 구현하는 공식 가이드다. SDK가 실행을 일시 중지하고 `interruptions` 배열을 반환하면, 개발자가 `RunState`를 통해 승인·거절 후 재개하는 흐름이 핵심이다. 직렬화 지원으로 서버 종료 후 장기 보류도 처리 가능하다.

## 핵심 내용

### 개요 및 적용 범위

[[hitl-승인-패턴]]의 툴 레벨 승인 변형을 SDK 레벨에서 구현한다. 승인 범위는 run 전체이며, 현재 에이전트뿐 아니라 **handoff**로 도달한 에이전트와 중첩된 `agent.asTool()` 내부 툴도 포함된다.

`agent.asTool()` 케이스에서는 두 레이어에서 승인이 발생할 수 있다:
1. `asTool({ needsApproval })`로 에이전트 툴 자체에 승인 요구
2. 중첩 run 시작 후 내부 툴이 자체 승인 요구
두 경우 모두 외부 run의 interruption 흐름으로 처리된다.

### needsApproval 옵션과 흐름 단계

툴 정의 시 `needsApproval` 옵션으로 승인 여부를 지정한다:

- **항상 승인**: `needsApproval: true`
- **조건부 승인**: `needsApproval: async (context, args) => boolean`

```ts
// 항상 승인 필요
const sensitiveTool = tool({
  name: 'cancelOrder',
  needsApproval: true,
  execute: async ({ orderId }, args) => { /* ... */ },
});

// 조건부 — 제목에 'spam' 포함 시만
const sendEmail = tool({
  name: 'sendEmail',
  needsApproval: async (_context, { subject }) => subject.includes('spam'),
  execute: async ({ to, subject, body }, args) => { /* ... */ },
});
```

흐름 단계:
1. 툴 호출 직전 SDK가 `needsApproval` 규칙 평가
2. 승인 필요 + 결정 미저장 → 툴 미실행, `RunToolApprovalItem` 기록
3. 해당 턴 종료 시 run 일시 중지, `result.interruptions` 배열로 보류 항목 반환
4. 각 항목을 `result.state.approve(interruption)` 또는 `result.state.reject(interruption)`으로 결정
   - `{ alwaysApprove: true }` / `{ alwaysReject: true }`: 동일 run 전체에서 해당 툴 고정 결정
   - `{ message: '...' }`: 거절 시 모델에 전달할 메시지 커스터마이즈
5. `runner.run(agent, state)`로 재개 — `agent`는 원래 최상위 에이전트

**부분 처리**: 모든 보류 항목을 한 번에 해결할 필요 없다. 일부만 결정 후 재실행하면 미해결 항목은 다음 `interruptions`에 재등장한다.

### 입력 가드레일과 승인의 관계

기본적으로 함수 툴의 입력 가드레일은 승인 후, 툴 실행 직전에 실행된다. `toolExecution: { preApprovalInputGuardrails: true }` 옵션을 `run()` 또는 `Runner`에 전달하면 승인 전에도 가드레일이 실행된다:

- 가드레일이 **거절** → approval interruption 대신 가드레일 메시지가 툴 출력으로 모델에 전달
- 가드레일이 **허용** → run은 여전히 승인을 위해 일시 중지, 승인 후 가드레일 재실행(대기 중 안전성 변화 대비)

### 자동 승인 결정 (Automatic Approval Decisions)

수동 interruption 루프 없이 코드에서 즉시 결정하는 방식:

| 툴 타입 | 방법 |
|---|---|
| 로컬 `shellTool()`, `applyPatchTool()` | `onApproval` 콜백 사용 |
| 호스팅 MCP 툴 | `requireApproval` + `onApproval` 조합 |
| 일반 함수 툴 | 수동 interruption 흐름만 지원 |

콜백이 결정을 반환하면 run이 일시 중지 없이 계속 진행된다.

### 스트리밍 및 세션 통합

스트리밍 run에서도 동일한 interruption 흐름이 적용된다:
1. 스트리밍 run 일시 중지 → `stream.completed` 대기
2. `stream.interruptions` 읽기
3. 항목 해결
4. `run(agent, state, { stream: true })`로 재개(스트리밍 유지)

**세션(session)** 사용 시 `RunState`에서 재개할 때 동일 `session`을 전달해야 한다. 재개 턴이 세션 메모리에 추가되어 입력 재준비가 불필요하다.

### 장기 보류 처리 — RunState 직렬화

서버를 종료하고 나중에 재개 가능한 설계를 지원한다:

- **직렬화**: `result.state.toString()` 또는 `JSON.stringify(result.state)`
- **역직렬화**: `RunState.fromString(agent, serializedState)` — `agent`는 전체 run을 시작한 최상위 에이전트
- `sticky decisions`(`alwaysApprove/alwaysReject`)는 직렬화 상태에 유지됨
- SDK는 안정적인 에이전트 ID를 기록해 같은 이름의 에이전트들도 구분 가능

**에이전트 그래프 재구성**: 역직렬화 시 SDK가 `agent`의 handoffs 및 `Agent.asTool()` 참조를 순회해 직렬화된 에이전트 참조를 재구성 그래프에 매핑한다. 대체 그래프로 재개 시에는 원래 그래프로 역직렬화 → 재직렬화 → 대체 루트 에이전트로 재역직렬화 순서를 따른다. `state.setCurrentAgent(agent)`는 활성 에이전트만 변경하며, 역직렬화 중 이미 해결된 중첩 참조는 변경 불가하다.

**컨텍스트 주입**: 재개 프로세스에 새 컨텍스트 객체가 필요할 때 `RunState.fromStringWithContext(agent, serializedState, context, { contextStrategy })`를 사용한다:

| `contextStrategy` | 동작 |
|---|---|
| `'merge'` (기본) | 제공된 `RunContext` 유지, 직렬화된 승인 상태 병합, 새 컨텍스트에 없는 `toolInput` 복원 |
| `'replace'` | 제공된 `RunContext`를 그대로 사용하여 run 재구성 |

**보안**: 직렬화 상태에는 앱 컨텍스트 + SDK 런타임 메타데이터가 포함되므로 `runContext.context`에 비밀값 저장을 피해야 한다. tracing API 키는 기본적으로 직렬화에서 제외되며, 포함하려면 `result.state.toString({ includeTracingApiKey: true })`를 명시해야 한다.

### Computer 툴 Interruption 특이사항

GA 모델에서 `computer_call` 하나가 여러 액션 배치를 나타낼 수 있다. SDK는 **액션별로** `needsApproval`을 평가하므로, 하나의 보류 승인이 move + click 같은 시퀀스를 커버할 수 있다. `interruption.rawItem` 검사 시 GA `actions` 배열과 레거시 단일 `action` 필드 **모두 처리**해야 한다. 직렬화된 `RunState`는 `computer` 툴명과 레거시 `computer_use_preview`명 모두에서 computer 승인을 보존하여 preview→GA 마이그레이션 중에도 재개 가능하다.

### 버전 관리 (Versioning Pending Tasks)

직렬화 상태를 장기 저장하면서 에이전트 정의나 SDK 버전을 변경할 계획이 있을 때 적용한다. 현재 권장 방법은 **패키지 별칭(package aliases)**으로 두 버전의 Agents SDK를 병렬 설치하고, 자체 코드에 버전 번호를 부여해 직렬화 상태와 함께 저장한 뒤, 역직렬화 시 저장된 버전 번호로 올바른 코드 버전을 분기하여 처리하는 방식이다.

## 연결

- [[hitl-승인-패턴]] — 이 문서가 구현하는 툴 레벨 승인 패턴의 개념 SoT; up 노드
- [[agentkit-human-in-the-loop-inngest-waitforevent]] — Inngest 기반 이벤트 수신 방식 HITL 구현 — 같은 툴 레벨 승인 패턴의 다른 프레임워크 구현 사례
- [[n8n-ai-에이전트-hitl-도구-승인]] — n8n 플랫폼 내장형 HITL 구현 — 코드 없이 UI로 동일 패턴 구현하는 비교 사례
- [[에이전틱-ai]] — 에이전트 실행 루프와 툴 호출 구조의 개념 SoT
