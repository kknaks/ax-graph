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
from axkg.services.ai.feature_spec import PLAN_ITEM_KEY
from axkg.services.ai.plan_project import PlanProjectContextBuilder
from axkg.services.gates import GateService
from axkg.services.graph import GraphService
from axkg.services.plan_fanout_execution import (
    _latest_by_seq,
    _resolve_feature_target,
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
    existing_spec = {
        "stem": "shared-calendar",
        "title": "공유 캘린더",
        "path": "projects/the-sc/spec/shared-calendar.md",
    }
    corp_specs = {"shared-calendar": existing_spec}
    ebs = {"shared-calendar": type("D", (), {"stem": "shared-calendar"})}
    # 기존 stem 재사용 → supplement + 기존 전문 주입
    a1 = _resolve_feature_target("shared-calendar", "the-sc", ebs, corp_specs, set(), root)
    assert a1.suggestion_type == "supplement_existing_feature"
    assert a1.target_stem == "shared-calendar"
    assert "기존 상세" in a1.existing_md
    # 새 stem(충돌 없음) → create as-is
    a2 = _resolve_feature_target("new-thing", "the-sc", {}, corp_specs, set(), root)
    assert a2.suggestion_type == "create_feature_spec"
    assert a2.final_stem == "new-thing" and a2.target_stem is None
    # 인덱스엔 있으나 파일이 없으면(전문 읽기 실패) supplement 안 하고 disambiguate create
    ghost_cs = {"ghost": {"stem": "ghost", "title": "g", "path": "projects/the-sc/spec/ghost.md"}}
    ghost_ebs = {"ghost": type("D", (), {"stem": "ghost"})}
    a3 = _resolve_feature_target("ghost", "the-sc", ghost_ebs, ghost_cs, set(), root)
    assert a3.suggestion_type == "create_feature_spec"
    assert a3.final_stem == "the-sc-ghost"  # 충돌 회피(전문 못 읽어 supplement 불가)


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
        # the-sc의 shared-calendar는 acme와 별개 → create(회사 넘는 매칭 안 함)이되, acme와 stem이
        # 겹치므로 disambiguate해 DUPLICATE_STEM을 피한다(the-sc-shared-calendar).
        assert latest[1].payload["suggestion_type"] == "create_feature_spec"
        assert latest[1].payload[PLAN_ITEM_KEY]["filename_candidate"] == "the-sc-shared-calendar.md"
        revision = await GateRepository(session).get_revision(rev_id)
        derived = revision.payload["form"]["derived_suggestions"]
        types = {d["suggestion_type"] for d in derived}
        assert types == {"create_feature_spec"}
        paths = {d["target_path"] for d in derived}
        assert "projects/the-sc/spec/the-sc-shared-calendar.md" in paths  # 별개 문서
    # acme 원본 문서는 불변(회사 넘는 매칭 안 함)
    async with session_factory() as session:
        acme = await DocumentRepository(session).get_by_stem("shared-calendar")
        assert acme.path == "projects/acme/spec/shared-calendar.md"


# ---------------------------------------------------------------------------
# create stem이 concept과 충돌 → disambiguate(concept 불변, DUPLICATE_STEM 안 남)
# ---------------------------------------------------------------------------


async def _index_concept(session_factory, root: MarkdownRoot, stem: str) -> None:
    rel = f"permanent/concepts/{stem}.md"
    root.write_new(rel, f"---\ntype: concept\ntitle: {stem}\n---\n\n# {stem}\n\n원자 개념.\n")
    async with session_factory() as s:
        await GraphService(s, root=root).rebuild_document(rel)
        await s.commit()


async def test_create_colliding_with_concept_disambiguates(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    sid, gate_id, rev_id, plan_task_id = await _setup_project_gate(session_factory, root)
    # 전역 concept 'review-manage'가 이미 있다(같은 stem을 plan이 뽑는 상황).
    await _index_concept(session_factory, root, "review-manage")

    await execute_plan_then_fanout(
        plan_task_id, gate_id, rev_id, client=RoutingFakeClient(fail_stems=set()),
        session_factory=session_factory, root=root,
    )
    async with session_factory() as session:
        feats = await AiTaskRepository(session).list_by_gate(gate_id, "generate_feature_spec")
        latest = _latest_by_seq(feats)
        # seq2(review-manage)는 supplement가 아니라(concept이므로) disambiguate create
        assert latest[2].payload["suggestion_type"] == "create_feature_spec"
        assert latest[2].payload[PLAN_ITEM_KEY]["filename_candidate"] == "the-sc-review-manage.md"
        revision = await GateRepository(session).get_revision(rev_id)
        main_md = revision.payload["form"]["document_draft"]["markdown_full"]
        # 원본요약 링크가 concept이 아니라 disambiguate된 feature를 가리킨다
        assert "[[the-sc-review-manage]]" in main_md
        assert "[[review-manage]]" not in main_md

    # 승인 → apply: DUPLICATE_STEM 없이 통과, concept 불변
    async with session_factory() as session:
        await GateService(session).approve(gate_id)  # ApplyValidationError 안 나야 함
        await session.commit()
    async with session_factory() as session:
        docs = DocumentRepository(session)
        concept = await docs.get_by_stem("review-manage")
        assert concept.document_type == "concept"  # 침범 안 됨
        assert concept.path == "permanent/concepts/review-manage.md"
        assert concept.version == 1  # 업그레이드/overwrite 안 됨
        # disambiguate된 feature는 별개 문서로 생성
        feat = await docs.get_by_stem("the-sc-review-manage")
        assert feat is not None and feat.document_type == "feature_spec"
        src = await SourceRepository(session).get(sid)
        assert src.status == "documented"  # apply 성공


# ---------------------------------------------------------------------------
# within-plan 중복 stem → 규칙대로(둘째는 매칭 없으면 disambiguate)
# ---------------------------------------------------------------------------


def test_within_plan_duplicate_disambiguates(markdown_root: Path) -> None:
    root = MarkdownRoot(str(markdown_root))
    # 인덱스 비어 있음. 같은 fanout에서 'cal'이 두 번 나오는 상황.
    assigned: set = set()
    a1 = _resolve_feature_target("cal", "the-sc", {}, {}, assigned, root)
    assert a1.suggestion_type == "create_feature_spec" and a1.final_stem == "cal"
    assigned.add(a1.final_stem)
    a2 = _resolve_feature_target("cal", "the-sc", {}, {}, assigned, root)
    # 둘째는 앞 기능과 충돌 → disambiguate(within-plan은 원본요약 재작성 대상 아님)
    assert a2.suggestion_type == "create_feature_spec"
    assert a2.final_stem == "the-sc-cal" and a2.remap_main is False
