// 그래프 노드 "파일 보기" 모달 (PLAN-010-T-006) — 원문(markdown_full) + 관련링크 내비.
// - 원문: GET /documents/{id} 의 markdown_full 을 MarkdownView(react-markdown)로 렌더.
// - 관련링크: 상류(up)/하류/backlink/참조([[ ]]) 를 링크 목록으로. resolve 된 링크 클릭 시
//   모달을 유지한 채 그 문서의 원문으로 전환하고(그래프 선택 노드도 동기화) 한다.
// staff·admin 공통 화면(/documents 는 로그인만 권한 — role 분기 없음). 이모지 금지.
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getDocument,
  getDocumentLinks,
  graphCaseMessage,
  type DocumentLink,
  type DocumentLinks,
  type DocumentMeta,
} from "@/lib/api-client/graph";
import { parseFrontmatter, type FrontmatterField } from "@/lib/frontmatter";
import { MarkdownView } from "@/components/markdown-view";

// document-graph.tsx 의 TYPE_COLOR 와 정합(색 SSOT 동기화). WORK-013 신규 타입 포함.
const TYPE_COLOR: Record<string, string> = {
  reference: "hsl(142 71% 45%)",
  resource: "hsl(142 71% 45%)",
  permanent: "hsl(262 83% 62%)",
  concept: "hsl(189 94% 43%)",
  area: "hsl(217 91% 60%)",
  project: "hsl(217 91% 60%)",
  baseline: "hsl(38 92% 50%)",
  feature_spec: "hsl(22 90% 52%)",
  context: "hsl(174 72% 40%)",
  company: "hsl(330 81% 56%)",
};
function typeColor(type: string): string {
  return TYPE_COLOR[type] ?? "hsl(0 0% 45%)";
}

/** 관련링크 한 줄 — resolve 된 target 은 클릭해 이동, broken 은 플레인 텍스트. */
function LinkItem({
  link,
  onNavigate,
}: {
  link: DocumentLink;
  onNavigate: (id: string) => void;
}) {
  const label = link.title || link.label || link.target;
  if (link.is_broken || !link.document_id) {
    return (
      <span className="block truncate px-2 py-1 text-[11px] text-destructive" title={label}>
        {label}
        <span className="ml-1 text-[10px]">(broken)</span>
      </span>
    );
  }
  const id = link.document_id;
  return (
    <button
      type="button"
      onClick={() => onNavigate(id)}
      title={label}
      className="block w-full truncate rounded-md px-2 py-1 text-left text-[11px] text-foreground hover:bg-secondary"
    >
      {label}
    </button>
  );
}

function LinkSection({
  label,
  links,
  onNavigate,
}: {
  label: string;
  links: DocumentLink[];
  onNavigate: (id: string) => void;
}) {
  if (links.length === 0) return null;
  return (
    <div className="mb-3">
      <div className="mb-1 px-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      {links.map((l, i) => (
        <LinkItem key={`${l.target}-${i}`} link={l} onNavigate={onNavigate} />
      ))}
    </div>
  );
}

// --- 로컬 이웃 미니그래프 (PLAN-010-T-009) ---
// 중심=현재 문서, 1촌 이웃(up/하류/backlink/참조)만. 데이터는 getDocumentLinks 결과 재사용.
// force-graph는 과하므로 경량 SVG 자작. 노드 클릭 = 관련링크 클릭과 동일(navigate + 동기화).
// 이웃의 document_type은 links 계약에 없어(색 매핑 불가) 이웃 노드는 중립색 + 엣지 스타일로
// 관계를 구분한다(lineage=점선/화살표, assoc=실선) — /graph 엣지 컨벤션과 정합.

interface MiniNeighbor {
  id: string | null;
  label: string;
  kind: "lineage" | "assoc";
  dir: "in" | "out" | "none"; // in: 이웃→중심(up), out: 중심→이웃(하류)
  broken: boolean;
}

const MINI_W = 272;
const MINI_H = 196;
const MINI_MAX = 14; // 이웃 표시 상한(초과분은 +N 표기)

function shorten(s: string, n = 12): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function DocumentMiniGraph({
  centerLabel,
  centerType,
  links,
  onNavigate,
}: {
  centerLabel: string;
  centerType: string;
  links: DocumentLinks;
  onNavigate: (id: string) => void;
}) {
  const downstream = links.backlinks.filter((l) => l.edge_type === "lineage");
  const assocBacklinks = links.backlinks.filter((l) => l.edge_type !== "lineage");
  const toNeighbor = (l: DocumentLink, kind: MiniNeighbor["kind"], dir: MiniNeighbor["dir"]): MiniNeighbor => ({
    id: l.document_id ?? null,
    label: l.title || l.label || l.target,
    kind,
    dir,
    broken: l.is_broken || !l.document_id,
  });
  const all: MiniNeighbor[] = [
    ...links.up.map((l) => toNeighbor(l, "lineage", "in")),
    ...downstream.map((l) => toNeighbor(l, "lineage", "out")),
    ...assocBacklinks.map((l) => toNeighbor(l, "assoc", "none")),
    ...links.wikilinks.map((l) => toNeighbor(l, "assoc", "none")),
  ];
  const neighbors = all.slice(0, MINI_MAX);
  const overflow = all.length - neighbors.length;

  const cx = MINI_W / 2;
  const cy = MINI_H / 2;
  const R = 72;
  const positions = neighbors.map((_, i) => {
    const angle = (-Math.PI / 2) + (i * 2 * Math.PI) / Math.max(1, neighbors.length);
    return { x: cx + R * Math.cos(angle), y: cy + R * Math.sin(angle) };
  });

  return (
    <div>
      <svg viewBox={`0 0 ${MINI_W} ${MINI_H}`} className="w-full" role="img" aria-label="현재 문서 로컬 그래프">
        <defs>
          <marker id="mini-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 z" fill="hsl(0 0% 55%)" />
          </marker>
        </defs>

        {/* 엣지 (노드 아래) — 방향 있는 lineage는 화살표 끝이 target에 오도록 좌표 정렬 */}
        {neighbors.map((n, i) => {
          const p = positions[i];
          const from = n.dir === "in" ? p : { x: cx, y: cy };
          const to = n.dir === "in" ? { x: cx, y: cy } : p;
          const directed = n.kind === "lineage";
          return (
            <line
              key={`e-${i}`}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke={n.broken ? "hsl(0 84% 60%)" : "hsl(0 0% 78%)"}
              strokeWidth={1}
              strokeDasharray={n.kind === "lineage" ? "3 2" : undefined}
              markerEnd={directed ? "url(#mini-arrow)" : undefined}
            />
          );
        })}

        {/* 이웃 노드 */}
        {neighbors.map((n, i) => {
          const p = positions[i];
          const clickable = !n.broken && n.id;
          return (
            <g
              key={`n-${i}`}
              transform={`translate(${p.x} ${p.y})`}
              onClick={clickable ? () => onNavigate(n.id as string) : undefined}
              style={{ cursor: clickable ? "pointer" : "default" }}
              role={clickable ? "button" : undefined}
              aria-label={n.label}
            >
              <title>{n.label}</title>
              <circle
                r={5}
                fill={n.broken ? "hsl(0 84% 60%)" : "hsl(0 0% 60%)"}
                opacity={n.broken ? 0.5 : 1}
              />
              <text y={15} textAnchor="middle" fontSize={8} fill="hsl(0 0% 30%)">
                {shorten(n.label, 10)}
              </text>
            </g>
          );
        })}

        {/* 중심 노드 (현재 문서) */}
        <g transform={`translate(${cx} ${cy})`}>
          <title>{centerLabel}</title>
          <circle r={7} fill={typeColor(centerType)} stroke="hsl(0 0% 9%)" strokeWidth={1.5} />
          <text y={-11} textAnchor="middle" fontSize={9} fontWeight={600} fill="hsl(0 0% 15%)">
            {shorten(centerLabel, 14)}
          </text>
        </g>
      </svg>

      <div className="mt-1 flex items-center gap-3 px-1 text-[10px] text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-0 w-3 border-t border-foreground/50" /> 참조
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-0 w-3 border-t border-dashed border-foreground/50" /> 계보
        </span>
        {overflow > 0 && <span className="ml-auto">+{overflow} 더</span>}
      </div>
    </div>
  );
}

// 헤더에 이미 있는 키는 메타 블록에서 생략(중복 방지).
const HEADER_KEYS = new Set(["title", "type", "document_type"]);

/** frontmatter를 본문 위 메타 블록으로 렌더 — tags/aliases/up 등은 chip, 그 외는 key-value. */
export function FrontmatterBlock({ fields }: { fields: FrontmatterField[] }) {
  const shown = fields.filter((f) => !HEADER_KEYS.has(f.key));
  if (shown.length === 0) return null;
  return (
    <div className="mb-4 rounded-lg border border-border bg-secondary/25 p-3">
      <dl className="space-y-2">
        {shown.map((f) => (
          <div key={f.key} className="grid grid-cols-[88px_1fr] gap-2">
            <dt className="pt-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {f.key}
            </dt>
            <dd className="min-w-0 text-xs text-foreground">
              {f.value.kind === "list" ? (
                f.value.items.length === 0 ? (
                  <span className="text-muted-foreground">—</span>
                ) : (
                  <div className="flex flex-wrap gap-1">
                    {f.value.items.map((item, i) => (
                      <span
                        key={`${item}-${i}`}
                        className="inline-block rounded-full border border-border bg-background px-2 py-0.5 text-[11px] text-foreground/90"
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                )
              ) : (
                <span className="break-words">{f.value.text}</span>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function DocumentFileModal({
  documentId,
  onClose,
  onNavigate,
}: {
  /** 열 문서 id. null 이면 닫힘. */
  documentId: string | null;
  onClose: () => void;
  /** 관련링크로 이동 시 그래프 선택 노드 동기화(선택). */
  onNavigate?: (id: string) => void;
}) {
  const [currentId, setCurrentId] = useState<string | null>(documentId);
  const [meta, setMeta] = useState<DocumentMeta | null>(null);
  const [links, setLinks] = useState<DocumentLinks | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 열릴 때(id 변경)마다 시작 문서로 리셋.
  useEffect(() => {
    setCurrentId(documentId);
  }, [documentId]);

  // 현재 문서의 원문 + 링크 로드.
  useEffect(() => {
    if (!currentId) return;
    let alive = true;
    setLoading(true);
    setError(null);
    setMeta(null);
    setLinks(null);
    Promise.all([
      getDocument(currentId),
      getDocumentLinks(currentId).catch(() => null),
    ])
      .then(([m, l]) => {
        if (!alive) return;
        setMeta(m);
        setLinks(l);
      })
      .catch((err) => {
        if (alive) setError(graphCaseMessage(err, "문서를 불러오지 못했습니다."));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [currentId]);

  // Esc 로 닫기.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    if (!documentId) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCloseRef.current();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [documentId]);

  const navigate = useCallback(
    (id: string) => {
      setCurrentId(id);
      onNavigate?.(id);
    },
    [onNavigate],
  );

  const raw = meta?.markdown_full ?? null;
  // frontmatter를 분리해 메타 블록으로, 본문만 MarkdownView로 렌더(파싱 실패 시 원문 fallback).
  const parsed = useMemo(() => (raw ? parseFrontmatter(raw) : null), [raw]);
  const fmFields = useMemo(() => parsed?.fields ?? [], [parsed]);

  // 상단 메타의 UP(상류)은 /documents/{id} 프론트매터가 아니라 /documents/{id}/links 의 up 에서 읽는다
  // (프론트매터 up 은 비어 "—" 로만 떠서 그래프 상류가 안 보였던 문제 fix). aliases/tags 는 상세 응답
  // 프론트매터 필드 그대로 둔다(빈 배열이면 "—" 가 정상). 관련링크 패널과 동일 소스(links.up)로 정합.
  const upLabels = useMemo(
    () => (links?.up ?? []).map((l) => l.title || l.label || l.target).filter(Boolean),
    [links],
  );
  const metaFields = useMemo<FrontmatterField[]>(() => {
    if (!links) return fmFields; // 링크 미로딩(실패 포함) 시 프론트매터 그대로 둔다.
    const upField: FrontmatterField = { key: "up", value: { kind: "list", items: upLabels } };
    if (fmFields.some((f) => f.key === "up")) {
      return fmFields.map((f) => (f.key === "up" ? upField : f));
    }
    return upLabels.length > 0 ? [upField, ...fmFields] : fmFields;
  }, [fmFields, upLabels, links]);

  if (!documentId) return null;

  // 관련링크 분해: 상류=up, 하류=incoming lineage, backlink=incoming assoc, 참조=wikilinks(out).
  const downstream = links?.backlinks.filter((l) => l.edge_type === "lineage") ?? [];
  const assocBacklinks = links?.backlinks.filter((l) => l.edge_type !== "lineage") ?? [];
  const hasAnyLink =
    (links?.up.length ?? 0) > 0 ||
    downstream.length > 0 ||
    assocBacklinks.length > 0 ||
    (links?.wikilinks.length ?? 0) > 0;
  const body = parsed?.body ?? null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-0 md:p-4"
      role="dialog"
      aria-modal="true"
      aria-label="파일 보기"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex h-[100dvh] w-full max-w-6xl flex-col overflow-hidden rounded-none border-border bg-background shadow-xl md:h-[85vh] md:rounded-xl md:border">
        {/* 헤더 */}
        <div className="flex items-center justify-between gap-2 border-b border-border px-5 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-sm font-semibold">
              {meta?.title ?? "문서"}
            </span>
            {meta && (
              <span
                className="shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium text-primary-foreground"
                style={{ background: typeColor(meta.document_type) }}
              >
                {meta.document_type}
              </span>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {meta?.source_url ? (
              <a
                href={meta.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium hover:bg-secondary/60"
              >
                원문 열기
              </a>
            ) : null}
            <button
              type="button"
              onClick={onClose}
              aria-label="닫기"
              className="grid h-7 w-7 place-items-center rounded-md border border-border text-muted-foreground hover:bg-secondary"
            >
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* 본문 + 관련링크. 데스크탑=좌우 2패널(각자 스크롤), 모바일=세로 스택 단일 스크롤 축. */}
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto md:flex-row md:overflow-hidden">
          {/* 원문 */}
          <div className="scroll-thin min-w-0 px-6 py-4 md:flex-1 md:overflow-y-auto">
            {loading ? (
              <p className="text-xs text-muted-foreground">문서를 불러오는 중…</p>
            ) : error ? (
              <p className="text-xs text-destructive">{error}</p>
            ) : body !== null ? (
              <>
                {metaFields.length > 0 && <FrontmatterBlock fields={metaFields} />}
                <MarkdownView markdown={body} />
              </>
            ) : (
              <div className="rounded-md border border-dashed border-border bg-secondary/30 p-4 text-center text-xs text-muted-foreground">
                이 문서의 본문을 불러올 수 없습니다.
                {meta?.path && <div className="mt-1 break-all font-mono text-[10px]">{meta.path}</div>}
              </div>
            )}
          </div>

          {/* 우측 레일: 로컬 그래프 + 관련링크. 데스크탑=좌측 320px 고정 사이드바(자체 스크롤),
              모바일=본문 아래 세로 스택(부모 단일 스크롤에 실림). */}
          <aside className="flex w-full shrink-0 flex-col border-t border-border bg-secondary/20 md:w-[320px] md:border-l md:border-t-0">
            <div className="shrink-0 border-b border-border p-3">
              <div className="mb-2 text-xs font-semibold">관련 그래프</div>
              {loading ? (
                <p className="text-[11px] text-muted-foreground">불러오는 중…</p>
              ) : hasAnyLink && meta && links ? (
                <DocumentMiniGraph
                  centerLabel={meta.title}
                  centerType={meta.document_type}
                  links={links}
                  onNavigate={navigate}
                />
              ) : (
                <p className="text-[11px] text-muted-foreground">이웃 문서가 없습니다.</p>
              )}
            </div>
            <div className="scroll-thin px-2 py-4 md:min-h-0 md:flex-1 md:overflow-y-auto">
              <div className="mb-2 px-2 text-xs font-semibold">관련링크</div>
              {loading ? (
                <p className="px-2 text-[11px] text-muted-foreground">불러오는 중…</p>
              ) : hasAnyLink ? (
                <>
                  <LinkSection label="상류 (up:)" links={links?.up ?? []} onNavigate={navigate} />
                  <LinkSection label="하류" links={downstream} onNavigate={navigate} />
                  <LinkSection label="backlinks" links={assocBacklinks} onNavigate={navigate} />
                  <LinkSection label="참조 [[ ]]" links={links?.wikilinks ?? []} onNavigate={navigate} />
                </>
              ) : (
                <p className="px-2 text-[11px] text-muted-foreground">연결된 문서가 없습니다.</p>
              )}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
