"""graph API 요청/응답 (AXKG-SPEC-005 Interface Contract).

FE Phase 4(그래프 뷰)가 소비하는 계약. 그래프 엣지 방향 규약:
- assoc(source_syntax=wikilink): 방향 없음(from→to는 저장 방향일 뿐).
- lineage(source_syntax=up): to_document가 upstream, from_document가 current
  (의미 방향 upstream→current). FE는 이 규약으로 상류/하류를 렌더한다.
`type=source`(raw record)는 그래프 노드 기본 노출에서 제외된다.
"""
import uuid

from pydantic import BaseModel, Field

from axkg.services.documents import IndexSnapshotEntry
from axkg.services.graph import (
    GraphEdge,
    GraphNode,
    GraphView,
    RebuildStats,
    RetrievalResult,
    RetrievedDocument,
)


class GraphNodeResponse(BaseModel):
    document_id: uuid.UUID
    stem: str
    title: str
    document_type: str

    @classmethod
    def from_node(cls, node: GraphNode) -> "GraphNodeResponse":
        return cls(
            document_id=node.document_id,
            stem=node.stem,
            title=node.title,
            document_type=node.document_type,
        )


class GraphEdgeResponse(BaseModel):
    from_document_id: uuid.UUID
    to_document_id: uuid.UUID
    edge_type: str
    source_syntax: str
    label: str | None = None
    is_broken: bool = False

    @classmethod
    def from_edge(cls, edge: GraphEdge) -> "GraphEdgeResponse":
        return cls(
            from_document_id=edge.from_document_id,
            to_document_id=edge.to_document_id,
            edge_type=edge.edge_type,
            source_syntax=edge.source_syntax,
            label=edge.label,
            is_broken=edge.is_broken,
        )


class GraphDocumentsResponse(BaseModel):
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]

    @classmethod
    def from_view(cls, view: GraphView) -> "GraphDocumentsResponse":
        return cls(
            nodes=[GraphNodeResponse.from_node(n) for n in view.nodes],
            edges=[GraphEdgeResponse.from_edge(e) for e in view.edges],
        )


class GraphSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    selected_stem: str | None = None
    top_n: int | None = Field(default=None, ge=1, le=50)


class RetrievedDocumentResponse(BaseModel):
    document_id: uuid.UUID
    stem: str
    title: str
    document_type: str
    score: float
    distance: int | None = None
    snippet: str

    @classmethod
    def from_retrieved(cls, doc: RetrievedDocument) -> "RetrievedDocumentResponse":
        return cls(
            document_id=doc.document_id,
            stem=doc.stem,
            title=doc.title,
            document_type=doc.document_type,
            score=doc.score,
            distance=doc.distance,
            snippet=doc.snippet,
        )


class IndexSnapshotEntryResponse(BaseModel):
    """유효 stem/alias/title 스냅샷 — 연결 후보 컨텍스트(WP3 Phase 2 소비)."""

    stem: str
    title: str
    document_type: str
    aliases: list[str] = Field(default_factory=list)

    @classmethod
    def from_entry(cls, entry: IndexSnapshotEntry) -> "IndexSnapshotEntryResponse":
        return cls(
            stem=entry.stem,
            title=entry.title,
            document_type=entry.document_type,
            aliases=list(entry.aliases),
        )


class GraphSearchResponse(BaseModel):
    query: str
    results: list[RetrievedDocumentResponse]
    index_snapshot: list[IndexSnapshotEntryResponse]

    @classmethod
    def from_result(cls, result: RetrievalResult) -> "GraphSearchResponse":
        return cls(
            query=result.query,
            results=[
                RetrievedDocumentResponse.from_retrieved(d) for d in result.documents
            ],
            index_snapshot=[
                IndexSnapshotEntryResponse.from_entry(e) for e in result.index_snapshot
            ],
        )


class GraphRebuildResponse(BaseModel):
    indexed: int
    removed: int
    edges: int
    broken_edges: int

    @classmethod
    def from_stats(cls, stats: RebuildStats) -> "GraphRebuildResponse":
        return cls(
            indexed=stats.indexed,
            removed=stats.removed,
            edges=stats.edges,
            broken_edges=stats.broken_edges,
        )
