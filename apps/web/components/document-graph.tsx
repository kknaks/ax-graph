// 문서 링크 그래프 (AXKG-SPEC-005 U-1/U-2 · 21-html page-graph section-spec-005).
// force graph 로 확정 문서(documents)와 엣지(assoc/lineage)를 그리고, 노드 클릭 시
// 상세(상류 up / 하류 / backlink / wikilink)를 보여준다. force-graph 는 클라이언트 전용 →
// dynamic import(ssr:false). 노드 id = document_id(데이터 키, index 금지).
"use client";

import dynamic from "next/dynamic";
import { type ComponentType, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getDocument,
  getDocumentLinks,
  getGraphDocuments,
  getNeighborhood,
  graphCaseMessage,
  type DocumentLink,
  type DocumentLinks,
  type DocumentMeta,
  type GraphDocuments,
} from "@/lib/api-client/graph";

// force-graph 는 window/canvas 의존 → SSR 비활성. accessor 타입은 라이브러리 제네릭과
// 반공변 충돌이 있어 프롭 타입을 느슨하게 캐스팅한다(콜백 내부는 FGNode/FGLink 로 명시).
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
}) as unknown as ComponentType<Record<string, unknown>>;

// document_type → 노드 색. 알 수 없는 타입은 muted 회색으로 폴백.
const TYPE_COLOR: Record<string, string> = {
  reference: "hsl(142 71% 45%)",
  resource: "hsl(142 71% 45%)",
  permanent: "hsl(262 83% 62%)",
  concept: "hsl(189 94% 43%)",
  area: "hsl(217 91% 60%)",
  project: "hsl(217 91% 60%)",
  baseline: "hsl(38 92% 50%)",
};
function typeColor(type: string): string {
  return TYPE_COLOR[type] ?? "hsl(0 0% 45%)";
}

type FGNode = {
  id: string;
  stem: string;
  title: string;
  document_type: string;
  x?: number;
  y?: number;
};
type FGLink = {
  source: string;
  target: string;
  edge_type: string;
  is_broken: boolean;
};

/** 상세 패널 링크 한 줄 — resolve 된 target 은 제목, 아니면 target(깨진 링크) 표시. */
function LinkRow({ link }: { link: DocumentLink }) {
  return (
    <span className={link.is_broken ? "text-destructive" : "text-foreground"}>
      {link.title || link.label || link.target}
      {link.is_broken && <span className="ml-1 text-[10px] text-destructive">(broken)</span>}
    </span>
  );
}

function LinkGroup({ label, links }: { label: string; links: DocumentLink[] }) {
  if (links.length === 0) return null;
  return (
    <div>
      <span className="font-medium text-foreground">{label}</span> ·{" "}
      {links.map((l, i) => (
        <span key={`${l.target}-${i}`}>
          {i > 0 && ", "}
          <LinkRow link={l} />
        </span>
      ))}
    </div>
  );
}

/** 그래프에서 선택된 노드 요약 — 채팅 context 동기화용(SPEC-006 S-1/U-1). */
export interface GraphSelection {
  id: string;
  title: string;
  document_type: string;
}

interface DocumentGraphProps {
  /** 노드 선택/해제 시 호출 — 채팅이 selected_node_id context 로 사용한다(S-1). */
  onSelectNode?: (selection: GraphSelection | null) => void;
  /** 외부(Evidence Block "그래프에서 보기")에서 특정 문서 노드를 강조 요청(S-3).
   * nonce 를 바꿔 같은 id 재요청도 트리거되게 한다. */
  focusRequest?: { id: string; nonce: number } | null;
}

export function DocumentGraph({ onSelectNode, focusRequest }: DocumentGraphProps = {}) {
  const [graph, setGraph] = useState<GraphDocuments | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [focused, setFocused] = useState(false); // neighborhood(관련 노드) 강조 모드

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ meta: DocumentMeta | null; links: DocumentLinks | null } | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  // --- 전체 그래프 로드 ---
  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getGraphDocuments();
      setGraph(data);
      setFocused(false);
    } catch (err) {
      setGraph(null);
      setError(graphCaseMessage(err, "그래프를 불러오지 못했습니다."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  // --- 캔버스 크기 추적 (force-graph 는 width/height 필요) ---
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () => setSize({ width: el.clientWidth, height: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // --- BE 노드/엣지 → force-graph 데이터. lineage 는 upstream→current 로 방향 정렬(arrow). ---
  const graphData = useMemo(() => {
    if (!graph) return { nodes: [] as FGNode[], links: [] as FGLink[] };
    const nodes: FGNode[] = graph.nodes.map((n) => ({
      id: n.document_id,
      stem: n.stem,
      title: n.title,
      document_type: n.document_type,
    }));
    const ids = new Set(nodes.map((n) => n.id));
    const links: FGLink[] = graph.edges
      // 서브그래프/깨진 참조로 한쪽 노드가 없으면 force-graph 가 깨지므로 제외.
      .filter((e) => ids.has(e.from_document_id) && ids.has(e.to_document_id))
      .map((e) =>
        e.edge_type === "lineage"
          ? {
              source: e.to_document_id, // upstream
              target: e.from_document_id, // current (arrow: upstream→current)
              edge_type: e.edge_type,
              is_broken: e.is_broken,
            }
          : {
              source: e.from_document_id,
              target: e.to_document_id,
              edge_type: e.edge_type,
              is_broken: e.is_broken,
            },
      );
    return { nodes, links };
  }, [graph]);

  // --- 선택 노드 상세(메타/링크) 로드 ---
  const loadDetail = useCallback(async (id: string) => {
    setDetail(null);
    setDetailLoading(true);
    try {
      const [meta, links] = await Promise.all([
        getDocument(id).catch(() => null),
        getDocumentLinks(id).catch(() => null),
      ]);
      setDetail({ meta, links });
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // --- 노드 클릭 → 선택 + 상세 로드 + 채팅 context 동기화(S-1) ---
  const handleNodeClick = useCallback(
    (node: { id?: string | number; title?: string; document_type?: string }) => {
      const id = String(node.id ?? "");
      if (!id) return;
      setSelectedId(id);
      onSelectNode?.({
        id,
        title: node.title ?? id,
        document_type: node.document_type ?? "",
      });
      void loadDetail(id);
    },
    [loadDetail, onSelectNode],
  );

  // --- 관련 노드 강조: neighborhood 서브그래프로 교체 ---
  const highlightNeighborhood = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const sub = await getNeighborhood(id, 1);
      setGraph(sub);
      setFocused(true);
    } catch (err) {
      setError(graphCaseMessage(err, "관련 노드를 불러오지 못했습니다."));
    } finally {
      setLoading(false);
    }
  }, []);

  // --- Evidence Block "그래프에서 보기"(S-3) → 해당 문서 노드 선택 + neighborhood 강조 ---
  useEffect(() => {
    if (!focusRequest?.id) return;
    const id = focusRequest.id;
    const hint = graph?.nodes.find((n) => n.document_id === id);
    setSelectedId(id);
    onSelectNode?.({
      id,
      title: hint?.title ?? id,
      document_type: hint?.document_type ?? "",
    });
    void loadDetail(id);
    void highlightNeighborhood(id);
    // nonce 변경마다 1회 실행(같은 id 재요청 포함). graph/콜백 참조는 최신값을 읽는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRequest?.nonce, focusRequest?.id]);

  const paintNode = useCallback(
    (node: FGNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const r = 5;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fillStyle = typeColor(node.document_type);
      ctx.fill();
      if (node.id === selectedId) {
        ctx.strokeStyle = "hsl(0 0% 9%)";
        ctx.lineWidth = 2 / scale;
        ctx.stroke();
      }
      const label = node.title || node.stem;
      const fontSize = Math.max(10 / scale, 2);
      ctx.font = `${fontSize}px Inter, Pretendard, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = "hsl(0 0% 20%)";
      ctx.fillText(label, x, y + r + 1);
    },
    [selectedId],
  );

  const nodeCount = graph?.nodes.length ?? 0;
  const edgeCount = graph?.edges.length ?? 0;

  // 상세 패널용 링크 분해: 상류=up, 하류=incoming lineage, backlink(assoc)=incoming assoc.
  const links = detail?.links;
  const downstream = links?.backlinks.filter((l) => l.edge_type === "lineage") ?? [];
  const assocBacklinks = links?.backlinks.filter((l) => l.edge_type !== "lineage") ?? [];

  return (
    <section className="flex h-full flex-col rounded-lg border border-border bg-card text-card-foreground shadow-sm">
      {/* 헤더: 제목 + 노드/엣지 수 + assoc/lineage legend */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <svg
            className="h-4 w-4 text-muted-foreground"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <rect x="16" y="16" width="6" height="6" rx="1" />
            <rect x="2" y="16" width="6" height="6" rx="1" />
            <rect x="9" y="2" width="6" height="6" rx="1" />
            <path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3M12 12V8" />
          </svg>
          <h2 className="text-sm font-semibold">문서 그래프</h2>
          <span className="font-mono text-xs text-muted-foreground">
            {nodeCount} nodes · {edgeCount} edges
          </span>
          {focused && (
            <button
              type="button"
              onClick={() => void loadGraph()}
              className="rounded-md border border-border px-2 py-0.5 text-[11px] font-medium hover:bg-secondary/60"
            >
              전체 보기
            </button>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-0 w-4 border-t-[1.5px] border-border" /> assoc{" "}
            <span className="font-mono">[[ ]]</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-0 w-4 border-t-[1.5px] border-dashed border-foreground" /> lineage{" "}
            <span className="font-mono">up:</span>
          </span>
        </div>
      </div>

      {/* 그래프 캔버스 */}
      <div
        ref={wrapRef}
        className="relative min-h-0 w-full flex-1 overflow-hidden rounded-b-lg bg-[radial-gradient(hsl(var(--border))_1px,transparent_1px)] [background-size:22px_22px]"
      >
        {loading ? (
          <div className="grid h-full place-items-center text-center text-xs text-muted-foreground">
            그래프를 불러오는 중…
          </div>
        ) : error ? (
          <div className="grid h-full place-items-center px-6 text-center text-xs text-destructive">
            {error}
          </div>
        ) : nodeCount === 0 ? (
          <div className="grid h-full place-items-center px-6 text-center text-xs leading-relaxed text-muted-foreground">
            아직 확정 문서가 없습니다.
            <br />
            승인 화면에서 문서화 게이트를 승인하면 문서 노드가 그래프에 나타납니다.
          </div>
        ) : (
          size.width > 0 && (
            <ForceGraph2D
              graphData={graphData}
              width={size.width}
              height={size.height}
              nodeId="id"
              nodeLabel={(n: FGNode) => `${n.title} · ${n.document_type}`}
              nodeColor={(n: FGNode) => typeColor(n.document_type)}
              nodeCanvasObject={paintNode}
              nodeCanvasObjectMode={() => "replace"}
              nodePointerAreaPaint={(node: FGNode, color: string, ctx: CanvasRenderingContext2D) => {
                ctx.beginPath();
                ctx.arc(node.x ?? 0, node.y ?? 0, 8, 0, 2 * Math.PI);
                ctx.fillStyle = color;
                ctx.fill();
              }}
              linkColor={(l: FGLink) => (l.is_broken ? "hsl(0 84% 60%)" : "hsl(0 0% 80%)")}
              linkLineDash={(l: FGLink) => (l.edge_type === "lineage" ? [4, 3] : null)}
              linkDirectionalArrowLength={(l: FGLink) => (l.edge_type === "lineage" ? 3.5 : 0)}
              linkDirectionalArrowRelPos={1}
              onNodeClick={handleNodeClick}
              onBackgroundClick={() => {
                setSelectedId(null);
                setDetail(null);
                onSelectNode?.(null);
              }}
              cooldownTicks={80}
            />
          )
        )}

        {/* 선택 노드 상세 카드 (SPEC-005 U-1/U-2) */}
        {selectedId && (
          <div className="absolute bottom-3 left-3 w-[280px] rounded-lg border border-border bg-card/95 p-3 text-left shadow-md backdrop-blur">
            {detailLoading ? (
              <p className="text-[11px] text-muted-foreground">상세를 불러오는 중…</p>
            ) : detail?.meta ? (
              <>
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-xs font-semibold">{detail.meta.title}</span>
                  <span
                    className="shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium text-primary-foreground"
                    style={{ background: typeColor(detail.meta.document_type) }}
                  >
                    {detail.meta.document_type}
                  </span>
                </div>
                <div className="mt-2 space-y-1.5 text-[11px] leading-relaxed text-muted-foreground">
                  <LinkGroup label="상류 (up:)" links={links?.up ?? []} />
                  <LinkGroup label="하류" links={downstream} />
                  <LinkGroup label="backlinks" links={assocBacklinks} />
                  <LinkGroup label="참조 [[ ]]" links={links?.wikilinks ?? []} />
                  {(links?.up.length ?? 0) === 0 &&
                    downstream.length === 0 &&
                    assocBacklinks.length === 0 &&
                    (links?.wikilinks.length ?? 0) === 0 && (
                      <div className="text-muted-foreground">연결된 문서가 아직 없습니다.</div>
                    )}
                  <div className="break-all font-mono text-[10px] text-foreground/60">
                    {detail.meta.path}
                  </div>
                </div>
                <div className="mt-2 flex gap-1.5">
                  {detail.meta.source_url ? (
                    <a
                      href={detail.meta.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium hover:bg-secondary/60"
                    >
                      원문 열기
                    </a>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => void highlightNeighborhood(selectedId)}
                    className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium hover:bg-secondary/60"
                  >
                    관련 노드 강조
                  </button>
                </div>
              </>
            ) : (
              <p className="text-[11px] text-muted-foreground">문서 상세를 불러오지 못했습니다.</p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
