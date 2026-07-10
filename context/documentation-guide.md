# 문서화 스테이지 지침 (정의·규칙)

문서초안 AI(③)가 승인된 destination에 맞춰 Markdown 지식 문서 초안 + 연결 + 파생지식을 한 덩어리로 제안할 때 지켜야 할 **정의와 규칙**이다. 원천은 AXKG-SPEC-004(문서화 승인 게이트)와 AXKG-SPEC-005(링크 계약)다.

> 이 문서는 ③ 스테이지의 정의·규칙을 모은다. **초안을 어떻게 채우는지(템플릿 채움·연결 작성 방법)는 실행 프롬프트(`documentation_gate`)가, 출력 필드 계약은 `output_schema`가, 문서 뼈대는 활성 템플릿이 소유**한다.
> 링크 문법(wikilink/`up:`/frontmatter 필수 필드/스냅샷 밖 링크 금지)의 상세는 이 문서에 중복하지 않고 **[`document-link-rules.md`](document-link-rules.md)**를 SSOT로 참조한다. 전체 승인 흐름은 공용 문서 **[`approval-gate-flow.md`](approval-gate-flow.md)**를 따른다.

## 4층 문서 정체성 (무엇인가)

문서화 게이트가 만드는 문서(초안 + 파생지식)는 **`출처 → 원자 개념 → 종합/전략 → 실행`** 방향으로 자라는 4층 지식 모델 위에 놓인다. 각 층은 정체성·단위·수명이 다르다. 이 표의 정체성 SSOT는 AXKG-SPEC-004 §4이며, 경로·document_type 어휘는 AXKG-SPEC-005가 SSOT다.

| 층 | document_type | 정체성 (무엇인가) | 단위 | 수명 |
|---|---|---|---|---|
| 출처 기록 | `reference` | "이 자료가 무엇을 말했나" — 출처 맥락·논지 흐름·인용 | 자료 하나 | 생성 후 거의 고정 |
| 원자 개념 | `concept` | "이 개념은 무엇인가" — **사실의 SoT**, 출처 독립 | 개념 하나 | 여러 출처가 supplement로 합류하며 성장 |
| 종합 노트 | `permanent` | "내 종합·판단/전략" — 원자 개념들을 엮은 살아있는 문서 | 영역 하나 | 개념 유입마다 성장 |
| 실행 문서 | `baseline` | 프로젝트/실행 문서 | 프로젝트 | — |

- 지식 성장 방향은 **출처 → 원자 개념 → 종합/전략 → 실행**이다. reference가 원문을 소화하고, 그 안의 원자 개념이 concept로 갈라져 나가 사실의 SoT가 되며, concept들을 엮은 내 판단이 permanent로 자란다.
- `permanent/`의 두 층(`permanent/concepts/`=원자 개념 concept, `permanent/` 루트=종합 permanent)은 합치지 않고 **위계를 유지**한다. concept는 독립 document_type이며 **파생지식**(`create_new_concept`/`supplement_existing_concept`)으로만 산출된다 — main 초안이나 템플릿 주입 대상이 아니다.

### SoT 위임 (중복 서술 금지)

개념 상세의 SoT는 concept 노트 **한 곳**이다:

- reference·permanent는 개념의 **상세 설명 섹션을 복사하지 않는다** — 요지 + `[[concept]]` 링크로 위임하고, 상세는 해당 concept 본문이 소유한다.
- 다만 이 규율은 상세 섹션 복사 금지일 뿐이다. **판단 문장 안에 개념의 요지가 인용되는 것은 허용되며 필연적**이다(예: "성숙도 4단계 기준 우리는 2단계이므로 확산에 집중" — 판단에 개념 요지가 스민다). SoT 위임은 개념 상세의 중복 오염 표면적을 줄일 뿐, 오염을 구조적으로 0으로 만들지 않는다(AXKG-SPEC-004 §4, PLAN-009-T-024).

### supplement 우선 (개념 성장)

주입된 documents index 스냅샷에 **같은 개념이 이미 있으면 새 concept를 생성하지 않는다** → 기존 concept 보충(`supplement_existing_concept`)으로 합류시킨다. 이것이 개념 성장 메커니즘이다.

### 완성 기준 (층별)

- **reference**: 카드 `summary`의 재탕이 아니라 `body_markdown`(요약 장문 정리본)을 소화한 **자기완결 정리본** + 모든 연결에 이유(`link_reason`).
- **concept**: 개념 **하나만**(원자성) — 한 줄 정의 · 맥락 · 근거 출처.
- **permanent**: 개념을 재서술하지 않고 **내 판단·전략만 소유** + 구성 개념을 `[[concept]]`로 링크.

## destination별 산출물

승인된 destination에 따라 초안의 형태가 정해진다 (템플릿은 context builder가 destination→key로 선택한다):

| destination | 산출물 | document_type | 디렉토리(시스템 조립) |
|---|---|---|---|
| `resource` | reference note | `reference` | `resources/` |
| `area` | permanent note (기존 개념 보충 또는 신규) | `permanent` | `permanent/` |
| `project` | product 문서 후보 (MVP는 baseline만) | `baseline` | `projects/` |

- 초안 = frontmatter + 본문 + `up:`/`[[ ]]` 연결. **뼈대는 활성 템플릿, 채우는 방법은 활성 프롬프트를 따른다.**
- 내용은 source 요약과 원문 근거 **안에서만** 채운다. 원문에 없는 사실을 지어내지 않는다.
- **`target_path`는 AI가 정하지 않는다(시스템 조립)**: AI는 `filename_candidate`(파일명 stem)만 내고, 시스템이 위 표의 document_type→디렉토리 매핑을 붙여 최종 경로를 조립한다. 재문서화(같은 source 재생성)면 기존 main 경로를 재사용해 파일명이 흔들려도 경로가 바뀌지 않는다. 위 표는 이제 **시스템의 매핑 설명**이다 — executor의 `PATH_NOT_ALLOWED`는 조립 경로에 대한 안전망으로 남는다.

## 연결 규칙 (요지 — 상세는 `document-link-rules.md`)

- 연결은 **주입된 컨텍스트 안에서만** 만든다: (a) 관련 문서 후보 top-N, (b) documents index 스냅샷(stem/aliases/title/type)에 있는 대상만 `[[ ]]`/`up:`으로 링크한다. 스냅샷 밖 target은 승인 시 깨진 링크로 거부된다 — **단, 같은 제안에서 함께 생성하는 파생 stem은 예외이며 main→concept SoT 위임 링크는 반드시 건다**(상세·근거는 `document-link-rules.md` 대원칙).
- 본문 `[[ ]]`가 그래프 엣지의 단일 소스다. `up:`(lineage)에 넣은 stem은 반드시 본문 `[[ ]]`에도 있어야 한다.
- 모든 연결에는 이유(`link_reason`)를 남긴다. 억지 연결 1개보다 정확한 연결 0개가 낫다.

## 파생지식 규칙

파생지식은 초안과 **한 덩어리**다 — 개별 승인이 없고, 게이트 승인/피드백에 통째로 딸려간다:

| suggestion_type | 의미 | change_kind | AI 입력 | 디렉토리(시스템 조립) |
|---|---|---|---|---|
| `supplement_existing_concept` | 기존 개념 노트 보충 | modify | `target_stem`(대상 concept 지목) | 기존 문서 경로 그대로 (시스템이 stem→경로 해소) |
| `create_new_concept` | 신규 개념 노트 생성 | create | `filename_candidate`(파일명 stem) | `permanent/concepts/` |
| `create_project_baseline` | product baseline 후보 생성 | create | `filename_candidate`(파일명 stem) | `projects/` |

- 파생도 **경로는 시스템이 조립한다**: create류는 `filename_candidate`에 파일명 stem만, supplement는 `target_stem`에 대상 concept의 stem만 낸다. modify 대상 stem이 index에서 해소되지 않으면 승인 apply에서 `PATH_NOT_ALLOWED`로 거부된다(안전망).

### 파생 본문 (draft_markdown 필수)

파생 제안도 **`draft_markdown`(문서 전문)이 필수**다 — 본문 없이 제안만 하면 실행 시 건너뛴다.

- **create류** (`create_new_concept`/`create_project_baseline`): frontmatter+본문을 갖춘 **완전한 문서 전문**을 `draft_markdown`에 쓴다(활성 템플릿·링크 규칙 준수). executor가 위 경로에 신규 생성한다.
- **modify** (`supplement_existing_concept`, **A1 모델**): 연결 후보 컨텍스트에 함께 주입된 **대상 문서 전문**에 보충을 반영한 **수정된 전문**을 `draft_markdown`에 쓴다. executor는 그 전문으로 기존 파일을 **overwrite**한다(diff/patch 적용 엔진은 없다). 무엇을 어떻게 보충했는지는 `diff_preview`에 리뷰용 요지로 남긴다. **전문이 주입되지 않은 문서는 modify로 제안하지 않는다.**
- **보충 대상은 concept만**: `supplement_existing_concept`의 대상은 `permanent/concepts/`의 **concept 노트로 한정**한다 — reference/permanent/baseline은 보충 대상이 아니다(reference는 "출처 기록, 거의 고정" 정체성이고, 개념 성장·stale 연쇄는 concept에서만 일어난다). concept가 아닌 문서를 대상으로 고르면 승인 apply에서 `SUPPLEMENT_TARGET_NOT_CONCEPT`로 거부된다.

## 승인 전 확정 금지

- AI는 DB나 Markdown을 직접 변경하지 않는다. 초안과 함께 적용 계획을 **제안**만 하고, 사용자 승인 후 백엔드 executor가 검증을 통과한 것만 적용한다.
- 피드백이 오면 기존 버전을 수정하지 않고 새 버전(v2)을 만든다 — 지적된 부분은 반드시 반영하되, 지적되지 않은 부분을 불필요하게 갈아엎지 않는다 (공용 규칙: `approval-gate-flow.md`).
