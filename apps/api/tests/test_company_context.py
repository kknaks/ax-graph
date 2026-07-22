"""AXKG-WORK-013 — 회사 루트 + context 층 + up: 회사 루트 수렴 (AXKG-DEC-009).

커버:
- P1 회사 루트 `{corp}.md`(document_type=company) 생성 + 그래프 노드 인덱싱
- P2 요구/context 분기 — 메모 성격 힌트로 requirement/context 판정, 라우팅
- P3 context 단일 문서 — projects/{corp}/context/{문서}.md(팬아웃 없음)로 apply
- P4/P5 up: 회사 루트 체인 — baseline·context→up:[{corp}], spec→up:[원본요약]→{corp} 수렴
"""
import json
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
from axkg.services import project_scaffold as ps
from axkg.services.document_anchor import apply_document_anchor
from axkg.services.documentation_gate_execution import execute_documentation_gate
from axkg.services.gates import GateService
from axkg.services.graph import GraphService
from axkg.services.plan_fanout_execution import execute_plan_then_fanout
from axkg.storage.markdown_parser import parse_markdown
from axkg.storage.markdown_root import MarkdownRoot
from tests.test_plan_fanout import RoutingFakeClient, _setup_project_gate

ADMIN_EMAIL = "kknaks@medisolveai.com"
SEED_PASSWORD = "1234"


@pytest.fixture
def markdown_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "axkg_markdown_root", str(tmp_path))
    return tmp_path


async def _headers(client: AsyncClient) -> dict[str, str]:
    res = await client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": SEED_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['token']}"}


class ContextDocFake(OpenKknaksClient):
    """generate_documentation_gate에 회사 context 단일 문서를 돌려주는 fake(파생 없음)."""

    def __init__(self, filename: str = "org.md") -> None:
        self._filename = filename

    async def submit_task(self, request):  # pragma: no cover
        return "okk"

    async def get_task_status(self, task_id):  # pragma: no cover
        return "done"

    async def wait_result(self, task_id, *, timeout_sec=None):  # pragma: no cover
        return OpenKknaksTaskResult(task_id=task_id, status="done")

    async def run_task(self, request: OpenKknaksTaskRequest) -> OpenKknaksTaskResult:
        md = (
            "---\ntype: reference\ntitle: 조직도\n---\n\n"
            "# 조직도\n\n## 요약\n회사 조직 배경.\n\n## 연결\n"
        )
        out = {
            "document_draft": {"filename_candidate": self._filename, "markdown_full": md},
            "derived_suggestions": [],
        }
        return OpenKknaksTaskResult(
            task_id="okk", status="done", result_text=json.dumps(out), session_id="s"
        )


# ---------------------------------------------------------------------------
# P2 — 요구/context sub-type 판정(메모 힌트 우선, 폴백 requirement)
# ---------------------------------------------------------------------------


def test_resolve_project_subtype() -> None:
    assert ps.resolve_project_subtype("SC 회사 정보야") == "context"
    assert ps.resolve_project_subtype("조직도 업로드") == "context"
    assert ps.resolve_project_subtype("휴가 업무 플로우") == "context"
    # 힌트 없으면 안전 폴백 requirement
    assert ps.resolve_project_subtype("더에스씨 요구사항 docx") == "requirement"
    assert ps.resolve_project_subtype("") == "requirement"
    assert ps.resolve_project_subtype(None) == "requirement"


# ---------------------------------------------------------------------------
# P1 — 회사 루트 {corp}.md 생성 + 그래프 노드 인덱싱
# ---------------------------------------------------------------------------


async def test_create_company_root_indexes_node(
    client: AsyncClient, markdown_root: Path
) -> None:
    headers = await _headers(client)
    res = await client.post(
        "/projects",
        json={"name": "The SC", "domain": "the-sc.com", "intro": "보험 AX 회사"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["root_path"] == "projects/the-sc/the-sc.md"
    # 회사 루트 파일 + 내용
    root_file = markdown_root / "projects/the-sc/the-sc.md"
    assert root_file.is_file()
    text = root_file.read_text()
    assert "type: company" in text and "the-sc.com" in text and "보험 AX 회사" in text


async def test_company_root_is_graph_node(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    scaffold = ps.create_scaffold(root, "the-sc")
    async with session_factory() as s:
        await GraphService(session=s, root=root).rebuild_document(scaffold["root_path"])
        await s.commit()
    async with session_factory() as s:
        doc = await DocumentRepository(s).get_by_stem("the-sc")
        assert doc is not None and doc.document_type == "company"  # up-target 허브 노드


# ---------------------------------------------------------------------------
# P2/P3 — context 메모 → 단일 문서 task 라우팅 + context/ 단일 apply
# ---------------------------------------------------------------------------


async def _setup_context_gate(session_factory, root, corp="the-sc"):
    """project + context 메모 상태의 문서화 게이트를 만든다(회사 루트 인덱싱 포함)."""
    scaffold = ps.create_scaffold(root, corp)
    async with session_factory() as s:
        await GraphService(session=s, root=root).rebuild_document(scaffold["root_path"])
        await s.commit()
    async with session_factory() as s:
        repo = SourceRepository(s)
        src = await repo.create(
            source_url=None, normalized_url=None, source_channel="upload",
            submitted_by=None, submitted_at=utcnow(),
            raw_text="회사 조직도: 대표-실장-팀원. 휴가 플로우: 신청→승인.",
            metadata={"intake_note": f"{corp} 회사 정보야"},
        )
        await repo.set_summary(src.id, {"title": "조직 배경", "summary": "회사 배경"})
        cls = await GateRepository(s).create_gate(
            source_id=src.id, gate_kind="classification", status="approved"
        )
        await repo.set_classification_destination(
            src.id, destination_type="project", gate_id=cls.id, archived=False
        )
        gate = await GateRepository(s).create_gate(
            source_id=src.id, gate_kind="documentation", status="not_started"
        )
        result = await GateService(s)._start_documentation_gate(gate, src, "project")
        await s.commit()
        return src.id, result.gate.id, result.revision.id, result.ai_task.id


async def test_context_memo_routes_to_single_doc_task(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    _sid, _gid, _rid, task_id = await _setup_context_gate(session_factory, root)
    async with session_factory() as s:
        from axkg.repositories.ai_tasks import AiTaskRepository

        task = await AiTaskRepository(s).get(task_id)
        # context는 plan_project 팬아웃이 아니라 단일 generate_documentation_gate
        assert task.task_type == "generate_documentation_gate"
        assert task.payload.get("project_subtype") == "context"
        assert task.payload.get("corp") == "the-sc"


async def test_context_applies_single_context_doc(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    sid, gate_id, rev_id, task_id = await _setup_context_gate(session_factory, root)
    await execute_documentation_gate(
        task_id, gate_id, rev_id, client=ContextDocFake("org.md"),
        session_factory=session_factory, root=root,
    )
    async with session_factory() as s:
        revision = await GateRepository(s).get_revision(rev_id)
        form = revision.payload["form"]
        # context = 단일 문서, 팬아웃(derived) 없음
        assert form["document_draft"]["document_type"] == "context"
        assert form["document_draft"]["target_path"] == "projects/the-sc/context/org.md"
        assert form["derived_suggestions"] == []
    # 승인 → apply: context/ 단일 문서 확정(기능정의서로 안 쪼개짐)
    async with session_factory() as s:
        await GateService(s).approve(gate_id)
        await s.commit()
    assert (markdown_root / "projects/the-sc/context/org.md").is_file()
    async with session_factory() as s:
        doc = await DocumentRepository(s).get_by_stem("org")
        assert doc.document_type == "context"
        # up: 회사 루트 수렴 + 본문 [[the-sc]]
        assert "the-sc" in doc.frontmatter.get("up", [])
        parsed = parse_markdown((markdown_root / "projects/the-sc/context/org.md").read_text())
        assert "the-sc" in {w.target for w in parsed.wikilinks}


# ---------------------------------------------------------------------------
# P4/P5 — 요구 팬아웃도 up: 회사 루트로 수렴 (baseline·spec 체인)
# ---------------------------------------------------------------------------


async def test_requirement_fanout_up_chain_converges(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    sid, gate_id, rev_id, plan_task_id = await _setup_project_gate(session_factory, root)
    await execute_plan_then_fanout(
        plan_task_id, gate_id, rev_id, client=RoutingFakeClient(fail_stems=set()),
        session_factory=session_factory, root=root,
    )
    async with session_factory() as s:
        form = (await GateRepository(s).get_revision(rev_id)).payload["form"]
    # 원본요약(main) → up:[the-sc] + 본문 [[the-sc]]
    main_md = form["document_draft"]["markdown_full"]
    main_parsed = parse_markdown(main_md)
    assert "the-sc" in main_parsed.up
    assert "the-sc" in {w.target for w in main_parsed.wikilinks}
    # 각 기능정의서(spec) → up:[원본요약 stem]
    for d in form["derived_suggestions"]:
        sp = parse_markdown(d["draft_markdown"])
        assert "the-sc-summary" in sp.up  # 원본요약 stem
        assert "the-sc-summary" in {w.target for w in sp.wikilinks}

    # 승인 → apply: baseline·spec 확정 + 회사 루트로 lineage 수렴(그래프)
    async with session_factory() as s:
        await GateService(s).approve(gate_id)
        await s.commit()
    async with session_factory() as s:
        docs = DocumentRepository(s)
        baseline = await docs.get_by_stem("the-sc-summary")
        assert baseline is not None and "the-sc" in baseline.frontmatter.get("up", [])
        # 회사 루트로 향하는 lineage 엣지 존재(baseline → the-sc)
        root_doc = await docs.get_by_stem("the-sc")
        edges = await docs.list_edges_to_document(root_doc.id)
        assert any(e.edge_type == "lineage" for e in edges)


# ---------------------------------------------------------------------------
# 순수 — 앵커 헬퍼(중복 방지·연결 섹션 없을 때 생성)
# ---------------------------------------------------------------------------


def test_apply_document_anchor_idempotent_and_creates_section() -> None:
    # 연결 섹션이 없으면 새로 만든다
    md = "---\ntype: baseline\ntitle: X\n---\n\n# X\n\n본문.\n"
    out = apply_document_anchor(md, document_type="baseline", up_target="sc")
    p = parse_markdown(out)
    assert "sc" in p.up and "sc" in {w.target for w in p.wikilinks}
    # 이미 있으면 중복 링크를 만들지 않는다
    out2 = apply_document_anchor(out, document_type="baseline", up_target="sc")
    assert out2.count("[[sc]]") == 1
    assert parse_markdown(out2).up.count("sc") == 1
