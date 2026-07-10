"""AXKG-SPEC-004 Apply Executor 테스트 (WP3 Phase 3).

커버 (fixture markdown_root = 임시 디렉토리, settings monkeypatch):
- 문서화 게이트 승인 → 초안 `.md` 확정 write + index + 증분 엣지 rebuild + source documented
  + revision/gate approved + apply_plans applied(db_actions는 executor가 derive)
- Derived Knowledge Apply Matrix: supplement(modify/patch)·create_new_concept(create)·
  create_project_baseline(create) 3종 적용 + 확정 문서 그래프 엣지 반영
- Case Matrix 거부(apply 안 함): BROKEN_WIKILINK / DUPLICATE_STEM / PATH_NOT_ALLOWED
- 멱등: 승인된 게이트 재승인 GATE_ALREADY_APPROVED (중복 파일/전이 없음)
- 라우트: POST /gates/{id}/approve(문서화) 성공 → source documented, 거부 → 에러코드

fake open-kknaks client로 문서화 초안을 review_pending까지 만든 뒤 승인한다.
"""
import json
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings
from axkg.integrations.open_kknaks import (
    OpenKknaksClient,
    OpenKknaksTaskRequest,
    OpenKknaksTaskResult,
)
from axkg.dto.ai import AiTaskDTO
from axkg.models.base import utcnow
from axkg.repositories.documents import DocumentRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.ai.documentation_gate import DocumentationGateContextBuilder
from axkg.services.classification_gate_execution import execute_classification_gate
from axkg.services.documentation_gate_execution import execute_documentation_gate
from axkg.services.gates import GateService
from axkg.services.graph import GraphService
from axkg.storage.markdown_root import MarkdownRoot
from axkg.workers.apply_executor import ApplyValidationError

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
    "suggested_tags": ["graph-rag"],
    "source_summary": "문서 그래프를 검색 context로 삼는 RAG 설계.",
    "confidence": 0.86,
}


def _main_markdown(body: str) -> str:
    return (
        "---\n"
        "type: reference\n"
        "title: Graph RAG 실전 설계 노트\n"
        "tags: [graph-rag]\n"
        "---\n\n"
        "# Graph RAG 실전 설계 노트\n\n"
        "## 요약\n\n" + body + "\n"
    )


PLAIN_DOC = {
    # AI는 파일명만 낸다 — 디렉토리(resources/)는 시스템이 조립한다(T-040).
    "document_draft": {
        "filename_candidate": "graph-rag-note.md",
        "markdown_full": _main_markdown("문서 그래프를 검색 컨텍스트로 삼는 RAG 설계."),
    },
    "derived_suggestions": [],
}


class FakeClient(OpenKknaksClient):
    def __init__(self, *, result_text: str, session_id: str = "okk-x") -> None:
        self._result_text = result_text
        self._session_id = session_id

    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:
        return "okk-x-1"

    async def get_task_status(self, task_id: str) -> str | None:
        return "done"

    async def wait_result(
        self, task_id: str, *, timeout_sec: float | None = None
    ) -> OpenKknaksTaskResult:
        return OpenKknaksTaskResult(
            task_id=task_id,
            status="done",
            result_text=self._result_text,
            session_id=self._session_id,
        )


@pytest.fixture
def markdown_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "axkg_markdown_root", str(tmp_path))
    return tmp_path


async def _seed_document(
    session_factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    rel: str,
    markdown: str,
) -> None:
    """확정 문서 하나를 미리 markdown_root에 쓰고 인덱싱한다(선행 문서 상황 구성)."""
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(markdown, "utf-8")
    async with session_factory() as session:
        await GraphService(session, root=MarkdownRoot(str(root))).rebuild_document(rel)
        await session.commit()


async def _to_review_pending(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    documentation_output: dict,
    url: str = "https://example.com/apply",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """summarized→분류 승인→문서화 초안 실행까지. (source_id, doc_gate_id, doc_revision_id)."""
    async with session_factory() as session:
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
        source_id = src.id
        result = await GateService(session).create_classification_gate(source_id)
        await session.commit()
        cls = (result.ai_task.id, result.gate.id, result.revision.id)
    await execute_classification_gate(
        *cls,
        client=FakeClient(result_text=json.dumps(RESOURCE_CLASSIFICATION)),
        session_factory=session_factory,
    )
    async with session_factory() as session:
        cls_gate = await GateRepository(session).get_gate_by_source_and_kind(
            source_id, "classification"
        )
        approve = await GateService(session).approve(cls_gate.id)
        await session.commit()
        doc = approve.documentation_task
    done = await execute_documentation_gate(
        doc.ai_task.id,
        doc.gate.id,
        doc.revision.id,
        client=FakeClient(result_text=json.dumps(documentation_output)),
        session_factory=session_factory,
    )
    assert done.status == "succeeded", done.error_message
    return source_id, doc.gate.id, doc.revision.id


async def _auth_headers(ac: AsyncClient) -> dict[str, str]:
    login = await ac.post(
        "/auth/login", json={"email": "kknaks@medisolveai.com", "password": "1234"}
    )
    return {"Authorization": f"Bearer {login.json()['token']}"}


# ---------------------------------------------------------------------------
# happy path — 초안 확정 + documented
# ---------------------------------------------------------------------------


async def test_approve_documents_source_and_writes_file(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    source_id, gate_id, revision_id = await _to_review_pending(
        session_factory, documentation_output=PLAIN_DOC
    )
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()

    # 파일이 markdown_root에 확정 생성됨
    assert (markdown_root / "resources/graph-rag-note.md").is_file()
    async with session_factory() as session:
        # documents 인덱스에 반영
        doc = await DocumentRepository(session).get_by_stem("graph-rag-note")
        assert doc is not None and doc.document_type == "reference"
        # source documented(+ inbox 숨김), 게이트/revision approved
        source = await SourceRepository(session).get(source_id)
        assert source.status == "documented"
        assert source.visible_in_inbox is False
        assert source.documented_at is not None
        repo = GateRepository(session)
        gate = await repo.get_gate(gate_id)
        assert gate.status == "approved"
        assert gate.approved_revision_id == revision_id
        assert (await repo.get_revision(revision_id)).status == "approved"


async def test_apply_plan_recorded_with_derived_db_actions(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    from axkg.repositories.apply_plans import ApplyPlanRepository

    source_id, gate_id, revision_id = await _to_review_pending(
        session_factory, documentation_output=PLAIN_DOC
    )
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()
    async with session_factory() as session:
        plan = await ApplyPlanRepository(session).get_by_revision(revision_id)
        assert plan is not None
        assert plan.validation_status == "valid"
        assert plan.status == "applied"
        assert plan.applied_at is not None
        types = [a["action_type"] for a in plan.db_actions]
        # executor가 derive: main create + source documented + gate approved
        assert "create_document" in types
        assert "update_source_status" in types
        assert "update_gate_status" in types


# ---------------------------------------------------------------------------
# Derived Knowledge Apply Matrix — 3종
# ---------------------------------------------------------------------------


async def test_apply_matrix_three_suggestions(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # 선행: 보강 대상 기존 concept 문서를 미리 인덱싱
    await _seed_document(
        session_factory,
        markdown_root,
        rel="permanent/concepts/agent-experience.md",
        markdown="---\ntype: concept\ntitle: Agent Experience\n---\n\n초기 개념.\n",
    )
    output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "markdown_full": _main_markdown(
                "관련 개념은 [[evidence-first-rag]]와 [[agent-experience]]다."
            ),
        },
        "derived_suggestions": [
            {
                "suggestion_type": "supplement_existing_concept",
                "target_stem": "agent-experience",
                "file_action": "overwrite_markdown",
                "target_document_id": "agent-experience",
                "draft_markdown": "---\ntype: concept\ntitle: Agent Experience\n---\n\n초기 개념. 보강됨(v2).\n",
                "link_reason": "이 reference가 개념을 보강한다.",
            },
            {
                "suggestion_type": "create_new_concept",
                "filename_candidate": "evidence-first-rag.md",
                "draft_markdown": "---\ntype: concept\ntitle: Evidence-first RAG\n---\n\n근거 우선 RAG.\n",
                "link_reason": "새 개념 정의.",
            },
            {
                "suggestion_type": "create_project_baseline",
                "filename_candidate": "baseline-002-graph-rag.md",
                "draft_markdown": "---\ntype: baseline\ntitle: Graph RAG QA Product\nstatus: draft\n---\n\n## 배경\n\nbaseline 후보.\n",
                "link_reason": "제품 baseline 후보.",
            },
        ],
    }
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=output, url="https://example.com/matrix"
    )
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()

    # 3종 모두 파일 반영
    assert (markdown_root / "permanent/concepts/evidence-first-rag.md").is_file()
    assert (markdown_root / "projects/baseline-002-graph-rag.md").is_file()
    patched = (markdown_root / "permanent/concepts/agent-experience.md").read_text("utf-8")
    assert "보강됨(v2)" in patched  # modify → 덮어쓰기 반영

    async with session_factory() as session:
        repo = DocumentRepository(session)
        main = await repo.get_by_stem("graph-rag-note")
        assert main is not None
        assert await repo.get_by_stem("evidence-first-rag") is not None
        assert await repo.get_by_stem("baseline-002-graph-rag") is not None
        # 확정 문서의 [[ ]]가 증분 rebuild로 엣지 반영(assoc)
        edges = {e.to_target: e for e in await repo.list_edges_from(main.id)}
        assert edges["evidence-first-rag"].is_broken is False
        assert edges["agent-experience"].is_broken is False


async def test_derived_version_lifecycle(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    """파생 문서 lifecycle 스탬프 (SPEC-004 D, PLAN-009-T-027):
    create=version 1 / supplement(overwrite)=version++ + producing revision/source."""
    # 선행: 보강 대상 기존 concept(version 1)
    await _seed_document(
        session_factory,
        markdown_root,
        rel="permanent/concepts/agent-experience.md",
        markdown="---\ntype: concept\ntitle: Agent Experience\n---\n\n초기 개념.\n",
    )
    output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "markdown_full": _main_markdown(
                "관련 개념은 [[evidence-first-rag]]와 [[agent-experience]]다."
            ),
        },
        "derived_suggestions": [
            {
                "suggestion_type": "supplement_existing_concept",
                "target_stem": "agent-experience",
                "file_action": "overwrite_markdown",
                "target_document_id": "agent-experience",
                "draft_markdown": "---\ntype: concept\ntitle: Agent Experience\n---\n\n초기 개념. 보강됨(v2).\n",
                "link_reason": "이 reference가 개념을 보강한다.",
            },
            {
                "suggestion_type": "create_new_concept",
                "filename_candidate": "evidence-first-rag.md",
                "draft_markdown": "---\ntype: concept\ntitle: Evidence-first RAG\n---\n\n근거 우선 RAG.\n",
                "link_reason": "새 개념 정의.",
            },
        ],
    }
    source_id, gate_id, revision_id = await _to_review_pending(
        session_factory, documentation_output=output, url="https://example.com/derived-ver"
    )
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()

    async with session_factory() as session:
        repo = DocumentRepository(session)
        # create_new_concept → version 1 + producing revision/source 스탬프
        created = await repo.get_by_stem("evidence-first-rag")
        assert created is not None
        assert created.version == 1
        assert created.producing_revision_id == revision_id
        assert created.source_id == source_id
        # supplement_existing_concept(overwrite) → version++ (1→2) + producing revision
        supplemented = await repo.get_by_stem("agent-experience")
        assert supplemented is not None
        assert supplemented.version == 2
        assert supplemented.producing_revision_id == revision_id
        # 파생 concept가 source_id를 스탬프해도 main 계보 판단은 concept를 제외한다
        main = await repo.get_current_main_by_source(source_id)
        assert main is not None
        assert main.stem == "graph-rag-note"
        assert main.document_type == "reference"


# ---------------------------------------------------------------------------
# Case Matrix — 거부(apply 안 함)
# ---------------------------------------------------------------------------


async def test_reject_broken_wikilink(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "markdown_full": _main_markdown("깨진 링크 [[does-not-exist-anywhere]]."),
        },
        "derived_suggestions": [],
    }
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=output, url="https://example.com/broken"
    )
    async with session_factory() as session:
        with pytest.raises(ApplyValidationError) as exc:
            await GateService(session).approve(gate_id)
        assert exc.value.primary_code == "BROKEN_WIKILINK"
        await session.rollback()
    # apply 안 됨: 파일 없음, source 여전히 summarized
    assert not (markdown_root / "resources/graph-rag-note.md").exists()
    async with session_factory() as session:
        assert (await SourceRepository(session).get(source_id)).status == "summarized"


async def test_reject_duplicate_stem(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # 같은 stem(graph-rag-note)을 다른 경로에 선행 인덱싱
    await _seed_document(
        session_factory,
        markdown_root,
        rel="existing/graph-rag-note.md",
        markdown="---\ntype: reference\ntitle: 기존\n---\n\n기존.\n",
    )
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=PLAIN_DOC, url="https://example.com/dup"
    )
    async with session_factory() as session:
        with pytest.raises(ApplyValidationError) as exc:
            await GateService(session).approve(gate_id)
        assert exc.value.primary_code == "DUPLICATE_STEM"
        await session.rollback()


async def test_reject_path_escape(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # T-040 이후 AI는 경로를 못 내므로 root escape를 만들 수 없다 — 손으로 주입해 executor
    # 안전망(PATH_NOT_ALLOWED)이 여전히 작동하는지 검증한다.
    output = {
        "document_draft": {
            "filename_candidate": "evil.md",
            "target_path": "../evil.md",
            "markdown_full": _main_markdown("root 밖 경로."),
        },
        "derived_suggestions": [],
    }
    with pytest.raises(ApplyValidationError) as exc:
        await _apply_crafted(
            session_factory, markdown_root, output=output, url="https://example.com/escape"
        )
    assert exc.value.primary_code == "PATH_NOT_ALLOWED"
    assert not (markdown_root.parent / "evil.md").exists()


# ---------------------------------------------------------------------------
# 멱등 — 승인된 게이트 재승인 거부
# ---------------------------------------------------------------------------


async def test_reapprove_rejected_idempotent(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    from axkg.services.gates import GateAlreadyApprovedError

    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=PLAIN_DOC, url="https://example.com/idem"
    )
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()
    async with session_factory() as session:
        with pytest.raises(GateAlreadyApprovedError):
            await GateService(session).approve(gate_id)
        await session.rollback()


# ---------------------------------------------------------------------------
# 라우트
# ---------------------------------------------------------------------------


async def test_route_approve_documentation_documents_source(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    markdown_root: Path,
) -> None:
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=PLAIN_DOC, url="https://example.com/route"
    )
    headers = await _auth_headers(client)
    res = await client.post(f"/gates/{gate_id}/approve", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved"
    detail = await client.get(f"/sources/{source_id}", headers=headers)
    assert detail.json()["status"] == "documented"


async def test_route_approve_broken_link_rejected(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    markdown_root: Path,
) -> None:
    output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "markdown_full": _main_markdown("깨진 [[nowhere-xyz]]."),
        },
        "derived_suggestions": [],
    }
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=output, url="https://example.com/route-broken"
    )
    headers = await _auth_headers(client)
    res = await client.post(f"/gates/{gate_id}/approve", headers=headers)
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "BROKEN_WIKILINK"
    # 거부 후 source는 여전히 summarized
    detail = await client.get(f"/sources/{source_id}", headers=headers)
    assert detail.json()["status"] == "summarized"


# ---------------------------------------------------------------------------
# 확정 문서 lifecycle — 재문서화 version++ / 경로변경 supersede (PLAN-009-T-012)
# ---------------------------------------------------------------------------


def _doc_revision_payload(output: dict, source_id: uuid.UUID) -> dict:
    """documentation.v1 envelope (ApplyExecutor가 읽는 form 최소 구조)."""
    draft = {"document_type": "reference", **output["document_draft"]}
    return {
        "schema_version": "documentation.v1",
        "gate_kind": "documentation",
        "source_id": str(source_id),
        "form": {
            "document_draft": draft,
            "derived_suggestions": output.get("derived_suggestions", []),
            "apply_plan": {
                "schema_version": "apply_plan.v1",
                "validation_status": "pending",
                "db_actions": [],
                "file_actions": [],
            },
        },
    }


async def _apply_crafted(
    session_factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    output: dict,
    url: str,
) -> None:
    """post-wrap envelope(임의 target_path 포함)를 담은 revision을 만들어 ApplyExecutor.apply를
    직접 호출한다 — wrap을 우회해 executor **경로 안전망**만 검증한다(T-040).

    T-040 이후 AI는 경로를 내지 않아 잘못된 디렉토리/root escape를 만들 수 없다. 그래도
    executor의 PATH_NOT_ALLOWED 검증은 안전망으로 유지되므로, 손으로 만든 나쁜 경로를
    직접 주입해 그 안전망이 여전히 작동하는지 확인한다.
    """
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=PLAIN_DOC, url=url
    )
    async with session_factory() as session:
        gates = GateRepository(session)
        gate = await gates.get_gate(gate_id)
        rev = await gates.create_revision(
            gate_id=gate_id,
            version=await gates.next_version(gate_id),
            status="reviewable",
            payload=_doc_revision_payload(output, source_id),
            form_schema_version="documentation.v1",
        )
        from axkg.workers.apply_executor import ApplyExecutor

        await ApplyExecutor(session, MarkdownRoot(str(root))).apply(gate, rev)


async def _redocument(
    session_factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    gate_id: uuid.UUID,
    source_id: uuid.UUID,
    output: dict,
) -> uuid.UUID:
    """같은 문서화 게이트에 새 reviewable revision을 만들고 ApplyExecutor를 재실행한다.

    재문서화(피드백 후 재승인/재분류)는 같은 게이트 row를 재사용한다(uq source_id·gate_kind).
    새 revision의 apply가 lifecycle version++/supersede를 수행하는지 직접 검증한다.
    """
    async with session_factory() as session:
        gates = GateRepository(session)
        gate = await gates.get_gate(gate_id)
        version = await gates.next_version(gate_id)
        rev = await gates.create_revision(
            gate_id=gate_id,
            version=version,
            status="reviewable",
            payload=_doc_revision_payload(output, source_id),
            form_schema_version="documentation.v1",
        )
        from axkg.workers.apply_executor import ApplyExecutor

        await ApplyExecutor(session, MarkdownRoot(str(root))).apply(gate, rev)
        await session.commit()
        return rev.id


async def test_redocument_same_path_bumps_version_and_producing_revision(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    source_id, gate_id, revision_id = await _to_review_pending(
        session_factory, documentation_output=PLAIN_DOC
    )
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()

    # v1 lifecycle: current, version 1, producing revision = 최초 revision, source 링크.
    async with session_factory() as session:
        doc_v1 = await DocumentRepository(session).get_by_stem("graph-rag-note")
        assert doc_v1.status == "current"
        assert doc_v1.version == 1
        assert doc_v1.producing_revision_id == revision_id
        assert doc_v1.source_id == source_id
        doc_id = doc_v1.id

    # 같은 경로 재문서화(동일 destination) — 본문만 개정.
    v2_output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "target_path": "resources/graph-rag-note.md",
            "markdown_full": _main_markdown("개정된 본문 v2 — 덮어쓰기지만 옛 버전은 DB 박제."),
        },
        "derived_suggestions": [],
    }
    v2_rev_id = await _redocument(
        session_factory, markdown_root, gate_id=gate_id, source_id=source_id, output=v2_output
    )

    # 파일은 덮어써지고, documents row는 같은 id로 version++·producing revision 갱신.
    assert "v2" in (markdown_root / "resources/graph-rag-note.md").read_text("utf-8")
    async with session_factory() as session:
        repo = DocumentRepository(session)
        doc_v2 = await repo.get_by_stem("graph-rag-note")
        assert doc_v2.id == doc_id  # 같은 경로 → 같은 row
        assert doc_v2.status == "current"
        assert doc_v2.version == 2
        assert doc_v2.producing_revision_id == v2_rev_id
        # current main 문서는 여전히 source당 1건.
        current = await repo.get_current_main_by_source(source_id)
        assert current is not None and current.id == doc_id


async def test_redocument_path_change_supersedes_old_and_excludes_from_graph(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=PLAIN_DOC
    )
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()
    async with session_factory() as session:
        old_doc = await DocumentRepository(session).get_by_stem("graph-rag-note")
        old_id = old_doc.id

    # 경로 변경 재문서화(재분류로 destination 이동) — 새 stem/경로.
    moved = {
        "document_draft": {
            "filename_candidate": "graph-rag-note-moved.md",
            "target_path": "resources/graph-rag-note-moved.md",
            "markdown_full": _main_markdown("경로가 바뀐 재문서화 — 옛 문서는 superseded."),
        },
        "derived_suggestions": [],
    }
    v2_rev_id = await _redocument(
        session_factory, markdown_root, gate_id=gate_id, source_id=source_id, output=moved
    )

    # 새 파일 존재 / 옛 파일 제거.
    assert (markdown_root / "resources/graph-rag-note-moved.md").is_file()
    assert not (markdown_root / "resources/graph-rag-note.md").exists()

    async with session_factory() as session:
        repo = DocumentRepository(session)
        old = await repo.get(old_id)
        assert old.status == "superseded"  # 박제 보존(row 유지)
        new = await repo.get_by_stem("graph-rag-note-moved")
        assert new.status == "current"
        assert new.version == 2
        assert new.producing_revision_id == v2_rev_id
        assert new.source_id == source_id
        # current main은 새 문서 1건뿐.
        current = await repo.get_current_main_by_source(source_id)
        assert current is not None and current.id == new.id

        # 그래프 기본 노출: superseded 제외, current만 노드로.
        view = await GraphService(session, root=MarkdownRoot(str(markdown_root))).graph_documents()
        stems = {n.stem for n in view.nodes}
        assert "graph-rag-note-moved" in stems
        assert "graph-rag-note" not in stems


# ---------------------------------------------------------------------------
# 문서화 승인 안전망: 형제 reviewable supersede sweep (PLAN-009-T-039, SPEC-002 §5/§7 OQ)
# ---------------------------------------------------------------------------


async def test_doc_approve_supersedes_leftover_reviewable_sibling(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # v1 reviewable(active)인 문서화 게이트에 병렬 누적된 형제 reviewable을 하나 더 만든다.
    source_id, gate_id, v1_id = await _to_review_pending(
        session_factory, documentation_output=PLAIN_DOC
    )
    async with session_factory() as session:
        gates = GateRepository(session)
        sibling = await gates.create_revision(
            gate_id=gate_id,
            version=await gates.next_version(gate_id),
            status="reviewable",
            payload=_doc_revision_payload(PLAIN_DOC, source_id),
            form_schema_version="documentation.v1",
            parent_revision_id=v1_id,
        )
        await session.commit()
        sibling_id = sibling.id

    # active(v1) 승인 → executor apply. 안전망 sweep이 형제 reviewable을 superseded 처리.
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()

    async with session_factory() as session:
        gates = GateRepository(session)
        revs = {r.id: r for r in await gates.list_revisions_by_gate(gate_id)}
        assert revs[v1_id].status == "approved"
        assert revs[sibling_id].status == "superseded"
        # approved 1 + dangling(reviewable 잔존) 0
        assert sum(1 for r in revs.values() if r.status == "approved") == 1
        assert await gates.list_reviewable_revisions_by_gate(gate_id) == []


# ---------------------------------------------------------------------------
# 경로 컨벤션 + 파생 본문 검증 (PLAN-009-T-016)
# ---------------------------------------------------------------------------


async def test_reject_main_path_convention(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # reference(document_type) main은 resources/ 여야 한다. T-040 이후 wrap이 항상 올바른
    # 디렉토리를 붙이므로 AI가 틀릴 수 없다 — 손으로 옛 reference/ 경로를 주입해 executor
    # 안전망(PATH_NOT_ALLOWED)이 유지되는지 검증한다.
    output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "target_path": "reference/graph-rag-note.md",
            "markdown_full": _main_markdown("잘못된 디렉토리 — reference는 resources/여야."),
        },
        "derived_suggestions": [],
    }
    with pytest.raises(ApplyValidationError) as exc:
        await _apply_crafted(
            session_factory, markdown_root, output=output, url="https://example.com/pathconv"
        )
    assert exc.value.primary_code == "PATH_NOT_ALLOWED"
    assert not (markdown_root / "reference/graph-rag-note.md").exists()


async def test_reject_derived_path_convention(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # create_new_concept 파생은 permanent/concepts/ 여야 한다. T-040 이후 wrap이 항상 올바른
    # 디렉토리를 조립하므로, 손으로 잘못된 경로를 주입해 executor 안전망을 검증한다.
    output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "target_path": "resources/graph-rag-note.md",
            "markdown_full": _main_markdown("메인은 깨끗함."),
        },
        "derived_suggestions": [
            {
                "suggestion_type": "create_new_concept",
                "change_kind": "create",
                "target_path": "resources/misplaced-concept.md",
                "draft_markdown": "---\ntype: concept\ntitle: X\n---\n\n본문.\n",
                "link_reason": "잘못된 위치.",
            }
        ],
    }
    with pytest.raises(ApplyValidationError) as exc:
        await _apply_crafted(
            session_factory, markdown_root, output=output, url="https://example.com/derivedpath"
        )
    assert exc.value.primary_code == "PATH_NOT_ALLOWED"


async def test_reject_derived_broken_wikilink(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # 파생 draft_markdown의 깨진 [[ ]]도 main과 동일하게 거부한다.
    output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "markdown_full": _main_markdown("메인은 깨끗함."),
        },
        "derived_suggestions": [
            {
                "suggestion_type": "create_new_concept",
                "filename_candidate": "new-concept.md",
                "draft_markdown": "---\ntype: concept\ntitle: New\n---\n\n깨진 [[nope-nowhere]] 링크.\n",
                "link_reason": "새 개념.",
            }
        ],
    }
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=output, url="https://example.com/derivedbroken"
    )
    async with session_factory() as session:
        with pytest.raises(ApplyValidationError) as exc:
            await GateService(session).approve(gate_id)
        assert exc.value.primary_code == "BROKEN_WIKILINK"
        await session.rollback()
    assert not (markdown_root / "permanent/concepts/new-concept.md").exists()


# ---------------------------------------------------------------------------
# supplement 대상은 concept만 (PLAN-009-T-036)
# ---------------------------------------------------------------------------


async def test_reject_supplement_target_not_concept(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # 프레시 E2E 실측 회귀: supplement가 reference 문서를 보충 대상으로 고르면 거부한다
    # (reference는 "출처 기록, 거의 고정"이고 concept 성장/stale 메커니즘을 우회).
    await _seed_document(
        session_factory,
        markdown_root,
        rel="resources/zettelkasten-note.md",
        markdown="---\ntype: reference\ntitle: Zettelkasten\n---\n\n출처 기록.\n",
    )
    output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "markdown_full": _main_markdown("메인은 깨끗함."),
        },
        "derived_suggestions": [
            {
                "suggestion_type": "supplement_existing_concept",
                "target_stem": "zettelkasten-note",
                "file_action": "overwrite_markdown",
                "draft_markdown": "---\ntype: reference\ntitle: Zettelkasten\n---\n\n출처 기록. 잘못된 보충.\n",
                "link_reason": "reference를 잘못 보충 시도.",
            }
        ],
    }
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=output, url="https://example.com/supplement-ref"
    )
    async with session_factory() as session:
        with pytest.raises(ApplyValidationError) as exc:
            await GateService(session).approve(gate_id)
        assert exc.value.primary_code == "SUPPLEMENT_TARGET_NOT_CONCEPT"
        await session.rollback()
    # apply 안 됨: reference 원본 유지(보충 미반영), main 미생성, source 여전히 summarized.
    assert "잘못된 보충" not in (
        markdown_root / "resources/zettelkasten-note.md"
    ).read_text("utf-8")
    assert not (markdown_root / "resources/graph-rag-note.md").exists()
    async with session_factory() as session:
        assert (await SourceRepository(session).get(source_id)).status == "summarized"


async def test_route_reject_supplement_target_not_concept(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    markdown_root: Path,
) -> None:
    # 라우트 표면화: 422 + SUPPLEMENT_TARGET_NOT_CONCEPT (Case Matrix 임시 표면화).
    await _seed_document(
        session_factory,
        markdown_root,
        rel="resources/zettelkasten-note.md",
        markdown="---\ntype: reference\ntitle: Zettelkasten\n---\n\n출처 기록.\n",
    )
    output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "markdown_full": _main_markdown("메인은 깨끗함."),
        },
        "derived_suggestions": [
            {
                "suggestion_type": "supplement_existing_concept",
                "target_stem": "zettelkasten-note",
                "file_action": "overwrite_markdown",
                "draft_markdown": "---\ntype: reference\ntitle: Zettelkasten\n---\n\n출처 기록. 잘못된 보충.\n",
                "link_reason": "reference를 잘못 보충 시도.",
            }
        ],
    }
    source_id, gate_id, _ = await _to_review_pending(
        session_factory,
        documentation_output=output,
        url="https://example.com/route-supplement-ref",
    )
    headers = await _auth_headers(client)
    res = await client.post(f"/gates/{gate_id}/approve", headers=headers)
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "SUPPLEMENT_TARGET_NOT_CONCEPT"


async def test_supplement_target_concept_passes(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # 대비: 같은 supplement가 concept 노트를 대상으로 하면 정상 통과·overwrite된다.
    await _seed_document(
        session_factory,
        markdown_root,
        rel="permanent/concepts/zettelkasten.md",
        markdown="---\ntype: concept\ntitle: Zettelkasten\n---\n\n초기 개념.\n",
    )
    output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "markdown_full": _main_markdown("관련 개념은 [[zettelkasten]]다."),
        },
        "derived_suggestions": [
            {
                "suggestion_type": "supplement_existing_concept",
                "target_stem": "zettelkasten",
                "file_action": "overwrite_markdown",
                "draft_markdown": "---\ntype: concept\ntitle: Zettelkasten\n---\n\n초기 개념. 보강됨(v2).\n",
                "link_reason": "이 reference가 개념을 보강한다.",
            }
        ],
    }
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=output, url="https://example.com/supplement-concept"
    )
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()
    # concept 보충 반영 + source documented.
    assert "보강됨(v2)" in (
        markdown_root / "permanent/concepts/zettelkasten.md"
    ).read_text("utf-8")
    async with session_factory() as session:
        assert (await SourceRepository(session).get(source_id)).status == "documented"


async def test_skipped_derived_recorded_in_apply_plan(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    from axkg.repositories.apply_plans import ApplyPlanRepository

    # 최초 문서화 승인.
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=PLAIN_DOC, url="https://example.com/skipped"
    )
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()

    # 재문서화 revision에 draft_markdown 없는 파생 제안 → executor가 skip + apply_plans.skipped 박제.
    v2 = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "target_path": "resources/graph-rag-note.md",
            "markdown_full": _main_markdown("본문 v2."),
        },
        "derived_suggestions": [
            {
                "suggestion_type": "create_new_concept",
                "change_kind": "create",
                "target_path": "permanent/concepts/no-body-concept.md",
                "link_reason": "본문 없는 제안.",
            }
        ],
    }
    rev_id = await _redocument(
        session_factory, markdown_root, gate_id=gate_id, source_id=source_id, output=v2
    )
    async with session_factory() as session:
        plan = await ApplyPlanRepository(session).get_by_revision(rev_id)
        assert plan is not None
        assert plan.status == "applied"
        assert len(plan.skipped) == 1
        assert plan.skipped[0]["target_path"] == "permanent/concepts/no-body-concept.md"
        assert plan.skipped[0]["reason"] == "no_draft_markdown"
    # skip된 파생 파일은 생성되지 않음.
    assert not (markdown_root / "permanent/concepts/no-body-concept.md").exists()


# ---------------------------------------------------------------------------
# 경로 시스템 강제: AI는 파일명만, 디렉토리는 시스템 (PLAN-009-T-040)
# ---------------------------------------------------------------------------


def _doc_task(
    *, source_id: uuid.UUID, gate_id: uuid.UUID, revision_id: uuid.UUID
) -> AiTaskDTO:
    """handle_result가 읽는 최소 필드만 담은 문서화 실행 task DTO(재문서화 시뮬레이션)."""
    return AiTaskDTO(
        id=uuid.uuid4(),
        task_type="regenerate_documentation_gate",
        status="running",
        provider="claude",
        source_id=source_id,
        gate_id=gate_id,
        revision_id=revision_id,
        open_kknaks_session_id="okk-doc-x",
        queued_at=utcnow(),
    )


async def test_prior_main_path_reused_on_redocument(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # ② 재문서화 시 AI 파일명이 흔들려도 시스템은 기존 main 경로를 재사용한다(경로 흔들림 차단).
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=PLAIN_DOC, url="https://example.com/reuse"
    )
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()  # current main = resources/graph-rag-note.md

    async with session_factory() as session:
        gates = GateRepository(session)
        v2 = await gates.create_revision(
            gate_id=gate_id,
            version=await gates.next_version(gate_id),
            status="drafting",
            payload={},
            form_schema_version="documentation.v1",
        )
        await session.commit()
        v2_id = v2.id

    shifted = {
        "document_draft": {
            "filename_candidate": "graph-rag-note-RENAMED.md",  # 흔들린 파일명
            "markdown_full": _main_markdown("본문 v2."),
        },
        "derived_suggestions": [],
    }
    async with session_factory() as session:
        builder = DocumentationGateContextBuilder(
            session, root=MarkdownRoot(str(markdown_root))
        )
        await builder.handle_result(
            _doc_task(source_id=source_id, gate_id=gate_id, revision_id=v2_id), shifted
        )
        await session.commit()

    async with session_factory() as session:
        rev = await GateRepository(session).get_revision(v2_id)
        # 파일명이 바뀌어도 target_path는 기존 main 경로 재사용.
        assert (
            rev.payload["form"]["document_draft"]["target_path"]
            == "resources/graph-rag-note.md"
        )


async def test_supplement_stem_resolved_to_existing_path(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # ④ supplement의 target_stem이 index에서 기존 concept 경로로 해소되어 envelope에 저장된다.
    await _seed_document(
        session_factory,
        markdown_root,
        rel="permanent/concepts/zettelkasten.md",
        markdown="---\ntype: concept\ntitle: Zettelkasten\n---\n\n초기 개념.\n",
    )
    output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "markdown_full": _main_markdown("관련 개념은 [[zettelkasten]]다."),
        },
        "derived_suggestions": [
            {
                "suggestion_type": "supplement_existing_concept",
                "target_stem": "zettelkasten",
                "file_action": "overwrite_markdown",
                "draft_markdown": "---\ntype: concept\ntitle: Zettelkasten\n---\n\n초기 개념. 보강.\n",
                "link_reason": "보강.",
            }
        ],
    }
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=output, url="https://example.com/stem-resolve"
    )
    async with session_factory() as session:
        gate = await GateRepository(session).get_gate(gate_id)
        rev = await GateRepository(session).get_revision(gate.active_revision_id)
        derived = rev.payload["form"]["derived_suggestions"][0]
        assert derived["target_path"] == "permanent/concepts/zettelkasten.md"


async def test_unresolvable_supplement_stem_rejected_by_executor(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # ⑤ target_stem이 해소되지 않으면 wrap이 target_path=""로 두고, executor 안전망
    # (PATH_NOT_ALLOWED)이 거부한다 — 신규 에러코드 발명 없음.
    output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "markdown_full": _main_markdown("메인은 깨끗함."),
        },
        "derived_suggestions": [
            {
                "suggestion_type": "supplement_existing_concept",
                "target_stem": "no-such-concept-anywhere",
                "file_action": "overwrite_markdown",
                "draft_markdown": "---\ntype: concept\ntitle: X\n---\n\n본문.\n",
                "link_reason": "해소 불가 대상.",
            }
        ],
    }
    source_id, gate_id, _ = await _to_review_pending(
        session_factory,
        documentation_output=output,
        url="https://example.com/unresolvable-stem",
    )
    async with session_factory() as session:
        with pytest.raises(ApplyValidationError) as exc:
            await GateService(session).approve(gate_id)
        assert exc.value.primary_code == "PATH_NOT_ALLOWED"
        await session.rollback()


async def test_filename_with_directory_and_ext_normalized_end_to_end(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    # ⑥ AI가 filename에 디렉토리/.md를 섞어 내도 시스템이 정규화해 올바른 경로에 확정한다.
    output = {
        "document_draft": {
            "filename_candidate": "concepts/graph-rag-note.md",  # 디렉토리 섞임
            "markdown_full": _main_markdown("정규화 대상."),
        },
        "derived_suggestions": [],
    }
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=output, url="https://example.com/normalize"
    )
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()
    assert (markdown_root / "resources/graph-rag-note.md").is_file()
    assert not (markdown_root / "resources/concepts/graph-rag-note.md").exists()
