// 문서 라이브러리 — 저장 문서 + 요약 트리 열람 (AXKG-SPEC-013, 읽기 전용).
// 좌: GET /documents 의 path + GET /summaries 의 path 를 한 트리로 병합(디렉토리 트리). 우: 선택
// 노드의 본문(문서=GET /documents/{id} markdown_full, 요약=GET /summaries/{source_id} markdown_full)을
// frontmatter 분리 후 FrontmatterBlock + MarkdownView 로 렌더.
// 데스크탑=좌 트리 + 우 본문 2단, 모바일(<md)=트리↔본문 전환형(mobileView) — Source Inbox 준용.
// 읽기 전용: 편집/이동/이름변경/삭제/폴더 생성 등 쓰기 표면·쓰기 API 호출 없음. 이모지 금지.
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "@/lib/api-client";
import { extractHeadings } from "@/lib/markdown-headings";
import { listDocuments, type DocumentListItem } from "@/lib/api-client/documents";
import { getDocument } from "@/lib/api-client/graph";
import { getSummary, listSummaries, type SummaryListItem } from "@/lib/api-client/summaries";
import { parseFrontmatter } from "@/lib/frontmatter";
import { MarkdownView } from "@/components/markdown-view";
import { FrontmatterBlock } from "@/components/document-file-modal";

// 트리 리프의 출처 — 조회 경로가 다르다(문서=/documents/{id}, 요약=/summaries/{source_id}).
type LeafSource = "document" | "summary";

// --- 트리 모델 (path 파생, 파일시스템 스캔 아님 — SPEC-013 §4) ---
/** documents/summaries 공통 리프 입력. id=문서 id 또는 요약 source_id. */
interface LeafEntry {
  path: string;
  id: string;
  title: string;
  source: LeafSource;
}
interface FileNode {
  kind: "file";
  name: string; // path 의 마지막 성분(문서/요약명)
  path: string;
  id: string;
  title: string;
  source: LeafSource;
}
interface DirNode {
  kind: "dir";
  name: string; // 디렉토리 성분명
  path: string; // 루트부터의 상대 경로(펼침 상태 키)
  children: TreeNode[];
}
type TreeNode = DirNode | FileNode;

/** 리프 식별 키(출처+id) — 문서/요약 id 공간이 달라 출처까지 묶어 구분. */
function leafKey(source: LeafSource, id: string): string {
  return `${source}:${id}`;
}

/** documents + summaries 의 path 를 `/` 로 분해해 하나의 디렉토리 트리(루트 children)로 병합. */
function buildTree(entries: LeafEntry[]): TreeNode[] {
  const root: DirNode = { kind: "dir", name: "", path: "", children: [] };
  const dirIndex = new Map<string, DirNode>([["", root]]);

  for (const entry of entries) {
    const segs = entry.path.split("/").filter(Boolean);
    if (segs.length === 0) continue;
    let parent = root;
    let parentPath = "";
    for (let i = 0; i < segs.length - 1; i++) {
      const seg = segs[i];
      const dirPath = parentPath ? `${parentPath}/${seg}` : seg;
      let dir = dirIndex.get(dirPath);
      if (!dir) {
        dir = { kind: "dir", name: seg, path: dirPath, children: [] };
        dirIndex.set(dirPath, dir);
        parent.children.push(dir);
      }
      parent = dir;
      parentPath = dirPath;
    }
    parent.children.push({
      kind: "file",
      name: segs[segs.length - 1],
      path: entry.path,
      id: entry.id,
      title: entry.title,
      source: entry.source,
    });
  }

  sortTree(root.children);
  return root.children;
}

/** 디렉토리 우선 + 이름 오름차순 정렬(재귀). */
function sortTree(nodes: TreeNode[]): void {
  nodes.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === "dir" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  for (const n of nodes) if (n.kind === "dir") sortTree(n.children);
}

/** 모든 디렉토리 경로 수집(초기 전체 펼침용). */
function collectDirPaths(nodes: TreeNode[], acc: string[] = []): string[] {
  for (const n of nodes) {
    if (n.kind === "dir") {
      acc.push(n.path);
      collectDirPaths(n.children, acc);
    }
  }
  return acc;
}

/** 문서/요약명 라벨 — path 성분에서 `.md` 확장자만 떼어 표시(여전히 path 파생). */
function fileLabel(name: string): string {
  return name.endsWith(".md") ? name.slice(0, -3) : name;
}

/** 본문 조회 에러 → SPEC-013 §4 Case Matrix 문구(출처별 404 분기). */
function bodyErrorMessage(err: unknown, source: LeafSource): string {
  if (err instanceof ApiError) {
    if (source === "summary" && err.errorCode === "SUMMARY_NOT_FOUND") {
      return "요약을 찾을 수 없습니다.";
    }
    if (source === "document" && err.errorCode === "DOCUMENT_NOT_FOUND") {
      return "문서를 찾을 수 없습니다.";
    }
  }
  return "문서 본문을 불러오지 못했습니다.";
}

/** 우측 본문 헤더/렌더에 쓰는 정규화 메타(문서/요약 공통). */
interface BodyMeta {
  title: string | null;
  documentType: string | null;
  markdownFull: string | null;
}

// --- 트리 렌더(재귀, hookless) ---
function TreeNodeList({
  nodes,
  depth,
  expanded,
  onToggle,
  selectedKey,
  onSelect,
}: {
  nodes: TreeNode[];
  depth: number;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  selectedKey: string | null;
  onSelect: (node: FileNode) => void;
}) {
  return (
    <ul className="text-sm">
      {nodes.map((node) => {
        const pad = { paddingLeft: `${depth * 14 + 8}px` };
        if (node.kind === "dir") {
          const open = expanded.has(node.path);
          return (
            <li key={`d:${node.path}`}>
              <button
                type="button"
                onClick={() => onToggle(node.path)}
                aria-expanded={open}
                style={pad}
                className="flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left text-muted-foreground hover:bg-secondary/60"
              >
                <svg
                  className={`h-3.5 w-3.5 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <path d="m9 18 6-6-6-6" />
                </svg>
                <svg
                  className="h-4 w-4 shrink-0"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
                </svg>
                <span className="truncate font-medium text-foreground/80">{node.name}</span>
              </button>
              {open && (
                <TreeNodeList
                  nodes={node.children}
                  depth={depth + 1}
                  expanded={expanded}
                  onToggle={onToggle}
                  selectedKey={selectedKey}
                  onSelect={onSelect}
                />
              )}
            </li>
          );
        }
        const active = leafKey(node.source, node.id) === selectedKey;
        return (
          <li key={`f:${leafKey(node.source, node.id)}`}>
            <button
              type="button"
              onClick={() => onSelect(node)}
              aria-current={active ? "true" : undefined}
              title={node.title || node.name}
              style={pad}
              className={
                active
                  ? "flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left font-medium text-secondary-foreground bg-secondary"
                  : "flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left text-foreground/90 hover:bg-secondary/60"
              }
            >
              <svg
                className="h-4 w-4 shrink-0 text-muted-foreground"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
                <path d="M14 2v4a2 2 0 0 0 2 2h4" />
                <path d="M10 9H8M16 13H8M16 17H8" />
              </svg>
              <span className="truncate">{fileLabel(node.name)}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export default function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentListItem[]>([]);
  const [summaries, setSummaries] = useState<SummaryListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const [selected, setSelected] = useState<FileNode | null>(null);
  const [bodyMeta, setBodyMeta] = useState<BodyMeta | null>(null);
  const [bodyLoading, setBodyLoading] = useState(false);
  const [bodyError, setBodyError] = useState<string | null>(null);

  // 모바일(<md) 전환형 master-detail — "tree"=트리 풀폭, "body"=본문 풀폭. 데스크탑은 md: 가 우선.
  const [mobileView, setMobileView] = useState<"tree" | "body">("tree");

  // 본문 pane 스크롤 컨테이너 + TOC 현재 섹션 하이라이트(스크롤 연동).
  const bodyPaneRef = useRef<HTMLDivElement | null>(null);
  const [activeHeadingId, setActiveHeadingId] = useState<string | null>(null);

  // documents + summaries 를 하나의 리프 목록으로 병합 → 한 트리.
  const entries = useMemo<LeafEntry[]>(
    () => [
      ...docs.map((d) => ({ path: d.path, id: d.id, title: d.title, source: "document" as const })),
      ...summaries.map((s) => ({ path: s.path, id: s.source_id, title: s.name, source: "summary" as const })),
    ],
    [docs, summaries],
  );
  const tree = useMemo(() => buildTree(entries), [entries]);

  // --- 목록 로드 (GET /documents current + GET /summaries) ---
  // 요약 목록은 additive — 조회 실패해도(BE T-006 병렬, 미배포 가능) 문서 트리를 깨지 않고 빈 브랜치로 둔다.
  const loadList = useCallback(async () => {
    setLoading(true);
    setListError(null);
    try {
      const [docItems, summaryItems] = await Promise.all([
        listDocuments(),
        listSummaries().catch(() => [] as SummaryListItem[]),
      ]);
      setDocs(docItems);
      setSummaries(summaryItems);
    } catch {
      setDocs([]);
      setSummaries([]);
      setListError("문서 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  // 트리 재구성 시 디렉토리 전체 펼침(초기 조망성).
  useEffect(() => {
    setExpanded(new Set(collectDirPaths(tree)));
  }, [tree]);

  // --- 본문 로드 (문서=/documents/{id}, 요약=/summaries/{source_id} markdown_full read-through) ---
  useEffect(() => {
    if (!selected) return;
    const node = selected;
    let alive = true;
    setBodyLoading(true);
    setBodyError(null);
    setBodyMeta(null);
    const req: Promise<BodyMeta> =
      node.source === "summary"
        ? getSummary(node.id).then((s) => ({
            title: s.name,
            documentType: "요약",
            markdownFull: s.markdown_full ?? null,
          }))
        : getDocument(node.id).then((m) => ({
            title: m.title,
            documentType: m.document_type,
            markdownFull: m.markdown_full ?? null,
          }));
    req
      .then((bm) => {
        if (alive) setBodyMeta(bm);
      })
      .catch((err) => {
        if (alive) setBodyError(bodyErrorMessage(err, node.source));
      })
      .finally(() => {
        if (alive) setBodyLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [selected]);

  const toggleDir = useCallback((path: string) => {
    setExpanded((cur) => {
      const next = new Set(cur);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const selectFile = useCallback((node: FileNode) => {
    setSelected(node);
    setMobileView("body"); // 모바일: 본문 풀폭 전환 (데스크탑은 무시)
  }, []);

  // frontmatter 를 분리해 메타 블록으로, 본문은 MarkdownView 렌더(기존 문서 보기 모달과 동일 처리).
  const raw = bodyMeta?.markdownFull ?? null;
  const parsed = useMemo(() => (raw ? parseFrontmatter(raw) : null), [raw]);
  const body = parsed?.body ?? null;
  const fmFields = parsed?.fields ?? [];

  const selectedKey = selected ? leafKey(selected.source, selected.id) : null;

  // 본문 h1~h3 목차. 2개 이상일 때만 노출(1개 이하·없음은 숨김).
  const headings = useMemo(() => (body ? extractHeadings(body) : []), [body]);
  const showToc = headings.length >= 2;

  // TOC 클릭 → 본문 pane 내부에서 해당 heading 으로 스크롤.
  const scrollToHeading = useCallback((id: string) => {
    const el = bodyPaneRef.current?.querySelector<HTMLElement>(`[id="${id}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      setActiveHeadingId(id);
    }
  }, []);

  // 스크롤 연동 현재 섹션 하이라이트 — pane 상단을 지난 마지막 heading 을 active 로.
  useEffect(() => {
    const root = bodyPaneRef.current;
    if (!root || headings.length < 2) {
      setActiveHeadingId(null);
      return;
    }
    const els = headings
      .map((h) => root.querySelector<HTMLElement>(`[id="${h.id}"]`))
      .filter((el): el is HTMLElement => el !== null);
    if (els.length === 0) return;
    const onScroll = () => {
      const top = root.getBoundingClientRect().top;
      let current = els[0].id;
      for (const el of els) {
        if (el.getBoundingClientRect().top - top <= 24) current = el.id;
        else break;
      }
      setActiveHeadingId(current);
    };
    onScroll();
    root.addEventListener("scroll", onScroll, { passive: true });
    return () => root.removeEventListener("scroll", onScroll);
  }, [headings]);

  return (
    <main className="flex h-[calc(100dvh-3.5rem)] w-full flex-col px-4 py-4 md:px-6 md:py-5">
      <div className="mb-4 shrink-0">
        <h1 className="text-xl font-semibold tracking-tight">문서 라이브러리</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">저장된 문서와 요약을 트리로 열람합니다 (읽기 전용).</p>
      </div>

      {/* 좌: 문서 트리(300px) / 우: 본문(1fr). 데스크탑 2컬럼 고정, 모바일(<md)은 전환형. */}
      <div className="flex min-h-0 flex-1 flex-col gap-4 md:grid md:grid-cols-[300px_1fr]">
        {/* 트리 pane */}
        <div
          className={`min-w-0 min-h-0 flex-col md:flex ${
            mobileView === "body" ? "hidden" : "flex flex-1"
          }`}
        >
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto rounded-lg border border-border bg-card p-2">
            {loading ? (
              <p className="p-2 text-xs text-muted-foreground">문서 목록을 불러오는 중…</p>
            ) : listError ? (
              <div className="p-2">
                <p className="text-xs text-destructive">{listError}</p>
                <button
                  type="button"
                  onClick={() => void loadList()}
                  className="mt-2 rounded-md border border-border px-2.5 py-1 text-xs font-medium hover:bg-secondary"
                >
                  다시 시도
                </button>
              </div>
            ) : tree.length === 0 ? (
              <p className="p-2 text-xs text-muted-foreground">저장된 문서가 없습니다.</p>
            ) : (
              <TreeNodeList
                nodes={tree}
                depth={0}
                expanded={expanded}
                onToggle={toggleDir}
                selectedKey={selectedKey}
                onSelect={selectFile}
              />
            )}
          </div>
        </div>

        {/* 본문 pane */}
        <div
          className={`min-w-0 min-h-0 flex-col md:flex ${
            mobileView === "tree" ? "hidden" : "flex flex-1"
          }`}
        >
          {/* 모바일 전용 백버튼 — 트리 뷰로 복귀(선택/본문 상태 유지). 데스크탑은 md:hidden. */}
          <button
            type="button"
            onClick={() => setMobileView("tree")}
            className="mb-2 inline-flex shrink-0 items-center gap-1.5 self-start rounded-md border border-border px-2.5 py-1.5 text-xs font-medium hover:bg-secondary md:hidden"
          >
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M19 12H5M12 19l-7-7 7-7" />
            </svg>
            목록
            {selected && (
              <span className="max-w-[55vw] truncate font-normal text-muted-foreground">
                · {selected.title || fileLabel(selected.name)}
              </span>
            )}
          </button>

          <div
            ref={bodyPaneRef}
            className="scroll-thin min-h-0 flex-1 overflow-y-auto rounded-lg border border-border bg-card"
          >
            {!selected ? (
              <div className="grid h-full min-h-[40vh] place-items-center p-6 text-center">
                <p className="text-sm text-muted-foreground">
                  왼쪽 트리에서 문서를 선택하면 본문이 여기에 표시됩니다.
                </p>
              </div>
            ) : bodyLoading ? (
              <p className="p-6 text-xs text-muted-foreground">문서를 불러오는 중…</p>
            ) : bodyError ? (
              <p className="p-6 text-xs text-destructive">{bodyError}</p>
            ) : body !== null ? (
              // 읽기 폭 제한(article max-w-3xl) + lg 이상에서만 우측 sticky 목차.
              <div className="px-6 py-6 lg:px-8">
                <div className="mx-auto flex w-full max-w-6xl justify-center gap-10">
                  <article className="min-w-0 w-full max-w-3xl">
                    <div className="mb-4 flex items-center gap-2 border-b border-border pb-3">
                      <h2 className="min-w-0 truncate text-lg font-semibold tracking-tight">
                        {bodyMeta?.title || selected.title || fileLabel(selected.name)}
                      </h2>
                      {bodyMeta?.documentType && (
                        <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                          {bodyMeta.documentType}
                        </span>
                      )}
                    </div>
                    {fmFields.length > 0 && <FrontmatterBlock fields={fmFields} />}
                    <MarkdownView markdown={body} headingIds />
                  </article>

                  {showToc && (
                    <aside className="hidden w-[220px] shrink-0 lg:block">
                      <nav
                        aria-label="이 문서 목차"
                        className="scroll-thin sticky top-0 max-h-[calc(100dvh-9rem)] overflow-y-auto"
                      >
                        <div className="mb-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                          목차
                        </div>
                        <ul className="border-l border-border">
                          {headings.map((h, i) => {
                            const active = activeHeadingId === h.id;
                            return (
                              <li key={`${h.id}-${i}`}>
                                <button
                                  type="button"
                                  onClick={() => scrollToHeading(h.id)}
                                  title={h.text}
                                  aria-current={active ? "true" : undefined}
                                  style={{ paddingLeft: `${(h.depth - 1) * 12 + 12}px` }}
                                  className={
                                    active
                                      ? "-ml-px block w-full truncate border-l-2 border-primary py-1 pr-2 text-left text-xs font-medium text-foreground"
                                      : "-ml-px block w-full truncate border-l-2 border-transparent py-1 pr-2 text-left text-xs text-muted-foreground hover:text-foreground"
                                  }
                                >
                                  {h.text}
                                </button>
                              </li>
                            );
                          })}
                        </ul>
                      </nav>
                    </aside>
                  )}
                </div>
              </div>
            ) : (
              // 200 이지만 markdown_full 이 null(파일 미존재/접근 불가) — 본문 조회 실패로 안내.
              <p className="p-6 text-xs text-destructive">문서 본문을 불러오지 못했습니다.</p>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
