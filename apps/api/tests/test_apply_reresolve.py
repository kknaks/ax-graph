"""apply 시점 stem 충돌 재해결(TOCTOU) — dedup→supplement / disambiguate + baseline 회피.

승인 지연 사이 라이브 DB가 바뀌어 spawn 배정이 무효화되는 TOCTOU를 apply_executor가
재해결하는지 검증한다(DUPLICATE_STEM/DocumentExistsError를 애초에 흡수). 커버:
- (a) cross-source baseline 충돌 → baseline disambiguate(기존 불변, 하드페일 없음)
- (b) TOCTOU feature 충돌(같은 corp current feature_spec) → create→supplement(merge), version++
- (c) create feature stem이 concept과 충돌 → disambiguate(concept 불변, supplement 가드 무침범)
- (d) 다른 corp 같은 stem → disambiguate(별개, 기존 corp 불변)
- (e) 링크 전파: main/feature stem 재작성 시 up:·`## 기능 목록`·본문 링크 정합
- (f) 회귀: 같은 소스 재-baseline(own)은 disambiguate 안 함 / 충돌 없으면 stem 불변

전략: execute_plan_then_fanout로 spawn+fan-in(충돌 없이 reviewable)까지 만든 뒤, 승인 직전
라이브 인덱스에 충돌 문서를 주입하고 approve → apply 재해결 경로를 탄다.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings
from axkg.models.base import utcnow
from axkg.repositories.documents import DocumentRepository
from axkg.repositories.gates import GateRepository
from axkg.repositories.sources import SourceRepository
from axkg.services import project_scaffold as ps
from axkg.services.gates import GateService
from axkg.services.graph import GraphService
from axkg.services.plan_fanout_execution import execute_plan_then_fanout
from axkg.storage.markdown_root import MarkdownRoot
from axkg.workers.apply_executor import ApplyExecutor, ApplyValidationError
from tests.test_plan_fanout import (
    SUMMARY_STEM,
    RoutingFakeClient,
    _setup_project_gate,
)


@pytest.fixture
def markdown_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "axkg_markdown_root", str(tmp_path))
    return tmp_path


def _baseline_md(stem: str) -> str:
    return (
        f"---\ntype: baseline\ntitle: {stem}\nup: [the-sc]\n---\n\n"
        f"# {stem}\n\n## 요구 개요\n기존 원본요약.\n\n## 연결\n- [[the-sc]] — 회사 루트\n"
    )


def _spec_md(stem: str, *, up: str = SUMMARY_STEM, body: str = "기존 상세.") -> str:
    return (
        f"---\ntype: feature_spec\ntitle: {stem}\nup: [{up}]\n---\n\n"
        f"# {stem}\n\n## 1. 요구 배경\n{body}\n\n## 8. 연결\n- [[{up}]] — 원본요약\n"
    )


async def _index(
    session_factory: async_sessionmaker[AsyncSession], root: MarkdownRoot,
    rel: str, md: str,
) -> None:
    root.write_new(rel, md)
    async with session_factory() as session:
        await GraphService(session, root=root).rebuild_document(rel)
        await session.commit()


async def _fanout_reviewable(
    session_factory: async_sessionmaker[AsyncSession], root: MarkdownRoot,
):
    """spawn+fan-in을 돌려 충돌 없이 reviewable까지 만든다(3기능 모두 create)."""
    sid, gate_id, rev_id, plan_task_id = await _setup_project_gate(session_factory, root)
    await execute_plan_then_fanout(
        plan_task_id, gate_id, rev_id, client=RoutingFakeClient(fail_stems=set()),
        session_factory=session_factory, root=root,
    )
    return sid, gate_id, rev_id


# ---------------------------------------------------------------------------
# (a) cross-source baseline 충돌 → disambiguate(기존 불변, DUPLICATE_STEM 없음)
# ---------------------------------------------------------------------------


async def test_cross_source_baseline_disambiguates(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    sid, gate_id, rev_id = await _fanout_reviewable(session_factory, root)
    # 승인 직전: 다른 소스가 같은 stem baseline(the-sc-summary)을 이미 만들어 둠(TOCTOU).
    await _index(
        session_factory, root,
        "projects/the-sc/baseline/the-sc-summary.md", _baseline_md("the-sc-summary"),
    )

    async with session_factory() as session:
        await GateService(session).approve(gate_id)  # DUPLICATE_STEM 없이 통과해야 함
        await session.commit()

    async with session_factory() as session:
        docs = DocumentRepository(session)
        # 새 baseline은 distinctive stem으로 회피됨(-2), 기존 baseline은 불변.
        original = await docs.get_by_path("projects/the-sc/baseline/the-sc-summary.md")
        assert original is not None and original.version == 1  # 기존 불변
        new_base = await docs.get_by_stem("the-sc-summary-2")
        assert new_base is not None and new_base.document_type == "baseline"
        src = await SourceRepository(session).get(sid)
        assert src.status == "documented"  # apply 성공
        # (e) 링크 전파: 파생 spec의 up:/본문이 새 원본요약 stem을 가리킨다(끊긴 링크 없음).
        cal = await docs.get_by_stem("shared-calendar")
        cal_md = root.read_text(cal.path)
        assert "[[the-sc-summary-2]]" in cal_md
        assert "[[the-sc-summary]]" not in cal_md.replace("[[the-sc-summary-2]]", "")
    # 새 원본요약 본문 파일이 새 경로에 확정됨.
    assert (markdown_root / "projects/the-sc/baseline/the-sc-summary-2.md").is_file()


# ---------------------------------------------------------------------------
# (b) TOCTOU feature 충돌 → create→supplement(merge), 기존 stem 업그레이드
# ---------------------------------------------------------------------------


async def test_toctou_feature_supplements(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    sid, gate_id, rev_id = await _fanout_reviewable(session_factory, root)
    # 승인 직전: 같은 corp에 shared-calendar 기능정의서가 새로 생김(spawn엔 없었음).
    await _index(
        session_factory, root,
        "projects/the-sc/spec/shared-calendar.md",
        _spec_md("shared-calendar", body="기존 캘린더 상세 정의."),
    )

    async with session_factory() as session:
        await GateService(session).approve(gate_id)  # DocumentExistsError 없이 통과
        await session.commit()

    async with session_factory() as session:
        docs = DocumentRepository(session)
        cal = await docs.get_by_stem("shared-calendar")
        assert cal.document_type == "feature_spec"
        assert cal.path == "projects/the-sc/spec/shared-calendar.md"  # 중복 문서 아님
        assert cal.version == 2  # 신규(1)가 아니라 supplement 업그레이드(2)
        # 다른 2기능은 신규 create.
        assert (await docs.get_by_stem("review-manage")).version == 1
    # 병합 보존: 기존 전문 본문이 파일에 남아 있다(정보 손실 없음).
    merged = root.read_text("projects/the-sc/spec/shared-calendar.md")
    assert "기존 캘린더 상세 정의." in merged
    assert "이전 정의(병합 보존)" in merged


# ---------------------------------------------------------------------------
# (c) create feature stem이 concept과 충돌 → disambiguate(concept 불변)
# ---------------------------------------------------------------------------


async def test_feature_colliding_concept_disambiguates(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    sid, gate_id, rev_id = await _fanout_reviewable(session_factory, root)
    # 승인 직전: 전역 concept 'review-manage'가 생김(feature와 같은 stem).
    await _index(
        session_factory, root,
        "permanent/concepts/review-manage.md",
        "---\ntype: concept\ntitle: review-manage\n---\n\n# review-manage\n\n원자 개념.\n",
    )

    async with session_factory() as session:
        await GateService(session).approve(gate_id)  # 통과(concept-supplement 가드 무침범)
        await session.commit()

    async with session_factory() as session:
        docs = DocumentRepository(session)
        concept = await docs.get_by_stem("review-manage")
        assert concept.document_type == "concept"  # 침범 안 됨
        assert concept.path == "permanent/concepts/review-manage.md"
        assert concept.version == 1  # overwrite/supplement 안 됨
        feat = await docs.get_by_stem("the-sc-review-manage")
        assert feat is not None and feat.document_type == "feature_spec"
        # (e) 링크 전파: 원본요약 `## 기능 목록`이 disambiguate된 feature를 가리킨다.
        base = await docs.get_by_stem("the-sc-summary")
        base_md = root.read_text(base.path)
        assert "[[the-sc-review-manage]]" in base_md
        assert "[[review-manage]]" not in base_md
        src = await SourceRepository(session).get(sid)
        assert src.status == "documented"


# ---------------------------------------------------------------------------
# (d) 다른 corp 같은 stem → disambiguate(별개, 기존 corp 불변)
# ---------------------------------------------------------------------------


async def test_different_corp_feature_disambiguates(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    sid, gate_id, rev_id = await _fanout_reviewable(session_factory, root)
    # 승인 직전: 다른 회사(acme)에 shared-calendar 기능정의서가 생김.
    ps.create_scaffold(root, "acme")
    await _index(
        session_factory, root,
        "projects/acme/spec/shared-calendar.md",
        _spec_md("shared-calendar", up="acme"),
    )

    async with session_factory() as session:
        await GateService(session).approve(gate_id)
        await session.commit()

    async with session_factory() as session:
        docs = DocumentRepository(session)
        # acme 원본은 불변(회사 넘는 매칭·supplement 안 함).
        acme = await docs.get_by_path("projects/acme/spec/shared-calendar.md")
        assert acme is not None and acme.version == 1
        # the-sc는 별개 문서로 disambiguate 생성.
        feat = await docs.get_by_stem("the-sc-shared-calendar")
        assert feat is not None
        assert feat.path == "projects/the-sc/spec/the-sc-shared-calendar.md"


# ---------------------------------------------------------------------------
# (f) 회귀: own(같은 소스) baseline은 disambiguate 안 함 / 충돌 없으면 stem 불변
# ---------------------------------------------------------------------------


async def test_reresolve_own_source_and_no_conflict(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    ps.create_scaffold(root, "the-sc")
    rel = "projects/the-sc/baseline/the-sc-summary.md"
    async with session_factory() as session:
        src = await SourceRepository(session).create(
            source_url=None, normalized_url=None, source_channel="upload",
            submitted_by=None, submitted_at=utcnow(), raw_text="요구",
            metadata={"intake_note": "the-sc"},
        )
        await session.commit()
    await _index(session_factory, root, rel, _baseline_md("the-sc-summary"))
    async with session_factory() as session:
        await DocumentRepository(session).set_main_lifecycle(
            path=rel, version=1, producing_revision_id=None, source_id=src.id
        )
        await session.commit()

    # 같은 소스 재-baseline(own) → 이름 안 바꿈(자기 자신).
    async with session_factory() as session:
        ex = ApplyExecutor(session, root)
        draft = {"target_path": rel, "filename_candidate": "the-sc-summary.md",
                 "markdown_full": _baseline_md("the-sc-summary")}
        await ex._reresolve_conflicts(draft, [], source_id=src.id)
        assert draft["target_path"] == rel

    # 다른 소스가 같은 stem → disambiguate.
    async with session_factory() as session:
        ex = ApplyExecutor(session, root)
        draft = {"target_path": rel, "filename_candidate": "the-sc-summary.md",
                 "markdown_full": _baseline_md("the-sc-summary")}
        await ex._reresolve_conflicts(draft, [], source_id=uuid.uuid4())
        assert draft["target_path"] == "projects/the-sc/baseline/the-sc-summary-2.md"

    # 충돌 없는 stem(신규) → 그대로.
    async with session_factory() as session:
        ex = ApplyExecutor(session, root)
        draft = {"target_path": "projects/the-sc/baseline/fresh-summary.md",
                 "filename_candidate": "fresh-summary.md", "markdown_full": "x"}
        await ex._reresolve_conflicts(draft, [], source_id=uuid.uuid4())
        assert draft["target_path"] == "projects/the-sc/baseline/fresh-summary.md"

    # 비프로젝트(corp 미바인딩) → no-op.
    async with session_factory() as session:
        ex = ApplyExecutor(session, root)
        draft = {"target_path": "resources/some-note.md",
                 "filename_candidate": "some-note.md", "markdown_full": "x"}
        await ex._reresolve_conflicts(draft, [], source_id=uuid.uuid4())
        assert draft["target_path"] == "resources/some-note.md"
