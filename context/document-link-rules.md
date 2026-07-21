# 문서 링크·그래프 규칙

문서초안 AI(③)가 초안과 파생지식에 연결을 넣을 때 지켜야 할 규칙이다. 원천은 AXKG-SPEC-005(링크 계약의 SSOT)다.

## 대원칙

- **본문 `[[ ]]`가 그래프 엣지의 단일 소스다.** frontmatter `up`은 그 위에 계보(lineage) 방향을 얹는 오버레이다.
- **주입된 컨텍스트 안에서만 링크한다.** 입력으로 받은 documents index 스냅샷(stem/aliases/title/type)에 없는 대상을 `[[ ]]`/`up:`으로 지어내지 않는다. 스냅샷 밖 링크는 승인 시 `BROKEN_WIKILINK`로 거부된다.
  - **예외 — 같은 제안에서 함께 생성하는 파생 stem**: 이 문서화 제안이 함께 만드는 파생 문서(concept/baseline)의 stem은 스냅샷에 없어도 링크할 수 있고, main→파생 concept의 **SoT 위임 링크는 반드시 걸어야 한다**. executor `_validate`가 이 apply plan이 새로 만드는 stem(plan 내 stem)을 유효 링크로 인정하므로 `BROKEN_WIKILINK`가 되지 않는다.
- 모든 연결에는 이유(`link_reason`)를 남긴다.

## 링크 문법

| 문법 | 의미 | 그래프 반영 |
|---|---|---|
| `[[stem]]` | 기본 연결 | edge `assoc` (방향 없음) |
| `[[stem|표시명]]` | 표시명 있는 연결 | edge `assoc` (target은 stem) |
| frontmatter `up: [stem]` | 계보/근거 연결 | edge `lineage` (upstream → 이 문서) |

- `up`에 넣은 stem은 **반드시 본문 `[[ ]]`에도** 있어야 한다. `up`에만 있으면 invalid.
- lineage는 "이 문서의 기반/상류"일 때만 쓴다. 단순 관련이면 본문 `[[ ]]`만.

## Frontmatter 필수 필드

| 필드 | 필수 | 규칙 |
|---|---|---|
| `type` | yes | `reference` / `permanent` / `concept` / `baseline` / `feature_spec` / `decision` / `spec` / `work` / `source` 중 하나. `product`라는 타입은 없다. project 팬아웃은 원본요약=`baseline`(회사 원본요약), 기능정의서=`feature_spec`을 쓴다 |
| `title` | yes | 문서 제목 |
| `aliases` | 권장 | 사람이 찾을 별칭 목록 (`[[alias]]` resolve용). 링크 resolve는 stem→alias 순 |
| `up` | 선택 | lineage upstream stem 목록 (`up: []` list 문법, 본문 링크 동반 필수) |
| `source` | 선택 | 외부 URL — **URL은 그래프 노드가 아니라 속성이다** |
| `id` | 선택 | Obsidian 호환 resolve용 호환 필드. 링크 대상은 기본적으로 파일 stem으로 잡는다 |
| `links` | 선택 | 사람이 읽는 추적용 묶음 — **그래프 엣지로 쓰이지 않는다** |

> 링크 resolve는 `stem → alias → id` 순으로 코드가 처리한다(Obsidian 호환). 새 문서 frontmatter에 `id`를 필수로 넣을 필요는 없다 — stem/alias로 충분하다.

## 그래프에 대한 사실

- 노드는 문서뿐이다. URL·사람·도구는 노드가 아니다.
- `type=source` 문서(raw source record)는 그래프 기본 노출에서 제외된다.
- 같은 stem이 두 개 있을 수 없다(duplicate stem 거부). 새 문서 파일명은 스냅샷과 충돌하지 않게 정한다.
- concept 문서의 경로 관례는 `permanent/concepts/*.md`다.

## project 팬아웃 연결·차용 규약 (원본요약 ↔ 기능정의서)

destination이 `project`면 산출물이 회사 프로젝트로 팬아웃된다(AXKG-SPEC-014). 원본요약(`projects/{corp}/baseline/`)과 기능정의서(`projects/{corp}/spec/`) 사이 연결은 다음 규약을 따른다.

- **원본요약(baseline) → 기능정의서(spec)**: 원본요약 본문 `## 기능 목록`에서 추출된 각 기능을 `[[기능-spec-stem]]`으로 링크한다(baseline↔spec 그래프를 여는 단일 소스). 이 stem들은 같은 제안에서 함께 생성하는 파생(기능정의서) stem이므로 스냅샷에 없어도 링크할 수 있다(위 대원칙 예외).
- **기능정의서(spec) → 원본요약(baseline)**: 기능정의서 frontmatter `up:`에 **회사 원본요약 stem**을 넣고(계보 upstream), 본문 `## 연결`에도 같은 stem을 `[[{corp}-원본요약]]`으로 둔다 — `up:`에 넣은 stem은 반드시 본문 `[[ ]]`에도 있어야 한다는 대원칙을 그대로 따른다.
- **기존 역량 차용 링크**: 기능정의서 본문 `## 연결`에는 원본요약 링크에 더해 ax-graph 기존 역량/문서를 차용 링크(`[[graph-chat]]` 등, 연결 후보 컨텍스트로 제안)로 둔다 — 주입된 documents index 스냅샷 안의 대상만 링크한다(스냅샷 밖은 `BROKEN_WIKILINK`).
- **빈 `[[ ]]` 금지**: 본문 `[[ ]]`가 그래프 엣지의 단일 소스이므로 채우지 않은 자리표시 `[[ ]]`를 남기지 않는다 — 실제로 링크할 대상이 없으면 그 불릿을 삭제한다.
- **기능 dedup 시**: 같은 corp 기존 기능정의서를 `supplement_existing_feature`로 보강할 때도 기존 문서의 `up:`·`## 연결` 링크(원본요약·차용 링크)를 보존하며 새 원본요약 링크를 합류시킨다(기존 링크를 갈아엎지 않는다).

## 연결의 질

- 후보 top-N에 있다고 전부 링크하지 않는다 — 본문 내용이 실제로 그 문서와 관련될 때만.
- 억지 연결 1개보다 정확한 연결 0개가 낫다. 연결이 없으면 없다고 두라(파생지식 빈 배열 허용).
