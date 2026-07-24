---
type: summary
title: VoltAgent Tools — 에이전트 도구 생성·실행·제어 완전 가이드
source_url: https://voltagent.dev/docs/agents/tools/
tags:
- VoltAgent
- createTool
- Tool Hooks
- needsApproval
- AbortController
- MCP
- client-side tools
- streaming tool
- ToolDeniedError
- multimodal
summarized_at: '2026-07-10T11:59:00.777195+00:00'
---

## 도구(Tool) 개요

- 도구는 에이전트가 외부 시스템·API·데이터베이스와 상호작용하거나 텍스트 생성 이상의 작업을 수행하게 한다.
- 모델은 도구 description과 현재 컨텍스트를 보고 **언제 도구를 호출할지 스스로 결정**한다.

## 도구 생성 (`createTool`)

```ts
import { createTool } from "@voltagent/core";
import { z } from "zod";

const weatherTool = createTool({
  name: "get_weather",
  description: "Get current weather for a location",
  parameters: z.object({ location: z.string().describe("The city name") }),
  execute: async ({ location }) => { /* ... */ },
});
```

각 도구의 필수/선택 필드:
- **`name`**: 고유 식별자
- **`description`**: 모델이 호출 시점 결정에 사용
- **`parameters`**: Zod 스키마로 입력 정의 (타입 자동 추론, IntelliSense 지원)
- **`execute`**: 도구 실행 함수
- `providerOptions` (선택): Anthropic 캐시 컨트롤 등 제공자별 고급 옵션
- `tags` (선택): 조직화·레이블링용 문자열 배열

## 도구 훅 (Tool Hooks)

- 도구별로 `onStart`·`onEnd` 훅을 붙여 실행 관찰 또는 결과 후처리 가능.
- **훅 실행 순서**: tool-level 훅 → agent-level `onToolEnd` (agent 훅이 이후에 오버라이드 가능)
- `onEnd`에서 `{ output }` 반환 시 결과 오버라이드 가능; `outputSchema`가 있으면 재검증됨.
- 스트리밍 도구(AsyncIterable)에서는 오버라이드가 **최종 출력에만** 적용됨.

파라미터:
- `onStart`: `{ tool, args, options }`
- `onEnd`: `{ tool, args, output, error, options }`

## 스트리밍 도구 결과 (Preliminary)

- `execute`에서 **`AsyncIterable`** 반환 시 각 `yield` 값이 중간(preliminary) 결과로 emit됨.
- **마지막 yield 값**이 최종 결과로 처리됨.
- 진행 상태나 중간 상태를 UI에 스트리밍할 때 유용.
- `outputSchema`로 `z.discriminatedUnion` 등 복합 스키마 사용 가능.

## 도구 태그 (Tool Tags)

- 선택적 문자열 레이블로 도구를 분류·카테고리화.
- **OpenTelemetry 스팬**과 **VoltAgent 옵저버빌리티 대시보드**에 포함.
- REST 엔드포인트(`GET /tools`, `POST /tools/:name/execute` 응답)에도 포함 → 프론트엔드 액세스 제어 구현 가능.
- 예시 태그: `"database"`, `"read-only"`, `"sql"`, `"destructive"`, `"external-api"`

## 제공자별 옵션 (Provider-Specific Options)

### Anthropic 캐시 컨트롤

- `providerOptions.anthropic.cacheControl.type: "ephemeral"` 설정으로 도구 정의를 캐시.
- 반복 도구 호출 시 비용·레이턴시 절감.

## 에이전트에 도구 연결

```ts
const agent = new Agent({
  name: "Weather Assistant",
  instructions: "...",
  model: "openai/gpt-4o",
  tools: [weatherTool],
});
const response = await agent.generateText("What's the weather in Paris?");
```

- 여러 도구를 배열로 전달하면 모델이 복합 쿼리에 맞춰 여러 도구를 조합 사용.

## 동적 도구 등록

- 생성 후 도구 추가: `agent.addTools([calculatorTool])`
- 특정 요청에만 도구 제공: `agent.generateText("...", { tools: [calculatorTool] })`

## 실행 컨텍스트 접근 (`ToolExecuteOptions`)

`execute(args, options)` 두 번째 파라미터가 `ToolExecuteOptions`(`Partial<OperationContext>` 확장):

**`toolContext`** (선택, VoltAgent 에이전트에서 호출 시 항상 존재; MCP 등 외부 시스템에서는 `undefined`일 수 있음):
- `toolContext.name`: 실행 중인 도구 이름
- `toolContext.callId`: 이 특정 도구 호출의 고유 ID (AI SDK 제공)
- `toolContext.messages`: 도구 호출 시점의 메시지 히스토리
- `toolContext.abortSignal`: 취소 감지용 AbortSignal

**`OperationContext` 필드 (options에 직접):**
- `operationId`: 이 operation의 고유 ID
- `userId`, `conversationId`: 선택적 식별자
- `workspace`: 에이전트에 설정된 워크스페이스 인스턴스
- `context`: 사용자 제공 컨텍스트 값의 Map
- `systemContext`: 내부 시스템 값 Map
- `isActive`: operation 활성 여부
- `input`: 원본 입력(string / UIMessage[] / BaseMessage[])
- `abortController`: operation 취소용 AbortController
- `logger`: 실행 범위 로거
- `traceContext`: OpenTelemetry 트레이스 컨텍스트
- `elicitation`: 사용자 입력 요청 함수 (선택)

## 취소 (AbortController)

- `options.abortController.signal`을 fetch 등에 전달해 취소 지원.
- 도구 내부에서 `abortController.abort(reason)`을 호출해 **전체 operation 취소** 가능.
- 에이전트 호출 시 `{ abortSignal: controller.signal }` 전달, `isAbortError(err)`로 취소 오류 구분.

## 도구 실행 승인 (`needsApproval`)

- 민감한 작업(결제·파일 변경·명령 실행 등) 도구에 `needsApproval: true` 설정.
- 함수로도 지정 가능: `needsApproval: async ({ amount }) => amount > 1000`

### 승인 플로우
1. 모델이 `needsApproval` 도구 호출
2. VoltAgent가 `state: "approval-requested"` 도구 파트 반환 (실행 안 함)
3. UI가 사용자에게 승인/거부 요청
4. VoltAgent에 승인 응답 전송
5. 승인 시 다음 스텝에서 도구 실행; 거부 시 모델이 거부 결과 확인 후 응답

### UI 구현 (`useChat`)
- `useChat`의 `addToolApprovalResponse({ id, approved, reason? })`로 승인/거부 응답 전송.
- `sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithApprovalResponses` 설정 시 자동 전송.

## 클라이언트 사이드 도구

- **`execute` 함수가 없는 도구**는 자동으로 클라이언트 사이드 도구가 됨.
- 브라우저 API(위치 정보, 클립보드 등) 접근에 적합.
- `useChat`의 `onToolCall` 콜백에서 처리하고, `addToolResult(result)`로 결과를 모델에 반환.
- 결과를 반환하지 않으면 모델이 도구 호출 실패로 간주.

## 에이전트 도구 훅 (Agent Tool Hooks)

`createHooks`로 에이전트 레벨 훅 정의:
- `onToolStart({ agent, tool, context, args })`: 도구 시작 시
- `onToolEnd({ agent, tool, output, error, context })`: 도구 종료 시; `isAbortError(error)`로 취소 구분
- `onToolError({ tool, originalError })`: `{ output }` 반환 시 오류 페이로드 커스터마이즈 → 모델에 반환

### 태그 기반 접근 제어

- `onToolStart`에서 `tool.tags?.includes("destructive")` 등으로 태그 확인.
- `ToolDeniedError` throw 시 도구 차단 + **전체 agent operation 즉시 중단**.

## `ToolDeniedError` 정책 집행

```ts
throw new ToolDeniedError({
  toolName: tool.name,
  message: "Pro plan required",
  code: "TOOL_PLAN_REQUIRED",
  httpStatus: 402,
});
```

`isToolDeniedError(err)`로 오류 구분, `err.name`, `err.httpStatus`, `err.code`, `err.message` 접근 가능.

허용 `code` 값: `TOOL_ERROR`, `TOOL_FORBIDDEN`, `TOOL_PLAN_REQUIRED`, `TOOL_QUOTA_EXCEEDED`, 커스텀 코드(예: `"TOOL_REGION_BLOCKED"`)

## 멀티모달 도구 결과

- `toModelOutput` 함수로 이미지·미디어 콘텐츠를 LLM에 반환 가능.
- 지원 제공자: **Anthropic, OpenAI**

반환 형식:
- `{ type: "text", value: "..." }` — 텍스트
- `{ type: "json", value: {...} }` — JSON 데이터
- `{ type: "content", value: [{ type: "text", text: "..." }, { type: "media", data: base64, mediaType: "image/png" }] }` — 텍스트 + 이미지 혼합
- `{ type: "error-text", value: "Failed: ..." }` — 오류 텍스트

## 모범 사례 (Best Practices)

### 명확한 Description
- 도구명과 파라미터 description이 모델의 호출 판단 근거.
- 모호한 description("Searches things")보다 구체적인 설명("Searches the web for current information. Use when you need recent or factual information not in your training data.") 권장.
- 파라미터에도 `.describe()`로 구체적 설명 추가.

### 오류 처리
- 모델에 유용한 피드백을 제공하는 오류 메시지 작성.
- `try/catch`로 감싸고 `throw new Error('Failed to process request: ...')` 형태로 재throw.

### 타임아웃 처리
- 장시간 작업에는 `AbortController`로 타임아웃 구현.
- 부모 `abortController.signal`의 abort 이벤트를 리스닝해 자식 취소 연계.

## MCP (Model Context Protocol) 지원

- `MCPConfiguration`으로 외부 MCP 호환 서버에 연결.
- 서버 타입: `http`(URL 지정) / `stdio`(로컬 프로세스 명령 실행)
- `mcpConfig.getToolsets()` → 서버별 그룹화된 도구, `mcpConfig.getTools()` → 전체 도구 통합
- 가져온 도구를 `Agent`의 `tools` 배열에 그대로 사용 가능.
