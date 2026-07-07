# 승인 게이트 흐름

source가 들어와서 영구 문서가 되기까지의 전체 흐름과, AI가 게이트에서 지켜야 할 규칙이다. **AI 제안은 사용자 승인 전까지 어떤 문서·상태도 확정하지 않는다.**

## 전체 흐름

```text
URL 수신 (Slack / 직접 입력)
→ sources.received
→ [자동] 원문 수집(adapter) + 요약 AI ①        … summarizing → summarized (실패: collection_failed)
→ 분류 게이트 ② — 분류기 AI가 PARA destination 제안
→ 사용자 승인
   ├─ destination = archive        → 종료 (문서화 없음)
   └─ project / area / resource   → 문서화 승인 게이트 ③ 자동 생성
→ 문서화 게이트 ③ — 초안 AI가 문서 초안 + 연결 + 파생지식을 한 덩어리로 제안
→ 사용자 승인
→ Apply Executor가 Markdown 생성/수정 + 그래프 반영
→ sources.documented
```

- 게이트는 2개뿐이다: **분류(②)**와 **문서화(③)**. 연결(connection)을 위한 별도 게이트는 없다 — 연결은 ③의 초안 안 `up:`/`[[ ]]`와 파생지식으로 발현된다.
- 요약(①)과 chat(④)은 게이트가 아니다. 요약은 자동 실행, chat은 조회다.

## 게이트 공통 규칙 (버전/피드백)

- 사용자가 승인하지 않으면 `피드백`을 남긴다. 피드백은 **기존 버전을 수정하지 않고 새 버전(v2)을 생성**한다. v1은 read-only로 보존된다.
- 재생성 AI는 원본 source + 이전 버전 + 사용자 피드백을 함께 받아 v2를 만든다. 피드백에서 지적된 부분을 반드시 반영하되, 지적되지 않은 부분을 불필요하게 갈아엎지 않는다.
- 승인된 버전(revision)은 불변이다. 승인 후 변경하려면 새 revision이 필요하다.

## 분류 게이트 ② 규칙

- 출력은 PARA destination 하나 + 판단 근거 + 제목/태그 후보 (기준: `para-classification.md`).
- **연결 후보를 만들지 않는다.** 그래프 컨텍스트도 입력에 없다.

## 문서화 게이트 ③ 규칙

- 초안은 destination별 형태로 생성한다:

| destination | 산출물 | document_type |
|---|---|---|
| `resource` | reference note | `reference` |
| `area` | permanent note (기존 개념 보충 또는 신규) | `permanent` |
| `project` | product 문서 후보 (MVP는 baseline만) | `baseline` |

- 초안 = frontmatter + 본문 + `up:`/`[[ ]]` 연결. 뼈대는 활성 템플릿, 채우는 방법은 활성 프롬프트를 따른다.
- **연결은 주입된 컨텍스트 안에서만 만든다**: 입력으로 받은 (a) 관련 문서 후보 top-N, (b) documents index 스냅샷(stem/aliases/title/type)에 있는 대상만 `[[ ]]`/`up:`으로 링크한다. 스냅샷에 없는 stem을 지어내면 승인 시 깨진 링크로 거부된다.
- 모든 연결에는 `link_reason`(왜 연결하는지)을 남긴다.
- lineage 연결(`up:`)은 반드시 본문 `[[ ]]`에도 같은 target이 있어야 한다.
- **파생지식**은 초안과 한 덩어리다 — 개별 승인이 없고, 게이트 승인/피드백에 통째로 딸려간다:

| suggestion_type | 의미 | change_kind |
|---|---|---|
| `supplement_existing_concept` | 기존 개념 노트 보충 (대상 문서 + diff) | modify |
| `create_new_concept` | 신규 개념 노트 생성 | create |
| `create_project_baseline` | product baseline 후보 생성 | create |

- AI는 DB나 Markdown을 직접 변경하지 않는다. 초안과 함께 적용 계획(apply_plan: db_actions + file_actions)을 **제안**만 하고, 승인 후 백엔드 executor가 검증을 통과한 것만 적용한다.

## 재분류 ("이 destination이 아님")

- 문서화 게이트에서 사용자가 "이 destination이 아님"을 이유와 함께 제출하면, 승인됐던 분류 게이트가 재오픈되고 destination이 리셋된다.
- 재분류 실행 AI는 그 이유를 반영해 **다른** destination을 새 버전으로 제안해야 한다. 같은 destination을 반복 제안하지 않는다.
