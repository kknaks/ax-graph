---
type: reference
title: "Cloudflare Agents — 에이전트 구축·호스팅 플랫폼 개요"
source: "https://developers.cloudflare.com/agents/"
aliases: ["Cloudflare Agents 플랫폼", "Build Agents on Cloudflare", "Cloudflare 에이전트 SDK"]
tags: ["Cloudflare Agents", "Agents SDK", "durable agent", "에이전트 런타임", "MCP", "Workers AI", "human-in-the-loop", "플랫폼 문서"]
up: ["에이전틱-ai"]
---

# Cloudflare Agents — 에이전트 구축·호스팅 플랫폼 개요

## 요약

Cloudflare가 제공하는 에이전트 구축·호스팅 플랫폼 공식 문서다. 각 에이전트 세션에 지속적 ID·로컬 SQL·예약 작업·복구 가능한 실행을 보장하며, 3개의 CLI 명령으로 스타터를 실행할 수 있다. 채팅·음성·이메일·Slack·웹훅 등 다양한 채널과 Workers AI, OpenAI, Anthropic 등 외부 AI 프로바이더를 지원한다.

## 핵심 내용

### 플랫폼 개요

Cloudflare Agents는 채팅, 음성, 이메일, Slack, 웹훅 등의 채널을 에이전트 런타임에 연결하여 에이전트를 구축·호스팅할 수 있는 플랫폼이다. 핵심 특징:

- 각 에이전트 세션은 **지속적 ID(durable identity)**, 로컬 SQL 스토리지, 실시간 연결, 예약 작업, 복구 가능한 실행을 보장한다.
- 한 번 배포하면 Cloudflare 글로벌 네트워크에서 실행되며 **수천만 개의 인스턴스**로 확장 가능하다.
- 별도의 인프라 관리, 세션 재구성, 외부 상태 저장이 필요 없다.

### 에이전트의 네 가지 구성 요소

[[cloudflare-agents-런타임]] 구조는 네 층으로 나뉜다.

**1. 통신 채널(Communication channels)** — 사용자 및 시스템이 에이전트에 접근하는 방식을 정의한다. 지원 채널: 채팅, 음성, 이메일, Slack, 웹훅 및 기타 이벤트 소스.

**2. 에이전트 하네스(Agent harness)** — 에이전트의 루프를 정의한다: 모델 호출 → 툴 선택 → 툴 결과 처리 → 응답 스트리밍 → 계속 여부 결정. 의견이 반영된(opinionated) 하네스인 Project Think 사용 옵션과, Agents SDK 런타임 위에서 직접 자체 루프를 구성하는 방식 모두 지원한다. [[루프-엔지니어링]] 맥락에서 하네스는 단일 에이전트 실행에 필요한 모든 것(프롬프트·컨텍스트·루프)을 담는 층이다.

**3. Agents SDK 런타임** — 지속 가능한 인프라를 제공한다. 구성 요소: `Agent` 클래스, 상태(state), 세션(sessions), 라우팅(routing), WebSockets, 스케줄링(scheduling), 파이버(fibers), 옵저버빌리티(observability).

**4. 툴(Tools)** — 에이전트에 기능을 부여한다. 제공 툴: 브라우저 자동화, 샌드박스 코드 실행, AI Search, MCP 툴, 결제(payments). Code Mode에서는 모델이 코드를 작성하여 여러 툴을 발견하고 오케스트레이션한다.

### 빠른 시작

3개의 명령으로 에이전트 실행 가능하며, 기본 AI 프로바이더는 **Workers AI**(별도 API 키 불필요)다.

```
npx create-cloudflare@latest --template cloudflare/agents-starter
cd agents-starter && npm install
npm run dev
```

스타터에 포함된 기능:
- 스트리밍 AI 채팅
- 서버 사이드 및 클라이언트 사이드 툴
- **Human-in-the-loop** 승인 — [[hitl-승인-패턴]] 참조
- 작업 스케줄링

AI 프로바이더 교체 지원: OpenAI, Anthropic, Google Gemini, 기타 프로바이더.

### 예제 에이전트 유형

| 에이전트 유형 | 설명 |
|---|---|
| **채팅 에이전트** | 툴 및 human-in-the-loop 승인이 포함된 스트리밍 AI 채팅 에이전트 |
| **Slack 에이전트** | Slack 메시지, 멘션, 커맨드에 응답하는 에이전트 |
| **음성 에이전트** | 음성-텍스트·텍스트-음성 변환이 포함된 실시간 음성 에이전트 |
| **브라우저 에이전트** | 페이지 검사, 스크린샷 캡처, 브라우저 툴 사용 에이전트 |
| **이메일 에이전트** | 이메일 발송·수신·라우팅·답장 에이전트 |

## 연결

- [[에이전틱-ai]] — Cloudflare Agents가 구현하는 에이전틱 AI 패러다임(지속 ID·멀티 인스턴스·자율 실행)의 개념 SoT; up 노드
- [[루프-엔지니어링]] — 에이전트 하네스가 루프 엔지니어링 스택에서 하네스 층에 해당하며, 스케줄링·자동화 요소도 연결됨
- [[hitl-승인-패턴]] — 스타터 기본 기능으로 Human-in-the-loop 승인이 포함되어 있어 패턴 구현 사례로 연결
- [[cloudflare-agents-런타임]] — 이 문서가 제시하는 Agents SDK 런타임 구성 요소(Agent 클래스·세션·WebSocket·스케줄링)의 SoT 위임
