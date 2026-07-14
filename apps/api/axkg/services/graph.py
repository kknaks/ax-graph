"""링크 파싱, graph cache rebuild, Graph RAG retriever (AXKG-SPEC-005/011). WP2.

이 서비스가 소유하는 것:
- **엣지 생성**: 본문 `[[ ]]`→assoc / 본문 `[[ ]]`+frontmatter `up`→lineage(upstream→current).
  `up`만 있고 본문 링크 없으면 invalid(UP_WITHOUT_BODY_LINK). `links`는 엣지 아님. resolve
  실패 target은 `to_document_id=null`+`is_broken`.
- **rebuild**: 문서 단위(증분)와 전체. rebuild는 Markdown을 **쓰지 않는다**(읽기 전용,
  cache는 언제든 Markdown에서 재빌드 — DEC-002).
- **link validation + preview**: 생성 경로 거부(BROKEN_WIKILINK/UP_WITHOUT_BODY_LINK/
  DUPLICATE_STEM), `is_broken`은 외부 편집 사후 표시.
- **retriever**: keyword score + edge distance, selected node neighborhood 우선.
  chat(④)과 문서화 게이트(③)가 공유하는 컴포넌트 + documents index 경량 스냅샷.

경계: Markdown **쓰기**(create/patch)는 WP3 Apply Executor, chat 응답 생성은 WP4,
embedding(pgvector)은 post-MVP(DEC-003, keyword+edge distance만). 여기서 손대지 않는다.
"""
from __future__ import annotations

import re
import uuid
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.document import DocumentDTO, DocumentEdgeDTO
from axkg.repositories.documents import DocumentRepository
from axkg.services.documents import (
    DocumentResolver,
    DocumentService,
    DuplicateStemError,
    IndexSnapshotEntry,
    InvalidDocumentError,
    stem_from_path,
)
from axkg.services.qmd import QmdCandidate, QmdClient, QmdUnavailable, NullQmdClient
from axkg.storage.markdown_parser import ParsedDocument, parse_markdown
from axkg.storage.markdown_root import MarkdownRoot, content_hash

# retriever 기본값 (SPEC-011 §7 OQ — 구현 기본값으로 시작, 관찰 후 조정. PLAN-013-T-006 확정값).
DEFAULT_TOP_N = 8
DEFAULT_SNIPPET_LEN = 240
DEFAULT_QMD_TOP_K = 12  # 1단 qmd 하이브리드 시드 개수(2단 확장의 seed 집합)
_NEIGHBOR_BOOST = {1: 4.0, 2: 2.0}  # selected 노드 neighborhood 우선(기존 계약 유지)
_DEFAULT_EXCLUDE = ("source",)
_TOKEN_RE = re.compile(r"[0-9a-z가-힣]+")

# --- 2단 그래프 확장 튜닝 (C-4, OQ 구현 기본값 — 리포트 기재) ---
# edge 타입별 가중치: lineage(up:, 상하위 계보)가 assoc(느슨한 연관)보다 강한 근거.
_EDGE_TYPE_WEIGHT = {"lineage": 1.5, "assoc": 1.0}
# hop 감쇠: 시드에서 멀어질수록 근거 기여 감쇠(hop1=1.0, hop2=0.5, hop3=0.25 …).
_HOP_DECAY = 0.5
# 2단 확장 최대 hop 반경.
_MAX_EXPANSION_HOP = 2
# 시드 자신(hop0)의 기본 근거 점수 — 여기에 qmd 상대순위 가중을 곱한다.
_SEED_BASE_SCORE = 10.0


# ---------------------------------------------------------------------------
# 엣지 생성 (순수)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgeSpec:
    to_target: str
    to_document_id: uuid.UUID | None
    edge_type: str
    source_syntax: str
    label: str | None
    is_broken: bool


@dataclass(frozen=True)
class LinkIssue:
    error_code: str
    target: str


def build_edges(
    parsed: ParsedDocument, resolver: DocumentResolver
) -> tuple[list[EdgeSpec], list[LinkIssue]]:
    """파싱된 문서 + resolver → (엣지 목록, 검증 이슈 목록).

    - 본문 unique target별 1개 엣지: `up`에 있으면 lineage(source_syntax=up), 아니면
      assoc(source_syntax=wikilink). `up`은 본문 링크의 타입 오버레이 → 둘을 동시에 만들지 않음.
    - `up`에만 있고 본문에 없는 stem → UP_WITHOUT_BODY_LINK(엣지 생성 안 함).
    - resolve 실패 → is_broken=True, to_document_id=None (BROKEN_WIKILINK로도 표면화).
    """
    up_set = set(parsed.up)
    edges: list[EdgeSpec] = []
    issues: list[LinkIssue] = []
    seen: set[str] = set()
    body_targets: set[str] = set()
    for link in parsed.wikilinks:
        body_targets.add(link.target)
        if link.target in seen:
            continue
        seen.add(link.target)
        is_up = link.target in up_set
        target_doc = resolver.resolve(link.target)
        is_broken = target_doc is None
        if is_broken:
            issues.append(LinkIssue("BROKEN_WIKILINK", link.target))
        edges.append(
            EdgeSpec(
                to_target=link.target,
                to_document_id=target_doc.id if target_doc else None,
                edge_type="lineage" if is_up else "assoc",
                source_syntax="up" if is_up else "wikilink",
                label=link.label,
                is_broken=is_broken,
            )
        )
    # up이 본문에 없으면 invalid (lineage는 본문 링크가 반드시 있어야 함).
    for stem in parsed.up:
        if stem not in body_targets:
            issues.append(LinkIssue("UP_WITHOUT_BODY_LINK", stem))
    return edges, issues


# ---------------------------------------------------------------------------
# rebuild 결과 / preview / retriever 데이터클래스
# ---------------------------------------------------------------------------


@dataclass
class RebuildStats:
    indexed: int = 0
    removed: int = 0
    edges: int = 0
    broken_edges: int = 0
    skipped: list[LinkIssue] = field(default_factory=list)
    duplicate_stems: list[str] = field(default_factory=list)
    invalid_documents: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LinkPreviewEntry:
    target: str
    label: str | None
    edge_type: str
    source_syntax: str
    resolved: bool
    document_id: uuid.UUID | None = None
    title: str | None = None
    stem: str | None = None


@dataclass(frozen=True)
class LinkPreview:
    links: list[LinkPreviewEntry] = field(default_factory=list)
    backlinks: list[LinkPreviewEntry] = field(default_factory=list)
    errors: list[LinkIssue] = field(default_factory=list)


@dataclass(frozen=True)
class RetrievedDocument:
    document_id: uuid.UUID
    stem: str
    title: str
    document_type: str
    score: float
    distance: int | None
    snippet: str
    path: str = ""


@dataclass(frozen=True)
class RetrievalPath:
    """2단 확장 근거 경로: qmd 시드에서 도달 문서까지의 stem 경로 + 총 hop."""

    seed_stem: str
    to_stem: str
    stems: tuple[str, ...]
    hop: int


@dataclass(frozen=True)
class EvidenceEdge:
    """근거로 traverse한 엣지(무방향 stem 쌍 + 타입)."""

    from_stem: str
    to_stem: str
    edge_type: str


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    documents: list[RetrievedDocument]
    index_snapshot: list[IndexSnapshotEntry]
    # --- 2단 retriever 관찰 필드 (AXKG-WORK-008, 기본값으로 기존 생성부 호환) ---
    # qmd 사이드카 장애로 keyword+edge 1단 폴백을 썼는지(C-5, RETRIEVER_FALLBACK_USED).
    fallback_used: bool = False
    # "qmd_two_stage"(qmd 1단 성공) | "keyword_edge"(폴백).
    retriever_mode: str = "keyword_edge"
    # 답변 근거 경로/엣지 강화 산출(C-4). SPEC-006 used_paths/evidence_edges 원천.
    used_paths: list[RetrievalPath] = field(default_factory=list)
    evidence_edges: list[EvidenceEdge] = field(default_factory=list)


@dataclass(frozen=True)
class GraphNode:
    document_id: uuid.UUID
    stem: str
    title: str
    document_type: str


@dataclass(frozen=True)
class GraphEdge:
    from_document_id: uuid.UUID
    to_document_id: uuid.UUID
    edge_type: str
    source_syntax: str
    label: str | None
    is_broken: bool


@dataclass(frozen=True)
class GraphView:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class GraphService:
    def __init__(
        self,
        session: AsyncSession,
        root: MarkdownRoot | None = None,
        *,
        qmd: QmdClient | None = None,
    ) -> None:
        self._session = session
        self._docs = DocumentRepository(session)
        self._documents = DocumentService(session)
        self._root = root
        # 1단 후보 발굴 클라이언트. 미주입이면 NullQmdClient → 항상 keyword+edge 폴백.
        self._qmd: QmdClient = qmd or NullQmdClient()

    # ------------------------------------------------------------------
    # rebuild (읽기 전용 — Markdown을 쓰지 않는다)
    # ------------------------------------------------------------------

    async def rebuild_all(self) -> RebuildStats:
        """document root 전체를 스캔해 인덱스+엣지를 재빌드한다(전체 재빌드).

        cache는 언제든 Markdown에서 재빌드 가능(DEC-002)해야 하므로, 엣지를 모두 지우고
        전 문서를 다시 인덱싱한 뒤 resolver를 만들어 엣지를 재구성한다.
        """
        if self._root is None:
            raise RuntimeError("markdown root not configured")
        stats = RebuildStats()
        rels = list(self._root.iter_markdown())

        # 1) 인덱스 upsert (파싱 실패/타입 누락/중복 stem은 건너뛰고 기록).
        parsed_by_path: dict[str, ParsedDocument] = {}
        seen_stems: dict[str, str] = {}
        for rel in rels:
            text = self._root.read_text(rel)
            parsed = parse_markdown(text)
            stem = stem_from_path(rel)
            if stem in seen_stems:
                stats.duplicate_stems.append(stem)
                continue
            try:
                await self._documents.index_document(
                    path=rel, parsed=parsed, content_hash=content_hash(text)
                )
            except DuplicateStemError:
                stats.duplicate_stems.append(stem)
                continue
            except InvalidDocumentError:
                stats.invalid_documents.append(rel)
                continue
            seen_stems[stem] = rel
            parsed_by_path[rel] = parsed
            stats.indexed += 1

        # 2) 디스크에서 사라진 문서 제거.
        on_disk = set(rels)
        for doc in await self._docs.list_all():
            if doc.path not in on_disk:
                removed_id = await self._docs.delete_by_path(doc.path)
                if removed_id is not None:
                    stats.removed += 1

        # 3) 엣지 전체 재구성.
        await self._docs.delete_all_edges()
        resolver = await self._documents.build_resolver()
        for rel, parsed in parsed_by_path.items():
            doc = await self._docs.get_by_path(rel)
            if doc is None:
                continue
            edges, issues = build_edges(parsed, resolver)
            stats.skipped.extend(
                i for i in issues if i.error_code == "UP_WITHOUT_BODY_LINK"
            )
            for spec in edges:
                await self._add_edge(doc.id, spec)
                stats.edges += 1
                if spec.is_broken:
                    stats.broken_edges += 1
        return stats

    async def rebuild_document(self, path: str) -> RebuildStats:
        """단일 문서 증분 rebuild — 그 문서의 인덱스+outgoing 엣지만 갱신하고 inbound heal.

        디스크에 파일이 없으면 인덱스에서 제거하고 inbound 엣지를 깨진 것으로 표시한다.
        """
        if self._root is None:
            raise RuntimeError("markdown root not configured")
        stats = RebuildStats()
        if not self._root.exists(path):
            removed_id = await self._docs.delete_by_path(path)
            if removed_id is not None:
                await self._docs.break_edges_to_document(removed_id)
                stats.removed += 1
            return stats

        text = self._root.read_text(path)
        parsed = parse_markdown(text)
        stem = stem_from_path(path)
        try:
            doc = await self._documents.index_document(
                path=path, parsed=parsed, content_hash=content_hash(text)
            )
        except DuplicateStemError:
            stats.duplicate_stems.append(stem)
            return stats
        except InvalidDocumentError:
            stats.invalid_documents.append(path)
            return stats
        stats.indexed += 1

        # 이 문서 stem을 가리키던 기존 엣지가 이제 resolve됨(inbound heal).
        await self._docs.resolve_edges_to_target(to_target=stem, to_document_id=doc.id)

        await self._docs.delete_edges_from(doc.id)
        resolver = await self._documents.build_resolver()
        edges, issues = build_edges(parsed, resolver)
        stats.skipped.extend(
            i for i in issues if i.error_code == "UP_WITHOUT_BODY_LINK"
        )
        for spec in edges:
            await self._add_edge(doc.id, spec)
            stats.edges += 1
            if spec.is_broken:
                stats.broken_edges += 1
        return stats

    async def _add_edge(self, from_document_id: uuid.UUID, spec: EdgeSpec) -> None:
        await self._docs.add_edge(
            from_document_id=from_document_id,
            to_document_id=spec.to_document_id,
            to_target=spec.to_target,
            edge_type=spec.edge_type,
            source_syntax=spec.source_syntax,
            label=spec.label,
            is_broken=spec.is_broken,
        )

    # ------------------------------------------------------------------
    # link validation + preview (생성 경로 거부)
    # ------------------------------------------------------------------

    async def preview_links(
        self,
        *,
        markdown: str,
        stem: str | None = None,
        document_id: uuid.UUID | None = None,
    ) -> LinkPreview:
        """draft markdown에서 연결 preview를 만든다(SPEC-005 U-1, POST link-preview).

        생성 경로 정책: resolve 불가 wikilink는 BROKEN_WIKILINK, 본문 없는 up은
        UP_WITHOUT_BODY_LINK, stem 충돌은 DUPLICATE_STEM으로 거부(errors에 실어 보냄).
        """
        parsed = parse_markdown(markdown)
        resolver = await self._documents.build_resolver()
        edges, issues = build_edges(parsed, resolver)

        errors = list(issues)
        effective_stem = stem
        if effective_stem is None and document_id is not None:
            doc = await self._docs.get(document_id)
            effective_stem = doc.stem if doc else None
        if effective_stem is not None:
            existing = await self._docs.get_by_stem(effective_stem)
            if existing is not None and existing.id != document_id:
                errors.append(LinkIssue("DUPLICATE_STEM", effective_stem))

        docs_by_id = {d.id: d for d in await self._docs.list_all()}
        links = [self._preview_entry(spec, docs_by_id) for spec in edges]

        backlinks: list[LinkPreviewEntry] = []
        if effective_stem is not None:
            target_doc = await self._docs.get_by_stem(effective_stem)
            if target_doc is not None:
                for edge in await self._docs.list_edges_to_document(target_doc.id):
                    backlinks.append(self._preview_entry_in(edge, docs_by_id))
        return LinkPreview(links=links, backlinks=backlinks, errors=errors)

    @staticmethod
    def _preview_entry(
        spec: EdgeSpec, docs_by_id: dict[uuid.UUID, DocumentDTO]
    ) -> LinkPreviewEntry:
        target_doc = docs_by_id.get(spec.to_document_id) if spec.to_document_id else None
        return LinkPreviewEntry(
            target=spec.to_target,
            label=spec.label,
            edge_type=spec.edge_type,
            source_syntax=spec.source_syntax,
            resolved=not spec.is_broken,
            document_id=target_doc.id if target_doc else None,
            title=target_doc.title if target_doc else None,
            stem=target_doc.stem if target_doc else None,
        )

    @staticmethod
    def _preview_entry_in(
        edge: DocumentEdgeDTO, docs_by_id: dict[uuid.UUID, DocumentDTO]
    ) -> LinkPreviewEntry:
        from_doc = docs_by_id.get(edge.from_document_id)
        return LinkPreviewEntry(
            target=from_doc.stem if from_doc else str(edge.from_document_id),
            label=edge.label,
            edge_type=edge.edge_type,
            source_syntax=edge.source_syntax,
            resolved=from_doc is not None,
            document_id=from_doc.id if from_doc else None,
            title=from_doc.title if from_doc else None,
            stem=from_doc.stem if from_doc else None,
        )

    # ------------------------------------------------------------------
    # graph 조회 (nodes/edges, neighborhood)
    # ------------------------------------------------------------------

    async def graph_documents(
        self, *, exclude_types: tuple[str, ...] = _DEFAULT_EXCLUDE
    ) -> GraphView:
        """문서 그래프 노드/엣지 (SPEC-005 GET /graph/documents). type=source 기본 제외.

        엣지는 resolve된 것만(양 끝이 노드 집합에 있고 to_document_id 존재) 내보낸다.
        """
        docs = await self._docs.list_by_types(exclude_types=exclude_types)
        node_ids = {d.id for d in docs}
        nodes = [
            GraphNode(
                document_id=d.id,
                stem=d.stem,
                title=d.title,
                document_type=d.document_type,
            )
            for d in docs
        ]
        edges: list[GraphEdge] = []
        for edge in await self._docs.list_all_edges():
            if edge.to_document_id is None or edge.is_broken:
                continue
            if edge.from_document_id not in node_ids or edge.to_document_id not in node_ids:
                continue
            edges.append(
                GraphEdge(
                    from_document_id=edge.from_document_id,
                    to_document_id=edge.to_document_id,
                    edge_type=edge.edge_type,
                    source_syntax=edge.source_syntax,
                    label=edge.label,
                    is_broken=edge.is_broken,
                )
            )
        return GraphView(nodes=nodes, edges=edges)

    async def neighborhood(
        self,
        document_id: uuid.UUID,
        *,
        depth: int = 1,
        exclude_types: tuple[str, ...] = _DEFAULT_EXCLUDE,
    ) -> GraphView:
        """선택 노드 기준 depth 이내 서브그래프 (retriever·그래프 뷰의 selected 우선)."""
        docs = await self._docs.list_by_types(exclude_types=exclude_types)
        by_id = {d.id: d for d in docs}
        adjacency = await self._resolved_adjacency(set(by_id))
        reachable = _bfs_within(document_id, adjacency, depth)
        reachable &= set(by_id)
        reachable.add(document_id)
        nodes = [
            GraphNode(
                document_id=d.id, stem=d.stem, title=d.title, document_type=d.document_type
            )
            for did, d in by_id.items()
            if did in reachable
        ]
        edges: list[GraphEdge] = []
        for edge in await self._docs.list_all_edges():
            if edge.to_document_id is None or edge.is_broken:
                continue
            if edge.from_document_id in reachable and edge.to_document_id in reachable:
                edges.append(
                    GraphEdge(
                        from_document_id=edge.from_document_id,
                        to_document_id=edge.to_document_id,
                        edge_type=edge.edge_type,
                        source_syntax=edge.source_syntax,
                        label=edge.label,
                        is_broken=edge.is_broken,
                    )
                )
        return GraphView(nodes=nodes, edges=edges)

    # ------------------------------------------------------------------
    # retriever — 2단 구조 (chat④·문서화③ 공유 컴포넌트, AXKG-WORK-008)
    #   1단 후보 발굴: qmd 하이브리드(BM25+벡터 RRF) top_k 시드
    #   2단 그래프 확장: 시드 wikilink 탐색(edge 가중치·hop 감쇠·다중 시드 합산·selected 우선)
    #   qmd 장애 시 1단을 keyword+edge로 graceful fallback (2단 확장 유지, C-5)
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        *,
        selected_stem: str | None = None,
        top_n: int = DEFAULT_TOP_N,
        snippet_len: int = DEFAULT_SNIPPET_LEN,
        top_k: int = DEFAULT_QMD_TOP_K,
        rerank: bool | None = None,
        exclude_types: tuple[str, ...] = _DEFAULT_EXCLUDE,
    ) -> RetrievalResult:
        """2단 Graph RAG retriever.

        1단(qmd 하이브리드) 후보를 시드로 2단 wikilink 그래프 확장을 한다. qmd 사이드카
        장애 시 1단을 keyword+edge 스캔으로 자동 폴백한다(품질 강등, RETRIEVER_FALLBACK_USED).
        selected_stem이 있으면 그 neighborhood를 우선한다. top_n 문서 + index 스냅샷 +
        근거 경로(used_paths/evidence_edges)를 반환한다.
        """
        docs = await self._docs.list_by_types(exclude_types=exclude_types)
        snapshot = await self._documents.index_snapshot(exclude_types=exclude_types)

        # --- 1단: qmd 하이브리드 후보 발굴 (실패 시 keyword+edge 폴백) ---
        try:
            candidates = await self._qmd.search(query, top_k=top_k, rerank=rerank)
        except QmdUnavailable:
            return await self._retrieve_keyword_edge(
                query,
                docs=docs,
                snapshot=snapshot,
                selected_stem=selected_stem,
                top_n=top_n,
                snippet_len=snippet_len,
            )
        return await self._retrieve_two_stage(
            query,
            candidates=candidates,
            docs=docs,
            snapshot=snapshot,
            selected_stem=selected_stem,
            top_n=top_n,
            snippet_len=snippet_len,
        )

    # ------------------------------------------------------------------
    # 1단 폴백: keyword score + edge distance (기존 계약 그대로 — 삭제 금지, C-5)
    # ------------------------------------------------------------------

    async def _retrieve_keyword_edge(
        self,
        query: str,
        *,
        docs: list[DocumentDTO],
        snapshot: list[IndexSnapshotEntry],
        selected_stem: str | None,
        top_n: int,
        snippet_len: int,
    ) -> RetrievalResult:
        by_id = {d.id: d for d in docs}
        tokens = _tokenize(query)

        distances: dict[uuid.UUID, int] = {}
        selected_id: uuid.UUID | None = None
        if selected_stem:
            selected = await self._docs.get_by_stem(selected_stem)
            if selected is not None:
                selected_id = selected.id
                adjacency = await self._resolved_adjacency(set(by_id) | {selected_id})
                distances = _bfs_distances(selected_id, adjacency)

        scored: list[RetrievedDocument] = []
        for doc in docs:
            if doc.id == selected_id:
                continue
            body = self._read_body(doc)
            score = _keyword_score(doc, body, tokens)
            distance = distances.get(doc.id)
            if distance is not None:
                score += _NEIGHBOR_BOOST.get(distance, 0.0)
            if score <= 0 and (distance is None or distance > 2):
                continue
            scored.append(
                RetrievedDocument(
                    document_id=doc.id,
                    stem=doc.stem,
                    title=doc.title,
                    document_type=doc.document_type,
                    score=round(score, 3),
                    distance=distance,
                    snippet=_snippet(body, tokens, snippet_len) or doc.title,
                    path=doc.path,
                )
            )
        scored.sort(
            key=lambda r: (-r.score, r.distance if r.distance is not None else 99, r.title)
        )
        return RetrievalResult(
            query=query,
            documents=scored[:top_n],
            index_snapshot=snapshot,
            fallback_used=True,
            retriever_mode="keyword_edge",
        )

    # ------------------------------------------------------------------
    # 2단: qmd 시드 → wikilink 그래프 확장 (C-4)
    # ------------------------------------------------------------------

    async def _retrieve_two_stage(
        self,
        query: str,
        *,
        candidates: list[QmdCandidate],
        docs: list[DocumentDTO],
        snapshot: list[IndexSnapshotEntry],
        selected_stem: str | None,
        top_n: int,
        snippet_len: int,
    ) -> RetrievalResult:
        by_id = {d.id: d for d in docs}
        by_path = {d.path: d for d in docs}
        tokens = _tokenize(query)

        # 1단 시드: qmd 후보 path → 문서. 시드 relevance는 qmd 순위 기반(상위일수록 큼).
        seeds: dict[uuid.UUID, float] = {}
        seed_order: list[uuid.UUID] = []
        n = max(1, len(candidates))
        for rank, cand in enumerate(candidates):
            doc = by_path.get(cand.path) or _match_by_suffix(cand.path, docs)
            if doc is None or doc.id in seeds:
                continue
            # 상위 시드일수록 큰 근거 점수(순위 선형 감쇠).
            seeds[doc.id] = _SEED_BASE_SCORE * (n - rank) / n
            seed_order.append(doc.id)

        # selected 노드도 시드로 편입(neighborhood 우선, 기존 계약 유지).
        selected_id: uuid.UUID | None = None
        if selected_stem:
            selected = await self._docs.get_by_stem(selected_stem)
            if selected is not None and selected.id in by_id:
                selected_id = selected.id
                seeds.setdefault(selected.id, _SEED_BASE_SCORE)

        # 시드가 하나도 문서로 매핑 안 되면 keyword+edge 폴백(빈 결과 방지).
        if not seeds:
            return await self._retrieve_keyword_edge(
                query,
                docs=docs,
                snapshot=snapshot,
                selected_stem=selected_stem,
                top_n=top_n,
                snippet_len=snippet_len,
            )

        # --- 2단: 각 시드에서 typed 엣지 BFS(hop 감쇠·edge 가중치), 다중 시드 점수 합산 ---
        typed_adj = await self._typed_adjacency(set(by_id))
        agg: dict[uuid.UUID, float] = {}
        min_hop: dict[uuid.UUID, int] = {}
        paths: list[RetrievalPath] = []
        evidence: dict[tuple[uuid.UUID, uuid.UUID], str] = {}

        # 확장 시드 = qmd 후보 + (있으면) selected 노드. 중복 제거·순서 유지.
        expansion_seeds = list(
            dict.fromkeys(seed_order + ([selected_id] if selected_id else []))
        )
        for seed_id in expansion_seeds:
            seed_score = seeds[seed_id]
            reach = _weighted_bfs(seed_id, typed_adj, _MAX_EXPANSION_HOP)
            for node_id, (hop, weight, _prev) in reach.items():
                # hop 감쇠: contrib = seed점수 × edge가중치누적 × decay^hop (hop0=1.0).
                contrib = seed_score * weight * (_HOP_DECAY ** hop)
                agg[node_id] = agg.get(node_id, 0.0) + contrib
                if node_id not in min_hop or hop < min_hop[node_id]:
                    min_hop[node_id] = hop
                if hop > 0 and node_id != seed_id:
                    stems = _path_stems(node_id, reach, by_id)
                    if stems:
                        paths.append(
                            RetrievalPath(
                                seed_stem=by_id[seed_id].stem,
                                to_stem=by_id[node_id].stem,
                                stems=tuple(stems),
                                hop=hop,
                            )
                        )

        # selected neighborhood 우선: selected로부터의 거리로 boost하고 그 거리를 distance로 보고
        # (기존 _NEIGHBOR_BOOST 계약 유지). qmd 시드 거리(min_hop)와 별개 축이다.
        selected_hop: dict[uuid.UUID, int] = {}
        if selected_id is not None:
            sel_reach = _weighted_bfs(selected_id, typed_adj, _MAX_EXPANSION_HOP)
            selected_hop = {nid: hop for nid, (hop, _w, _p) in sel_reach.items()}
            for node_id, hop in selected_hop.items():
                agg[node_id] = agg.get(node_id, 0.0) + _NEIGHBOR_BOOST.get(hop, 0.0)

        # evidence edges: 확장에서 traverse한 typed 엣지(무방향 stem 쌍).
        for a, neighbors in typed_adj.items():
            if a not in agg:
                continue
            for b, etype in neighbors.items():
                if b in agg and a < b:
                    evidence[(a, b)] = etype

        scored: list[RetrievedDocument] = []
        for node_id, score in agg.items():
            if node_id == selected_id:
                continue  # selected 노드 자신은 결과에서 제외(폴백 경로와 동일 계약).
            doc = by_id.get(node_id)
            if doc is None:
                continue
            body = self._read_body(doc)
            # 거리 축: selected가 있으면 selected로부터의 hop, 없으면 qmd 시드로부터의 hop.
            hop = selected_hop.get(node_id) if selected_id is not None else min_hop.get(node_id)
            scored.append(
                RetrievedDocument(
                    document_id=doc.id,
                    stem=doc.stem,
                    title=doc.title,
                    document_type=doc.document_type,
                    score=round(score, 3),
                    distance=hop,
                    snippet=_snippet(body, tokens, snippet_len) or doc.title,
                    path=doc.path,
                )
            )
        scored.sort(
            key=lambda r: (-r.score, r.distance if r.distance is not None else 99, r.title)
        )
        evidence_edges = [
            EvidenceEdge(from_stem=by_id[a].stem, to_stem=by_id[b].stem, edge_type=t)
            for (a, b), t in evidence.items()
        ]
        return RetrievalResult(
            query=query,
            documents=scored[:top_n],
            index_snapshot=snapshot,
            fallback_used=False,
            retriever_mode="qmd_two_stage",
            used_paths=paths,
            evidence_edges=evidence_edges,
        )

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    async def _resolved_adjacency(
        self, node_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, set[uuid.UUID]]:
        """resolve된 엣지로 무방향 인접 리스트를 만든다(neighborhood/거리 계산용)."""
        adjacency: dict[uuid.UUID, set[uuid.UUID]] = {nid: set() for nid in node_ids}
        for edge in await self._docs.list_all_edges():
            if edge.to_document_id is None or edge.is_broken:
                continue
            a, b = edge.from_document_id, edge.to_document_id
            if a not in node_ids or b not in node_ids:
                continue
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)
        return adjacency

    async def _typed_adjacency(
        self, node_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, dict[uuid.UUID, str]]:
        """resolve된 엣지로 무방향 typed 인접(neighbor→edge_type)을 만든다(2단 확장용).

        같은 쌍에 여러 엣지가 있으면 edge 가중치가 큰 타입을 유지한다(lineage > assoc).
        """
        adj: dict[uuid.UUID, dict[uuid.UUID, str]] = {nid: {} for nid in node_ids}
        for edge in await self._docs.list_all_edges():
            if edge.to_document_id is None or edge.is_broken:
                continue
            a, b, etype = edge.from_document_id, edge.to_document_id, edge.edge_type
            if a not in node_ids or b not in node_ids:
                continue
            for x, y in ((a, b), (b, a)):
                cur = adj[x].get(y)
                if cur is None or _EDGE_TYPE_WEIGHT.get(etype, 1.0) > _EDGE_TYPE_WEIGHT.get(
                    cur, 1.0
                ):
                    adj[x][y] = etype
        return adj

    def _read_body(self, doc: DocumentDTO) -> str:
        if self._root is None:
            return ""
        try:
            if not self._root.exists(doc.path):
                return ""
            return parse_markdown(self._root.read_text(doc.path)).body
        except OSError:
            return ""


# ---------------------------------------------------------------------------
# scoring helpers (순수)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= 2]


def _keyword_score(doc: DocumentDTO, body: str, tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    fields = " ".join([doc.title, doc.stem, *doc.aliases]).lower()
    tags = " ".join(doc.tags).lower()
    body_lower = body.lower()
    score = 0.0
    for token in tokens:
        if token in fields:
            score += 3.0
        if token in tags:
            score += 2.0
        if body_lower:
            score += min(body_lower.count(token), 3) * 1.0
    return score


def _snippet(body: str, tokens: list[str], length: int) -> str:
    text = " ".join(body.split())
    if not text:
        return ""
    lowered = text.lower()
    pos = -1
    for token in tokens:
        pos = lowered.find(token)
        if pos != -1:
            break
    if pos == -1:
        return text[:length].strip()
    start = max(0, pos - length // 3)
    return text[start : start + length].strip()


def _bfs_distances(
    start: uuid.UUID, adjacency: dict[uuid.UUID, set[uuid.UUID]]
) -> dict[uuid.UUID, int]:
    distances = {start: 0}
    queue: deque[uuid.UUID] = deque([start])
    while queue:
        node = queue.popleft()
        for neighbor in adjacency.get(node, ()):
            if neighbor not in distances:
                distances[neighbor] = distances[node] + 1
                queue.append(neighbor)
    return distances


def _bfs_within(
    start: uuid.UUID, adjacency: dict[uuid.UUID, set[uuid.UUID]], depth: int
) -> set[uuid.UUID]:
    distances = _bfs_distances(start, adjacency)
    return {node for node, dist in distances.items() if dist <= depth}


def _weighted_bfs(
    start: uuid.UUID,
    typed_adj: dict[uuid.UUID, dict[uuid.UUID, str]],
    max_hop: int,
) -> dict[uuid.UUID, tuple[int, float, uuid.UUID | None]]:
    """시드에서 max_hop 이내 typed 엣지 BFS.

    node → (hop, cumulative_edge_weight, prev). cumulative_weight = 경로 edge 타입
    가중치의 곱. 최단 hop 트리를 따르고 시드 자신은 (0, 1.0, None).
    """
    reach: dict[uuid.UUID, tuple[int, float, uuid.UUID | None]] = {
        start: (0, 1.0, None)
    }
    queue: deque[uuid.UUID] = deque([start])
    while queue:
        node = queue.popleft()
        hop, weight, _prev = reach[node]
        if hop >= max_hop:
            continue
        for neighbor, etype in typed_adj.get(node, {}).items():
            if neighbor in reach:
                continue
            reach[neighbor] = (
                hop + 1,
                weight * _EDGE_TYPE_WEIGHT.get(etype, 1.0),
                node,
            )
            queue.append(neighbor)
    return reach


def _path_stems(
    node_id: uuid.UUID,
    reach: dict[uuid.UUID, tuple[int, float, uuid.UUID | None]],
    by_id: dict[uuid.UUID, DocumentDTO],
) -> list[str]:
    """reach의 prev 체인을 따라 시드→node stem 경로를 복원한다."""
    chain: list[str] = []
    cur: uuid.UUID | None = node_id
    seen: set[uuid.UUID] = set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        doc = by_id.get(cur)
        if doc is None:
            return []
        chain.append(doc.stem)
        entry = reach.get(cur)
        cur = entry[2] if entry else None
    chain.reverse()
    return chain


def _match_by_suffix(
    path: str, docs: list[DocumentDTO]
) -> DocumentDTO | None:
    """qmd path가 root 상대경로와 정확히 안 맞을 때 suffix로 매칭(collection prefix 변주 대비)."""
    if not path:
        return None
    for doc in docs:
        if doc.path == path or doc.path.endswith("/" + path) or path.endswith(
            "/" + doc.path
        ):
            return doc
    return None
