---
type: reference
title: "AgentKit Human in the Loop — Inngest waitForEvent 기반 인간 개입 도구 구현"
source: "https://agentkit.inngest.com/advanced-patterns/human-in-the-loop"
aliases: ["AgentKit HITL", "Inngest waitForEvent HITL", "AgentKit 인간 개입 도구"]
tags: ["AgentKit", "Inngest", "Human-in-the-Loop", "waitForEvent", "에이전트-워크플로우", "createTool"]
up: ["hitl-승인-패턴", "에이전틱-ai"]
---

# AgentKit Human in the Loop — Inngest waitForEvent 기반 인간 개입 도구 구현

## 요약

AgentKit과 Inngest를 결합해 에이전트 실행 중 인간 입력을 기다리는 도구를 만드는 방법을 다룬 공식 문서다. Inngest의 `step.waitForEvent()`가 핵심 메커니즘으로, 지정 이벤트가 수신될 때까지 에이전트 네트워크 실행 전체를 일시 정지한다. [[hitl-승인-패턴]]의 이벤트 기반 구현 레퍼런스로 활용할 수 있다.

## 핵심 내용

### Human in the Loop 도구 생성 — `createTool` + `step.waitForEvent`

`createTool()`로 `ask_developer` 도구를 정의하고, handler 내부에서 `step.waitForEvent()`를 호출한다. [[hitl-승인-패턴]]의 툴 레벨 승인 변형에 해당하되, suspend/resume 대신 **이벤트 수신 대기** 방식을 사용한다는 점이 다르다.

```ts
import { createTool } from "@inngest/agent-kit";

createTool({
  name: "ask_developer",
  description: "Ask a developer for input on a technical issue",
  parameters: z.object({
    question: z.string().describe("The technical question for the developer"),
    context: z.string().describe("Additional context about the issue"),
  }),
  handler: async ({ question, context }, { step }) => {
    if (!step) {
      return { error: "This tool requires step context" };
    }
    const developerResponse = await step.waitForEvent("developer.response", {
      event: "app/support.ticket.developer-response",
      timeout: "4h",
      match: "data.ticketId",
    });
    if (!developerResponse) {
      return { error: "No developer response provided" };
    }
    return {
      developerResponse: developerResponse.data.answer,
      responseTime: developerResponse.data.timestamp,
    };
  },
});
```

동작 방식:
- `ask_developer` 도구가 호출되면 **최대 4시간** 동안 `"app/support.ticket.developer-response"` 이벤트를 기다린다.
- 대기 중에는 **AgentKit 네트워크 실행 전체가 일시 정지**된다.
- `match: "data.ticketId"` 옵션으로 트리거 이벤트의 `ticketId`와 응답 이벤트를 매칭해 올바른 워크플로우에만 응답이 전달된다.
- `step` 컨텍스트가 없으면 오류를 반환하도록 방어 처리한다.

### AgentKit 네트워크를 Inngest 함수로 래핑

`waitForEvent`의 이벤트 매칭이 동작하려면 AgentKit 네트워크를 반드시 Inngest 함수로 감싸야 한다. 3단계로 구성된다.

**1단계 — Inngest 클라이언트 생성**
```ts
import { Inngest } from "inngest";
const inngest = new Inngest({ id: "my-agentkit-network" });
```

**2단계 — 네트워크를 Inngest 함수로 래핑**
```ts
const supportAgentWorkflow = inngest.createFunction(
  { id: "support-agent-workflow" },
  { event: "app/support.ticket.created" },
  async ({ step, event }) => {
    const ticket = await step.run("get_ticket_details", async () => {
      return await getTicketDetails(event.data.ticketId);
    });
    if (!ticket || "error" in ticket) {
      throw new NonRetriableError(`Ticket not found: ${ticket.error}`);
    }
    const response = await supportNetwork.run(ticket.title);
    return { response, ticket };
  }
);
```
트리거 이벤트 `"app/support.ticket.created"`는 반드시 `data.ticketId` 필드를 포함해야 한다. `ask_developer`의 `waitForEvent`가 이 값을 기준으로 응답 이벤트를 매칭한다.

**3단계 — 서버 등록**
```ts
const server = createServer({
  functions: [supportAgentWorkflow as any],
});
server.listen(3010, () => console.log("Support Agent demo server is running on port 3010"));
```

### 예시: Support Agent 네트워크 구성

고객지원 에이전트 네트워크 예시(`examples/support-agent-human-in-the-loop`):

| 에이전트 | 역할 | 사용 도구 |
|---|---|---|
| Customer Support Agent | 일반 고객 문의 처리 | `searchKnowledgeBase` |
| Technical Support Agent | 중요 티켓 처리, 복잡한 문제 시 개발자 질의 | `searchLatestReleaseNotes`, `ask_developer` |
| Supervisor Routing Agent | 티켓을 적절한 에이전트로 라우팅 | `createRoutingAgent` |

모든 에이전트는 `claude-3-5-haiku-latest` 모델, `max_tokens: 1000` 설정을 공유한다.

### 전체 실행 흐름

1. `"app/support.ticket.created"` 이벤트 발생 → Inngest 함수 트리거
2. Inngest 함수 내에서 `supportNetwork.run()` 실행 → 에이전트 네트워크 동작
3. Technical Support Agent가 복잡한 문제 감지 → `ask_developer` 도구 호출
4. `step.waitForEvent()`로 실행 일시 정지, 개발자에게 알림(예: Slack) 전송
5. 개발자가 `"app/support.ticket.developer-response"` 이벤트 전송
6. `ticketId` 매칭 성공 → 에이전트 실행 재개, 개발자 답변을 컨텍스트로 활용

## 연결

- [[hitl-승인-패턴]] — 이 문서가 구현하는 HITL 툴 레벨 승인 패턴의 개념 SoT; up 노드이며 Inngest waitForEvent 방식이 패턴의 이벤트 기반 변형에 해당
- [[에이전틱-ai]] — AgentKit 에이전트 네트워크가 에이전틱 AI 패러다임 위에서 동작하는 구현체; up 노드
- [[agent-workflow-조합]] — Inngest 함수로 에이전트 네트워크를 감싸는 구조가 에이전트·워크플로우 조합 패턴에 해당
- [[mastra-workflows-overview]] — Mastra 워크플로우도 Inngest를 외부 workflow runner로 지원하며, waitForEvent와 suspend/resume은 다른 프레임워크의 유사 HITL 메커니즘으로 비교 대상
