# context

AI 스테이지가 실행 시 읽는 **가이드(정의·규칙)** 디렉토리다. 코드레포가 소유한다(DB에서 동적 관리하는 prompt/template과 달리, 이 디렉토리는 코드 배포로 버전 관리한다).

## 3층 taxonomy

한 스테이지의 총 지시는 세 층이 합쳐진 것이다:

- **가이드** (`context/*.md`, 이 디렉토리) — 정의·규칙 (원문 성격, PARA 정의, 링크 규칙 등).
- **프롬프트** (DB, `seeds.py` PROMPT_SEEDS) — 작성 방법 (어떻게 채우고 어떤 형식으로 쓰는지).
- **템플릿** (DB, `seeds.py` TEMPLATE_SEEDS) — 출력 양식. **문서화③만** 가진다.

worker는 `context/*.md`를 자동 주입받지 않는다. **각 DB 프롬프트가 "먼저 해당 `context/*.md`를 읽어라"로 라우팅**하고, worker(workspace에서 실행되는 claude)가 그 파일을 직접 읽는다. api는 이 디렉토리를 런타임에 파일로 로드하지 않는다(실행 모델 PLAN-005-T-008).

## 스테이지 → context 라우팅

| Stage | 가이드 (context) | 프롬프트 (DB) | 템플릿 |
|---|---|---|---|
| ① 요약 | `source-summary-guide.md` | `source_summary` | 없음 |
| ② 분류 | `para-classification.md` | `classification_gate` | 없음 |
| ③ 문서화 | `documentation-guide.md` (+ `document-link-rules.md`) | `documentation_gate` | ✅ reference/permanent/project_baseline |
| ④ chat | `graph-chat-rules.md` | `graph_rag_chat` | 없음 |
| 공용 | `approval-gate-flow.md` (②③ 승인 흐름) | — | — |

- `document-link-rules.md` — wikilink/`up:` 문법, frontmatter 필수 필드, 스냅샷 밖 링크 금지. ③의 링크 계약 SSOT이며 `documentation-guide.md`가 참조한다.
- `approval-gate-flow.md` — 수집→요약→분류→문서화 승인 게이트 전체 흐름과 버전/피드백 규칙. ②③이 공용으로 참조한다.
