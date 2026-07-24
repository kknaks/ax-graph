---
type: reference
title: "Mastra RequestContext — 런타임 요청별 컨텍스트 주입 가이드"
source: "https://mastra.ai/docs/server/request-context"
aliases: ["Mastra RequestContext", "Mastra 런타임 컨텍스트", "requestContextSchema", "MASTRA_RESOURCE_ID_KEY", "MASTRA_THREAD_ID_KEY"]
tags: ["Mastra", "RequestContext", "런타임컨텍스트", "에이전트프레임워크", "미들웨어", "스키마검증", "멀티테넌트", "TypeScript"]
up: ["에이전틱-ai"]
---

# Mastra RequestContext — 런타임 요청별 컨텍스트 주입 가이드

## 요약

Mastra의 [[mastra-request-context]]는 에이전트·워크플로·툴·네트워크 등 모든 프리미티브에 요청 범위 데이터를 주입하는 메커니즘이다. 런타임 조건(사용자 속성, 로케일, 실험 변형 등)에 따라 프리미티브 동작을 동적으로 분기할 수 있으며, 멀티테넌트 환경에서는 예약 키로 사용자 격리를 강제한다.

## 핵심 내용

### RequestContext 개요

[[mastra-request-context]]는 `@mastra/core/request-context`에서 임포트하는 클래스다. 에이전트 메모리(대화 히스토리·상태 지속)와는 별개로, **단일 요청 범위 내 데이터 전달**이 목적이다. [[에이전틱-ai]] 시스템에서 런타임 조건에 따라 프리미티브 동작을 바꿔야 할 때 — 사용자 속성에 따른 모델·스토리지 전환, 로케일별 instructions·툴 선택 조정 — 사용한다.

```ts
import { RequestContext } from '@mastra/core/request-context'

export type UserTier = { 'user-tier': 'enterprise' | 'pro' }

const requestContext = new RequestContext<UserTier>()
requestContext.set('user-tier', 'enterprise')
```

TypeScript 제네릭 `RequestContext<MyContext>`를 사용하면 `.set()` · `.get()` · `.keys()` · `.entries()` 모두 완전한 타입 추론을 제공한다.

### 프리미티브별 전달 방법

[[agent-workflow-조합]] 구조의 모든 진입점에 동일 requestContext 인스턴스를 전달한다.

```ts
// 에이전트
await agent.generate("...", { requestContext })

// 네트워크
routingAgent.network("...", { requestContext })

// 워크플로 시작 / 재개
await run.start({ inputData: { location: 'London' }, requestContext })
await run.resume({ resumeData: { city: 'New York' }, requestContext })

// 툴 직접 실행
await weatherTool.execute({ location: 'London' }, { requestContext })
```

[[mastra-workflows-overview]]의 `run.start()`/`run.resume()` API가 requestContext를 받아 스텝으로 전파한다.

### 서버 미들웨어 동적 설정

요청 헤더에서 정보를 추출해 requestContext에 주입하는 패턴으로, 배포 환경별 분기를 코드 변경 없이 처리한다. 예: Cloudflare `CF-IPCountry` 헤더로 `temperature-unit` 결정.

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

Best Practice: 미들웨어에서 `.set()`하는 필드를 `requestContextSchema`에 그대로 선언해 계약을 명시적·검증 가능하게 유지한다. 조건부 컨텍스트에는 `.optional()`을 사용한다.

### 에이전트에서 값 접근 — Dynamic Instructions 패턴

에이전트의 `instructions`, `model`, `tools`, `memory`, `agents`, `workflows`, `scorers`, `inputProcessors`, `outputProcessors` 옵션을 **함수로 선언**해 `requestContext`를 수신할 수 있다. `tools`를 함수로 선언하면 [[dynamic-tool-injection]] 패턴의 Mastra 구현이 된다.

```ts
export const weatherAgent = new Agent({
  instructions: async ({ requestContext }) => {
    const userTier = requestContext.get('user-tier') as UserTier['user-tier']
    const locale   = requestContext?.get('locale')
    const basePrompt = userTier === 'enterprise'
      ? 'You are a premium support agent. Provide detailed, thorough responses.'
      : 'You are a helpful assistant. Be concise and friendly.'
    const localeInstructions = locale === 'ja' ? 'Respond in Japanese using formal keigo.' : ''
    return `${basePrompt} ${localeInstructions}`.trim()
  },
  model: ({ requestContext }) => { /* ... */ },
  tools: ({ requestContext }) => { /* requestContext 기반 툴 선택 */ },
  memory: ({ requestContext }) => { /* ... */ },
})
```

Dynamic instructions 주요 패턴:
- **Personalization**: 사용자 속성·티어에 따라 instructions 개인화
- **Localization**: 로케일 기반 언어·톤 조정
- **A/B testing**: 실험 변형별 프롬프트 제공
- **External prompt management**: 프롬프트 레지스트리에서 런타임 조회 — 재배포 없이 업데이트

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

### 워크플로 스텝과 툴에서 값 접근

스텝 `execute` 함수는 `{ requestContext }` 파라미터로 값을 받는다:

```ts
const stepOne = createStep({
  id: 'step-one',
  execute: async ({ requestContext }) => {
    const userTier = requestContext.get('user-tier') as UserTier['user-tier']
    if (userTier === 'enterprise') { /* ... */ }
  },
})
```

툴 `execute`는 두 번째 `context` 파라미터 경유로 접근한다(`context?.requestContext?.get(...)`). 툴은 스키마 검증 실패 시 throw 대신 에러 객체를 반환하므로, 크리티컬한 경우 에이전트·워크플로 로직에서 명시적으로 에러 확인이 필요하다.

### 예약 키 (멀티테넌트 격리)

| 키 | 목적 |
|---|---|
| `MASTRA_RESOURCE_ID_KEY` | 모든 메모리 작업에 이 리소스 ID 강제 적용. 서버가 스레드 소유권 검증 후 미일치 시 403 반환 |
| `MASTRA_THREAD_ID_KEY` | 스레드 작업에 이 thread ID 강제 적용, 클라이언트 제공 값 override |

`mapUserToResourceId` 콜백(auth config)으로 간편하게 설정하거나, 미들웨어에서 직접 설정:

```ts
import { MASTRA_RESOURCE_ID_KEY, MASTRA_THREAD_ID_KEY } from '@mastra/core/request-context'
requestContext.set(MASTRA_RESOURCE_ID_KEY, user.id)
requestContext.set(MASTRA_THREAD_ID_KEY, threadId)
```

### 스키마 검증 (requestContextSchema)

`requestContextSchema`에 Zod·Valibot·ArkType 등 Standard JSON Schema 호환 스키마를 정의해 런타임 검증을 수행한다. 컴포넌트마다 검증 시점과 실패 동작이 다르다:

| 컴포넌트 | 검증 시점 | 실패 시 동작 |
|---|---|---|
| **Agent** | `generate()`/`stream()` 시작 시 | `MastraError` throw |
| **Tool** | `execute()` 실행 전 | 에러 객체 반환 |
| **Workflow** | `run.start()` 시작 시 | `Error` throw |
| **Step** | 스텝 `execute()` 실행 전 | 스텝 실패 |

```ts
export const validatedAgent = new Agent({
  requestContextSchema: z.object({ userId: z.string(), apiKey: z.string() }),
  instructions: ({ requestContext }) => {
    const { userId, apiKey } = requestContext.all
    return `You are helping user ${userId}`
  },
})
// 검증 실패 시:
// Request context validation failed for agent 'validated-agent':
// - apiKey: Required
```

워크플로와 스텝 간 스키마를 공유해 일관성을 유지할 수 있으며, 스텝마다 개별 스키마 정의도 가능하다.

### Studio 프리셋

`mastra dev --request-context-presets ./presets.json` 플래그로 Named 프리셋을 로드하면 Studio UI에 드롭다운이 추가되어 요청 컨텍스트 설정을 전환할 수 있다. 수동 JSON 편집 시 드롭다운이 "Custom"으로 전환된다.

```json
{
  "development": { "userId": "dev-user", "env": "development" },
  "production":  { "userId": "prod-user", "env": "production" }
}
```

## 연결

- [[에이전틱-ai]] — 에이전틱 AI 프리미티브 전반의 SoT; up 노드
- [[mastra-request-context]] — RequestContext 개념 상세의 SoT 위임
- [[agent-workflow-조합]] — RequestContext가 에이전트·워크플로·툴 모든 조합 진입점에 걸쳐 전달됨
- [[mastra-workflows-overview]] — run.start()/run.resume()에 requestContext 파라미터를 전달하는 워크플로우 실행 레퍼런스
- [[dynamic-tool-injection]] — tools 옵션을 함수로 선언해 requestContext 기반 동적 툴 주입 — DTI 패턴의 Mastra 구현
