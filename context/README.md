# context

AI 스테이지가 실행 시 읽는 **배경지식** 디렉토리다. 코드레포가 소유한다(DB에서 동적 관리하는 prompt/template과 달리, 이 디렉토리는 코드 배포로 버전 관리한다).

context builder가 스테이지별로 필요한 문서를 골라 입력 컨텍스트에 포함한다.

| 문서                        | 내용                                                              | 주 소비 스테이지     |
| --------------------------- | ----------------------------------------------------------------- | -------------------- |
| `para-classification.md`  | PARA 분류 기준 (project/area/resource/archive)                    | ② 분류              |
| `approval-gate-flow.md`   | 수집→요약→분류→문서화 승인 게이트 전체 흐름과 게이트 규칙      | ② 분류, ③ 문서초안 |
| `document-link-rules.md`  | wikilink/`up:` 문법, frontmatter 필수 필드, 스냅샷 밖 링크 금지 | ③ 문서초안          |
| `graph-chat-rules.md`     | evidence 기반 응답, 근거 부족 시 추측 금지                        | ④ chat              |

> ① 요약 스테이지의 지침은 이 디렉토리가 아니라 요약 worker의 실행 workspace가 소유한다:
> `apps/worker/workspace/context/source-summary-guide.md`. worker가 claude를 그 workspace
> **안에서** 실행하고(진입 문서 `CLAUDE.md`/`agent.md`), claude가 스스로 읽는다. api는 요약
> 지침을 파일로 로드하지 않는다(PLAN-005-T-008 실행 모델 재설계).

