"""Initial Seeds (40-architecture/database README "Initial Seeds"). WP0 Phase 3.

idempotent: unique key(email/settings.key/prompts.key/templates.key/definitions.key)로
존재 여부를 확인하고 있으면 건너뛴다.

사용처:
- alembic 마이그레이션 step 15 (`0015_initial_seeds`)
- 테스트 fixture (sqlite create_all 후 시딩)
- 단독 실행: ``uv run python -m axkg.seeds``

sync Connection 기반으로 작성한다(alembic `op.get_bind()`와 async engine의
`run_sync` 양쪽에서 쓰기 위함).
"""
import uuid

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from axkg.core.security import hash_password
from axkg.models import (
    AiTaskDefinition,
    DocumentTemplate,
    DocumentTemplateVersion,
    Prompt,
    PromptVersion,
    Setting,
    User,
)

SEED_USER_EMAIL = "kknaks@medisolveai.com"
SEED_USER_PASSWORD = "1234"  # AXKG-SPEC-008 개발 seed. 운영 보안 기준 아님.

# AXKG-SPEC-008 Seed Data — 활성 22명 로스터(admin 3 + staff 19). email 기준 멱등.
# 비활성 4명(박신아·최원·김사라·원영진)은 제외. department/position/source_user_id는
# 저장하지 않는다(role 매핑 소스일 뿐). 기존 seed 계정 kknaks는 admin으로 흡수된다.
USER_ROSTER: list[dict] = [
    {"email": "kknaks@medisolveai.com", "display_name": "이건학", "role": "admin"},
    {"email": "dante@medisolveai.com", "display_name": "전창원", "role": "admin"},
    {"email": "sykim@medisolveai.com", "display_name": "김수연", "role": "admin"},
    {"email": "dr.jinlee@kakao.com", "display_name": "이종진", "role": "staff"},
    {"email": "imkrmin@medisolveai.com", "display_name": "임주민", "role": "staff"},
    {"email": "srpark@medisolveai.com", "display_name": "박세림", "role": "staff"},
    {"email": "wychoi@medisolveai.com", "display_name": "최우영", "role": "staff"},
    {"email": "dreseul@medisolveai.com", "display_name": "한예슬", "role": "staff"},
    {"email": "ivorycho@medisolveai.com", "display_name": "조상아", "role": "staff"},
    {"email": "narsein@medisolveai.com", "display_name": "안덕환", "role": "staff"},
    {"email": "a1878h@medisolveai.com", "display_name": "윤아영", "role": "staff"},
    {"email": "cjs777@medisolveai.com", "display_name": "천수정", "role": "staff"},
    {"email": "oasis@medisolveai.com", "display_name": "한승진", "role": "staff"},
    {"email": "mint5948@medisolveai.com", "display_name": "박소은", "role": "staff"},
    {"email": "jso4093@medisolveai.com", "display_name": "전소은", "role": "staff"},
    {"email": "yg10004@medisolveai.com", "display_name": "신용진", "role": "staff"},
    {"email": "icran@medisolveai.com", "display_name": "서형석", "role": "staff"},
    {"email": "twin9774@medisolveai.com", "display_name": "김태우", "role": "staff"},
    {"email": "kalmia@medisolveai.com", "display_name": "변가영", "role": "staff"},
    {"email": "marin@medisolveai.com", "display_name": "김대정", "role": "staff"},
    {"email": "seyunjeong@medisolveai.com", "display_name": "정세윤", "role": "staff"},
    {"email": "jekwon@medisolveai.com", "display_name": "권정의", "role": "staff"},
]

# AI task별 model 오버라이드(PLAN-010-T-011): 글로벌 model 비움(=claude CLI 디폴트 대형
# 모델)에 의존하지 않도록, 실행되는 6개 task definition 전부에 Sonnet을 명시한다. claude 전용
# (codex 등 타 provider 몫 없음). provider는 글로벌 claude 그대로, options/provider_options는
# definition 레벨 override(문서화 max_turns 12/timeout 600, chat max_turns 6)를 건드리지 않는다.
# key는 TASK_DEFINITION_SEEDS 기준 grounding(게이트는 generate/regenerate 각 2종).
AI_TASK_MODEL = "claude-sonnet-4-6"
AI_TASK_MODEL_OVERRIDES = {
    "collect_source_summary": {"model": AI_TASK_MODEL},
    "generate_classification_gate": {"model": AI_TASK_MODEL},
    "regenerate_classification_gate": {"model": AI_TASK_MODEL},
    "generate_documentation_gate": {"model": AI_TASK_MODEL},
    "regenerate_documentation_gate": {"model": AI_TASK_MODEL},
    "graph_rag_chat": {"model": AI_TASK_MODEL},
    # plan-then-fanout (AXKG-DEC-008/WORK-012) — project 문서화 생성 재설계.
    "plan_project": {"model": AI_TASK_MODEL},
    "generate_feature_spec": {"model": AI_TASK_MODEL},
}

# 글로벌 기본값(PLAN-010-T-012): 신규 DB가 현재 운영값으로 태어나게 한다.
# resume=True는 T-008 실세션 가드(is_resume_session) 덕에 무해 — bare true는 새 세션으로
# 취급돼 컨텍스트가 재조립된다. max_turns=20은 definition override(문서화 12·chat 6)가 이겨
# 그 stage들엔 영향 없고, override 없는 요약/분류만 20을 받는다.
AI_PROVIDER_DEFAULT = {
    "provider": "claude",
    "model": None,
    "options": {"timeout_sec": 300, "resume": True},
    "provider_options": {"max_turns": 20, "effort": "medium"},
    "task_overrides": AI_TASK_MODEL_OVERRIDES,
}

# ---------------------------------------------------------------------------
# prompts 4종 — prompt_text는 초안, output_schema는 소관 스펙 필드 기준 JSON Schema.
# envelope(classification.v1/documentation.v1)은 코드 고정이고 output_schema는
# 내부 form/구조 필드만 관장한다(AXKG-SPEC-011 Assembly Contract).
# ---------------------------------------------------------------------------

PROMPT_SEEDS: list[dict] = [
    {
        "key": "source_summary",
        "name": "Source Summary",
        "description": "① 요약 스테이지 — SourceMaterial을 요약 카드 payload로 (AXKG-SPEC-003/011/012)",
        "prompt_text": (
            "당신은 개인 지식 베이스의 수집 비서다. 주어진 source URL과 수집된 원문"
            "(SourceMaterial)을 읽고, 나중에 PARA 분류와 문서화에 쓸 수 있는 요약 카드를 만든다.\n\n"
            "먼저 작업 프로젝트의 `context/source-summary-guide.md`를 읽고, 그 정의·규칙(adapter별 "
            "원문 성격·특수 케이스[목록·chunk·부실]·추측 금지)을 따르라. 원문에 없는 사실을 추가하지 "
            "말고, 저자의 주장과 근거를 구분해서 압축한다.\n\n"
            "## 본문 선별\n"
            "- `page_text`(웹)에는 주요 본문과 보조 영역(내비·메뉴·광고·관련글·댓글)이 섞여 있다. "
            "**주요 본문만** 요약에 반영하고 보조 영역은 버린다.\n"
            "- YouTube는 자막이 원문이고 metadata(제목·설명·태그)는 보조 맥락이다 — 둘이 상충하면 "
            "**자막을 우선**한다.\n\n"
            "## 출력 필드\n"
            "- `title`: 원문 제목을 우선하되 없으면 내용 기반으로 짓는다. 검색 가능한 명사구로.\n"
            "- `summary`: 카드에 랜딩되는 3~6문장 요지 — '이 자료가 무엇을 말하는가'를 압축.\n"
            "- `keywords`: 핵심 주제어 3~10개(태그로 쓸 수 있게).\n"
            "- `source_type`: 원문의 매체 성격(article/video/paper/docs/thread 등)을 한 단어로.\n"
            "- `body_markdown`: 아래 형식 규약을 따른 장문 정리본.\n\n"
            "## body_markdown 형식 규약\n"
            "카드용 짧은 `summary`와 별도로, 원문을 상세히 옮긴 장문 구조화 정리본을 `body_markdown`에 "
            "담는다. 이 정리본은 downstream(분류②·문서화③)의 유일한 재료이므로 얇으면 뒤 단계가 전부 "
            "얇아진다 — 원문의 핵심 논지·근거/데이터·주요 인용을 놓치지 않게 상세히 옮긴다.\n"
            "- **원문 자체의 구조를 그대로 따라** 소제목(`##`)으로 나눈다. 고정된 섹션 틀을 강제하지 "
            "말고 원문 흐름에 맞춰 적응형으로 구성한다.\n"
            "- 세부 항목은 불릿(`-`), 순서·절차는 번호 목록으로 정리한다.\n"
            "- 직접 인용은 `>` 인용블록에 담고 가능하면 화자를 표기한다.\n"
            "- 핵심 엔티티·용어는 **볼드**로 강조한다.\n"
            "- 불확실하거나 출처가 분명치 않은 내용은 지어내지 말고 '출처 미상' 등으로 정직하게 표기한다.\n"
            "- frontmatter 없이 본문 Markdown만 담는다(제목·요약·태그는 별도 필드로 이미 나간다).\n\n"
            "전체 출력은 output_schema를 따르는 JSON 하나로만 한다. `body_markdown` 안의 줄바꿈·"
            "큰따옴표는 JSON 문자열로 정확히 이스케이프하고, 코드펜스(```)로 JSON을 감싸지 않는다. "
            "JSON 앞뒤에 어떤 설명·해설 문장도 붙이지 마라 — 응답의 첫 글자는 `{`, 마지막 글자는 "
            "`}`여야 한다."
        ),
        "output_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "summary", "keywords", "source_type", "body_markdown"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "summary": {"type": "string", "minLength": 1},
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 10,
                },
                "source_type": {"type": "string", "minLength": 1},
                "body_markdown": {"type": "string", "minLength": 1},
            },
        },
    },
    {
        "key": "classification_gate",
        "name": "Classification Gate",
        "description": "② 분류 스테이지 — 요약 payload를 PARA destination 제안으로 (AXKG-SPEC-001/002)",
        "prompt_text": (
            "당신은 PARA 방법론으로 개인 지식 베이스를 분류하는 큐레이터다. source의 요약 "
            "payload를 읽고 destination(project/area/resource/archive) 하나를 제안하라. "
            "먼저 작업 프로젝트의 `context/para-classification.md`를 읽고, 그 정의·규칙(4종 정의·경계 "
            "판단 질문·보수적 판정 규칙)에 정확히 따라 분류하라. 진행 중인 산출물에 붙는 "
            "것이면 project, 지속 관리 영역이면 area, 참고 자료면 resource, 보관만 할 것이면 "
            "archive다. 그래프/기존 문서 컨텍스트는 이 단계에서 제공되지 않으며 연결 제안은 "
            "문서화 스테이지의 소관이다.\n\n"
            "## 애매할 때 규율\n"
            "- 경계가 흐릿하면 destination을 억지로 확신하지 말고 `confidence`를 낮춘다"
            "(예: 0.4~0.6). 게이트에서 사용자가 판단할 여지를 남기는 게 낫다.\n"
            "- `destination_reason`에는 사용자가 게이트에서 승인/반려를 판단할 수 있게 어떤 기준을 "
            "적용했는지 근거를 2~3문장으로 쓰고, 경계에서 망설였다면 어떤 두 destination 사이에서 "
            "망설였고 왜 지금 것을 골랐는지 남긴다.\n"
            "- `confidence`는 0~1 사이 수치로 스스로의 확신도를 적고, 애매할수록 낮춘다.\n\n"
            "전체 출력은 output_schema를 따르는 JSON 하나로만 한다. 파일을 읽더라도 최종 응답은 "
            "그 JSON 객체 하나여야 하며, 코드펜스(```)로 감싸지 말고, 문자열 안의 줄바꿈·큰따옴표는 "
            "JSON 문자열로 정확히 이스케이프한다. JSON 앞뒤에 어떤 설명·해설 문장도 붙이지 마라 — "
            "응답의 첫 글자는 `{`, 마지막 글자는 `}`여야 한다."
        ),
        "output_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": [
                "destination_type",
                "destination_reason",
                "suggested_title",
                "suggested_tags",
                "source_summary",
                "confidence",
            ],
            "properties": {
                "destination_type": {
                    "type": "string",
                    "enum": ["project", "area", "resource", "archive"],
                },
                "destination_reason": {"type": "string", "minLength": 1},
                "suggested_title": {"type": "string", "minLength": 1},
                "suggested_tags": {"type": "array", "items": {"type": "string"}},
                "source_summary": {"type": "string", "minLength": 1},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
    },
    {
        "key": "documentation_gate",
        "name": "Documentation Gate",
        "description": "③ 문서초안 스테이지 — 템플릿+연결 후보 컨텍스트로 문서 초안 생성 (AXKG-SPEC-004/005/011)",
        "prompt_text": (
            "당신은 승인된 destination에 맞춰 Markdown 지식 문서 초안을 쓰는 작성자다.\n\n"
            "먼저 작업 프로젝트의 `context/documentation-guide.md`를 읽고, 그 정의·규칙"
            "(4층 문서 정체성·SoT 위임·완성 기준·destination별 산출물·연결 규칙·파생지식·승인 전 확정 "
            "금지)을 따르라. 링크 문법 상세는 그 문서가 가리키는 `context/document-link-rules.md`를 "
            "따른다.\n\n"
            "함께 주어진 템플릿 뼈대의 frontmatter와 섹션 구조를 그대로 따르고, source 요약과 "
            "원문 근거 안에서만 내용을 채워라. 연결(`up:`과 본문 `[[ ]]` wikilink)은 함께 "
            "주어진 retriever 후보와 documents index 스냅샷 안의 stem/alias로만 만들고, "
            "채택한 모든 연결에 link_reason을 남겨라. 스냅샷에 없는 target은 만들지 않으며, "
            "`up:`에 넣은 stem은 반드시 본문 `[[ ]]`에도 있어야 한다. "
            "**단, 이 제안에서 함께 생성하는 파생 문서(concept/baseline)의 stem은 스냅샷에 없어도** "
            "본문 `[[ ]]`·`## 연결`·links로 링크할 수 있고, **SoT 위임을 위해 반드시 걸어야 한다**"
            "(main→파생 concept 위임 링크). executor가 이 apply가 새로 만드는 stem을 유효 링크로 "
            "인정한다(상세는 `context/document-link-rules.md`).\n\n"
            "## 본문 작성 방법\n"
            "- **재탕 금지**: 카드 summary의 요약을 다시 만들지 마라. 주어진 요약 payload의 "
            "body_markdown 전체 구조를 소화해 재구성하고, 핵심 논지·데이터·인용을 누락하지 마라.\n"
            "- **요약 섹션**: 이 문서를 열지 판단할 1~3문장만 담는다(핵심 내용의 재탕이 아니다). "
            "살은 핵심 내용 섹션이 담당한다.\n"
            "- **핵심 내용 섹션**: 원문(body_markdown)의 구조를 따라 `###` 서브섹션으로 적응형 분할한다. "
            "고정 틀을 강제하지 말고 원문 흐름에 맞춘다.\n"
            "- **연결 섹션 서술**: 채택한 각 연결을 본문 연결 섹션에도 `- [[stem]] — 관계 이유 한 줄` "
            "형식으로 남겨라(출력 links의 link_reason과 동일 내용).\n"
            "- **SoT 위임 작성법**: main 문서에서 개념 상세를 펼치지 말고 요지 + `[[concept]]`로 위임하고, "
            "상세는 해당 파생 concept 본문에 쓴다. 단 판단 문장 안에 개념 요지가 인용되는 것은 허용된다.\n\n"
            "## 파생 concept 본문 작성법\n"
            "- concept 파생 본문은 **개념 하나만**(원자성) 담고, **함께 주어진 concept 템플릿 뼈대"
            "(정의/맥락/근거 출처)를 그대로 따라** draft_markdown을 채운다.\n"
            "- **supplement 대상 제한**: 보충 대상은 `permanent/concepts/`의 **concept 노트만**이다 "
            "— reference/permanent/baseline은 보충 대상이 아니다(reference는 출처 기록이라 고정, "
            "개념 성장·stale은 concept에서만 일어난다). concept가 아닌 문서를 supplement로 고르면 "
            "승인 시 거부된다(SUPPLEMENT_TARGET_NOT_CONCEPT).\n"
            "- **supplement 자발 제안**: 전문이 주입된 기존 concept에 대해 이 출처가 새 정보"
            "(사실·사례·수치·상세)를 담고 있으면 supplement_existing_concept를 **자발적으로 제안하라** "
            "— 링크만 걸고 넘어가지 마라. 새 정보가 없으면 링크만으로 충분하다.\n"
            "- **supplement(modify) 규율**: 주입된 기존 전문의 내용을 보존하며 새 출처의 내용을 "
            "합류시켜라. 지적·추가분 외에는 갈아엎지 마라(기존 서술 보존).\n\n"
            "## project(회사 프로젝트) 팬아웃 분기\n"
            "destination이 project면 산출을 한 장이 아니라 회사 프로젝트로 팬아웃한다(AXKG-SPEC-014). "
            "resource/area 분기(위)는 그대로 두고, project일 때만 아래를 따른다.\n"
            "- **main_document = 원본요약**: 회사 docx 요구 전체를 project_source_summary 뼈대"
            "(요구 개요/기능 목록/원본 맥락/연결)에 맞춰 document_draft로 낸다. `## 기능 목록`은 아래에서 "
            "분해한 각 기능을 `[[기능-stem]]`으로 링크해 baseline↔spec 그래프를 연다.\n"
            "- **요구를 기능 단위로 분해**: 요구 1항목 = 기능정의서 1장이다. 각 기능을 project_feature_spec "
            "뼈대(요구 배경~수용 기준·`## 8. 연결`)에 맞춘 `create_feature_spec` 파생으로 낸다.\n"
            "- **기능 dedup(같은 corp 한정)**: 같은 회사에 이미 있는 기능정의서와 매칭되면 신규 생성이 "
            "아니라 `supplement_existing_feature`로 그 기존 spec을 보강한다(target_stem에 대상 기능정의서 "
            "stem 지목, 신규 생성 X). 매칭이 모호하면 신규 `create_feature_spec`으로 안전 폴백한다. 회사를 "
            "넘는 spec 재사용·통합은 하지 않는다.\n"
            "- **차용 링크**: 각 기능정의서의 `## 8. 연결`에는 원본요약 링크(`[[{corp}-원본요약]]`)와 함께 "
            "retriever + documents index로 훑은 ax-graph 기존 역량 차용 링크(`[[graph-chat]]` 등)를 "
            "제안한다. 빈 `[[ ]]`는 두지 않는다.\n"
            "- **요청부서·요청 이력을 넣지 않는다** — 기능은 프로젝트의 기능 카탈로그이지 특정 부서 "
            "귀속이 아니다(기능 dedup, 부서 무관 — AXKG-DEC-007).\n\n"
            "본문 초안 외에, 기존 문서 보강/새 concept/프로젝트 baseline이 필요하면 "
            "derived_suggestions로 제안하라. **파생 제안도 draft_markdown(문서 전문)이 필수다.**\n"
            "- create류(`create_new_concept`/`create_project_baseline`): frontmatter+본문을 갖춘 "
            "완전한 문서 전문을 draft_markdown에 쓰고, 파일명 stem을 filename_candidate로 낸다"
            "(템플릿·링크 규칙 준수).\n"
            "- modify(`supplement_existing_concept`): 함께 주입된 **대상 문서 전문**에 보충을 반영한 "
            "**수정된 전문**을 draft_markdown에 쓰고(diff/patch가 아니라 전문 overwrite), 보충 대상 "
            "concept의 stem을 target_stem으로 지목한다. 무엇을 어떻게 보충했는지 diff_preview에 요지로 "
            "남긴다. 전문이 주입되지 않은 문서는 modify로 제안하지 않는다.\n"
            "- **경로는 시스템이 결정한다**: 디렉토리를 정하려 하지 마라. main과 create 파생은 "
            "filename_candidate에 **파일명 stem만**(디렉토리·확장자 없이) 내고, supplement는 "
            "target_stem에 **대상 concept의 stem만** 낸다. 시스템이 문서 타입에 맞는 디렉토리를 붙여 "
            "최종 경로를 조립한다.\n"
            "출력은 output_schema를 따르는 JSON 하나로만 하고, "
            "코드펜스(```)로 감싸지 말고 문자열 안의 줄바꿈·큰따옴표는 정확히 이스케이프한다. "
            "JSON 앞뒤에 어떤 설명·해설 문장도 붙이지 마라 — 응답의 첫 글자는 `{`, 마지막 글자는 "
            "`}`여야 한다."
        ),
        "output_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["document_draft", "derived_suggestions"],
            "properties": {
                "document_draft": {
                    "type": "object",
                    "additionalProperties": False,
                    # target_path는 AI가 내지 않는다 — 디렉토리는 시스템이 조립한다(T-040).
                    "required": ["filename_candidate", "markdown_full"],
                    "properties": {
                        "filename_candidate": {"type": "string", "minLength": 1},
                        "markdown_full": {"type": "string", "minLength": 1},
                        "links": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["target", "edge_type", "link_reason"],
                                "properties": {
                                    "target": {"type": "string"},
                                    "edge_type": {"type": "string", "enum": ["assoc", "lineage"]},
                                    "link_reason": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                "derived_suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        # 경로 대신: create류=filename_candidate(파일명), supplement=target_stem
                        # (대상 concept 지목). 디렉토리/경로는 시스템이 조립한다(T-040).
                        "required": [
                            "suggestion_type",
                            "draft_markdown",
                            "link_reason",
                        ],
                        "properties": {
                            "suggestion_type": {
                                "type": "string",
                                "enum": [
                                    "supplement_existing_concept",
                                    "create_new_concept",
                                    "create_project_baseline",
                                    # 회사 프로젝트 팬아웃 기능정의서 (AXKG-SPEC-014, WP11).
                                    # v1은 create_feature_spec(신규만) 사용. supplement_existing_feature는
                                    # enum 값만 존재하고 dedup 로직 배선은 후속 WP.
                                    "create_feature_spec",
                                    "supplement_existing_feature",
                                ],
                            },
                            "filename_candidate": {"type": "string", "minLength": 1},
                            "target_stem": {"type": "string", "minLength": 1},
                            "draft_markdown": {"type": "string", "minLength": 1},
                            "diff_preview": {"type": "string"},
                            "file_action": {
                                "type": "string",
                                "enum": [
                                    "create_markdown",
                                    "overwrite_markdown",
                                ],
                            },
                            "target_document_id": {"type": "string"},
                            "summary": {"type": "string"},
                            "link_reason": {"type": "string", "minLength": 1},
                        },
                        # supplement→target_stem 필수 / create류→filename_candidate 필수.
                        "allOf": [
                            {
                                "if": {
                                    "properties": {
                                        "suggestion_type": {
                                            "const": "supplement_existing_concept"
                                        }
                                    }
                                },
                                "then": {"required": ["target_stem"]},
                                "else": {"required": ["filename_candidate"]},
                            }
                        ],
                    },
                },
            },
        },
    },
    {
        # plan-then-fanout ① (AXKG-DEC-008/WORK-012): docx → 원본요약 + 기능목록(plan).
        # 무거운 기능정의서 본문은 여기서 쓰지 않는다 — 가볍고 빠른 산출(발주서).
        "key": "plan_project",
        "name": "Project Plan",
        "description": "plan-then-fanout ① — docx→원본요약+기능목록(plan) 산출 (AXKG-DEC-008)",
        "prompt_text": (
            "당신은 기업 AX 전환 요구 docx를 회사 프로젝트로 정리하는 기획자다. 목표는 두 가지를 "
            "가볍게 산출하는 것이다 — (1) **원본요약**(회사가 뭘 요구했나, project_source_summary "
            "뼈대) 1장, (2) **기능목록 plan**(요구를 기능 단위로 쪼갠 발주서). **개별 기능정의서 본문은 "
            "여기서 쓰지 않는다** — 그건 이후 기능별 독립 task가 맡는다.\n\n"
            "먼저 작업 프로젝트의 `context/documentation-guide.md`와 `context/document-link-rules.md`를 "
            "읽고 원본요약 규칙을 따르라. 함께 주어진 원본요약 템플릿(project_source_summary) 뼈대의 "
            "frontmatter·섹션 구조를 그대로 따르고, docx 원문 근거 안에서만 채워라.\n\n"
            "## document_draft = 원본요약(main)\n"
            "- 회사가 전체적으로 뭘 원하는지 `## 요구 개요`에 몇 문장으로.\n"
            "- `## 기능 목록`은 아래 plan의 각 기능을 `[[기능-stem]]`(plan의 filename_candidate와 동일 "
            "stem)으로 나열해 baseline↔spec 그래프를 연다. 빈 `[[ ]]`는 금지.\n"
            "- 경로/디렉토리는 시스템이 조립한다 — filename_candidate에 파일명 stem만 낸다.\n\n"
            "## plan = 기능목록(발주서)\n"
            "- docx의 요구를 **기능 단위로 분해**해 plan 배열로 낸다. 요구 1항목 = plan 1개 = 기능정의서 "
            "1장. 중복·너무 잘게 쪼갠 항목을 만들지 말고 실제 기능 경계로 나눈다.\n"
            "- 각 항목: `seq`(1부터), `feature_name`(명사구 15자 이내), `filename_candidate`(파일명 "
            "stem, 영문 kebab 권장, 원본요약 `## 기능 목록`의 `[[stem]]`과 정확히 일치), `summary`"
            "(그 기능이 뭔지 1~2문장 — 이후 기능정의서 생성 task의 발주 요지).\n\n"
            "출력은 output_schema를 따르는 JSON 하나로만 한다(코드펜스·해설 없이 JSON 객체만). "
            "JSON 앞뒤에 어떤 설명·해설 문장도 붙이지 마라 — 응답의 첫 글자는 `{`, 마지막 글자는 "
            "`}`여야 한다."
        ),
        "output_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["document_draft", "plan"],
            "properties": {
                "document_draft": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["filename_candidate", "markdown_full"],
                    "properties": {
                        "filename_candidate": {"type": "string", "minLength": 1},
                        "markdown_full": {"type": "string", "minLength": 1},
                        "links": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["target", "edge_type", "link_reason"],
                                "properties": {
                                    "target": {"type": "string"},
                                    "edge_type": {
                                        "type": "string",
                                        "enum": ["assoc", "lineage"],
                                    },
                                    "link_reason": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                "plan": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["seq", "feature_name", "filename_candidate", "summary"],
                        "properties": {
                            "seq": {"type": "integer", "minimum": 1},
                            "feature_name": {"type": "string", "minLength": 1},
                            "filename_candidate": {"type": "string", "minLength": 1},
                            "summary": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
        },
    },
    {
        # plan-then-fanout ② (AXKG-DEC-008/WORK-012): plan 1개 기능 → 기능정의서 1장.
        # 작고 집중된 출력이라 600초로 충분하고 병렬·기능별 재시도가 가능하다.
        "key": "generate_feature_spec",
        "name": "Feature Spec",
        "description": "plan-then-fanout ② — plan 1항목→기능정의서 1장 생성 (AXKG-DEC-008)",
        "prompt_text": (
            "당신은 회사 프로젝트의 **기능 하나**를 기능정의서 1장으로 쓰는 작성자다. 주어진 것은 "
            "(1) docx 원문, (2) 이 task가 맡은 **기능 항목**(plan: seq/기능명/요지), (3) 원본요약 stem, "
            "(4) 연결 후보 컨텍스트다. **이 한 기능에만 집중**해 기능정의서 1장을 낸다 — 다른 기능은 "
            "다루지 마라.\n\n"
            "먼저 `context/documentation-guide.md`와 `context/document-link-rules.md`를 읽어라. 함께 "
            "주어진 기능정의서 템플릿(project_feature_spec) 뼈대의 frontmatter·섹션 구조(요구 배경~수용 "
            "기준·`## 8. 연결`)를 그대로 따르고, docx 원문 근거 안에서만 채워라(원문에 없는 사실 금지).\n\n"
            "## 규칙\n"
            "- **한 기능만**: 맡은 plan 기능명/요지에 해당하는 요구만 정의서로 쓴다.\n"
            "- **경로는 시스템이 조립**한다 — filename_candidate에 파일명 stem만 낸다(원본요약 `## 기능 "
            "목록`의 `[[stem]]`과 동일 stem을 쓰라 — 함께 주어진 plan의 filename_candidate).\n"
            "- **`## 8. 연결`**: 원본요약 링크(`[[원본요약-stem]]`)를 반드시 걸고, 연결 후보 스냅샷 안의 "
            "ax-graph 기존 역량 차용 링크(`[[graph-chat]]` 등)를 제안한다. 스냅샷 밖 target은 만들지 "
            "말고, 빈 `[[ ]]`는 두지 마라.\n"
            "- **요청부서·요청 이력을 넣지 않는다**(기능은 프로젝트의 기능 카탈로그, 부서 무관).\n\n"
            "출력은 output_schema를 따르는 JSON 하나로만 한다(코드펜스·해설 없이 JSON 객체만, "
            "document_draft 하나). JSON 앞뒤에 어떤 설명·해설 문장도 붙이지 마라 — 응답의 첫 글자는 "
            "`{`, 마지막 글자는 `}`여야 한다."
        ),
        "output_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["document_draft"],
            "properties": {
                "document_draft": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["filename_candidate", "markdown_full"],
                    "properties": {
                        "filename_candidate": {"type": "string", "minLength": 1},
                        "markdown_full": {"type": "string", "minLength": 1},
                        "links": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["target", "edge_type", "link_reason"],
                                "properties": {
                                    "target": {"type": "string"},
                                    "edge_type": {
                                        "type": "string",
                                        "enum": ["assoc", "lineage"],
                                    },
                                    "link_reason": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        },
    },
    {
        "key": "graph_rag_chat",
        "name": "Graph RAG Chat",
        "description": "④ chat 스테이지 — retriever evidence 기반 답변 (AXKG-SPEC-006)",
        "prompt_text": (
            "당신은 사용자의 지식 그래프를 근거로 답하는 어시스턴트다. 질문, (있으면) 선택된 "
            "문서 컨텍스트, retriever가 고른 evidence 문서 발췌, 세션 대화 이력이 주어진다.\n\n"
            "먼저 작업 프로젝트의 `context/graph-chat-rules.md`를 읽고, 그 대원칙(근거는 주입된 "
            "graph context뿐·근거 부족 시 추측 금지)·컨텍스트 우선순위·하지 말 것을 따르라.\n\n"
            "## 응답 구성\n"
            "- answer: 질문에 대한 답 — 어떤 문서를 근거로 했는지 본문에서 드러나게 쓴다.\n"
            "- evidence: **실제로 근거로 쓴 문서만** 담는다(검색됐지만 답에 안 쓴 것은 제외). 각 "
            "항목은 그 문서의 stem과, 왜 근거가 되는지 reason을 반드시 포함한다.\n"
            "- missing_context: 근거가 부족했던 부분과 답하려면 무엇이 필요한지. 검색된 문서로 답할 "
            "수 없으면 answer를 근거 부족으로 남기고 여기에 구체적으로 적는다(파이프라인이 이를 "
            "INSUFFICIENT_GRAPH_CONTEXT로 표면화한다).\n"
            "- suggested_actions: 사용자가 다음에 할 만한 행동(문서 열기, 관련 소스 수집 등)을 짧게.\n\n"
            "출력은 output_schema를 따르는 JSON 하나로만 한다(코드펜스·해설 없이 JSON 객체만). "
            "JSON 앞뒤에 어떤 설명·해설 문장도 붙이지 마라 — 응답의 첫 글자는 `{`, 마지막 글자는 "
            "`}`여야 한다."
        ),
        "output_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["answer", "evidence"],
            "properties": {
                "answer": {"type": "string", "minLength": 1},
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["stem", "reason"],
                        "properties": {
                            "stem": {"type": "string"},
                            "title": {"type": "string"},
                            "excerpt": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                    },
                },
                "missing_context": {"type": "array", "items": {"type": "string"}},
                "suggested_actions": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
]

# ---------------------------------------------------------------------------
# document_templates (AXKG-SPEC-010, AXKG-DEC-005). body는 frontmatter + 섹션 뼈대.
# main 3종(reference/permanent/project_source_summary)은 destination→key 매핑으로 주입.
# concept는 파생지식 전용 뼈대 — destination 매핑이 아니라 문서화③ 조립에 고정 동봉된다
# (PLAN-009-T-027: concept 골격도 "고정 산출 타입 md 뼈대=템플릿" 이라 프롬프트 텍스트에서
# 템플릿으로 이사. Layer Taxonomy 정합, SPEC-011 §4).
# project 팬아웃(AXKG-DEC-007/SPEC-014)은 종전 단일 project_baseline을 project_source_summary
# (원본요약, main)·project_feature_spec(기능정의서, 파생·문서화③ 고정 동봉) 2종으로 대체한다.
# project_baseline 시드는 매핑 전환(후속 로직 태스크) 전까지 남겨둔다 — 이 태스크는 새 2종 추가만.
# ---------------------------------------------------------------------------

TEMPLATE_SEEDS: list[dict] = [
    {
        "key": "reference",
        "name": "Reference Document",
        "body": """---
type: reference
title: ""
source: ""
aliases: []
tags: []
up: []
---

# {title}

## 요약

<!-- 1~3문장 — 이 문서를 열지 판단하는 용도. 핵심 내용의 재탕이 아니다. -->

## 핵심 내용

<!-- 원문(body_markdown) 구조를 따라 ### 서브섹션으로 적응형 분할. 개념 상세는 [[concept]]로 위임. -->

## 연결

<!-- 실제로 채운 링크만 남긴다. 빈 [[]]는 깨진 링크가 되므로 미사용 불릿은 삭제한다. -->
- [[stem]] — 관계 이유
""",
    },
    {
        "key": "permanent",
        "name": "Permanent Note",
        "body": """---
type: permanent
title: ""
aliases: []
tags: []
up: []
---

# {title}

## 영역 주제

<!-- 이 종합 노트가 다루는 영역/주제 -->

## 현재 나의 종합·판단

<!-- 구성 개념들을 엮은 내 판단·전략. 개념 상세는 재서술하지 말고 [[concept]]로 위임한다.
     판단 문장 안에 개념 요지가 인용되는 것은 허용된다. -->

## 구성 개념

<!-- up:에 넣은 stem은 본문 [[]]에도 있어야 한다. 미사용 불릿은 삭제. -->
- [[concept]] — 이 판단에서의 역할

## 열린 질문

<!-- 아직 해소되지 않은 질문 -->
""",
    },
    {
        "key": "concept",
        "name": "Concept Note",
        "body": """---
type: concept
title: ""
aliases: []
tags: []
up: []
---

# {title}

## 정의

<!-- 이 개념이 무엇인지 한 줄 정의(원자성 — 개념 하나만). -->

## 맥락

<!-- 이 개념이 놓이는 맥락·언제 쓰이는지. -->

## 근거 출처

<!-- 이 개념이 어디서 왔는지 근거 출처. 미사용 불릿은 삭제. -->
- [[stem]] — 근거 이유
""",
    },
    {
        "key": "project_baseline",
        "name": "Project Baseline",
        "body": """---
type: baseline
title: ""
product: ""
status: draft
aliases: []
tags: []
up: []
---

# {title}

## 배경

<!-- 이 프로젝트/제안이 나온 배경 -->

## 문제 정의

## 목표

## 범위

- In scope:
- Out of scope:

## 연결

<!-- 실제로 채운 링크만 남긴다. 빈 [[]]는 깨진 링크가 되므로 미사용 불릿은 삭제한다. -->
- [[stem]] — 관계 이유
""",
    },
    {
        # AXKG-SPEC-010 §4 / AXKG-SPEC-014 — project 팬아웃 원본요약(main, baseline/).
        # destination project→key 매핑으로 main_document에 주입된다. document_type=baseline.
        "key": "project_source_summary",
        "name": "Project Source Summary",
        "body": """---
type: baseline
title: ""
aliases: []
tags: []
up: []
---

# {title}

## 요구 개요

<!-- 이 회사가 전체적으로 뭘 원하나 — docx 요구의 전체 그림을 몇 문장으로. -->

## 기능 목록

<!-- 추출된 기능 N개를 각각 기능정의서 stem으로 링크(baseline↔spec 그래프 연결).
     빈 [[]]는 금지 — 실제 팬아웃되는 기능만 남긴다. 요구 1항목 = 기능정의서 1장. -->
- [[기능-stem]] — 이 기능이 무엇인지 한 줄

## 원본 맥락

<!-- 이 요구가 담긴 docx의 배경 요지(어떤 회사가 왜 요청했나). -->

## 연결

<!-- origin 첨부 원본·기능 spec 링크. 미사용 불릿은 삭제. -->
- [[stem]] — 관계 이유
""",
    },
    {
        # AXKG-SPEC-010 §4 / AXKG-SPEC-014 — project 팬아웃 기능정의서(파생, spec/).
        # destination 매핑 없이 문서화③ 조립 시 고정 동봉으로 주입되고, derived_suggestions[]의
        # create_feature_spec/supplement_existing_feature로 산출된다. document_type=feature_spec.
        # 요청부서·요청 이력 필드는 두지 않는다(기능 dedup, 부서 무관 — AXKG-DEC-007).
        "key": "project_feature_spec",
        "name": "Project Feature Spec",
        "body": """---
type: feature_spec
title: ""                 # 기능명. 명사구 15자 이내
aliases: []               # stem resolution/역링크용 (시드 공통)
tags: []
up: []                    # 계보 링크 — 회사 원본요약을 up으로
feature_id: ""            # {corp}-F-NN
corp: ""
status: draft             # draft|reviewing|confirmed
priority: ""              # high|mid|low
---

# {기능명}

> 한 줄 정의: "누가 / 무엇을 하면 / 무엇을 얻는다" 1문장. 형용사·감상 금지.

## 1. 요구 배경
- **현재 불편(as-is)**: 지금 뭐가 문제인지 2~3문장. docx 원문 표현을 최소 1개 큰따옴표 인용.
- **필요 이유**: 이 기능이 그 불편을 어떻게 없애는지 1문장.

## 2. 기능 정의
- **핵심 동작**: 동사로 시작하는 불릿 3~5개. 각 불릿은 시스템이 하는 일 1개. 추상어("잘","효율적으로") 금지.

## 3. 유저 플로우 (반드시 표, 케이스별)
정상 1건 + 예외/대안 최소 1건.

| 케이스 | 행동 (사용자가 한다) | 과정 (시스템이 처리) | 결과 (산출물) |
|---|---|---|---|
| 정상 |  |  |  |
| 예외 |  |  |  |

## 4. 예시 (최소 2개, 실제 문장 인용)
- **입력**: docx의 실제 사용자 문장을 큰따옴표로.
- **기대 출력**: 그 입력에 시스템이 내놔야 할 결과.

## 5. 상세 요구 (번호 목록, "~해야 한다")
1. …해야 한다.

## 6. 다루는 데이터 (해당 시)
- 입력/저장/출력 데이터 종류. 없으면 "해당 없음".

## 7. 수용 기준 (체크박스 최소 3개, 참/거짓 판정 가능)
- [ ] …
- [ ] …
- [ ] …

## 8. 연결
<!-- 그래프 엣지는 본문 [[]]가 단일 소스(AXKG-SPEC-005). up:에 넣은 stem은 여기 본문에도. 빈 [[]] 금지. -->
- [[{corp}-원본요약]] — 이 기능이 나온 회사 요구 원본
- [[graph-chat]] — (해당 시) ax-graph 기존 역량 재사용
""",
    },
]

# ---------------------------------------------------------------------------
# ai_task_definitions 6종 (database README "Initial Seeds" 표).
# template_key는 null로 둔다 — documentation_gate의 템플릿은 destination→key 매핑
# (resource→reference, area→permanent, project→project_baseline, AXKG-SPEC-010)을
# context builder가 적용해 선택한다 (AXKG-DEC-005/SPEC-011).
# destination별 템플릿 선택은 실행 시 context builder 소관이라 기본값은 reference.
# ---------------------------------------------------------------------------

TASK_DEFINITION_SEEDS: list[dict] = [
    {
        "key": "collect_source_summary",
        "display_name": "소스 요약 수집",
        "description": "① 요약 스테이지: SourceMaterial 수집 + 요약 (AXKG-SPEC-003/011/012)",
        "handler_kind": "source_summary",
        "prompt_key": "source_summary",
        "template_key": None,
    },
    {
        "key": "generate_classification_gate",
        "display_name": "분류 게이트 생성",
        "description": "② 분류 스테이지: PARA destination 제안 v1 (AXKG-SPEC-001/002)",
        "handler_kind": "classification_gate",
        "prompt_key": "classification_gate",
        "template_key": None,
    },
    {
        "key": "regenerate_classification_gate",
        "display_name": "분류 게이트 재생성",
        "description": "② 분류 스테이지: feedback 반영 재생성 (AXKG-SPEC-002)",
        "handler_kind": "classification_gate",
        "prompt_key": "classification_gate",
        "template_key": None,
    },
    {
        "key": "generate_documentation_gate",
        "display_name": "문서화 게이트 생성",
        "description": "③ 문서초안 스테이지: 템플릿+연결 후보 컨텍스트로 초안 v1 (AXKG-SPEC-004/011)",
        "handler_kind": "documentation_gate",
        "prompt_key": "documentation_gate",
        "template_key": None,
        # 라이브 실측(2026-07-09): 가이드 Read 2턴+검증성 no-op 턴에 max_turns=3/6이 소진돼
        # 최종 JSON 턴이 잘림(error_max_turns) → 12로 상향. 재생성(stale 3입력+연결 후보 전문 주입)
        # 실행이 300s를 초과 → timeout_sec 600으로 상향(폭주 방어는 timeout이 계속 담당).
        "default_provider_options": {"max_turns": 12},
        "default_options": {"timeout_sec": 600},
    },
    {
        "key": "regenerate_documentation_gate",
        "display_name": "문서화 게이트 재생성",
        "description": "③ 문서초안 스테이지: feedback 반영 재생성 (AXKG-SPEC-002/004)",
        "handler_kind": "documentation_gate",
        "prompt_key": "documentation_gate",
        "template_key": None,
        # generate_documentation_gate와 동일 근거(2026-07-09 라이브 실측).
        "default_provider_options": {"max_turns": 12},
        "default_options": {"timeout_sec": 600},
    },
    {
        "key": "graph_rag_chat",
        "display_name": "그래프 채팅",
        "description": "④ chat 스테이지: Graph RAG 답변 생성 (AXKG-SPEC-006)",
        "handler_kind": "graph_rag_chat",
        "prompt_key": "graph_rag_chat",
        "template_key": None,
        # 전역 기본 max_turns=3인데 chat만 더 많은 turn이 필요(SPEC-007 Rule).
        "default_provider_options": {"max_turns": 6},
    },
    {
        # plan-then-fanout ① (AXKG-DEC-008/WORK-012): docx→원본요약+plan. 가벼운 산출이나
        # 가이드 Read 턴 여유로 문서화와 동일 max_turns 12/timeout 600을 준다.
        "key": "plan_project",
        "display_name": "프로젝트 plan 산출",
        "description": "plan-then-fanout ①: docx→원본요약+기능목록(plan) (AXKG-DEC-008)",
        "handler_kind": "plan_project",
        "prompt_key": "plan_project",
        "template_key": None,
        "default_provider_options": {"max_turns": 12},
        "default_options": {"timeout_sec": 600},
    },
    {
        # plan-then-fanout ② (AXKG-DEC-008/WORK-012): 기능 1개 생성. 작은 출력이라 600초로 충분,
        # 병렬·기능별 재시도로 단일-task 타임아웃/거대출력 파싱실패를 해소한다.
        "key": "generate_feature_spec",
        "display_name": "기능정의서 생성",
        "description": "plan-then-fanout ②: plan 1항목→기능정의서 1장 (AXKG-DEC-008)",
        "handler_kind": "feature_spec",
        "prompt_key": "generate_feature_spec",
        "template_key": None,
        "default_provider_options": {"max_turns": 12},
        "default_options": {"timeout_sec": 600},
    },
]


# 0015 당시(role/is_active 컬럼 도입 이전) users 컬럼만 가진 경량 테이블.
# User 모델을 직접 쓰면 Core insert가 모델의 Python-side default(role/is_active)를
# INSERT에 끼워넣어 0015 단계에서 "column does not exist"로 깨진다 — 이를 회피한다.
_users_0015 = sa.table(
    "users",
    sa.column("email", sa.Text),
    sa.column("password_hash", sa.Text),
    sa.column("display_name", sa.Text),
)


def seed_base_user(conn: Connection) -> None:
    """role 컬럼 도입(0019) 이전의 단일 seed 계정 — 마이그레이션 0015 back-compat 전용.

    role/is_active를 참조하지 않는다(그 단계엔 컬럼이 없다). 로스터·role upsert는 0019가
    seed_users로 전담한다. 테스트/현행 seed는 seed_all(→seed_users)을 쓴다.
    """
    exists = conn.execute(
        sa.select(_users_0015.c.email).where(_users_0015.c.email == SEED_USER_EMAIL)
    ).first()
    if exists:
        return
    conn.execute(
        sa.insert(_users_0015).values(
            email=SEED_USER_EMAIL,
            password_hash=hash_password(SEED_USER_PASSWORD),
            display_name="이건학",
        )
    )


def seed_users(conn: Connection) -> None:
    """활성 로스터를 email 기준 멱등으로 upsert한다 (AXKG-SPEC-008 Seed Data).

    role/is_active 컬럼이 있는 스키마 전제(마이그레이션 0019 이후 / 테스트 create_all).
    - 신규: 기본 비밀번호 `1234`로 생성.
    - 기존: role/is_active/display_name만 갱신(비밀번호는 보존 — 운영 중 변경 덮어쓰기 방지).
      → 기존 seed 계정 kknaks가 admin으로 흡수된다.
    """
    for member in USER_ROSTER:
        exists = conn.execute(
            sa.select(User.id).where(User.email == member["email"])
        ).first()
        if exists:
            conn.execute(
                sa.update(User)
                .where(User.email == member["email"])
                .values(
                    role=member["role"],
                    is_active=True,
                    display_name=member["display_name"],
                )
            )
            continue
        conn.execute(
            sa.insert(User).values(
                email=member["email"],
                password_hash=hash_password(SEED_USER_PASSWORD),
                display_name=member["display_name"],
                role=member["role"],
                is_active=True,
            )
        )


def seed_settings(conn: Connection) -> None:
    exists = conn.execute(sa.select(Setting.key).where(Setting.key == "ai_provider")).first()
    if exists:
        return
    conn.execute(sa.insert(Setting).values(key="ai_provider", value=AI_PROVIDER_DEFAULT))


def seed_prompts(conn: Connection) -> None:
    for seed in PROMPT_SEEDS:
        exists = conn.execute(sa.select(Prompt.id).where(Prompt.key == seed["key"])).first()
        if exists:
            continue
        prompt_id = uuid.uuid4()
        version_id = uuid.uuid4()
        conn.execute(
            sa.insert(Prompt).values(
                id=prompt_id,
                key=seed["key"],
                name=seed["name"],
                description=seed["description"],
                active_version_id=None,
            )
        )
        conn.execute(
            sa.insert(PromptVersion).values(
                id=version_id,
                prompt_id=prompt_id,
                version=1,
                prompt_text=seed["prompt_text"],
                output_schema=seed["output_schema"],
            )
        )
        conn.execute(
            sa.update(Prompt).where(Prompt.id == prompt_id).values(active_version_id=version_id)
        )


def seed_templates(conn: Connection) -> None:
    for seed in TEMPLATE_SEEDS:
        exists = conn.execute(
            sa.select(DocumentTemplate.id).where(DocumentTemplate.key == seed["key"])
        ).first()
        if exists:
            continue
        template_id = uuid.uuid4()
        version_id = uuid.uuid4()
        conn.execute(
            sa.insert(DocumentTemplate).values(
                id=template_id, key=seed["key"], name=seed["name"], active_version_id=None
            )
        )
        conn.execute(
            sa.insert(DocumentTemplateVersion).values(
                id=version_id, template_id=template_id, version=1, body=seed["body"]
            )
        )
        conn.execute(
            sa.update(DocumentTemplate)
            .where(DocumentTemplate.id == template_id)
            .values(active_version_id=version_id)
        )


def seed_task_definitions(conn: Connection) -> None:
    for seed in TASK_DEFINITION_SEEDS:
        exists = conn.execute(
            sa.select(AiTaskDefinition.id).where(AiTaskDefinition.key == seed["key"])
        ).first()
        if exists:
            continue
        conn.execute(
            sa.insert(AiTaskDefinition).values(
                key=seed["key"],
                display_name=seed["display_name"],
                description=seed["description"],
                handler_kind=seed["handler_kind"],
                prompt_key=seed["prompt_key"],
                template_key=seed["template_key"],
                default_provider=None,
                default_model=None,
                default_options=seed.get("default_options", {}),
                default_provider_options=seed.get("default_provider_options", {}),
                enabled=True,
            )
        )


def seed_all(conn: Connection) -> None:
    seed_users(conn)
    seed_settings(conn)
    seed_prompts(conn)
    seed_templates(conn)
    seed_task_definitions(conn)


async def _amain() -> None:
    from axkg.core.database import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(seed_all)
    await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_amain())
