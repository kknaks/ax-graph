---
type: reference
title: "장기 실행 에이전트를 위한 효과적 하네스 설계 (Anthropic)"
source: "https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents"
aliases: ["Long-Running Agent Harness", "Anthropic 에이전트 하네스 설계", "effective harnesses long-running agents"]
tags: ["long-running-agents", "agent-harness", "claude-agent-sdk", "incremental-progress", "browser-automation", "anthropic-engineering"]
up: ["에이전틱-ai"]
---

# 장기 실행 에이전트를 위한 효과적 하네스 설계 (Anthropic)

## 요약

여러 컨텍스트 윈도우에 걸쳐 장기 작업을 수행하는 AI 에이전트의 실패 패턴을 분석하고, 초기화 에이전트와 코딩 에이전트 역할을 분리한 두 축 하네스 구조로 해결하는 방법론을 제시한다. git 히스토리·진행 파일·JSON 기능 목록·Puppeteer MCP 브라우저 자동화를 조합해 세션 간 맥락 연속성과 기능 완료 판정 정확도를 확보한다.

## 핵심 내용

### 문제: 세션 교체가 만드는 맥락 단절

[[에이전틱-ai]] 시스템이 수 시간~수 일에 걸친 복잡한 작업을 맡는 사례가 늘고 있으나, 새로운 세션은 이전 세션의 기억 없이 시작된다. 저자는 이를 "교대 근무마다 전임자 기억 없이 출근하는 엔지니어"에 비유한다. Claude Agent SDK는 컨텍스트 관리(compaction 포함)를 지원하지만, compaction만으로는 충분하지 않다.

관찰된 실패 패턴 두 가지:

1. **한 번에 너무 많이**: 에이전트가 앱을 원샷으로 완성하려다 컨텍스트 중간에 구현이 끊기고, 다음 세션이 절반만 구현된 상태를 이어받아 상황 추측에 많은 토큰을 소비.
2. **조기 완료 선언**: 일부 기능이 이미 구현된 상태를 보고 에이전트가 "작업 완료"를 선언하는 경향.

### 해결: 두 에이전트 역할 분리 — [[장기-에이전트-하네스]]

> "We developed a two-fold solution to enable the Claude Agent SDK to work effectively across many context windows: an initializer agent that sets up the environment on the first run, and a coding agent that is tasked with making incremental progress in every session."

**초기화 에이전트(Initializer Agent)** — 최초 세션에서만 실행:
1. `init.sh` 스크립트 작성 (개발 서버 실행용)
2. `claude-progress.txt` 작성 (에이전트 간 진행 로그)
3. 초기 git 커밋 생성
4. 사용자 입력 프롬프트를 확장한 기능 목록 파일(JSON) 작성

**코딩 에이전트(Coding Agent)** — 이후 모든 세션에서 실행:

세션 시작: `pwd` → git 로그 + 진행 파일 읽기 → 미완료 최우선 기능 하나 선택 → `init.sh`로 서버 시작 → 기본 E2E 테스트로 앱 상태 검증

세션 종료: 기능 목록 `passes` 필드만 변경(삭제·수정 금지) → 설명적 커밋 → 진행 파일 업데이트

### 기능 목록 파일 설계 (JSON)

Markdown 대신 JSON을 채택한 이유: 에이전트가 임의로 수정·덮어쓸 가능성이 낮음. `claude.ai` 클론 예시에서 200개 이상의 기능 항목 포함.

```json
{
  "category": "functional",
  "description": "New chat button creates a fresh conversation",
  "steps": [
    "Navigate to main interface",
    "Click the 'New Chat' button",
    "Verify a new conversation is created",
    "Check that chat area shows welcome state",
    "Verify conversation appears in sidebar"
  ],
  "passes": false
}
```

코딩 에이전트에게 강한 지시 부여: *"It is unacceptable to remove or edit tests because this could lead to missing or buggy functionality."*

### 테스트: [[버파이어]]로서의 브라우저 자동화

에이전트는 코드 변경 후 기능을 완료로 표시하는 경향이 있으나, 명시적 지시 없이는 E2E 검증을 누락한다. **Puppeteer MCP 서버**를 통한 브라우저 자동화 도입으로 성능이 크게 향상됐다. 실제 사용자처럼 브라우저에서 기능을 검증하고 스크린샷 촬영도 가능하다.

한계: Claude의 비전 능력 제한 및 브라우저 자동화 도구 한계로 일부 버그 미탐지. 예: 브라우저 네이티브 alert 모달은 Puppeteer MCP로 볼 수 없음.

### 실패 모드 요약

| 문제 | 초기화 에이전트 대응 | 코딩 에이전트 대응 |
|---|---|---|
| 조기 완료 선언 | 기능 목록 JSON 파일 설정 | 세션 시작 시 기능 목록 읽고 단일 기능 선택 |
| 버그·미문서 상태 방치 | 초기 git 저장소 + 진행 노트 파일 생성 | 진행 노트·git 로그 읽기, 기본 테스트 실행, 세션 종료 시 커밋+업데이트 |
| 기능 조기 완료 표시 | 기능 목록 파일 설정 | 모든 기능 자기 검증, 신중한 테스트 후에만 passing 표시 |
| 앱 실행 방법 파악에 시간 낭비 | `init.sh` 스크립트 작성 | 세션 시작 시 `init.sh` 읽기 |

### 향후 과제

- 단일 범용 코딩 에이전트 vs. 다중 에이전트 아키텍처(테스트 에이전트, QA 에이전트, 코드 정리 에이전트) 중 어느 쪽이 나은지 불명확.
- 현재 구현은 풀스택 웹 앱 개발에 최적화 — 과학 연구, 금융 모델링 등 다른 분야로의 일반화가 향후 방향.

## 연결

- [[에이전틱-ai]] — 장기 에이전트 하네스가 에이전틱 AI의 세션 간 연속성 문제를 구체적 하네스 설계로 해결한 구현 사례; up 노드
- [[루프-엔지니어링]] — 초기화+코딩 에이전트 구조는 루프 엔지니어링의 '에이전트 친화적 코드베이스(실행 가능성·검증 가능성)' 원칙의 구체적 구현
- [[버파이어]] — Puppeteer MCP 기반 브라우저 자동화가 기능 완료 판정의 검증기(verifier) 역할을 담당
- [[장기-에이전트-하네스]] — 이 문서가 제시하는 초기화 에이전트·코딩 에이전트 역할 분리 패턴의 SoT 위임
