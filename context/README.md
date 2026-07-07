# context

AI 스테이지가 실행 시 읽는 **배경지식** 디렉토리다. 코드레포가 소유한다(DB에서 동적 관리하는 prompt/template과 달리, 이 디렉토리는 코드 배포로 버전 관리한다).

context builder가 스테이지별로 필요한 문서를 골라 입력 컨텍스트에 포함한다.

| 문서                        | 내용                                                              | 주 소비 스테이지     |
| --------------------------- | ----------------------------------------------------------------- | -------------------- |
| `source-summary-guide.md` | SourceMaterial(adapter별 원문 성격) 요약 지침, 출력 계약          | ① 요약              |
| `para-classification.md`  | PARA 분류 기준 (project/area/resource/archive)                    | ② 분류              |
| `approval-gate-flow.md`   | 수집→요약→분류→문서화 승인 게이트 전체 흐름과 게이트 규칙      | ② 분류, ③ 문서초안 |
| `document-link-rules.md`  | wikilink/`up:` 문법, frontmatter 필수 필드, 스냅샷 밖 링크 금지 | ③ 문서초안          |
| `graph-chat-rules.md`     | evidence 기반 응답, 근거 부족 시 추측 금지                        | ④ chat              |

