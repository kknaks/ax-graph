---
type: summary
title: Mastra RequestContext — 런타임 요청별 컨텍스트 주입 가이드
source_url: https://mastra.ai/docs/server/request-context
tags:
- Mastra
- RequestContext
- 런타임 컨텍스트
- 미들웨어
- 에이전트
- 워크플로
- 툴
- 스키마 검증
- 멀티테넌트
- TypeScript
summarized_at: '2026-07-10T11:59:57.418172+00:00'
---

## RequestContext 개요

- **RequestContext**는 `@mastra/core/request-context`에서 임포트하는 클래스
- 에이전트(Agent), 네트워크(Network), 워크플로(Workflow), 툴(Tool) 등 모든 Mastra 프리미티브에 요청별 값을 전달하는 수단
- 에이전트 메모리(대화 히스토리·상태 지속)와는 별개 개념 — 단일 요청 범위 내 데이터 전달이 목적

## 언제 사용하는가

- 런타임 조건에 따라 프리미티브 동작을 바꿔야 할 때
  - 사용자 속성에 따라 모델이나 스토리지 백엔드를 전환
  - 언어/로케일에 따라 instructions·툴 선택 조정

## 값 설정 (Setting values)

### 기본 사용법

```ts
import { RequestContext } from '@mastra/core/request-context'

export type UserTier = { 'user-tier': 'enterprise' | 'pro' }

const requestContext = new RequestContext<UserTier>()
requestContext.set('user-tier', 'enterprise')
```

- `.set(key, value)`: 키-값 쌍 등록
- `.get(key)`: 값 읽기

### 에이전트·네트워크·워크플로·툴에 전달

```ts
// 에이전트
await agent.generate("...", { requestContext })

// 네트워크
routingAgent.network("...", { requestContext })

// 워크플로 시작
await run.start({ inputData: { location: 'London' }, requestContext })

// 워크플로 재개
await run.resume({ resumeData: { city: 'New York' }, requestContext })

// 툴 직접 실행
await weatherTool.execute({ location: 'London' }, { requestContext })
```

### 서버 미들웨어에서 동적 설정

- 요청 헤더에서 정보를 추출해 requestContext에 주입
- 예시: Cloudflare `CF-IPCountry` 헤더로 `temperature-unit` 결정

```ts
server: {
  middleware: [
    async (context, next) => {
      const country = context.req.header('CF-IPCountry')
      const requestContext = context.get('requestContext')
      requestContext.set('temperature-unit', country === 'US' ? 'fahrenheit' : 'celsius')
      await next()
    },
  ],
}
```

## Studio에서 프리셋 사용

- `mastra dev --request-context-presets ./presets.json` 플래그로 Named 프리셋 로드
- Studio UI에 드롭다운이 추가되어 설정 전환 가능
- 수동으로 JSON 편집 시 드롭다운이 "Custom"으로 전환

```json
{
  "development": { "userId": "dev-user", "env": "development" },
  "production":  { "userId": "prod-user", "env": "production" }
}
```

## 에이전트에서 값 접근

- `instructions`, `model`, `tools`, `memory`, `agents`, `workflows`, `scorers`, `inputProcessors`, `outputProcessors` 옵션을 함수로 선언해 `requestContext` 수신 가능

```ts
export const weatherAgent = new Agent({
  instructions: async ({ requestContext }) => {
    const userTier = requestContext.get('user-tier') as UserTier['user-tier']
    if (userTier === 'enterprise') { /* ... */ }
  },
  model: ({ requestContext }) => { /* ... */ },
  tools: ({ requestContext }) => { /* ... */ },
  memory: ({ requestContext }) => { /* ... */ },
})
```

### Dynamic instructions 패턴

- **Personalization**: 사용자 속성·티어에 따라 instructions 개인화
- **Localization**: 로케일 기반 언어·톤 조정
- **A/B testing**: 실험 변형별 프롬프트 제공
- **External prompt management**: 프롬프트 레지스트리에서 런타임 조회 (재배포 없이 업데이트)

```ts
instructions: async ({ requestContext }) => {
  const userTier = requestContext?.get('user-tier')
  const locale   = requestContext?.get('locale')
  const basePrompt = userTier === 'enterprise'
    ? 'You are a premium support agent. Provide detailed, thorough responses.'
    : 'You are a helpful assistant. Be concise and friendly.'
  const localeInstructions = locale === 'ja' ? 'Respond in Japanese using formal keigo.' : ''
  return `${basePrompt} ${localeInstructions}`.trim()
}
```

#### 프롬프트 레지스트리 연동 예시

```ts
instructions: async ({ requestContext }) => {
  const prompt = await promptRegistry.getPrompt({
    promptId: 'customer-support-agent',
    variant: requestContext?.get('experiment-variant'),
    userId:  requestContext?.get('user-id'),
  })
  return prompt.content
}
```

## 워크플로 스텝에서 값 접근

```ts
const stepOne = createStep({
  id: 'step-one',
  execute: async ({ requestContext }) => {
    const userTier = requestContext.get('user-tier') as UserTier['user-tier']
    if (userTier === 'enterprise') { /* ... */ }
  },
})
```

## 툴에서 값 접근

```ts
export const weatherTool = createTool({
  id: 'weather-tool',
  execute: async (inputData, context) => {
    const userTier = context?.requestContext?.get('user-tier') as UserTier['user-tier'] | undefined
    if (userTier === 'enterprise') { /* ... */ }
  },
})
```

## 예약 키 (Reserved keys)

| 키 | 목적 |
|---|---|
| **MASTRA_RESOURCE_ID_KEY** | 모든 메모리 작업에 이 리소스 ID 강제 적용. 서버가 스레드 소유권 검증 후 미일치 시 403 반환 |
| **MASTRA_THREAD_ID_KEY** | 스레드 작업에 이 thread ID 강제 적용, 클라이언트 제공 값 override |

- `mapUserToResourceId` 콜백(auth config)으로 간편하게 설정 가능
- 미들웨어에서 직접 설정도 가능

```ts
import { MASTRA_RESOURCE_ID_KEY, MASTRA_THREAD_ID_KEY } from '@mastra/core/request-context'
requestContext.set(MASTRA_RESOURCE_ID_KEY, user.id)
requestContext.set(MASTRA_THREAD_ID_KEY, threadId)
```

## TypeScript 지원

- 제네릭 타입 파라미터 `RequestContext<MyContext>` 제공 시 `.set()` · `.get()` · `.keys()` · `.entries()` 모두 완전 타입 추론

```ts
type MyContext = { userId: string; maxTokens: number; isPremium: boolean }
const ctx = new RequestContext<MyContext>()
ctx.set('maxTokens', 4096)   // ✓
ctx.set('maxTokens', 'wrong') // ✗ TypeScript error
const tokens = ctx.get('maxTokens') // number로 추론
```

## 스키마 검증 (Schema validation)

`requestContextSchema`에 Zod·Valibot·ArkType 등 Standard JSON Schema 호환 스키마를 정의해 런타임 검증 수행

### 컴포넌트별 검증 동작

| 컴포넌트 | 속성 | 검증 시점 | 실패 시 동작 |
|---|---|---|---|
| **Agent** | `requestContextSchema` | `generate()`/`stream()` 시작 시 | `MastraError` throw |
| **Tool** | `requestContextSchema` | `execute()` 실행 전 | 에러 객체 반환 |
| **Workflow** | `requestContextSchema` | `run.start()` 시작 시 | `Error` throw |
| **Step** | `requestContextSchema` | 스텝 `execute()` 실행 전 | 스텝 실패 |

### 에이전트 스키마 검증 예시

```ts
export const validatedAgent = new Agent({
  requestContextSchema: z.object({ userId: z.string(), apiKey: z.string() }),
  instructions: ({ requestContext }) => {
    const { userId, apiKey } = requestContext.all  // { userId: string; apiKey: string }
    return `You are helping user ${userId}`
  },
})
// 검증 실패 시:
// Request context validation failed for agent 'validated-agent':
// - apiKey: Required
```

### 툴 스키마 검증 예시

```ts
// 검증 실패 시 throw 대신 에러 객체 반환:
{
  "error": true,
  "message": "Request context validation failed for validated-tool. ..."
}
```

### 워크플로 스키마 검증 예시

- 스키마를 워크플로와 스텝 간에 공유해 일관성 유지
- 스텝에도 개별 `requestContextSchema` 정의 가능 (스텝 레벨 검증)

## Best Practices

1. **미들웨어와 스키마를 일치시킬 것**: 미들웨어에서 set하는 필드를 `requestContextSchema`에 그대로 선언해 계약을 명시적·검증 가능하게 유지
2. **조건부 컨텍스트에는 `.optional()` 사용**: 항상 존재하지 않는 값은 optional 처리
3. **툴 검증 에러 처리**: 툴은 throw 대신 에러 객체를 반환하므로, 툴 실행이 크리티컬한 경우 에이전트·워크플로 로직에서 명시적으로 에러 확인 필요
