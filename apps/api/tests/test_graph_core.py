"""AXKG-SPEC-005 문서·그래프 코어 테스트 (WP2 Phase 1~3, 서비스 계층).

커버:
- index upsert + stem/alias resolve + duplicate stem 거부
- 엣지 생성: 본문 [[ ]]→assoc / 본문+up→lineage / links 비엣지 / resolve 실패 is_broken
- rebuild 트리거: 전체/증분, 외부 편집 시나리오(파일 수정→rebuild→엣지 갱신), inbound heal
- rebuild 읽기 전용(Markdown 미변경)
- retriever: keyword+edge distance 순위, neighborhood 우선, index 스냅샷
"""
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.repositories.documents import DocumentRepository
from axkg.services.documents import DocumentService, DuplicateStemError
from axkg.services.graph import GraphService
from axkg.storage.markdown_parser import parse_markdown
from axkg.storage.markdown_root import MarkdownRoot

CONCEPT = """---
type: concept
id: CONCEPT-GRAPH-RAG
title: Graph RAG
aliases: [grag]
tags: [ai, retrieval]
---
Graph RAG combines retrieval with a knowledge graph.
"""

RETRIEVER = """---
type: reference
id: REF-RETRIEVER
title: Retriever design note
up: [graph-rag]
source: https://example.com/retriever
links:
  related: ["[[graph-rag]]"]
---
The retriever uses keyword score and edge distance. See [[graph-rag]].
"""

INBOX = """---
type: reference
id: REF-INBOX
title: Source inbox note
---
Relates to [[retriever-note|the retriever]]. Also [[ghost-doc]] which is missing.
"""

SOURCE = """---
type: source
id: SRC-1
title: Raw source record
---
Raw captured text about retrieval.
"""


def _write_fixture(tmp_path: Path) -> MarkdownRoot:
    (tmp_path / "permanent" / "concepts").mkdir(parents=True)
    (tmp_path / "references").mkdir()
    (tmp_path / "sources").mkdir()
    (tmp_path / "permanent" / "concepts" / "graph-rag.md").write_text(CONCEPT, "utf-8")
    (tmp_path / "references" / "retriever-note.md").write_text(RETRIEVER, "utf-8")
    (tmp_path / "references" / "inbox-note.md").write_text(INBOX, "utf-8")
    (tmp_path / "sources" / "raw-source.md").write_text(SOURCE, "utf-8")
    return MarkdownRoot(tmp_path)


# ---------------------------------------------------------------------------
# Phase 1 — index + resolve + duplicate
# ---------------------------------------------------------------------------


async def test_index_and_resolve_by_stem_and_alias(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = _write_fixture(tmp_path)
    async with session_factory() as session:
        await GraphService(session, root=root).rebuild_all()
        await session.commit()
    async with session_factory() as session:
        resolver = await DocumentService(session).build_resolver()
        # 파일명 stem resolve
        assert resolver.resolve("graph-rag").title == "Graph RAG"
        # alias resolve
        assert resolver.resolve("grag").stem == "graph-rag"
        # frontmatter id resolve
        assert resolver.resolve("CONCEPT-GRAPH-RAG").stem == "graph-rag"
        assert resolver.resolve("nope") is None


async def test_duplicate_stem_rejected(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    async with session_factory() as session:
        service = DocumentService(session)
        parsed = parse_markdown(CONCEPT)
        await service.index_document(path="a/graph-rag.md", parsed=parsed, content_hash="h1")
        with pytest.raises(DuplicateStemError):
            await service.index_document(
                path="b/graph-rag.md", parsed=parsed, content_hash="h2"
            )


# ---------------------------------------------------------------------------
# Phase 2 — edges (assoc/lineage/broken/up), links 비엣지
# ---------------------------------------------------------------------------


async def test_rebuild_edges_assoc_lineage_broken(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = _write_fixture(tmp_path)
    async with session_factory() as session:
        stats = await GraphService(session, root=root).rebuild_all()
        await session.commit()
    assert stats.indexed == 4
    async with session_factory() as session:
        repo = DocumentRepository(session)
        retriever = await repo.get_by_stem("retriever-note")
        inbox = await repo.get_by_stem("inbox-note")

        # 본문 [[graph-rag]] + up:[graph-rag] → lineage(source_syntax=up), assoc 아님
        r_edges = await repo.list_edges_from(retriever.id)
        assert len(r_edges) == 1
        assert r_edges[0].edge_type == "lineage"
        assert r_edges[0].source_syntax == "up"
        assert r_edges[0].to_target == "graph-rag"
        assert r_edges[0].is_broken is False

        # inbox: assoc → retriever-note(label 보존), broken → ghost-doc
        i_edges = {e.to_target: e for e in await repo.list_edges_from(inbox.id)}
        assert i_edges["retriever-note"].edge_type == "assoc"
        assert i_edges["retriever-note"].source_syntax == "wikilink"
        assert i_edges["retriever-note"].label == "the retriever"
        assert i_edges["retriever-note"].is_broken is False
        assert i_edges["ghost-doc"].is_broken is True
        assert i_edges["ghost-doc"].to_document_id is None
        assert stats.broken_edges == 1


async def test_frontmatter_links_not_edge(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = _write_fixture(tmp_path)
    async with session_factory() as session:
        await GraphService(session, root=root).rebuild_all()
        await session.commit()
    async with session_factory() as session:
        repo = DocumentRepository(session)
        retriever = await repo.get_by_stem("retriever-note")
        edges = await repo.list_edges_from(retriever.id)
        # links.related의 [[graph-rag]]는 별도 엣지를 만들지 않는다 — lineage 1개뿐.
        assert len(edges) == 1


async def test_up_without_body_link_invalid(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = MarkdownRoot(tmp_path)
    (tmp_path / "bad.md").write_text(
        "---\ntype: reference\nid: B\ntitle: Bad\nup: [orphan]\n---\nNo body link.\n",
        "utf-8",
    )
    async with session_factory() as session:
        stats = await GraphService(session, root=root).rebuild_all()
        await session.commit()
        repo = DocumentRepository(session)
        bad = await repo.get_by_stem("bad")
        assert await repo.list_edges_from(bad.id) == []
    assert any(i.error_code == "UP_WITHOUT_BODY_LINK" for i in stats.skipped)


# ---------------------------------------------------------------------------
# Phase 2 — rebuild 트리거 / 외부 편집 시나리오 / 읽기 전용
# ---------------------------------------------------------------------------


async def test_external_edit_incremental_rebuild(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = _write_fixture(tmp_path)
    async with session_factory() as session:
        await GraphService(session, root=root).rebuild_all()
        await session.commit()

    # 외부(Obsidian/git) 편집: 누락됐던 ghost-doc 파일을 새로 추가.
    (tmp_path / "references" / "ghost-doc.md").write_text(
        "---\ntype: reference\nid: GHOST\ntitle: Ghost doc\n---\nNow exists.\n", "utf-8"
    )
    async with session_factory() as session:
        await GraphService(session, root=root).rebuild_document(
            "references/ghost-doc.md"
        )
        await session.commit()
    async with session_factory() as session:
        repo = DocumentRepository(session)
        inbox = await repo.get_by_stem("inbox-note")
        ghost = await repo.get_by_stem("ghost-doc")
        edges = {e.to_target: e for e in await repo.list_edges_from(inbox.id)}
        # inbound heal: 깨졌던 ghost-doc 엣지가 이제 resolve된다.
        assert edges["ghost-doc"].is_broken is False
        assert edges["ghost-doc"].to_document_id == ghost.id


async def test_incremental_rebuild_updates_edges_on_body_change(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = _write_fixture(tmp_path)
    async with session_factory() as session:
        await GraphService(session, root=root).rebuild_all()
        await session.commit()
    # 본문에서 [[graph-rag]] 제거 → lineage 엣지가 사라져야 한다.
    (tmp_path / "references" / "retriever-note.md").write_text(
        "---\ntype: reference\nid: REF-RETRIEVER\ntitle: Retriever design note\n---\nNo links now.\n",
        "utf-8",
    )
    async with session_factory() as session:
        await GraphService(session, root=root).rebuild_document(
            "references/retriever-note.md"
        )
        await session.commit()
    async with session_factory() as session:
        repo = DocumentRepository(session)
        retriever = await repo.get_by_stem("retriever-note")
        assert await repo.list_edges_from(retriever.id) == []


async def test_rebuild_is_read_only(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = _write_fixture(tmp_path)
    before = {p: p.read_text("utf-8") for p in tmp_path.rglob("*.md")}
    async with session_factory() as session:
        await GraphService(session, root=root).rebuild_all()
        await session.commit()
    after = {p: p.read_text("utf-8") for p in tmp_path.rglob("*.md")}
    assert before == after


# ---------------------------------------------------------------------------
# Phase 3 — retriever + neighborhood + snapshot
# ---------------------------------------------------------------------------


async def test_retriever_keyword_ranking(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = _write_fixture(tmp_path)
    async with session_factory() as session:
        await GraphService(session, root=root).rebuild_all()
        await session.commit()
    async with session_factory() as session:
        result = await GraphService(session, root=root).retrieve("retriever keyword")
        stems = [d.stem for d in result.documents]
        assert stems, "expected at least one hit"
        # 제목/본문에 keyword가 있는 retriever-note가 최상위.
        assert stems[0] == "retriever-note"
        # source(raw record)는 기본 제외.
        assert "raw-source" not in stems


async def test_retriever_neighborhood_priority(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = _write_fixture(tmp_path)
    async with session_factory() as session:
        await GraphService(session, root=root).rebuild_all()
        await session.commit()
    async with session_factory() as session:
        result = await GraphService(session, root=root).retrieve(
            "graph", selected_stem="graph-rag"
        )
        by_stem = {d.stem: d for d in result.documents}
        # graph-rag의 이웃(retriever-note: 거리 1)이 결과에 들어오고 거리 boost를 받는다.
        assert "retriever-note" in by_stem
        assert by_stem["retriever-note"].distance == 1


async def test_index_snapshot_excludes_source(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = _write_fixture(tmp_path)
    async with session_factory() as session:
        await GraphService(session, root=root).rebuild_all()
        await session.commit()
    async with session_factory() as session:
        snapshot = await DocumentService(session).index_snapshot()
        stems = {e.stem for e in snapshot}
        assert stems == {"graph-rag", "retriever-note", "inbox-note"}
        assert "raw-source" not in stems
