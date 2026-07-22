"""회사 내부 기능 dedup(supplement). AXKG-SPEC-014 Feature Dedup / AXKG-DEC-007 D4.

같은 `{corp}`에 같은 기능(같은 stem)이 다시 들어오면 신규 문서를 또 만들지 않고 **기존
기능정의서를 supplement로 업그레이드**한다(부서 무관·corp 경계 한정). 커버:
- 같은 corp 같은 기능 재유입 → supplement_existing_feature(target_stem=기존 stem, 기존 전문 주입)
- 새 기능 → create_feature_spec(현행 유지)
- 다른 corp 같은 이름 → 별개 create(회사 넘는 매칭 금지)
- 기존 전문 읽기 실패 → 안전 폴백 create
- 승인 apply: supplement=기존 문서 overwrite(version++), create=신규
"""
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings
from axkg.models.base import utcnow
from axkg.repositories.ai_tasks import AiTaskRepository
from axkg.repositories.documents import DocumentRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services import project_scaffold as ps
from axkg.services.ai.plan_project import PlanProjectContextBuilder
from axkg.services.gates import GateService
from axkg.services.graph import GraphService
from axkg.services.plan_fanout_execution import (
    _apply_dedup_branch,
    _latest_by_seq,
    execute_plan_then_fanout,
)
from axkg.storage.markdown_root import MarkdownRoot
from tests.test_plan_fanout import (
    SUMMARY_STEM,
    RoutingFakeClient,
    _setup_project_gate,
)


@pytest.fixture
def markdown_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "axkg_markdown_root", str(tmp_path))
    return tmp_path


def _spec_md(stem: str) -> str:
    return (
        f"---\ntype: feature_spec\ntitle: {stem}\nup: [{SUMMARY_STEM}]\n---\n\n"
        f"# {stem}\n\n## 1. 요구 배경\n기존 상세.\n\n## 8. 연결\n- [[{SUMMARY_STEM}]] — 원본요약\n"
    )


async def _index_spec(
    session_factory: async_sessionmaker[AsyncSession], root: MarkdownRoot,
    corp: str, stem: str,
) -> str:
    """기존 기능정의서 하나를 projects/{corp}/spec/에 쓰고 인덱싱한다(dedup 대상 선행 상황)."""
    rel = ps.project_spec_path(corp, f"{stem}.md")
    root.write_new(rel, _spec_md(stem))
    async with session_factory() as session:
        await GraphService(session, root=root).rebuild_document(rel)
        await session.commit()
    return rel


# ---------------------------------------------------------------------------
# 순수 분기 — _apply_dedup_branch
# ---------------------------------------------------------------------------


async def test_dedup_branch_supplement_vs_create(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    ps.create_scaffold(root, "the-sc")
    root.write_new("projects/the-sc/spec/shared-calendar.md", _spec_md("shared-calendar"))
    existing = {
        "shared-calendar": {
            "stem": "shared-calendar",
            "title": "공유 캘린더",
            "path": "projects/the-sc/spec/shared-calendar.md",
        }
    }
    # 기존 stem 재사용 → supplement + 기존 전문 주입
    p1: dict = {}
    _apply_dedup_branch({"filename_candidate": "shared-calendar.md"}, existing, root, p1)
    assert p1["suggestion_type"] == "supplement_existing_feature"
    assert p1["target_stem"] == "shared-calendar"
    assert "기존 상세" in p1["existing_spec_markdown"]
    # 새 stem → create
    p2: dict = {}
    _apply_dedup_branch({"filename_candidate": "new-thing.md"}, existing, root, p2)
    assert p2["suggestion_type"] == "create_feature_spec"
    assert "target_stem" not in p2
    # 인덱스엔 있으나 파일이 없으면(전문 읽기 실패) 안전 폴백 create
    ghost = {"ghost": {"stem": "ghost", "title": "g", "path": "projects/the-sc/spec/ghost.md"}}
    p3: dict = {}
    _apply_dedup_branch({"filename_candidate": "ghost.md"}, ghost, root, p3)
    assert p3["suggestion_type"] == "create_feature_spec"


# ---------------------------------------------------------------------------
# plan 단계 — 기존 기능 컨텍스트 주입
# ---------------------------------------------------------------------------


async def test_plan_injects_existing_corp_features(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    ps.create_scaffold(root, "the-sc")
    await _index_spec(session_factory, root, "the-sc", "shared-calendar")
    async with session_factory() as session:
        src = await SourceRepository(session).create(
            source_url=None, normalized_url=None, source_channel="upload",
            submitted_by=None, submitted_at=utcnow(), raw_text="요구",
            metadata={"intake_note": "the-sc"},
        )
        await session.commit()
        builder = PlanProjectContextBuilder(session)

        class _Task:
            source_id = src.id
            payload = {"corp": "the-sc"}

        blocks = await builder.build_data_blocks(_Task(), None)
    labels = [b.label for b in blocks]
    assert "existing_corp_features" in labels
    text = next(b.text for b in blocks if b.label == "existing_corp_features")
    assert "shared-calendar" in text


# ---------------------------------------------------------------------------
# e2e — 같은 corp 같은 기능 재유입 → supplement 업그레이드
# ---------------------------------------------------------------------------


async def test_same_corp_same_feature_supplements(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    sid, gate_id, rev_id, plan_task_id = await _setup_project_gate(session_factory, root)
    # 선행: the-sc에 shared-calendar 기능정의서가 이미 있고 인덱싱됨(회사 루트도 인덱싱됨).
    await _index_spec(session_factory, root, "the-sc", "shared-calendar")

    await execute_plan_then_fanout(
        plan_task_id, gate_id, rev_id, client=RoutingFakeClient(fail_stems=set()),
        session_factory=session_factory, root=root,
    )
    async with session_factory() as session:
        # 기능 task: seq1(shared-calendar)=supplement, 나머지=create
        feats = await AiTaskRepository(session).list_by_gate(gate_id, "generate_feature_spec")
        latest = _latest_by_seq(feats)
        assert latest[1].payload["suggestion_type"] == "supplement_existing_feature"
        assert latest[1].payload["target_stem"] == "shared-calendar"
        assert latest[2].payload["suggestion_type"] == "create_feature_spec"
        # 조립된 revision derived: supplement 1 + create 2
        revision = await GateRepository(session).get_revision(rev_id)
        derived = revision.payload["form"]["derived_suggestions"]
        by_type: dict = {}
        for d in derived:
            by_type.setdefault(d["suggestion_type"], []).append(d)
        assert len(by_type["supplement_existing_feature"]) == 1
        assert len(by_type["create_feature_spec"]) == 2
        supp = by_type["supplement_existing_feature"][0]
        assert supp["change_kind"] == "modify"
        assert supp["target_path"] == "projects/the-sc/spec/shared-calendar.md"

    # 승인 → apply: 기존 shared-calendar overwrite(version++), 신규 2장 create.
    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()
    async with session_factory() as session:
        docs = DocumentRepository(session)
        cal = await docs.get_by_stem("shared-calendar")
        assert cal.document_type == "feature_spec"
        assert cal.version == 2  # 신규(1)가 아니라 업그레이드(2)
        assert cal.path == "projects/the-sc/spec/shared-calendar.md"  # 중복 문서 아님
        # 새 기능 2장은 신규 생성됨
        assert (await docs.get_by_stem("review-manage")).version == 1
    assert (markdown_root / "projects/the-sc/spec/shared-calendar.md").is_file()


# ---------------------------------------------------------------------------
# 다른 corp 같은 이름 → 별개 create (회사 넘는 매칭 금지)
# ---------------------------------------------------------------------------


async def test_different_corp_same_name_creates_separate(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    sid, gate_id, rev_id, plan_task_id = await _setup_project_gate(session_factory, root, corp="the-sc")
    # 다른 회사(acme)에 shared-calendar가 있어도 the-sc 팬아웃엔 영향 없음.
    ps.create_scaffold(root, "acme")
    await _index_spec(session_factory, root, "acme", "shared-calendar")

    await execute_plan_then_fanout(
        plan_task_id, gate_id, rev_id, client=RoutingFakeClient(fail_stems=set()),
        session_factory=session_factory, root=root,
    )
    async with session_factory() as session:
        feats = await AiTaskRepository(session).list_by_gate(gate_id, "generate_feature_spec")
        latest = _latest_by_seq(feats)
        # the-sc의 shared-calendar는 acme와 별개 → create(회사 넘는 매칭 안 함)
        assert latest[1].payload["suggestion_type"] == "create_feature_spec"
        revision = await GateRepository(session).get_revision(rev_id)
        types = {d["suggestion_type"] for d in revision.payload["form"]["derived_suggestions"]}
        assert types == {"create_feature_spec"}
