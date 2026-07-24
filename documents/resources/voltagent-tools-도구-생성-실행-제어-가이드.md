---
type: reference
title: "VoltAgent Tools — 에이전트 도구 생성·실행·제어 완전 가이드"
source: "https://voltagent.dev/docs/agents/tools/"
aliases: ["VoltAgent 도구 가이드", "VoltAgent createTool", "VoltAgent 툴 시스템"]
tags: ["VoltAgent", "AI-Agent", "tool-use", "createTool", "needsApproval", "MCP", "docs", "LLM-tooling"]
up: ["에이전틱-ai"]
---

# VoltAgent Tools — 에이전트 도구 생성·실행·제어 완전 가이드

## 요약

VoltAgent의 공식 도구(Tool) 레퍼런스 문서다. `createTool`로 Zod 타입 안전 도구를 정의하는 기본부터 훅·승인 흐름·취소·멀티모달 결과·MCP 연동까지 도구 생태계 전반을 다룬다. 모델이 `description`을 보고 호출 시점을 스스로 결정하는 구조가 핵심이며, `ToolDeniedError`와 태그 기반 접근 제어로 정책 집행도 구현할 수 있다.

## 핵심 내용

### 도구 개요

도구(Tool)는 에이전트가 외부 시스템·API·데이터베이스와 상호작용하거나 텍스트 생성 이상의 작업을 수행하게 한다. 모델은 도구의 `description`과 현재 컨텍스트를 보고 **언제 도구를 호출할지 스스로 결정**한다.

### 도구 생성 (`createTool`)

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

필수/선택 필드:
- **`name`**: 고유 식별자
- **`description`**: 모델이 호출 시점 결정에 사용 — 구체적일수록 호출 정확도 향상
- **`parameters`**: Zod 스키마로 입력 정의 (타입 자동 추론, IntelliSense 지원)
- **`execute`**: 도구 실행 함수
- `providerOptions` (선택): Anthropic 캐시 컨트롤(`type: "ephemeral"`) 등 제공자별 고급 옵션 — 반복 도구 호출 시 비용·레이턴시 절감
- `tags` (선택): 조직화·레이블링용 문자열 배열

에이전트에 도구를 연결할 때는 `tools` 배열로 전달하며, 여러 도구를 동시에 주면 모델이 복합 쿼리에서 조합 사용한다.

### 동적 도구 등록

[[dynamic-tool-injection]] 패턴의 VoltAgent 구현체다. 두 가지 API를 지원한다.

- **런타임 추가**: `agent.addTools([calculatorTool])` — 에이전트 생성 후 툴 추가
- **요청별 주입**: `agent.generateText("...", { tools: [calculatorTool] })` — 특정 요청에만 툴 한정 제공

### 도구 훅 (Tool Hooks)

도구별로 `onStart`·`onEnd` 훅을 붙여 실행 관찰 또는 결과 후처리가 가능하다.

- **훅 실행 순서**: tool-level 훅 → agent-level `onToolEnd` (agent 훅이 이후에 오버라이드 가능)
- `onEnd`에서 `{ output }` 반환 시 결과 오버라이드 가능; `outputSchema`가 있으면 재검증됨
- 스트리밍 도구(AsyncIterable)에서는 오버라이드가 **최종 출력에만** 적용됨

파라미터: `onStart`는 `{ tool, args, options }`, `onEnd`는 `{ tool, args, output, error, options }`.

에이전트 레벨 훅(`createHooks`)도 지원한다:
- `onToolStart({ agent, tool, context, args })`: 도구 시작 시
- `onToolEnd({ agent, tool, output, error, context })`: 도구 종료 시; `isAbortError(error)`로 취소 구분
- `onToolError({ tool, originalError })`: `{ output }` 반환 시 오류 페이로드 커스터마이즈

### 스트리밍 도구 결과

`execute`에서 `AsyncIterable`을 반환하면 각 `yield` 값이 중간(preliminary) 결과로 emit된다. **마지막 yield 값**이 최종 결과로 처리되며, 진행 상태나 중간 상태를 UI에 스트리밍할 때 유용하다. `outputSchema`로 `z.discriminatedUnion` 등 복합 스키마도 사용 가능하다.

### 도구 태그와 정책 집행

선택적 문자열 레이블(`"database"`, `"read-only"`, `"destructive"` 등)로 도구를 분류한다. OpenTelemetry 스팬과 VoltAgent 옵저버빌리티 대시보드, REST 엔드포인트(`GET /tools`, `POST /tools/:name/execute`) 응답에도 포함되어 프론트엔드 액세스 제어 구현이 가능하다.

`onToolStart` 훅에서 `tool.tags?.includes("destructive")`를 확인해 `ToolDeniedError`를 던지면 해당 도구를 차단하고 **전체 agent operation을 즉시 중단**할 수 있다.

```ts
throw new ToolDeniedError({
  toolName: tool.name,
  message: "Pro plan required",
  code: "TOOL_PLAN_REQUIRED",
  httpStatus: 402,
});
```

허용 `code` 값: `TOOL_ERROR`, `TOOL_FORBIDDEN`, `TOOL_PLAN_REQUIRED`, `TOOL_QUOTA_EXCEEDED`, 커스텀 코드. `isToolDeniedError(err)`로 구분, `err.httpStatus`·`err.code`·`err.message` 접근 가능.

### 도구 실행 승인 (`needsApproval`)

[[hitl-승인-패턴]]의 VoltAgent 구현이다. 민감한 작업(결제·파일 변경·명령 실행 등) 도구에 적용한다.

```ts
// 불리언 또는 조건 함수로 지정
needsApproval: true
needsApproval: async ({ amount }) => amount > 1000
```

승인 플로우:
1. 모델이 `needsApproval` 도구 호출
2. VoltAgent가 `state: "approval-requested"` 도구 파트 반환 (실행 안 함)
3. UI가 사용자에게 승인/거부 요청
4. VoltAgent에 승인 응답 전송
5. 승인 시 도구 실행; 거부 시 모델이 거부 결과를 확인 후 응답

UI에서는 `useChat`의 `addToolApprovalResponse({ id, approved, reason? })`로 승인/거부 응답을 전송한다.

### 클라이언트 사이드 도구

`execute` 함수가 없는 도구는 자동으로 클라이언트 사이드 도구가 된다. 브라우저 API(위치 정보, 클립보드 등) 접근에 적합하며, `useChat`의 `onToolCall` 콜백에서 처리하고 `addToolResult(result)`로 결과를 모델에 반환한다. 결과를 반환하지 않으면 모델이 도구 호출 실패로 간주한다.

### 실행 컨텍스트 접근 (`ToolExecuteOptions`)

`execute(args, options)` 두 번째 파라미터로 실행 컨텍스트에 접근한다.

**`toolContext`** (VoltAgent 에이전트에서 호출 시 항상 존재; MCP 등 외부에서는 `undefined`일 수 있음):
- `toolContext.callId`: 이 특정 호출의 고유 ID (AI SDK 제공)
- `toolContext.messages`: 도구 호출 시점의 메시지 히스토리
- `toolContext.abortSignal`: 취소 감지용 AbortSignal

**`OperationContext` 필드** (options에 직접):
- `operationId`, `userId`, `conversationId`: 식별자
- `workspace`: 에이전트에 설정된 워크스페이스 인스턴스
- `abortController`: operation 취소용 AbortController
- `logger`, `traceContext`: 실행 범위 로거·OpenTelemetry 트레이스
- `isActive`: operation 활성 여부
- `elicitation`: 사용자 입력 요청 함수 (선택)

### 취소 (AbortController)

`options.abortController.signal`을 fetch 등에 전달해 취소를 지원한다. 도구 내부에서 `abortController.abort(reason)`을 호출해 **전체 operation을 취소**할 수도 있다. 에이전트 호출 시 `{ abortSignal: controller.signal }` 전달, `isAbortError(err)`로 취소 오류를 구분한다.

### 멀티모달 도구 결과

`toModelOutput` 함수로 이미지·미디어 콘텐츠를 LLM에 반환할 수 있다 (지원 제공자: Anthropic, OpenAI).

반환 형식:
- `{ type: "text", value: "..." }` — 텍스트
- `{ type: "json", value: {...} }` — JSON 데이터
- `{ type: "content", value: [{ type: "text", text: "..." }, { type: "media", data: base64, mediaType: "image/png" }] }` — 텍스트+이미지 혼합
- `{ type: "error-text", value: "..." }` — 오류 텍스트

### MCP (Model Context Protocol) 연동

`MCPConfiguration`으로 외부 MCP 호환 서버에 연결한다. 서버 타입: `http`(URL 지정) / `stdio`(로컬 프로세스 명령 실행). `mcpConfig.getToolsets()`로 서버별 그룹화된 도구, `mcpConfig.getTools()`로 전체 통합 도구를 가져와 `Agent`의 `tools` 배열에 그대로 사용한다.

### 모범 사례

- **명확한 Description**: "Searches things"보다 "Searches the web for current information. Use when you need recent or factual information not in your training data." 형태로 구체화. 파라미터에도 `.describe()`로 설명 추가
- **오류 처리**: `try/catch`로 감싸고 모델에 유용한 피드백을 제공하는 오류 메시지 작성
- **타임아웃 처리**: 장시간 작업에는 `AbortController`로 타임아웃 구현; 부모 signal의 abort 이벤트를 리스닝해 자식 취소 연계

## 연결

- [[에이전틱-ai]] — 도구 호출 루프가 에이전틱 AI의 핵심 실행 메커니즘; up 노드
- [[dynamic-tool-injection]] — VoltAgent의 `addTools`·per-request tools가 동적 툴 주입 패턴의 구체적 API 구현체
- [[hitl-승인-패턴]] — `needsApproval` 메커니즘(불리언·조건 함수·5단계 승인 플로우)이 이 패턴의 VoltAgent 구현체
- [[voltagent-워크플로우-suspend-resume-cancellation]] — VoltAgent 내 취소(AbortController) 메커니즘과 워크플로우 suspend/resume이 동일 operation 생명주기를 공유
