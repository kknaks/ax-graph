---
type: summary
title: n8n AI 에이전트 도구에 Human-in-the-loop(HITL) 적용하기
source_url: https://docs.n8n.io/advanced-ai/human-in-the-loop-tools/
tags:
- n8n
- Human-in-the-loop
- HITL
- AI Agent
- tool approval
- workflow automation
- Slack approval
- $fromAI
- $tool
- AI oversight
summarized_at: '2026-07-10T12:00:34.657626+00:00'
---

## 개요

n8n AI 에이전트 노드에 연결된 도구에 대해 **Human-in-the-loop(HITL)** 승인 단계를 설정할 수 있다. 도구 실행 전 워크플로우가 일시 중지되고 검토자가 **승인(Approve)** 또는 **거부(Deny)** 중 하나를 선택한다.

- **Approve**: AI가 지정한 입력값으로 도구가 실행됨
- **Deny**: 해당 액션이 취소되고 실행되지 않음

## HITL을 사용해야 하는 경우

- **비가역적 행동을 수행하는 도구**: 데이터 삭제, 외부 커뮤니케이션 발송, 구매 등
- **컴플라이언스 요구사항**: 규제 산업에서 특정 자동화 행동에 사람의 승인이 필요한 경우
- **고가치 의사결정**: 비즈니스 영향이 큰 행동
- **AI 워크플로우 신뢰 구축 단계**: 초기에 HITL을 활성화한 후 신뢰가 쌓이면 점진적으로 감독 수준을 줄이는 전략

> HITL은 AI 에이전트 노드에 연결된 모든 도구에 적용하거나, 선택된 개별 도구에만 적용할 수 있어 일반적인 출력 게이팅보다 세밀한 제어가 가능하다.

## 작동 방식

1. AI 에이전트가 사람 검토가 활성화된 도구를 사용해야 한다고 판단한다.
2. 워크플로우가 일시 중지되고 설정된 채널(Slack, Telegram, n8n Chat 등)을 통해 승인 요청이 전송된다.
3. 검토자는 AI가 사용하려는 도구와 파라미터를 확인한다.
4. 검토자가 승인 또는 거부를 선택한다.
5. 승인 시 AI가 지정한 입력으로 도구가 실행되고, 거부 시 액션이 취소되고 AI에게 거부 사실이 전달된다.

### 다른 채널을 통한 승인

- 메인 상호작용 채널과 승인 채널을 다르게 설정할 수 있다.
- 예: 사용자는 n8n Chat으로 에이전트와 대화하고, 승인 요청은 특정 담당자의 Slack으로 전달

## 설정 방법

### Step 1: Tools 패널 열기
- 워크플로우에서 AI 에이전트 노드의 **Tools** 커넥터를 클릭해 Tools 패널을 연다.

### Step 2: Human review 단계 추가
- Tools 패널에서 **Human review** 섹션을 찾는다.
- 원하는 승인 채널을 선택한다.
- 해당 채널의 자격증명(credentials)과 설정을 구성한다.

### Step 3: 도구를 review 단계에 연결
- 승인이 필요한 도구를 human review 단계의 tool 커넥터에 추가한다.
- 각 도구를 일반적인 방식으로 설정한다.

## 사용 가능한 승인 채널

| 채널 | 설명 |
|------|------|
| **Chat** | n8n 내장 채팅 인터페이스 |
| **Slack** | Slack 채널 또는 DM으로 승인 요청 전송 |
| **Discord** | Discord 채널로 승인 요청 전송 |
| **Telegram** | Telegram을 통해 승인 요청 전송 |
| **Microsoft Teams** | Teams 채널 또는 채팅으로 전송 |
| **Gmail** | 이메일로 승인 요청 전송 |
| **WhatsApp Business Cloud** | WhatsApp을 통해 전송 |
| **Google Chat** | Google Chat으로 전송 |
| **Microsoft Outlook** | Outlook 이메일로 전송 |

## 표현식 활용

### $tool 변수

human review 단계 설정 시 **`$tool`** 변수를 사용해 검토자에게 맥락 정보를 제공하는 메시지를 구성할 수 있다.

| 속성 | 설명 |
|------|------|
| `$tool.name` | AI 에이전트가 호출하려는 도구의 이름 (n8n 캔버스에 표시되는 노드 이름) |
| `$tool.parameters` | AI 에이전트가 도구 호출에 사용하려는 파라미터 (`$fromAI()` 표현식으로 설정된 필드 포함) |

**예시 메시지 구성:**
```
The AI wants to use {{ $tool.name }} with the following parameters:

{{ JSON.stringify($tool.parameters, null, 2) }}
```

### $fromAI() 함수와의 연동

- **`$fromAI()`** 함수는 human review 단계에 연결된 도구에서도 정상 작동한다.
- AI가 동적으로 지정한 파라미터 값이 검토자에게 그대로 표시되고, 검토자는 그 값을 기준으로 승인/거부를 결정한다.

## 시스템 프롬프트 설정 권장사항

AI 에이전트가 도구 호출 거부를 올바르게 해석하고 처리하려면, **시스템 프롬프트에 human review 설정 정보를 포함**해야 한다.

포함할 내용:
- 어떤 도구가 사람의 승인을 필요로 하는지
- 승인이 거부되었을 때 어떤 일이 발생하는지
- 거부 시 AI가 어떻게 응답해야 하는지 (예: 사용자에게 알리기, 대안 제시, 명확화 요청)

## 체이닝 및 서브에이전트

- AI 에이전트를 다른 AI 에이전트의 도구로 사용하는 경우(서브에이전트), **서브에이전트 내의 human review 단계도 정상 작동**한다.
