# Agent Entry (ax-graph)

이 레포는 ax-knowledge-graph 제품의 **코드 레포**다.

- 제품 문서(스펙 AXKG-SPEC-001~012, 아키텍처)는 별도 문서 레포(SSOT)에서 관리하며, 그 계약이 이 레포 구현의 기준이다.
- tool/workflow 정의 파일(`.agent.md`/`decision-pipe.md` 등)은 이 레포가 소유한다(AXKG-SPEC-009 경계). 제품 설정 UI는 prompt/template만 편집한다.

## Layout

```text
apps/web            Next.js UI (Source Inbox, 승인 게이트, graph/chat, settings)
apps/api            FastAPI API (axkg 패키지, routes→services→repositories) + Alembic migration
apps/worker         open-kknaks worker (Redis broker 소비, claude CLI 실행)
packages/           공유 계약 (OpenAPI 파생 타입/JSON Schema)
context/            AI 스테이지가 읽는 배경지식 (승인 게이트 흐름, PARA 분류 기준)
data/documents      실험용 로컬 Markdown root (기본 아님 — 운영은 workspace bind mount)
docker-compose.yml  postgres + redis + api + worker (+ web profile)
```
