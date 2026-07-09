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

AI_PROVIDER_DEFAULT = {
    "provider": "claude",
    "model": None,
    "options": {"timeout_sec": 300, "resume": False},
    "provider_options": {"max_turns": 3, "effort": "medium"},
    "task_overrides": {},
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
            "(SourceMaterial)을 읽고, 나중에 PARA 분류와 문서화에 쓸 수 있는 요약 카드를 만든다. "
            "먼저 작업 프로젝트의 `context/source-summary-guide.md`를 읽고, 그 지침(adapter별 원문 "
            "성격·본문 선별·출력 계약·특수 케이스)에 따라 요약하라. "
            "원문에 없는 사실을 추가하지 말고, 저자의 주장과 근거를 구분해서 압축하라.\n\n"
            "출력은 반드시 output_schema를 따르는 JSON 하나로만 한다. "
            "`title`은 원문 제목을 우선하되 없으면 내용 기반으로 짓고, `summary`는 3~6문장, "
            "`keywords`는 핵심 주제어 3~10개, `source_type`은 원문의 매체 성격"
            "(article/video/paper/docs/thread 등)을 한 단어로 적는다."
        ),
        "output_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "summary", "keywords", "source_type"],
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
            "진행 중인 산출물에 붙는 것이면 project, 지속 관리 영역이면 area, 참고 자료면 "
            "resource, 보관만 할 것이면 archive다. 그래프/기존 문서 컨텍스트는 이 단계에서 "
            "제공되지 않으며 연결 제안은 문서화 스테이지의 소관이다.\n\n"
            "출력은 output_schema를 따르는 JSON 하나로만 한다. `destination_reason`에는 "
            "사용자가 게이트에서 승인/반려를 판단할 수 있게 근거를 2~3문장으로 쓰고, "
            "`confidence`는 0~1 사이 수치로 스스로의 확신도를 적는다."
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
            "당신은 승인된 destination에 맞춰 Markdown 지식 문서 초안을 쓰는 작성자다. "
            "함께 주어진 템플릿 뼈대의 frontmatter와 섹션 구조를 그대로 따르고, source 요약과 "
            "원문 근거 안에서만 내용을 채워라. 연결(`up:`과 본문 `[[ ]]` wikilink)은 함께 "
            "주어진 retriever 후보와 documents index 스냅샷 안의 stem/alias로만 만들고, "
            "채택한 모든 연결에 link_reason을 남겨라. 스냅샷에 없는 target은 만들지 않는다.\n\n"
            "본문 초안 외에, 기존 문서 보강/새 concept/프로젝트 baseline이 필요하면 "
            "derived_suggestions로 제안하라. 출력은 output_schema를 따르는 JSON 하나로만 한다."
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
                    "required": ["filename_candidate", "target_path", "markdown_full"],
                    "properties": {
                        "filename_candidate": {"type": "string", "minLength": 1},
                        "target_path": {"type": "string", "minLength": 1},
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
                        "additionalProperties": True,
                        "required": ["suggestion_type", "target_path", "link_reason"],
                        "properties": {
                            "suggestion_type": {
                                "type": "string",
                                "enum": [
                                    "supplement_existing_concept",
                                    "create_new_concept",
                                    "create_project_baseline",
                                ],
                            },
                            "target_path": {"type": "string", "minLength": 1},
                            "file_action": {
                                "type": "string",
                                "enum": [
                                    "create_markdown",
                                    "patch_markdown",
                                    "update_frontmatter",
                                ],
                            },
                            "summary": {"type": "string"},
                            "link_reason": {"type": "string", "minLength": 1},
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
            "## 대원칙\n"
            "- 답변의 근거는 **주입된 graph context뿐이다**: retriever가 검색한 문서, 그 연결 "
            "엣지, (선택 노드가 있으면) 그 neighborhood와 edge path. 이 발췌 밖의 내용으로 답을 "
            "채우지 않는다.\n"
            "- **근거가 부족하면 추측하지 않는다.** 검색된 문서로 답할 수 없으면 단정하지 말고, "
            "answer를 근거 부족으로 남기고 무엇이 더 있으면 답할 수 있는지 missing_context에 "
            "구체적으로 적는다(파이프라인이 이를 INSUFFICIENT_GRAPH_CONTEXT로 표면화한다).\n"
            "- 이 chat의 가치는 일반 지식 응답이 아니라 '내 그래프에 무엇이 있고 어떻게 연결되는가'를 "
            "근거로 답하는 것이다. 그래프에 없는 일반론으로 빈틈을 메우지 않는다.\n\n"
            "## 응답 구성\n"
            "- answer: 질문에 대한 답 — 어떤 문서를 근거로 했는지 본문에서 드러나게 쓴다.\n"
            "- evidence: **실제로 근거로 쓴 문서만** 담는다(검색됐지만 답에 안 쓴 것은 제외). 각 "
            "항목은 그 문서의 stem과, 왜 근거가 되는지 reason을 반드시 포함한다.\n"
            "- missing_context: 근거가 부족했던 부분과 답하려면 무엇이 필요한지.\n"
            "- suggested_actions: 사용자가 다음에 할 만한 행동(문서 열기, 관련 소스 수집 등)을 짧게.\n\n"
            "## 컨텍스트 우선순위\n"
            "- 사용자가 그래프에서 **노드를 선택한 상태**면 그 노드의 neighborhood가 우선 컨텍스트다 "
            "— 질문이 모호하면 선택 노드 관점으로 해석한다.\n"
            "- 이어지는 대화에서는 이전 턴의 맥락을 유지하되, 근거는 매번 현재 검색 결과에서 다시 댄다.\n\n"
            "## 하지 말 것\n"
            "- 문서를 생성·수정·분류하지 않는다 — chat은 조회 전용이다.\n"
            "- evidence에 없는 문서 제목/내용을 지어내지 않는다.\n"
            "- 그래프 밖 최신 정보(웹, 일반 상식)를 그래프에 있는 것처럼 말하지 않는다. 일반 지식을 "
            "보조로 쓸 때는 그래프 근거와 명확히 구분해 표시한다.\n\n"
            "출력은 output_schema를 따르는 JSON 하나로만 한다(코드펜스·해설 없이 JSON 객체만)."
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
# document_templates 3종 (AXKG-SPEC-010 MVP scope, AXKG-DEC-005).
# body는 frontmatter + 섹션 뼈대 초안.
# ---------------------------------------------------------------------------

TEMPLATE_SEEDS: list[dict] = [
    {
        "key": "reference",
        "name": "Reference Document",
        "body": """---
type: reference
title: ""
source_url: ""
tags: []
up: ""
created_at: ""
---

# {title}

## 요약

<!-- source 요약 3~6문장 -->

## 핵심 내용

<!-- 원문 근거 안에서 주장/근거 정리 -->

## 인용/발췌

<!-- 필요한 경우 원문 발췌 -->

## 연결

- up: [[]]
- 관련: [[]]
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
up: ""
created_at: ""
---

# {title}

## 한 줄 주장

<!-- 이 노트가 말하는 단 하나의 주장 -->

## 맥락

<!-- 왜 이 주장이 성립하는지, 어떤 source에서 왔는지 -->

## 내 결론

<!-- TODO: 작성자 결론 -->

## 연결

- up: [[]]
- 관련: [[]]
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
tags: []
created_at: ""
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

- up: [[]]
- 관련: [[]]
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
    },
    {
        "key": "regenerate_documentation_gate",
        "display_name": "문서화 게이트 재생성",
        "description": "③ 문서초안 스테이지: feedback 반영 재생성 (AXKG-SPEC-002/004)",
        "handler_kind": "documentation_gate",
        "prompt_key": "documentation_gate",
        "template_key": None,
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
]


def seed_user(conn: Connection) -> None:
    exists = conn.execute(
        sa.select(User.id).where(User.email == SEED_USER_EMAIL)
    ).first()
    if exists:
        return
    conn.execute(
        sa.insert(User).values(
            email=SEED_USER_EMAIL,
            password_hash=hash_password(SEED_USER_PASSWORD),
            display_name="kknaks",
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
                default_options={},
                default_provider_options=seed.get("default_provider_options", {}),
                enabled=True,
            )
        )


def seed_all(conn: Connection) -> None:
    seed_user(conn)
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
