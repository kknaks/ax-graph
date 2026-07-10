"""요약 확정 시 요약 보관 md 생성 테스트 (PLAN-009-T-014).

커버 (fixture markdown_root = 임시 디렉토리, settings monkeypatch):
- [분류] 진입(요약 확정) → active summary 버전을 `summaries/{slug}.md`로 확정 생성
  (frontmatter type/title/source_url/tags/summarized_at + body_markdown 본문)
- 그래프 제외: 전체 스캔(rebuild_all) 후에도 요약 md stem이 index/graph/index_snapshot에 없음
- 재확정(재피드백 후 다시 [분류]) → 같은 stem md overwrite (현재 active 버전 하나)
- root 미provision(markdown_root fixture 없이)이면 보관 md write 생략(오염 없음)
"""
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.config import settings
from axkg.models.base import utcnow
from axkg.repositories.documents import DocumentRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.documents import DocumentService
from axkg.services.gates import GateService
from axkg.services.graph import GraphService
from axkg.services.summary_archive import slugify
from axkg.storage.markdown_root import MarkdownRoot

SUMMARY_V1 = {
    "title": "Graph RAG 실전 설계",
    "summary": "짧은 카드 요약.",
    "keywords": ["graph-rag", "retriever"],
    "source_type": "article",
    "body_markdown": "## 개요\n\n장문 정리본 v1 본문.",
}


@pytest.fixture
def markdown_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "axkg_markdown_root", str(tmp_path))
    return tmp_path


async def _summarized_source(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    payload: dict = SUMMARY_V1,
    url: str = "https://example.com/s",
):
    """요약 완료(summarized) source 하나 — active summary revision을 갖는다(T-012)."""
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
        await repo.set_summary(src.id, payload)
        await session.commit()
        return src.id


async def test_classification_entry_writes_summary_archive(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    source_id = await _summarized_source(session_factory)
    async with session_factory() as session:
        await GateService(session).create_classification_gate(source_id)
        await session.commit()

    stem = slugify(SUMMARY_V1["title"])
    md = markdown_root / "summaries" / f"{stem}.md"
    assert md.is_file()
    text = md.read_text("utf-8")
    # frontmatter + 본문
    assert "type: summary" in text
    assert SUMMARY_V1["title"] in text
    assert "https://example.com/s" in text
    assert "graph-rag" in text  # keywords → tags
    assert "summarized_at:" in text
    assert "장문 정리본 v1 본문." in text


async def test_summary_archive_excluded_from_graph(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    source_id = await _summarized_source(session_factory)
    async with session_factory() as session:
        await GateService(session).create_classification_gate(source_id)
        await session.commit()

    stem = slugify(SUMMARY_V1["title"])
    # 전체 스캔 재빌드 — summaries/는 iter_markdown에서 제외되므로 인덱싱되지 않는다.
    async with session_factory() as session:
        await GraphService(session, root=MarkdownRoot(str(markdown_root))).rebuild_all()
        await session.commit()

    async with session_factory() as session:
        # 인덱스/그래프/스냅샷 어디에도 요약 md stem이 없다.
        assert await DocumentRepository(session).get_by_stem(stem) is None
        view = await GraphService(
            session, root=MarkdownRoot(str(markdown_root))
        ).graph_documents()
        assert stem not in {n.stem for n in view.nodes}
        snapshot = await DocumentService(session).index_snapshot()
        assert stem not in {e.stem for e in snapshot}


async def test_reconfirm_overwrites_summary_archive(
    session_factory: async_sessionmaker[AsyncSession], markdown_root: Path
) -> None:
    source_id = await _summarized_source(session_factory)
    async with session_factory() as session:
        await GateService(session).create_classification_gate(source_id)
        await session.commit()

    # 재피드백 → v2(같은 title, 다른 body): active 버전이 v2로 바뀐다(T-012).
    v2 = {**SUMMARY_V1, "body_markdown": "## 개요\n\n개정된 장문 v2 본문."}
    async with session_factory() as session:
        await SourceRepository(session).set_summary(source_id, v2)
        await session.commit()
    # 다시 [분류] → 같은 stem md를 overwrite(현재 active 하나만 남는다).
    async with session_factory() as session:
        await GateService(session).create_classification_gate(source_id)
        await session.commit()

    stem = slugify(SUMMARY_V1["title"])
    text = (markdown_root / "summaries" / f"{stem}.md").read_text("utf-8")
    assert "개정된 장문 v2 본문." in text
    assert "장문 정리본 v1 본문." not in text


async def test_no_archive_written_when_root_absent(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # markdown root가 provision되지 않은 경로면 보관 md를 건너뛴다(DB active revision이 SoT).
    missing = tmp_path / "not-provisioned"
    monkeypatch.setattr(settings, "axkg_markdown_root", str(missing))
    source_id = await _summarized_source(session_factory)
    async with session_factory() as session:
        # 예외 없이 정상 진행(분류 게이트는 생성됨).
        result = await GateService(session).create_classification_gate(source_id)
        await session.commit()
        assert result.gate.status == "generating"
    assert not missing.exists()
