"""AXKG-SPEC-004 ③ 문서화 게이트 배선 테스트 (WP3 Phase 2).

커버:
- 분류 승인 → 문서화 게이트 generating + 첫 revision(drafting) + generate task 큐잉(destination payload)
- DocumentationGateContextBuilder + execute_documentation_gate:
  - 성공: documentation.v1 envelope 저장(destination_type/document_draft[document_type/
    markdown_full/frontmatter·body preview/links]/derived_suggestions[change_kind]/apply_plan
    pending) + revision reviewable + gate review_pending + session id
  - 연결 후보 2단 컨텍스트(retriever + documents index 스냅샷) 항상 주입
  - destination→template 매핑(resource→reference 템플릿 body 조립)
  - 스키마 불일치 → revision failed + gate failed(부분 소비 금지)
- feedback → regenerate v2(통째 재생성) → v2 reviewable, v1 superseded
- retry: failed 문서화 게이트 재시도 → 새 revision + 새 ai_task(retry_of)
- 조회 뷰: GET /documentation-gates, GET drafts/{v}/markdown, DRAFT_MARKDOWN_NOT_FOUND

fake open-kknaks client로 네트워크/redis 없이 검증한다(분류 테스트 패턴).
"""
import json
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.dto.ai import AiTaskDefinitionDTO, AiTaskDTO
from axkg.integrations.open_kknaks import (
    OpenKknaksClient,
    OpenKknaksTaskRequest,
    OpenKknaksTaskResult,
)
from axkg.models.base import utcnow
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.ai.documentation_gate import (
    DESTINATION_TEMPLATE_KEY,
    DocumentationGateContextBuilder,
)
from axkg.services.classification_gate_execution import execute_classification_gate
from axkg.services.documentation_gate_execution import execute_documentation_gate
from axkg.services.gates import GateService

VALID_SUMMARY = {
    "title": "Graph RAG 실전 설계",
    "summary": "문서 그래프를 검색 컨텍스트로 삼는 RAG 설계 자료 요약.",
    "keywords": ["graph-rag", "retriever"],
    "source_type": "article",
}

RESOURCE_CLASSIFICATION = {
    "destination_type": "resource",
    "destination_reason": "외부 자료를 참고용 reference note로 보존할 가치가 있다. 재사용 가능.",
    "suggested_title": "Graph RAG 실전 설계 노트",
    "suggested_tags": ["graph-rag", "retriever"],
    "source_summary": "문서 그래프를 검색 context로 삼는 RAG 설계 자료.",
    "confidence": 0.86,
}

DRAFT_MARKDOWN = (
    "---\n"
    "type: reference\n"
    "title: Graph RAG 실전 설계 노트\n"
    "tags: [graph-rag, retriever]\n"
    "---\n\n"
    "# Graph RAG 실전 설계 노트\n\n"
    "## 요약\n\n문서 그래프를 검색 컨텍스트로 삼는 RAG 설계.\n"
)

VALID_DOCUMENTATION = {
    # AI는 파일명(create)·target_stem(supplement)만 낸다 — 디렉토리는 시스템 조립(T-040).
    "document_draft": {
        "filename_candidate": "graph-rag-practical-design.md",
        "markdown_full": DRAFT_MARKDOWN,
        "links": [
            {"target": "graph-rag", "edge_type": "assoc", "link_reason": "관련 개념 참조"}
        ],
    },
    "derived_suggestions": [
        {
            "suggestion_type": "supplement_existing_concept",
            "target_stem": "agent-experience",
            "file_action": "overwrite_markdown",
            "target_document_id": "doc-agent-experience",
            "draft_markdown": "---\ntype: concept\ntitle: Agent Experience\n---\n\n초기 개념. reference로 보강됨.\n",
            "diff_preview": "본문 말미에 보강 문단 추가.",
            "link_reason": "이 reference가 개념을 보강한다.",
        },
        {
            "suggestion_type": "create_new_concept",
            "filename_candidate": "evidence-first-rag.md",
            "draft_markdown": "---\ntype: concept\ntitle: Evidence-first RAG\n---\n\n근거 우선 RAG 개념.\n",
            "link_reason": "새 개념을 정의할 가치가 있다.",
        },
    ],
}

VALID_DOCUMENTATION_V2 = {
    **VALID_DOCUMENTATION,
    "document_draft": {
        **VALID_DOCUMENTATION["document_draft"],
        "markdown_full": DRAFT_MARKDOWN + "\n## 핵심 내용\n\n피드백 반영 v2.\n",
    },
}


class FakeClient(OpenKknaksClient):
    """제출 request와 반환 session_id를 관찰 가능한 fake."""

    def __init__(
        self, *, result_text: str, status: str = "done", session_id: str = "okk-doc-1"
    ) -> None:
        self._result_text = result_text
        self._status = status
        self._session_id = session_id
        self.requests: list[OpenKknaksTaskRequest] = []

    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:
        self.requests.append(request)
        return "okk-doc-task-1"

    async def get_task_status(self, task_id: str) -> str | None:
        return self._status

    async def wait_result(
        self, task_id: str, *, timeout_sec: float | None = None
    ) -> OpenKknaksTaskResult:
        return OpenKknaksTaskResult(
            task_id=task_id,
            status=self._status,  # type: ignore[arg-type]
            result_text=self._result_text,
            session_id=self._session_id,
        )


async def _summarized_source(
    session: AsyncSession, url: str = "https://example.com/doc"
) -> uuid.UUID:
    repo = SourceRepository(session)
    src = await repo.create(
        source_url=url,
        normalized_url=url,
        source_channel="manual",
        submitted_by=None,
        submitted_at=utcnow(),
        raw_text=None,
    )
    await repo.set_summary(src.id, VALID_SUMMARY)
    return src.id


async def _approve_to_documentation(
    session_factory: async_sessionmaker[AsyncSession],
    url: str = "https://example.com/doc",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """summarized → 분류 게이트 생성·실행·승인 → 문서화 게이트 generating.

    returns (source_id, doc_gate_id, doc_task_id, doc_revision_id).
    """
    async with session_factory() as session:
        source_id = await _summarized_source(session, url)
        result = await GateService(session).create_classification_gate(source_id)
        await session.commit()
        cls_task, cls_gate, cls_rev = (
            result.ai_task.id,
            result.gate.id,
            result.revision.id,
        )
    await execute_classification_gate(
        cls_task,
        cls_gate,
        cls_rev,
        client=FakeClient(result_text=json.dumps(RESOURCE_CLASSIFICATION)),
        session_factory=session_factory,
    )
    async with session_factory() as session:
        gate = await GateRepository(session).get_gate_by_source_and_kind(
            source_id, "classification"
        )
        approve = await GateService(session).approve(gate.id)
        await session.commit()
        doc = approve.documentation_task
        assert doc is not None
        return source_id, doc.gate.id, doc.ai_task.id, doc.revision.id


async def _execute_documentation(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    result_text: str,
    session_id: str = "okk-doc-1",
) -> tuple[uuid.UUID, uuid.UUID, FakeClient]:
    """분류 승인까지 마친 뒤 문서화 초안 생성을 실행한다. (source_id, doc_gate_id, client)."""
    source_id, gate_id, task_id, revision_id = await _approve_to_documentation(
        session_factory
    )
    client = FakeClient(result_text=result_text, session_id=session_id)
    done = await execute_documentation_gate(
        task_id, gate_id, revision_id, client=client, session_factory=session_factory
    )
    assert done.status == "succeeded", done.error_message
    return source_id, gate_id, client


async def _auth_headers(ac: AsyncClient) -> dict[str, str]:
    login = await ac.post(
        "/auth/login", json={"email": "kknaks@medisolveai.com", "password": "1234"}
    )
    return {"Authorization": f"Bearer {login.json()['token']}"}


# ---------------------------------------------------------------------------
# 승인 → 문서화 게이트 생성 + 큐잉
# ---------------------------------------------------------------------------


async def test_approve_creates_documentation_gate_generating(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, gate_id, task_id, revision_id = await _approve_to_documentation(
        session_factory
    )
    async with session_factory() as session:
        repo = GateRepository(session)
        gate = await repo.get_gate(gate_id)
        assert gate.gate_kind == "documentation"
        assert gate.status == "generating"
        assert gate.active_revision_id == revision_id
        revision = await repo.get_revision(revision_id)
        assert revision.status == "drafting"
        assert revision.form_schema_version == "documentation.v1"


# ---------------------------------------------------------------------------
# 초안 생성 성공 — documentation.v1 envelope
# ---------------------------------------------------------------------------


async def test_documentation_success_saves_envelope(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, gate_id, client = await _execute_documentation(
        session_factory, result_text=json.dumps(VALID_DOCUMENTATION)
    )
    async with session_factory() as session:
        repo = GateRepository(session)
        gate = await repo.get_gate(gate_id)
        assert gate.status == "review_pending"
        revision = await repo.get_revision(gate.active_revision_id)
        assert revision.status == "reviewable"
        assert revision.open_kknaks_session_id == "okk-doc-1"

        form = revision.payload["form"]
        assert revision.payload["schema_version"] == "documentation.v1"
        assert form["destination_type"] == "resource"

        draft = form["document_draft"]
        # resource → document_type reference (SPEC-005 어휘, DEC-005 'product' 아님)
        assert draft["document_type"] == "reference"
        # 경로는 시스템 조립: reference → resources/ + 정규화된 파일명 (T-040)
        assert draft["target_path"] == "resources/graph-rag-practical-design.md"
        assert draft["markdown_full"].startswith("---")
        assert "type: reference" in draft["frontmatter_preview"]
        assert "## 요약" in draft["body_preview"]
        assert draft["links"][0]["target"] == "graph-rag"

        # 파생지식: change_kind 파생 + file_action
        derived = {d["suggestion_type"]: d for d in form["derived_suggestions"]}
        assert derived["supplement_existing_concept"]["change_kind"] == "modify"
        assert derived["supplement_existing_concept"]["file_action"] == "overwrite_markdown"
        assert derived["supplement_existing_concept"]["target_document_id"] == "doc-agent-experience"
        assert derived["create_new_concept"]["change_kind"] == "create"
        assert derived["create_new_concept"]["file_action"] == "create_markdown"

        # apply_plan은 제안(pending)만 — 실행은 Phase 3
        apply_plan = form["apply_plan"]
        assert apply_plan["validation_status"] == "pending"
        assert apply_plan["db_actions"] == []
        roles = {a["role"] for a in apply_plan["file_actions"]}
        assert roles == {"main_document", "derived_suggestion"}


async def test_documentation_injects_connection_context_and_template(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, _, client = await _execute_documentation(
        session_factory, result_text=json.dumps(VALID_DOCUMENTATION)
    )
    prompt = client.requests[0].prompt
    # 연결 후보 2단 컨텍스트(항상 주입, 확정 문서 없어 빈 목록이어도 블록 유지)
    assert "[연결 후보" in prompt
    assert "documents_index_snapshot" in prompt
    # destination=resource → reference 템플릿 body 조립(코드 프레임 + 템플릿)
    assert "## 핵심 내용" in prompt
    # 파생 concept 뼈대가 main 템플릿과 별개로 문서화③ 조립에 고정 동봉됨 (PLAN-009-T-027)
    assert "[파생 concept 뼈대]" in prompt
    assert "## 근거 출처" in prompt


def test_destination_template_mapping() -> None:
    # project → 원본요약(main) 템플릿. 기능정의서(project_feature_spec)는 파생 고정 동봉이라
    # destination 매핑에 없다(AXKG-SPEC-014/010, WP11 Phase 3).
    assert DESTINATION_TEMPLATE_KEY == {
        "resource": "reference",
        "area": "permanent",
        "project": "project_source_summary",
    }


async def test_select_template_key_uses_payload_destination(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        builder = DocumentationGateContextBuilder(session)
        definition = AiTaskDefinitionDTO(
            id=uuid.uuid4(),
            key="generate_documentation_gate",
            display_name="doc",
            handler_kind="documentation_gate",
            prompt_key="documentation_gate",
            template_key=None,
        )
        task = AiTaskDTO(
            id=uuid.uuid4(),
            task_type="generate_documentation_gate",
            status="queued",
            provider="claude",
            queued_at=utcnow(),
            payload={"destination_type": "area"},
        )
        assert builder.select_template_key(task, definition) == "permanent"


# ---------------------------------------------------------------------------
# 실패 — 스키마 불일치
# ---------------------------------------------------------------------------


async def test_documentation_schema_mismatch_fails_gate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, gate_id, task_id, revision_id = await _approve_to_documentation(
        session_factory
    )
    # document_draft.markdown_full 누락 → OUTPUT_SCHEMA_MISMATCH
    bad = {"document_draft": {"filename_candidate": "x"}, "derived_suggestions": []}
    client = FakeClient(result_text=json.dumps(bad))
    done = await execute_documentation_gate(
        task_id, gate_id, revision_id, client=client, session_factory=session_factory
    )
    assert done.status == "failed"
    async with session_factory() as session:
        repo = GateRepository(session)
        assert (await repo.get_gate(gate_id)).status == "failed"
        assert (await repo.get_revision(revision_id)).status == "failed"


# ---------------------------------------------------------------------------
# feedback → regenerate v2
# ---------------------------------------------------------------------------


async def test_documentation_feedback_regenerate_v2(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, gate_id, _ = await _execute_documentation(
        session_factory, result_text=json.dumps(VALID_DOCUMENTATION)
    )
    async with session_factory() as session:
        service = GateService(session)
        await service.submit_feedback(gate_id, body="본문에 핵심 내용 섹션을 더 채워줘 부탁해")
        await session.commit()
    async with session_factory() as session:
        service = GateService(session)
        result = await service.regenerate(gate_id)
        await session.commit()
        v2_task, v2_gate, v2_rev = (
            result.ai_task.id,
            result.gate.id,
            result.revision.id,
        )
        assert result.ai_task.task_type == "regenerate_documentation_gate"
        assert result.ai_task.payload["destination_type"] == "resource"
        assert result.gate.status == "regenerating"
    done = await execute_documentation_gate(
        v2_task,
        v2_gate,
        v2_rev,
        client=FakeClient(result_text=json.dumps(VALID_DOCUMENTATION_V2)),
        session_factory=session_factory,
    )
    assert done.status == "succeeded"
    async with session_factory() as session:
        repo = GateRepository(session)
        gate = await repo.get_gate(gate_id)
        assert gate.status == "review_pending"
        revisions = {r.version: r for r in await repo.list_revisions_by_gate(gate_id)}
        assert revisions[1].status == "superseded"
        assert revisions[2].status == "reviewable"
        assert "핵심 내용" in revisions[2].payload["form"]["document_draft"]["markdown_full"]


# ---------------------------------------------------------------------------
# retry — 실패한 문서화 게이트
# ---------------------------------------------------------------------------


async def test_documentation_retry_after_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, gate_id, task_id, revision_id = await _approve_to_documentation(
        session_factory
    )
    # 첫 생성 실패
    await execute_documentation_gate(
        task_id,
        gate_id,
        revision_id,
        client=FakeClient(result_text="not json"),
        session_factory=session_factory,
    )
    async with session_factory() as session:
        service = GateService(session)
        result = await service.retry(gate_id)
        await session.commit()
        assert result.ai_task.task_type == "generate_documentation_gate"
        assert result.ai_task.retry_of_task_id == task_id
        assert result.gate.status == "generating"
    # 재시도 실행 성공
    done = await execute_documentation_gate(
        result.ai_task.id,
        result.gate.id,
        result.revision.id,
        client=FakeClient(result_text=json.dumps(VALID_DOCUMENTATION)),
        session_factory=session_factory,
    )
    assert done.status == "succeeded"


# ---------------------------------------------------------------------------
# 조회 뷰 — GET /documentation-gates + drafts markdown
# ---------------------------------------------------------------------------


async def test_list_documentation_gates_view(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, gate_id, _ = await _execute_documentation(
        session_factory, result_text=json.dumps(VALID_DOCUMENTATION)
    )
    headers = await _auth_headers(client)
    res = await client.get("/documentation-gates", headers=headers)
    assert res.status_code == 200
    gates = res.json()["documentation_gates"]
    match = [g for g in gates if g["source_id"] == str(source_id)]
    assert len(match) == 1
    assert match[0]["destination_type"] == "resource"
    assert match[0]["status"] == "draft_ready"  # review_pending → draft_ready


async def test_get_draft_markdown(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, _, _ = await _execute_documentation(
        session_factory, result_text=json.dumps(VALID_DOCUMENTATION)
    )
    headers = await _auth_headers(client)
    res = await client.get(
        f"/documentation-gates/{source_id}/drafts/1/markdown", headers=headers
    )
    assert res.status_code == 200
    assert res.json()["markdown"].startswith("---")
    assert "Graph RAG 실전 설계 노트" in res.json()["markdown"]


async def test_get_draft_markdown_not_found(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, _, _ = await _execute_documentation(
        session_factory, result_text=json.dumps(VALID_DOCUMENTATION)
    )
    headers = await _auth_headers(client)
    # 존재하지 않는 draft version
    res = await client.get(
        f"/documentation-gates/{source_id}/drafts/9/markdown", headers=headers
    )
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "DRAFT_MARKDOWN_NOT_FOUND"


async def test_documentation_gates_requires_auth(client: AsyncClient) -> None:
    res = await client.get("/documentation-gates")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# resume 잠복 버그 (PLAN-010-T-008): bare resume=true + 세션 유실 → full 컨텍스트
# ---------------------------------------------------------------------------


def _doc_feedback_task(source_id: uuid.UUID, options: dict) -> AiTaskDTO:
    return AiTaskDTO(
        id=uuid.uuid4(),
        task_type="regenerate_documentation_gate",
        status="queued",
        provider="claude",
        queued_at=utcnow(),
        source_id=source_id,
        options=options,
        payload={
            "feedback": "근거를 더 촘촘히 보강해줘",
            "prior_payload": {"document_draft": {"filename_candidate": "x"}},
            "destination_type": "resource",
        },
    )


def _doc_definition() -> AiTaskDefinitionDTO:
    return AiTaskDefinitionDTO(
        id=uuid.uuid4(),
        key="regenerate_documentation_gate",
        display_name="doc",
        handler_kind="documentation_gate",
        prompt_key="documentation_gate",
        template_key=None,
    )


async def test_documentation_feedback_bare_resume_rebuilds_full_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # bare resume=true + 세션 없음: 요약 payload 등 full 컨텍스트를 다시 공급한다.
    async with session_factory() as session:
        source_id = await _summarized_source(session)
        builder = DocumentationGateContextBuilder(session)
        blocks = await builder.build_data_blocks(
            _doc_feedback_task(source_id, {"resume": True}), _doc_definition()
        )
        labels = [b.label for b in blocks]
        assert "summary_payload" in labels  # 원문 요약 컨텍스트 재공급
        assert "feedback" in labels


async def test_documentation_feedback_real_session_stays_feedback_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source_id = await _summarized_source(session)
        builder = DocumentationGateContextBuilder(session)
        blocks = await builder.build_data_blocks(
            _doc_feedback_task(
                source_id, {"resume": {"mode": "session", "session_id": "s1"}}
            ),
            _doc_definition(),
        )
        labels = [b.label for b in blocks]
        # 세션 resume: 요약 재전송 없이 연결 후보 + 피드백만(summary_payload 없음).
        assert "summary_payload" not in labels
        assert "feedback" in labels
