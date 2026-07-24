---
type: concept
title: "HITL 승인 위치 패턴"
aliases: ["Human-in-the-Loop 승인 패턴", "툴 레벨 승인", "워크플로 스텝 승인", "HITL placement pattern"]
tags: ["HITL", "Human-in-the-Loop", "승인 패턴", "agentic-application", "suspend-resume", "createStep", "Mastra", "VoltAgent", "Inngest", "waitForEvent", "n8n", "openai-agents-sdk", "interruptions", "RunState"]
up: ["agent-workflow-조합"]
---

# HITL 승인 위치 패턴

## 정의

agentic 시스템에서 사람의 승인을 삽입하는 위치를 결정하는 설계 패턴 집합 — 에이전트 툴 호출 전 또는 워크플로 스텝 내부에 승인 게이트를 두는 4가지 변형으로 구성된다.

## 맥락

[[agent-workflow-조합]] 구조에서 HITL을 구현할 때 "언제"가 아닌 "어디에" 승인을 넣을지가 핵심 설계 결정이다. 패턴 선택은 두 기준으로 한다: (1) 위험이 어디에 있는가, (2) 사람이 합리적으로 판단할 수 있는 시점이 언제인가.

4가지 패턴:

| 패턴 | 진입점 | 승인 위치 | 적합 상황 | 트레이드오프 |
|---|---|---|---|---|
| 툴 레벨 승인 | 에이전트 | 툴 호출 전 | 툴 호출 자체가 위험한 행위 | 워크플로 이력에 승인 기록 안 됨 |
| 워크플로 레벨 승인 | 에이전트 | 워크플로 스텝 내부 | 위험이 스텝 안에 있고 컨텍스트 수집이 필요할 때 | 툴은 이미 실행된 상태에서 승인 |
| 스텝 내 에이전트 호출 | 워크플로 | 스텝 suspend 후 `agent.generate()` | 에이전트 호출을 세밀하게 제어할 때 | 에이전트 호출이 스텝 내부에 은닉되어 트레이스 어려움 |
| 에이전트 as 스텝 (`createStep`) | 워크플로 | 승인 스텝 suspend → `.map()` → 에이전트 스텝 | 가시성과 명확한 분리가 필요할 때 | 스텝 수 증가, `.map()` 데이터 변환 필요 |

다층 승인(Layered approval)은 넓은 결정과 특정 고위험 행위를 별도로 확인할 때 강력하지만 사용자 피로를 유발할 수 있다. 승인이 워크플로 상태에 의존하는데 아직 아무것도 실행되지 않았다면 설계를 재검토해야 한다는 신호다.

### 워크플로 suspend/resume 구현 메커니즘

워크플로 스텝 내 HITL 승인은 `suspend()`/`resume()` 메커니즘으로 구현된다. 스텝 `execute` 함수 안에서 사용할 수 있는 핵심 변수:

- **`resumeData`**: resume 시 전달된 승인 데이터 (첫 실행 시 undefined) — `if (resumeData) return ...` 패턴으로 resume 케이스를 먼저 처리하고 아니면 `suspend` 호출
- **`suspendData`**: `suspend(data)` 인자로 중단 시점에 저장하는 데이터 (검증 코드, 만료 시각 등). 재개 시 자동으로 채워진다
- **`resumeSchema`** (Zod): resume 시 받을 데이터를 타입 체크. 워크플로우 레벨 또는 스텝 레벨에 각각 독립 지정 가능해, 다단계 승인 워크플로우에서 스텝마다 다른 입력 타입을 강제할 수 있다

공통 구현 패턴:
- **Auto-Approve 패턴**: 조건 충족 시(소액 등) `suspend` 없이 즉시 반환, 아니면 suspend. VoltAgent 빠른 시작 데모([[voltagent-빠른시작-데모-에이전트-워크플로우-voltops]])에서는 $500 임계값을 기준으로 미만이면 자동 승인, 초과면 `suspend(비용 상세)`로 매니저 승인을 대기하는 비용 승인 워크플로우(`createWorkflowChain`)로 이 패턴을 구체적으로 구현한다. VoltOps 타임라인은 `suspend` → `resume` 각 이벤트를 단계별로 시각화하여 HITL 워크플로우 디버깅 효율을 높인다.
- **Timeout 패턴**: `suspendData.expiresAt`에 만료 시각 저장 → resume 시 현재 시각과 비교해 만료 분기 → `"expired"` / `"completed"` / `"cancelled"` 반환

**중단 스텝 식별**: 실행 결과의 `result.status === 'suspended'`로 중단 여부를 확인하고, `result.suspended` 배열로 중단된 스텝 경로를 얻어 `resume({ step: result.suspended[0], ... })`에 직접 전달한다.

**스토리지에서 중단 실행 복구** (Mastra): `workflow.getWorkflowRunById(runId)`로 저장된 실행 상태를 가져온 뒤, `createWorkflowStateReader(state)`로 리더를 만들어 `getSuspendedStep()`·`getResumeLabel(label)` API를 통해 재개 경로와 foreach 인덱스를 추출한다. 원시 스냅샷을 직접 파싱할 필요 없이 구조화된 방식으로 중단 실행을 복구할 수 있다.

**sleep vs suspend 구분**: `sleep(ms)`/`sleepUntil(date)`는 워크플로우 레벨에서 상태를 `waiting`으로 설정하고 시간이 지나면 자동 재개된다. `suspend()`는 스텝 레벨에서 상태를 `suspended`로 설정하며 명시적 `resume()` 호출이 있어야만 재개된다 — 두 메커니즘은 서로 다르다.

### 이벤트 기반 HITL — Inngest `step.waitForEvent`

suspend/resume과 달리, Inngest 기반 에이전트 네트워크에서는 **외부 이벤트 수신**으로 HITL을 구현한다. [[agentkit-human-in-the-loop-inngest-waitforevent]] 참조.

- `createTool()`로 정의한 도구의 handler 안에서 `step.waitForEvent(label, { event, timeout, match })`를 호출하면 에이전트 네트워크 실행이 일시 정지된다.
- **`match` 옵션**: 트리거 이벤트와 응답 이벤트를 공통 필드(예: `"data.ticketId"`)로 매칭해 여러 동시 실행 워크플로우에 올바른 응답이 전달되도록 보장한다.
- **Timeout**: `"4h"` 등 문자열로 지정. 시간 내 이벤트가 수신되지 않으면 `null` 반환.
- 이 방식은 명시적 `resume()` 호출 없이 외부 이벤트 전송만으로 재개된다는 점에서 suspend/resume과 구별된다.
- AgentKit 네트워크는 반드시 Inngest 함수로 감싸야(`inngest.createFunction`) 이벤트 매칭이 동작한다.

### 플랫폼 내장형 HITL — n8n

n8n은 코드 없이 워크플로우 빌더 UI에서 HITL을 구성하는 **플랫폼 내장형 접근**이다. [[n8n-ai-에이전트-hitl-도구-승인]] 참조.

- AI 에이전트 노드의 **Human review** 섹션에서 승인 채널(Slack, Telegram, Discord, Teams, Gmail 등 9종)과 자격증명을 설정한다.
- 승인이 필요한 도구를 human review 단계의 tool 커넥터에 연결하면, 도구 실행 전 워크플로우가 자동 일시 중지되고 검토자에게 요청이 전송된다.
- **`$tool` 변수**: `$tool.name`(도구 이름)·`$tool.parameters`(AI가 전달하려는 파라미터)로 검토자에게 맥락 메시지를 구성한다. `$fromAI()` 함수로 동적으로 설정된 파라미터도 그대로 표시된다.
- **시스템 프롬프트 권장**: AI가 거부를 올바르게 처리하려면 어떤 도구가 승인을 요구하는지, 거부 시 어떻게 행동해야 하는지를 시스템 프롬프트에 명시한다.
- 서브에이전트 체이닝 환경에서도 서브에이전트 내 human review가 정상 작동한다.
- 코드 기반 프레임워크(Mastra, VoltAgent, Inngest)와 달리 `needsApproval` 함수나 `suspend()` 호출 없이 UI 설정만으로 동일한 툴 레벨 승인 효과를 얻는다.

### SDK 내장형 interruption 흐름 — OpenAI Agents SDK

OpenAI Agents JS SDK는 suspend/resume이나 waitForEvent 없이 **SDK가 직접 run을 일시 중지하고 `interruptions` 배열을 반환**하는 방식으로 HITL을 구현한다. [[openai-agents-js-hitl-승인-흐름-가이드]] 참조.

## 근거 출처

- [[hitl-approval-placement-patterns-mastra]] — Mastra 에이전트·워크플로 가이드에서 4가지 패턴 정의 도출
- [[agentkit-human-in-the-loop-inngest-waitforevent]] — Inngest waitForEvent 기반 이벤트 구동 HITL 구현 레퍼런스
- [[n8n-ai-에이전트-hitl-도구-승인]] — n8n 플랫폼 내장형 HITL 구현 레퍼런스
- [[openai-agents-js-hitl-승인-흐름-가이드]] — OpenAI Agents JS SDK interruption 흐름 레퍼런스
- [[voltagent-워크플로우-suspend-resume-cancellation]] — VoltAgent suspend/resume 메커니즘 레퍼런스
- [[voltagent-빠른시작-데모-에이전트-워크플로우-voltops]] — VoltAgent $500 임계값 Auto-Approve 패턴 구체 데모 사례
