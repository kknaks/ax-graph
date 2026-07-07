# 문서 링크·그래프 규칙

문서초안 AI(③)가 초안과 파생지식에 연결을 넣을 때 지켜야 할 규칙이다. 원천은 AXKG-SPEC-005(링크 계약의 SSOT)다.

## 대원칙

- **본문 `[[ ]]`가 그래프 엣지의 단일 소스다.** frontmatter `up`은 그 위에 계보(lineage) 방향을 얹는 오버레이다.
- **주입된 컨텍스트 안에서만 링크한다.** 입력으로 받은 documents index 스냅샷(stem/aliases/title/type)에 없는 대상을 `[[ ]]`/`up:`으로 지어내지 않는다. 스냅샷 밖 링크는 승인 시 `BROKEN_WIKILINK`로 거부된다.
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
| `type` | yes | `reference` / `permanent` / `concept` / `baseline` / `decision` / `spec` / `work` / `source` 중 하나. `product`라는 타입은 없다 |
| `id` | yes | 제품 안에서 유일 |
| `title` | yes | 문서 제목 |
| `aliases` | 권장 | id와 사람이 찾을 별칭 (`[[id]]` resolve용) |
| `up` | 선택 | lineage upstream stem 목록 (본문 링크 동반 필수) |
| `source` | 선택 | 외부 URL — **URL은 그래프 노드가 아니라 속성이다** |
| `links` | 선택 | 사람이 읽는 추적용 묶음 — **그래프 엣지로 쓰이지 않는다** |

## 그래프에 대한 사실

- 노드는 문서뿐이다. URL·사람·도구는 노드가 아니다.
- `type=source` 문서(raw source record)는 그래프 기본 노출에서 제외된다.
- 같은 stem이 두 개 있을 수 없다(duplicate stem 거부). 새 문서 파일명은 스냅샷과 충돌하지 않게 정한다.
- concept 문서의 경로 관례는 `permanent/concepts/*.md`다.

## 연결의 질

- 후보 top-N에 있다고 전부 링크하지 않는다 — 본문 내용이 실제로 그 문서와 관련될 때만.
- 억지 연결 1개보다 정확한 연결 0개가 낫다. 연결이 없으면 없다고 두라(파생지식 빈 배열 허용).
