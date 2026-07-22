"""AXKG-WORK-012 — plan-then-fanout (project 문서화 생성 재설계). AXKG-DEC-008.

커버:
- P1 plan_project: docx→원본요약+기능목록(plan) 산출, revision.payload 보관
- P2 fan-out: plan 각 기능 → generate_feature_spec task 병렬 발주·실행
- P3 fan-in: N draft 취합 → 게이트 revision(main=원본요약, derived=기능 N) 조립
- 부분 실패 정책: 한 기능 실패 시 나머지로 조립 진행 + 원본요약의 실패 기능 링크 제거(apply-safe)
- 기능 단위 재시도: 실패 기능만 재실행 → revision 재조립(11개 통째 재생성 아님)
- P4 진행률(N중 M) 상태, P5 라우팅: project 분류→plan_project task(단일 문서화 task 아님)
- e2e: 3기능 → 팬아웃 → 승인 → apply(origin+baseline 1+spec N) 기존 경로 재사용
"""
import json
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings
from axkg.integrations.open_kknaks import (
    OpenKknaksClient,
    OpenKknaksTaskRequest,
    OpenKknaksTaskResult,
)
from axkg.models.base import utcnow
from axkg.repositories.ai_tasks import AiTaskRepository
from axkg.repositories.documents import DocumentRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services import project_scaffold as ps
from axkg.services.gates import GateService
from axkg.services.plan_fanout_execution import (
    compute_fanout_progress,
    execute_feature_retry,
    execute_plan_then_fanout,
)
from axkg.storage.markdown_root import MarkdownRoot

SUMMARY_STEM = "the-sc-summary"

PLAN_OUTPUT = {
    "document_draft": {
        "filename_candidate": "the-sc-summary.md",
        "markdown_full": (
            "---\ntype: baseline\ntitle: 더에스씨 원본요약\n---\n\n"
            "# 더에스씨 원본요약\n\n## 요구 개요\n회사 요구.\n\n## 기능 목록\n"
            "- [[shared-calendar]] — 공유 캘린더\n"
            "- [[review-manage]] — 리뷰 관리\n"
            "- [[fail-feature]] — 실패 기능\n"
        ),
    },
    "plan": [
        {"seq": 1, "feature_name": "공유 캘린더", "filename_candidate": "shared-calendar.md", "summary": "부서 공유 캘린더"},
        {"seq": 2, "feature_name": "리뷰 관리", "filename_candidate": "review-manage.md", "summary": "병원 리뷰 관리"},
        {"seq": 3, "feature_name": "실패 기능", "filename_candidate": "fail-feature.md", "summary": "실패한다"},
    ],
}

_FC_RE = re.compile(r'"filename_candidate":\s*"([^"]+)"')


class RoutingFakeClient(OpenKknaksClient):
    """task_type별로 다른 출력을 돌려주는 fake. 기능 task는 프롬프트의 배정 기능 stem을 읽어
    그 기능정의서를 echo하고, fail_stems에 든 기능은 실패(status=failed)로 반환한다."""

    def __init__(self, *, fail_stems: set[str] | None = None) -> None:
        self._fail_stems = fail_stems or set()
        self.feature_calls = 0

    async def submit_task(self, request: OpenKknaksTaskRequest) -> str:  # pragma: no cover
        return "okk-x"

    async def get_task_status(self, task_id: str) -> str | None:  # pragma: no cover
        return "done"

    async def wait_result(self, task_id, *, timeout_sec=None):  # pragma: no cover
        return OpenKknaksTaskResult(task_id=task_id, status="done")

    async def run_task(self, request: OpenKknaksTaskRequest) -> OpenKknaksTaskResult:
        ttype = request.metadata.get("axkg_task_type")
        if ttype == "plan_project":
            return OpenKknaksTaskResult(
                task_id="okk-plan", status="done",
                result_text=json.dumps(PLAN_OUTPUT), session_id="s-plan",
            )
        # generate_feature_spec: 프롬프트에서 배정 기능 filename 추출.
        match = _FC_RE.search(request.prompt)
        fc = match.group(1) if match else "unknown.md"
        stem = fc[:-3] if fc.lower().endswith(".md") else fc
        self.feature_calls += 1
        if stem in self._fail_stems:
            return OpenKknaksTaskResult(
                task_id="okk-f", status="failed", error="simulated feature failure"
            )
        md = (
            f"---\ntype: feature_spec\ntitle: {stem}\nup: [{SUMMARY_STEM}]\n---\n\n"
            f"# {stem}\n\n## 8. 연결\n- [[{SUMMARY_STEM}]] — 원본요약\n"
        )
        out = {"document_draft": {"filename_candidate": fc, "markdown_full": md}}
        return OpenKknaksTaskResult(
            task_id="okk-f", status="done", result_text=json.dumps(out), session_id="s-f"
        )


@pytest.fixture
def markdown_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "axkg_markdown_root", str(tmp_path))
    return tmp_path


async def _setup_project_gate(
    session_factory: async_sessionmaker[AsyncSession], root: MarkdownRoot, corp: str = "the-sc"
):
    """project 분류 확정 상태의 문서화 게이트 + plan_project task를 만든다(scaffold 선행)."""
    scaffold = ps.create_scaffold(root, corp)
    async with session_factory() as session:
        # 회사 루트 {corp}.md를 인덱싱(라우트 미러) — baseline up:[{corp}] 링크가 resolve되도록.
        if scaffold.get("root_path"):
            from axkg.services.graph import GraphService

            await GraphService(session, root=root).rebuild_document(scaffold["root_path"])
            await session.commit()
    async with session_factory() as session:
        repo = SourceRepository(session)
        src = await repo.create(
            source_url=None, normalized_url=None, source_channel="upload",
            submitted_by=None, submitted_at=utcnow(),
            raw_text="요구 1: 공유 캘린더\n요구 2: 리뷰 관리\n요구 3: 기타",
            metadata={"intake_note": corp},
        )
        await repo.set_summary(src.id, {"title": "더에스씨 요구", "summary": "요약"})
        cls_gate = await GateRepository(session).create_gate(
            source_id=src.id, gate_kind="classification", status="approved"
        )
        await repo.set_classification_destination(
            src.id, destination_type="project", gate_id=cls_gate.id, archived=False
        )
        gate = await GateRepository(session).create_gate(
            source_id=src.id, gate_kind="documentation", status="not_started"
        )
        svc = GateService(session)
        result = await svc._start_documentation_gate(gate, src, "project")
        await session.commit()
        return src.id, result.gate.id, result.revision.id, result.ai_task.id


# ---------------------------------------------------------------------------
# 순수 로직
# ---------------------------------------------------------------------------


def test_compute_fanout_progress() -> None:
    plan = [{"seq": 1, "feature_name": "a"}, {"seq": 2, "feature_name": "b"}, {"seq": 3, "feature_name": "c"}]

    class _T:
        def __init__(self, status, seq):
            self.status = status
            self.payload = {"plan_item": {"seq": seq}}

    latest = {1: _T("succeeded", 1), 2: _T("failed", 2), 3: _T("running", 3)}
    prog = compute_fanout_progress(plan, latest)
    assert prog["total"] == 3 and prog["completed"] == 1 and prog["failed"] == 1
    assert prog["running"] == 1 and prog["status"] == "generating"
    assert prog["failed_features"] == [{"seq": 2, "feature_name": "b"}]


# ---------------------------------------------------------------------------
# P5 라우팅 — project 분류는 plan_project task로 시작
# ---------------------------------------------------------------------------


async def test_project_routes_to_plan_task(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    _sid, gate_id, _rev, plan_task_id = await _setup_project_gate(session_factory, root)
    async with session_factory() as session:
        task = await AiTaskRepository(session).get(plan_task_id)
        assert task.task_type == "plan_project"  # 단일 generate_documentation_gate 아님
        assert task.payload.get("corp") == "the-sc"  # corp 바인딩


# ---------------------------------------------------------------------------
# P1~P4 e2e — 팬아웃 + 부분 실패 + 진행률
# ---------------------------------------------------------------------------


async def test_plan_then_fanout_assembles_revision(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    sid, gate_id, rev_id, plan_task_id = await _setup_project_gate(session_factory, root)

    # 3기능 중 fail-feature 하나 실패 → 나머지 2로 조립(부분 진행).
    client = RoutingFakeClient(fail_stems={"fail-feature"})
    await execute_plan_then_fanout(
        plan_task_id, gate_id, rev_id, client=client,
        session_factory=session_factory, root=root,
    )
    assert client.feature_calls == 3  # 3개 기능 task 병렬 발주됨

    async with session_factory() as session:
        gates = GateRepository(session)
        gate = await gates.get_gate(gate_id)
        revision = await gates.get_revision(rev_id)
        assert gate.status == "review_pending"  # fan-in 조립 완료
        assert revision.status == "reviewable"
        form = revision.payload["form"]
        # main=원본요약, derived=성공 기능 2장(create-only)
        assert form["document_draft"]["document_type"] == "baseline"
        derived = form["derived_suggestions"]
        assert len(derived) == 2
        assert {d["suggestion_type"] for d in derived} == {"create_feature_spec"}
        paths = sorted(d["target_path"] for d in derived)
        assert paths == [
            "projects/the-sc/spec/review-manage.md",
            "projects/the-sc/spec/shared-calendar.md",
        ]
        # 진행률: 총 3, 완료 2, 실패 1
        assert form["fanout"]["total"] == 3
        assert form["fanout"]["completed"] == 2
        assert form["fanout"]["failed"] == 1
        # 부분 실패: 원본요약에서 실패 기능 링크가 제거돼 apply-safe
        assert "[[fail-feature]]" not in form["document_draft"]["markdown_full"]
        assert "[[shared-calendar]]" in form["document_draft"]["markdown_full"]

    # 진행률 조회(P4)
    async with session_factory() as session:
        prog = await GateService(session).get_fanout_progress(gate_id)
        assert prog["completed"] == 2 and prog["failed"] == 1


async def test_feature_retry_recovers_and_reassembles(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    sid, gate_id, rev_id, plan_task_id = await _setup_project_gate(session_factory, root)
    # 첫 실행: fail-feature 실패.
    await execute_plan_then_fanout(
        plan_task_id, gate_id, rev_id, client=RoutingFakeClient(fail_stems={"fail-feature"}),
        session_factory=session_factory, root=root,
    )
    # 기능 단위 재시도 큐잉(seq 3만).
    async with session_factory() as session:
        result = await GateService(session).retry_feature(gate_id, 3)
        await session.commit()
        retry_task_id = result.ai_task.id
    # 재시도 실행(이번엔 성공) → 재조립.
    await execute_feature_retry(
        retry_task_id, gate_id, rev_id, client=RoutingFakeClient(fail_stems=set()),
        session_factory=session_factory, root=root,
    )
    async with session_factory() as session:
        revision = await GateRepository(session).get_revision(rev_id)
        form = revision.payload["form"]
        assert len(form["derived_suggestions"]) == 3  # 3장 모두 조립
        assert form["fanout"]["completed"] == 3 and form["fanout"]["failed"] == 0
        # 재조립 시 원본요약의 그 기능 링크가 되살아남
        assert "[[fail-feature]]" in form["document_draft"]["markdown_full"]


async def test_retry_feature_rejects_non_failed(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    from axkg.services.gates import FeatureRetryNotAllowedError

    root = MarkdownRoot(str(markdown_root))
    sid, gate_id, rev_id, plan_task_id = await _setup_project_gate(session_factory, root)
    await execute_plan_then_fanout(
        plan_task_id, gate_id, rev_id, client=RoutingFakeClient(fail_stems={"fail-feature"}),
        session_factory=session_factory, root=root,
    )
    async with session_factory() as session:
        # seq 1은 성공했으므로 재시도 거부
        with pytest.raises(FeatureRetryNotAllowedError):
            await GateService(session).retry_feature(gate_id, 1)


# ---------------------------------------------------------------------------
# e2e — 팬아웃 → 승인 → apply(기존 main+derived 경로 재사용)
# ---------------------------------------------------------------------------


async def test_fanout_then_approve_applies_pantout(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    sid, gate_id, rev_id, plan_task_id = await _setup_project_gate(session_factory, root)
    # 전 기능 성공(부분 실패 없음) → 3장 조립.
    await execute_plan_then_fanout(
        plan_task_id, gate_id, rev_id, client=RoutingFakeClient(fail_stems=set()),
        session_factory=session_factory, root=root,
    )
    # 게이트 승인 → apply(기존 apply_executor, main+derived 팬아웃 재사용).
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()
    # 원본요약 1장 + 기능정의서 3장이 회사 프로젝트 3층에 확정 문서화됨.
    assert (markdown_root / "projects/the-sc/baseline/the-sc-summary.md").is_file()
    for stem in ("shared-calendar", "review-manage", "fail-feature"):
        assert (markdown_root / f"projects/the-sc/spec/{stem}.md").is_file()
    async with session_factory() as session:
        docs = DocumentRepository(session)
        assert (await docs.get_by_stem("the-sc-summary")).document_type == "baseline"
        assert (await docs.get_by_stem("shared-calendar")).document_type == "feature_spec"
        src = await SourceRepository(session).get(sid)
        assert src.status == "documented"
