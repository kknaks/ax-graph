# ax-knowledge-graph

AX 관련 기사, 영상, 링크를 수집해 지식그래프로 만드는 제품의 작업 레포다.

제품 스펙(AXKG-SPEC-001~012)과 아키텍처 문서는 별도 문서 레포(SSOT)에서 관리한다. 이 레포는 구현 코드와 AI 런타임 배경지식(`context/`)만 가진다.

## Core Workflow

```text
source input (Slack / manual URL)
-> collection adapter (YouTube / static web / dynamic web)
-> AI summary
-> classification approval gate (PARA)
-> documentation approval gate (draft + links + derived knowledge)
-> permanent documentation + graph
```

게이트는 2개다(분류·문서화). 연결은 별도 게이트가 아니라 문서화 초안의 `up:`/`[[ ]]`로 발현된다. 승인 게이트가 마음에 들지 않으면 사용자가 피드백을 남기고, 시스템은 기존 버전을 보존한 채 새 버전을 생성한다.

## Layout

```text
apps/web        Next.js UI (Source Inbox, 승인 게이트, graph/chat, settings)
apps/api        FastAPI API (axkg 패키지) + Alembic migration
packages/       공유 계약 (OpenAPI 파생 타입/JSON Schema)
context/        AI 스테이지가 읽는 배경지식
data/documents  실험용 로컬 Markdown root (운영은 workspace bind mount)
```

## Stack

Next.js + FastAPI + PostgreSQL(운영 상태/그래프 캐시) + Markdown SoT + open-kknaks(AI provider 실행). Redis는 필요 시 도입.
