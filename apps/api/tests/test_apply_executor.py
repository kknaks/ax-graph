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
from axkg.models.base import utcnow
from axkg.repositories.documents import DocumentRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
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
    "document_draft": {
        "filename_candidate": "graph-rag-note.md",
        "target_path": "reference/graph-rag-note.md",
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
    assert (markdown_root / "reference/graph-rag-note.md").is_file()
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
            "target_path": "reference/graph-rag-note.md",
            "markdown_full": _main_markdown(
                "관련 개념은 [[evidence-first-rag]]와 [[agent-experience]]다."
            ),
        },
        "derived_suggestions": [
            {
                "suggestion_type": "supplement_existing_concept",
                "target_path": "permanent/concepts/agent-experience.md",
                "file_action": "patch_markdown",
                "target_document_id": "agent-experience",
                "draft_markdown": "---\ntype: concept\ntitle: Agent Experience\n---\n\n초기 개념. 보강됨(v2).\n",
                "link_reason": "이 reference가 개념을 보강한다.",
            },
            {
                "suggestion_type": "create_new_concept",
                "target_path": "permanent/concepts/evidence-first-rag.md",
                "draft_markdown": "---\ntype: concept\ntitle: Evidence-first RAG\n---\n\n근거 우선 RAG.\n",
                "link_reason": "새 개념 정의.",
            },
            {
                "suggestion_type": "create_project_baseline",
                "target_path": "baselines/baseline-002-graph-rag.md",
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
    assert (markdown_root / "baselines/baseline-002-graph-rag.md").is_file()
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


# ---------------------------------------------------------------------------
# Case Matrix — 거부(apply 안 함)
# ---------------------------------------------------------------------------


async def test_reject_broken_wikilink(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    output = {
        "document_draft": {
            "filename_candidate": "graph-rag-note.md",
            "target_path": "reference/graph-rag-note.md",
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
    assert not (markdown_root / "reference/graph-rag-note.md").exists()
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
    output = {
        "document_draft": {
            "filename_candidate": "evil.md",
            "target_path": "../evil.md",
            "markdown_full": _main_markdown("root 밖 경로."),
        },
        "derived_suggestions": [],
    }
    source_id, gate_id, _ = await _to_review_pending(
        session_factory, documentation_output=output, url="https://example.com/escape"
    )
    async with session_factory() as session:
        with pytest.raises(ApplyValidationError) as exc:
            await GateService(session).approve(gate_id)
        assert exc.value.primary_code == "PATH_NOT_ALLOWED"
        await session.rollback()
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
            "target_path": "reference/graph-rag-note.md",
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
