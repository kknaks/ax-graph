---
type: summary
title: AgentKit Human in the Loop — Inngest waitForEvent 기반 인간 개입 도구 구현
source_url: https://agentkit.inngest.com/advanced-patterns/human-in-the-loop
tags:
- AgentKit
- Inngest
- Human in the Loop
- waitForEvent
- 에이전트 네트워크
- createTool
- Support Agent
- step context
- 이벤트 매칭
- 워크플로우 자동화
summarized_at: '2026-07-10T12:00:30.628180+00:00'
---

## Human in the Loop 개요

- **Support Agent, Coding Agent, Research Agent** 등은 인간 감독(human oversight)이 필요한 경우가 있다.
- **AgentKit**과 **Inngest**를 결합하면 인간 입력을 기다리는 Tool을 생성할 수 있다.
- 핵심 메커니즘: Inngest의 `step.waitForEvent()` step 메서드.

---

## "Human in the Loop" 도구 생성

### 기본 구현 패턴

`createTool()`로 `ask_developer` 도구를 정의한다:

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
    // 예: 개발자에게 Slack 메시지 전송
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

### 동작 방식

- `ask_developer` 도구는 **최대 4시간** 동안 `"developer.response"` 이벤트를 기다린다.
- 대기 중에는 **AgentKit 네트워크 실행이 일시 정지**된다.
- 수신된 응답 이벤트는 **`data.ticketId` 필드**를 기준으로 트리거 이벤트와 매칭된다.
- 이 매칭 동작을 위해 AgentKit 네트워크는 반드시 **Inngest 함수로 감싸야** 한다.

---

## 예시: Human in the Loop가 포함된 Support Agent 네트워크

### 에이전트 구성

- **Customer Support Agent**: 고객 문의 처리, `searchKnowledgeBase` 도구 사용.
- **Technical Support Agent**: 중요 티켓 처리, `searchLatestReleaseNotes` 도구 사용. 개발자 입력이 필요하면 `ask_developer` 도구 사용.
- **Supervisor Routing Agent** (`createRoutingAgent`): 티켓을 적절한 에이전트로 라우팅.
- 모델: 모두 `claude-3-5-haiku-latest` 사용, `max_tokens: 1000`.
- 완성 예제 코드 위치: `examples/support-agent-human-in-the-loop` 디렉토리.

---

## AgentKit 네트워크를 Inngest 함수로 변환하는 방법

### 1단계: Inngest 클라이언트 생성

```ts
import { Inngest } from "inngest";

const inngest = new Inngest({ id: "my-agentkit-network" });
```

### 2단계: 네트워크를 Inngest 함수로 래핑

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

### 3단계: 서버 등록

```ts
const server = createServer({
  functions: [supportAgentWorkflow as any],
});
server.listen(3010, () => console.log("Support Agent demo server is running on port 3010"));
```

### 주요 포인트

- `network.run()`은 이제 Inngest 함수 내에서 실행된다.
- 트리거 이벤트 `"app/support.ticket.created"`는 **`data.ticketId`** 필드를 포함해야 한다.
- `ask_developer` 도구의 `waitForEvent`는 이 `ticketId`를 기준으로 응답 이벤트를 매칭한다.
- `createServer`의 `functions` 프로퍼티에 함수를 반드시 등록해야 한다.

---

## 전체 흐름 요약

1. `"app/support.ticket.created"` 이벤트 발생 → Inngest 함수 트리거.
2. Inngest 함수 내에서 `supportNetwork.run()` 실행 → 에이전트 네트워크 동작.
3. **Technical Support Agent**가 복잡한 문제 감지 → `ask_developer` 도구 호출.
4. `step.waitForEvent()`로 실행 일시 정지, 개발자에게 알림(예: Slack) 전송.
5. 개발자가 응답 이벤트(`"app/support.ticket.developer-response"`) 전송.
6. `ticketId` 매칭 성공 → 에이전트 실행 재개, 개발자 답변을 컨텍스트로 활용.

---

## 참고

- 추가 세부 사항 및 예시: Inngest 공식 `step.waitForEvent()` 문서 참조.
