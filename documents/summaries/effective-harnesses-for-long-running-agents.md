---
type: summary
title: Effective Harnesses for Long-Running Agents
source_url: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
tags:
- long-running agents
- context window
- agent harness
- Claude Agent SDK
- initializer agent
- coding agent
- incremental progress
- git
- feature list
- browser automation
summarized_at: '2026-07-10T11:57:42.067012+00:00'
---

## 문제 배경

- AI 에이전트가 복잡한 작업(수 시간~수 일)을 맡는 사례가 늘고 있지만, **여러 컨텍스트 윈도우에 걸쳐 일관된 진행**을 유지하는 것은 미해결 과제다.
- 새로운 세션은 이전 세션의 기억이 전혀 없는 상태로 시작된다. 저자는 이를 "교대 근무마다 전임자 기억 없이 출근하는 엔지니어"에 비유한다.
- **Claude Agent SDK**는 컨텍스트 관리(compaction 포함)를 지원하지만, compaction만으로는 충분하지 않다.

## 관찰된 실패 패턴

### 패턴 1: 한 번에 너무 많이 하려는 경향
- 에이전트가 앱을 "원샷"으로 완성하려다 컨텍스트 중간에 구현이 끊김.
- 다음 세션이 절반만 구현된 상태를 이어받아 상황을 추측하는 데 많은 토큰을 소비.
- compaction이 다음 에이전트에게 명확한 지시를 항상 전달하지는 않음.

### 패턴 2: 조기 완료 선언
- 일부 기능이 이미 구현된 상태를 보고 에이전트가 "작업 완료"를 선언하는 경향.

## 해결 방안: 두 가지 에이전트 역할 분리

> "We developed a two-fold solution to enable the Claude Agent SDK to work effectively across many context windows: an initializer agent that sets up the environment on the first run, and a coding agent that is tasked with making incremental progress in every session."

### 초기화 에이전트 (Initializer Agent)
- 최초 세션에서만 실행되는 특수 프롬프트.
- 수행 작업:
  1. **`init.sh`** 스크립트 작성 (개발 서버 실행용)
  2. **`claude-progress.txt`** 작성 (에이전트 간 진행 로그)
  3. **초기 git 커밋** 생성
  4. 사용자 입력 프롬프트를 확장한 **기능 목록 파일(JSON)** 작성

### 코딩 에이전트 (Coding Agent)
- 이후 모든 세션에서 실행.
- 세션 시작 시 수행:
  1. `pwd` 실행으로 작업 디렉토리 확인
  2. git 로그와 진행 파일 읽기
  3. 기능 목록 파일에서 미완료 최우선 기능 선택
  4. `init.sh`로 개발 서버 시작
  5. 기본 엔드-투-엔드 테스트로 앱 상태 검증
- 세션 종료 시 수행:
  - 기능 목록에서 해당 기능의 `passes` 필드만 변경 (삭제/수정 금지)
  - 설명적 커밋 메시지와 함께 git 커밋
  - 진행 파일 업데이트

## 기능 목록 파일 설계

- 형식: **JSON** (Markdown 대비 에이전트가 임의로 수정·덮어쓸 가능성이 낮음)
- `claude.ai` 클론 예시에서 200개 이상의 기능 항목 포함.
- 각 항목 예시:
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
- 코딩 에이전트에게 강한 지시 부여: *"It is unacceptable to remove or edit tests because this could lead to missing or buggy functionality."*

## 테스트

- 에이전트가 코드 변경 후 기능을 완료로 표시하는 경향이 있으나, 명시적 지시 없이는 엔드-투-엔드 검증을 누락.
- **Puppeteer MCP 서버**를 통한 브라우저 자동화 도입으로 성능 크게 향상.
  - 실제 사용자처럼 브라우저에서 기능을 검증.
  - Puppeteer를 통해 스크린샷 촬영 가능.
- 한계: Claude의 비전 능력 제한 및 브라우저 자동화 도구의 한계로 일부 버그 미탐지. 예: 브라우저 네이티브 alert 모달은 Puppeteer MCP로 볼 수 없음.

## 세션 시작 표준 흐름 (실제 예시)

```
[Assistant] I'll start by getting my bearings and understanding the current state of the project.
[Tool Use] <bash - pwd>
[Tool Use] <read - claude-progress.txt>
[Tool Use] <read - feature_list.json>
[Assistant] Let me check the git log to see recent work.
[Tool Use] <bash - git log --oneline -20>
...
<Starts the development server>
...
<Tests basic functionality>
...
<Starts work on a new feature>
```

## 실패 모드 요약표

| 문제 | 초기화 에이전트 대응 | 코딩 에이전트 대응 |
|---|---|---|
| 조기 완료 선언 | 기능 목록 JSON 파일 설정 | 세션 시작 시 기능 목록 읽고 단일 기능 선택 |
| 버그·미문서 상태 방치 | 초기 git 저장소 + 진행 노트 파일 생성 | 진행 노트·git 로그 읽기, 기본 테스트 실행, 세션 종료 시 커밋+업데이트 |
| 기능 조기 완료 표시 | 기능 목록 파일 설정 | 모든 기능 자기 검증, 신중한 테스트 후에만 passing 표시 |
| 앱 실행 방법 파악에 시간 낭비 | `init.sh` 스크립트 작성 | 세션 시작 시 `init.sh` 읽기 |

## 향후 과제

- **단일 범용 코딩 에이전트** vs. **다중 에이전트 아키텍처** (테스트 에이전트, QA 에이전트, 코드 정리 에이전트 등) 중 어느 쪽이 더 나은지 불명확.
- 현재 구현은 **풀스택 웹 앱 개발**에 최적화 — 과학 연구, 금융 모델링 등 다른 분야로의 일반화가 향후 방향.

## 저자 및 기여
- 작성: **Justin Young**
- 기여: David Hershey, Prithvi Rajasakeran, Jeremy Hadfield 외 다수 (Anthropic 내 여러 팀)
