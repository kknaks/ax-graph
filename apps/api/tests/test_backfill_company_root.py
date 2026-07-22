"""회사 루트 backfill 스크립트 테스트 (WORK-013 backfill). 멱등·삭제 없음·dry-run.

WORK-013 배포 전 생성된 회사 프로젝트(회사 루트·baseline up: 없음)를 삭제 없이 in-place로
보정: 회사 루트 company 노드 생성·인덱싱 + baseline up:[{corp}] + baseline→{corp} lineage 엣지.
"""
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings
from axkg.repositories.documents import DocumentRepository
from axkg.scripts.backfill_company_root import backfill_company_root
from axkg.services import project_scaffold as ps
from axkg.storage.markdown_parser import extract_wikilinks, parse_markdown
from axkg.storage.markdown_root import MarkdownRoot

CORP = "sc"
BASELINE_STEM = "sc-summary"


@pytest.fixture
def markdown_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "axkg_markdown_root", str(tmp_path))
    return tmp_path


def _old_project(root: MarkdownRoot, corp: str = CORP) -> None:
    """WORK-013 이전 상태의 회사 프로젝트 — 회사 루트도, baseline up:도 없다."""
    for sub in ("origin", "baseline", "spec"):
        root.mkdirs(ps.corp_subdir(corp, sub))
    # baseline: up: [] (회사 루트 미배선)
    root.write_new(
        ps.project_baseline_path(corp, f"{BASELINE_STEM}.md"),
        "---\ntype: baseline\ntitle: SC 원본요약\nup: []\n---\n\n"
        "# SC 원본요약\n\n## 기능 목록\n- [[sc-cal]] — 캘린더\n\n## 연결\n",
    )
    # spec: 이미 up: [원본요약] (2단 체인 대상, backfill이 건드리지 않음)
    root.write_new(
        ps.project_spec_path(corp, "sc-cal.md"),
        "---\ntype: feature_spec\ntitle: 캘린더\nup: [sc-summary]\n---\n\n"
        "# 캘린더\n\n## 8. 연결\n- [[sc-summary]] — 원본요약\n",
    )


# ---------------------------------------------------------------------------
# fresh backfill — 루트 생성·인덱싱 + baseline up: + lineage 엣지
# ---------------------------------------------------------------------------


async def test_backfill_creates_root_and_up_chain(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    _old_project(root)
    async with session_factory() as s:
        report = await backfill_company_root(s, root, CORP)
        await s.commit()

    assert report.root_created is True
    assert report.baselines_updated == [BASELINE_STEM]
    assert report.specs_total == 1  # spec은 확인만(변경 없음)

    # 회사 루트 파일 생성 + company 타입
    root_file = markdown_root / "projects/sc/sc.md"
    assert root_file.is_file()
    assert "type: company" in root_file.read_text()

    # baseline 파일에 up:[sc] + 본문 [[sc]] 추가됨
    baseline_text = (markdown_root / "projects/sc/baseline/sc-summary.md").read_text()
    parsed = parse_markdown(baseline_text)
    assert "sc" in parsed.up
    assert "sc" in {w.target for w in extract_wikilinks(parsed.body)}

    # DB: company 노드 + baseline → sc lineage 엣지 materialize
    async with session_factory() as s:
        docs = DocumentRepository(s)
        company = await docs.get_by_stem("sc")
        assert company is not None and company.document_type == "company"
        baseline = await docs.get_by_stem("sc-summary")
        assert baseline is not None and "sc" in baseline.frontmatter.get("up", [])
        edges = await docs.list_edges_to_document(company.id)
        assert any(e.edge_type == "lineage" for e in edges)  # baseline→sc 수렴


# ---------------------------------------------------------------------------
# 멱등 — 재실행해도 중복 생성/중복 up 없음
# ---------------------------------------------------------------------------


async def test_backfill_idempotent(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    _old_project(root)
    async with session_factory() as s:
        await backfill_company_root(s, root, CORP)
        await s.commit()
    first = (markdown_root / "projects/sc/baseline/sc-summary.md").read_text()

    async with session_factory() as s:
        report2 = await backfill_company_root(s, root, CORP)
        await s.commit()
    # 두 번째 실행: 루트 이미 있음, baseline은 skip(추가 없음)
    assert report2.root_created is False
    assert report2.root_already_existed is True
    assert report2.baselines_updated == []
    assert report2.baselines_skipped == [BASELINE_STEM]
    # baseline 파일 내용 불변(중복 up/링크 churn 없음)
    assert (markdown_root / "projects/sc/baseline/sc-summary.md").read_text() == first
    # up: sc 하나만(중복 없음)
    assert parse_markdown(first).up.count("sc") == 1
    assert first.count("[[sc]]") == 1


# ---------------------------------------------------------------------------
# dry-run — write/인덱싱 없이 예상만
# ---------------------------------------------------------------------------


async def test_backfill_dry_run_no_writes(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    _old_project(root)
    async with session_factory() as s:
        report = await backfill_company_root(s, root, CORP, dry_run=True)
        await s.commit()

    # 예상 보고는 채우되…
    assert report.dry_run is True
    assert report.root_created is True  # 생성 예정
    assert report.baselines_updated == [BASELINE_STEM]  # 추가 예정
    # …실제 write/index는 없다
    assert not (markdown_root / "projects/sc/sc.md").exists()
    unchanged = (markdown_root / "projects/sc/baseline/sc-summary.md").read_text()
    assert "up: []" in unchanged  # baseline 원본 그대로
    async with session_factory() as s:
        assert await DocumentRepository(s).get_by_stem("sc") is None  # 인덱싱 안 됨
    # render 출력에 DRY-RUN 표기
    assert "DRY-RUN" in report.render()


# ---------------------------------------------------------------------------
# --root-md — 커스텀 회사 루트 내용 사용(type company 보장)
# ---------------------------------------------------------------------------


async def test_backfill_uses_root_md_content(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    _old_project(root)
    custom = "---\ntype: company\ntitle: 더에스씨\naliases: [SC]\n---\n\n# 더에스씨\n\n보험 AX 전문.\n"
    async with session_factory() as s:
        await backfill_company_root(s, root, CORP, root_md_content=custom)
        await s.commit()
    text = (markdown_root / "projects/sc/sc.md").read_text()
    assert "보험 AX 전문" in text and "type: company" in text
    async with session_factory() as s:
        company = await DocumentRepository(s).get_by_stem("sc")
        assert company.document_type == "company" and company.title == "더에스씨"


async def test_backfill_missing_project(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    root = MarkdownRoot(str(markdown_root))
    async with session_factory() as s:
        report = await backfill_company_root(s, root, "nope")
    assert report.project_found is False
    assert "프로젝트가 없습니다" in report.render()
