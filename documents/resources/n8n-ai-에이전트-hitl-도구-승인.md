---
type: reference
title: "n8n AI 에이전트 도구에 Human-in-the-loop(HITL) 승인 적용하기"
source: "https://docs.n8n.io/advanced-ai/human-in-the-loop-tools/"
aliases: ["n8n HITL", "n8n 도구 승인", "n8n Human-in-the-loop"]
tags: ["n8n", "human-in-the-loop", "HITL", "AI-agent", "tool-approval", "workflow-automation", "AI-oversight"]
up: ["hitl-승인-패턴"]
---

# n8n AI 에이전트 도구에 Human-in-the-loop(HITL) 승인 적용하기

## 요약

n8n에서 AI 에이전트가 특정 도구를 실행하기 전에 사람의 승인을 요구하는 HITL 기능을 설명하는 공식 문서다. 코드 없이 워크플로우 빌더 UI로 승인 채널(Slack, Telegram 등)을 구성하며, 비가역적 행동이나 컴플라이언스 요구가 있는 도구에 선택적으로 적용한다. [[hitl-승인-패턴]]의 플랫폼 내장형 구현 레퍼런스다.

## 핵심 내용

### HITL 적용 대상

모든 도구에 일괄 적용하거나 선택된 개별 도구에만 적용할 수 있다. 적합한 도구 유형:

- **비가역적 행동**: 데이터 삭제, 외부 커뮤니케이션 발송, 구매 등
- **컴플라이언스 요구**: 규제 산업에서 특정 자동화 행동에 사람 승인이 법적으로 필요한 경우
- **고가치 의사결정**: 비즈니스 영향이 큰 행동
- **신뢰 구축 단계**: 초기에 HITL을 활성화한 후 신뢰가 쌓이면 점진적으로 감독 수준을 줄이는 전략

[[hitl-승인-패턴]]에서 도구 호출 자체가 위험한 경우(툴 레벨 승인)에 해당하며, 일반적인 출력 게이팅보다 세밀한 제어가 가능하다.

### 작동 흐름

1. AI 에이전트가 human review 활성화 도구를 호출해야 한다고 판단
2. 워크플로우 일시 중지 → 설정된 채널로 승인 요청 전송
3. 검토자가 도구 이름·파라미터 확인
4. **Approve**: AI가 지정한 입력으로 도구 실행 / **Deny**: 액션 취소, AI에게 거부 사실 전달

메인 상호작용 채널(예: n8n Chat)과 승인 채널(예: 담당자 Slack)을 다르게 설정할 수 있다.

### 설정 방법

1. AI 에이전트 노드의 **Tools** 커넥터를 열어 Tools 패널로 진입
2. **Human review** 섹션에서 승인 채널과 자격증명 설정
3. 승인이 필요한 도구를 human review 단계의 tool 커넥터에 추가

### 지원 승인 채널

| 채널 | 설명 |
|------|------|
| Chat | n8n 내장 채팅 인터페이스 |
| Slack | 채널 또는 DM |
| Discord | Discord 채널 |
| Telegram | Telegram 메시지 |
| Microsoft Teams | Teams 채널 또는 채팅 |
| Gmail | 이메일 |
| WhatsApp Business Cloud | WhatsApp 메시지 |
| Google Chat | Google Chat |
| Microsoft Outlook | Outlook 이메일 |

### $tool 변수와 $fromAI() 연동

human review 단계 설정 시 **`$tool`** 변수로 검토자에게 맥락 정보를 제공하는 메시지를 구성한다.

| 속성 | 설명 |
|------|------|
| `$tool.name` | 에이전트가 호출하려는 도구 이름(캔버스에 표시되는 노드 이름) |
| `$tool.parameters` | 도구 호출에 사용하려는 파라미터(`$fromAI()`로 설정된 필드 포함) |

메시지 구성 예시:
```
The AI wants to use {{ $tool.name }} with the following parameters:

{{ JSON.stringify($tool.parameters, null, 2) }}
```

`$fromAI()` 함수는 human review 단계에 연결된 도구에서도 정상 작동한다. AI가 동적으로 지정한 파라미터 값이 검토자에게 그대로 표시되어 승인/거부 판단 근거가 된다.

### 시스템 프롬프트 권장사항

AI가 거부를 올바르게 해석하고 처리하려면 시스템 프롬프트에 다음을 포함해야 한다:

- 어떤 도구가 사람의 승인을 필요로 하는지
- 승인이 거부되었을 때 어떤 일이 발생하는지
- 거부 시 AI가 어떻게 응답해야 하는지 (사용자에게 알리기, 대안 제시, 명확화 요청 등)

### 서브에이전트 체이닝

AI 에이전트를 다른 AI 에이전트의 도구로 사용하는 서브에이전트 구조에서도 **서브에이전트 내의 human review 단계가 정상 작동**한다.

## 연결

- [[hitl-승인-패턴]] — n8n의 HITL이 구현하는 툴 레벨 승인 패턴 개념 SoT; up 노드
