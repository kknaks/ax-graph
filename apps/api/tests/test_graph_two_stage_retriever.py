"""AXKG-WORK-008 — Graph RAG 2단 retriever 테스트 (PLAN-013-T-006 C-3/C-4/C-5).

1단(qmd 하이브리드)은 FakeQmd로 mock하고, 2단 그래프 확장(edge 가중치·hop 감쇠·다중
시드 합산·selected 우선)과 qmd 장애 graceful fallback을 검증한다.

corpus(그래프): inbox-note —(assoc)— retriever-note —(lineage)— graph-rag  (chain)
  raw-source(type=source)는 retriever 기본 제외.
"""
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.services.graph import GraphService
from axkg.services.qmd import QmdCandidate, QmdUnavailable
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


class FakeQmd:
    """주어진 순서의 후보 path를 그대로 돌려주는 1단 mock."""

    def __init__(self, paths: list[str]) -> None:
        self._paths = paths
        self.calls = 0

    async def search(self, query, *, top_k, rerank=None):
        self.calls += 1
        return [
            QmdCandidate(path=p, score=1.0 - i * 0.1, docid=f"#{i}", title=p)
            for i, p in enumerate(self._paths[:top_k])
        ]


class BrokenQmd:
    """항상 장애를 내는 1단 mock (graceful fallback 트리거)."""

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query, *, top_k, rerank=None):
        self.calls += 1
        raise QmdUnavailable("boom")


GRAPH_RAG = "permanent/concepts/graph-rag.md"
RETRIEVER_P = "references/retriever-note.md"
INBOX_P = "references/inbox-note.md"


async def _seed(session_factory, tmp_path):
    root = _write_fixture(tmp_path)
    async with session_factory() as session:
        await GraphService(session, root=root).rebuild_all()
        await session.commit()
    return root


# ---------------------------------------------------------------------------
# C-3/C-4 — 2단 확장
# ---------------------------------------------------------------------------


async def test_two_stage_expands_from_qmd_seed(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = await _seed(session_factory, tmp_path)
    qmd = FakeQmd([GRAPH_RAG])
    async with session_factory() as session:
        result = await GraphService(session, root=root, qmd=qmd).retrieve("무엇이든")
    stems = {d.stem for d in result.documents}
    # 시드(graph-rag)에서 wikilink 그래프 확장 → 이웃 문서가 결과에 편입.
    assert "graph-rag" in stems
    assert "retriever-note" in stems  # hop1 (lineage)
    assert "inbox-note" in stems  # hop2 (assoc)
    assert result.retriever_mode == "qmd_two_stage"
    assert result.fallback_used is False
    assert qmd.calls == 1
    # 근거 경로(used_paths) 산출됨.
    assert any(p.to_stem == "inbox-note" and p.hop == 2 for p in result.used_paths)


async def test_hop_decay_orders_by_distance_from_seed(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = await _seed(session_factory, tmp_path)
    qmd = FakeQmd([GRAPH_RAG])
    async with session_factory() as session:
        result = await GraphService(session, root=root, qmd=qmd).retrieve("q")
    score = {d.stem: d.score for d in result.documents}
    # hop 감쇠: 시드(hop0) > hop1 > hop2.
    assert score["graph-rag"] > score["retriever-note"] > score["inbox-note"]


async def test_edge_type_weight_lineage_over_assoc(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = await _seed(session_factory, tmp_path)
    # 시드=retriever-note: graph-rag는 hop1 lineage(1.5), inbox-note는 hop1 assoc(1.0).
    qmd = FakeQmd([RETRIEVER_P])
    async with session_factory() as session:
        result = await GraphService(session, root=root, qmd=qmd).retrieve("q")
    score = {d.stem: d.score for d in result.documents}
    # 같은 hop1이라도 lineage 근거가 assoc보다 강하다.
    assert score["graph-rag"] > score["inbox-note"]


async def test_multi_seed_score_aggregation(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = await _seed(session_factory, tmp_path)
    # retriever-note는 두 시드(graph-rag, inbox-note) 양쪽에서 hop1로 도달 → 점수 합산.
    async with session_factory() as session:
        single = await GraphService(
            session, root=root, qmd=FakeQmd([GRAPH_RAG])
        ).retrieve("q")
    async with session_factory() as session:
        multi = await GraphService(
            session, root=root, qmd=FakeQmd([GRAPH_RAG, INBOX_P])
        ).retrieve("q")
    s_single = {d.stem: d.score for d in single.documents}["retriever-note"]
    s_multi = {d.stem: d.score for d in multi.documents}["retriever-note"]
    # 다중 시드에서 retriever-note가 양쪽 기여를 합산해 더 높다.
    assert s_multi > s_single


async def test_selected_node_neighborhood_priority(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = await _seed(session_factory, tmp_path)
    # qmd 시드는 inbox-note지만 selected=graph-rag → graph-rag neighborhood 우선(boost).
    qmd = FakeQmd([INBOX_P])
    async with session_factory() as session:
        result = await GraphService(session, root=root, qmd=qmd).retrieve(
            "q", selected_stem="graph-rag"
        )
    by_stem = {d.stem: d for d in result.documents}
    # graph-rag의 이웃 retriever-note(거리1)가 결과에 있고 neighbor boost를 받는다.
    assert "retriever-note" in by_stem
    assert by_stem["retriever-note"].distance == 1


# ---------------------------------------------------------------------------
# C-5 — graceful fallback
# ---------------------------------------------------------------------------


async def test_fallback_when_qmd_unavailable(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = await _seed(session_factory, tmp_path)
    broken = BrokenQmd()
    async with session_factory() as session:
        result = await GraphService(session, root=root, qmd=broken).retrieve(
            "retriever keyword"
        )
    # qmd 장애 → keyword+edge 폴백. 결과는 성립하고 폴백 사실이 관찰된다.
    assert broken.calls == 1
    assert result.fallback_used is True
    assert result.retriever_mode == "keyword_edge"
    stems = [d.stem for d in result.documents]
    assert stems and stems[0] == "retriever-note"


async def test_default_no_qmd_is_keyword_fallback(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = await _seed(session_factory, tmp_path)
    # qmd 미주입(기본 NullQmdClient) → 기존 keyword+edge 동작 그대로(폴백).
    async with session_factory() as session:
        result = await GraphService(session, root=root).retrieve("retriever keyword")
    assert result.fallback_used is True
    assert result.retriever_mode == "keyword_edge"
    assert [d.stem for d in result.documents][0] == "retriever-note"


async def test_unmappable_seeds_fall_back(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = await _seed(session_factory, tmp_path)
    # qmd가 인덱스에 없는 path만 돌려주면(빈 시드) keyword+edge 폴백으로 강등.
    qmd = FakeQmd(["nonexistent/ghost.md"])
    async with session_factory() as session:
        result = await GraphService(session, root=root, qmd=qmd).retrieve(
            "retriever keyword"
        )
    assert result.fallback_used is True
    assert result.retriever_mode == "keyword_edge"
