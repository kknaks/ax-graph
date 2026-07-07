# ax-knowledge-graph

AX 관련 기사, 영상, 링크를 수집해 지식그래프로 만드는 제품의 작업 레포다.

## Product SSOT

`/Users/kknaks/git/toy_pr2/kknaks_profile/products/ax-knowledge-graph`

## Initial Scope

- 정보 수집: AI가 링크의 영상/문서를 탐색하고 요약한다.
- 정보 분류: AI가 PARA 기반 분류 승인 게이트를 만든다.
- 정보 연결: AI가 기존 정보와의 연결 추천 승인 게이트를 만든다.
- 문서화: 승인된 분류와 연결만 영구 문서로 편입한다.

## Core Workflow

```text
source input
-> AI collection summary
-> classification approval gate
-> connection approval gate
-> permanent documentation
```

승인 게이트가 마음에 들지 않으면 사용자가 피드백을 남기고, 시스템은 기존 게이트를 보존한 채 피드백을 반영한 새 게이트 버전을 생성한다.

## Open Decisions

- AX의 제품 내 정의
- 수집 채널: manual, RSS, Slack, browser extension
- 그래프 저장소: file-first, SQLite, Neo4j, graph DB alternative
- UI 우선순위: curation queue, graph explorer, source library
