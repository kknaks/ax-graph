# PARA 분류 기준

source(외부 URL 자료)를 4개 destination 중 하나로 분류하는 기준이다. 분류기 AI(②)는 이 기준으로 **분류만** 한다 — 연결 추천이나 문서 초안은 만들지 않는다.

## Destination 4종

### `project` — 지금 실제로 만들거나 진행할 일

- 이 자료가 **진행 중인 제품/작업에 직접 반영될 구체적 액션**을 담고 있을 때.
- 대표 입력: 제품 기능 아이디어, MVP 작업 후보, 스펙 변경 제안.
- 승인 후: product 문서(baseline 후보)로 문서화된다.
- 판단 힌트: "이걸 보고 우리 제품에 무엇을 바꾸거나 만들 것인가"에 구체적 답이 나오면 project.

### `area` — 계속 관리할 책임/관심 영역

- 특정 프로젝트에 종속되지 않지만 **지속적으로 쌓아갈 주제/역량**에 해당할 때.
- 대표 입력: AX 전략, AI 전환 역량, 조직 지식관리, Agent Experience 연구 주제.
- 승인 후: permanent note(영구 개념 노트) 후보로 문서화된다.
- 판단 힌트: 끝나는 시점이 없고, 개념·원칙·방법론으로 축적되는 성격이면 area.

### `resource` — 나중에 참고할 외부 자료

- 당장 액션은 없지만 **참고 가치가 있는 외부 자료**일 때. 가장 흔한 destination이다.
- 대표 입력: 기사, 유튜브, 논문, 도구 링크, 사례 분석.
- 승인 후: reference note 후보로 문서화된다.
- 판단 힌트: "언젠가 찾아볼 자료"면 resource. `resource`는 PARA 분류 라벨이고 `reference note`는 그 산출 노트 타입이다 — 같은 대상의 두 이름.

### `archive` — 지금 쓰지 않을 자료

- 보존은 하되 **문서화·연결을 하지 않을** 자료일 때.
- 대표 입력: 중복 링크, 오래된 자료, 품질 낮은 자료, 현재 범위(AI Transformation) 밖 자료.
- 승인 후: archive 처리로 종료된다. 문서화 게이트로 넘어가지 않는다.

## 경계 판단 가이드

- **project vs resource**: 자료 자체는 외부 참고물이어도, 내용이 우리 제품의 구체적 변경을 직접 제안하면 project. 단순히 "유용해 보임"이면 resource.
- **area vs resource**: 개념/원칙으로 소화해 영구 노트에 녹일 가치면 area, 원문을 참조하는 것으로 충분하면 resource. 애매하면 resource가 안전하다 — 문서화 후 파생지식으로 개념 보충이 가능하다.
- **archive 기준은 보수적으로**: 확신이 없으면 archive보다 resource. archive는 문서화 자체를 막는다.

## 출력 계약 (classification.v1 form)

| 필드 | 필수 | 내용 |
|---|---|---|
| `destination_type` | yes | `project` / `area` / `resource` / `archive` |
| `destination_reason` | yes | 왜 이 destination인지 판단 근거. 위 기준을 인용해 구체적으로 |
| `suggested_title` | yes | 다음 문서화 단계에서 쓸 제목 후보 |
| `suggested_tags` | no | 태그 후보 |
| `source_type` | no | `article` / `video` / `document` / `unknown` (콘텐츠 유형) |
| `confidence` | no | 판단 신뢰도 0~1 |

## 하지 말 것

- 연결 후보(`[[ ]]`, up:)를 만들지 않는다 — 연결은 문서화 게이트(③)의 초안에서 발현된다.
- destination을 복수로 제안하지 않는다 — 하나만 고르고 이유를 명확히 한다.
- 요약을 다시 쓰지 않는다 — 입력으로 받은 요약을 근거로 분류만 한다.
