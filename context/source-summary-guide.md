# 요약 스테이지 지침

요약 AI(①)가 수집된 원문(`SourceMaterial`)을 요약할 때의 지침이다. 원천은 AXKG-SPEC-011(실행 계약)과 AXKG-SPEC-012(수집 계약)다.

## 입력: SourceMaterial

`adapter`(수집 방식)에 따라 원문 성격이 다르다:

| adapter | content_format | 원문 성격 |
|---|---|---|
| `youtube` | `transcript` | 자막 전문 — 구어체, 문단 구분 없음, 반복·필러 많음. `metadata.description`(영상 설명)이 함께 온다 |
| `youtube` | `video_description` | **자막이 없는 영상** — 영상 설명(description)만으로 요약하는 fallback. 설명에 없는 영상 내용을 추측하지 않는다 |
| `static_web` / `dynamic_web` | `page_text` | UI 요소(script/nav/footer/폼 등) 제거 후 페이지 전체 visible text — **네비게이션, 메뉴, 광고, 관련글, 댓글 문구가 섞여 있을 수 있다.** 정적이 동적보다 대체로 깨끗하지만 규칙은 같다 |

- YouTube 입력은 항상 두 갈래다: metadata(제목·채널·설명·태그·길이)와 자막. 자막이 원문이고 metadata는 보조 맥락이다 — 둘이 상충하면 자막을 우선한다.
- `page_text`는 주요 본문과 보조 영역을 구분하고, **요약에는 주요 본문만 반영**하라. 본문 선별은 adapter가 아니라 요약 AI의 책임이다.

## 출력 계약

`title`, `summary`, `keywords`, `source_type`을 JSON으로 낸다(활성 output_schema가 강제한다).

- `title`/`summary`/`keywords`는 이후 생성될 문서의 **frontmatter 시드**가 된다 — 분류 게이트와 문서화 초안이 그대로 이어받으니, 제목은 검색 가능한 명사구로, 키워드는 태그로 쓸 수 있게.
- `source_type`은 콘텐츠 유형이다: `article` / `video` / `document` / `unknown`. adapter가 힌트를 준다(`youtube`→`video`, 웹→기본 `article`) — 본문 기준으로 보정하라.
- 요약은 "이 자료가 무엇을 말하는가"를 담는다. 분류 판단(PARA)이나 연결 추천은 하지 않는다 — 그건 이후 스테이지의 일이다.

## 특수 케이스

- **목록 페이지** (`metadata.page_kind=list`): 단일 본문이 아니라 article 후보 목록이 주 콘텐츠다. 페이지가 무엇의 목록인지 요약하고, 눈에 띄는 article 후보들을 언급하라.
- **chunk 입력**: 원문이 길어 chunk로 나뉘어 오면 각 chunk를 같은 스키마로 요약한다. 병합은 시스템이 한다 — chunk에 없는 내용을 추측해 채우지 않는다.
- **원문이 부실할 때**: 본문이 광고/메뉴 위주라 실질 내용이 없으면, 없는 내용을 지어내지 말고 확인된 것만 짧게 요약한다.
