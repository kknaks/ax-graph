// 회사 프로젝트 (AXKG-SPEC-014 U-1~U-5 · AXKG-WORK-013) — "프로젝트 추가" + corp 트리 열람(admin 전용).
// 좌: 회사 프로젝트 목록 → 선택 corp 의 회사 루트 {corp}.md + origin/baseline/spec/context 트리(GET /projects/{corp}).
// 우: 선택한 회사 루트·baseline·spec·context 문서 본문 — SPEC-013 문서 read-through 재사용(path → GET /documents/{id}).
//     origin 은 첨부 docx 원본(그래프 노드 아님) — 본문 렌더 없이 안내만.
//     회사 루트 {corp}.md 는 트리 응답 folders 에 없고 경로가 결정적이라(projects/{corp}/{corp}.md) FE 가 앵커로 합성한다.
// 팬아웃(origin 보관 + baseline 1 + spec N)은 문서화 승인 게이트(③) 결과로 트리에 나타난다(U-4는 게이트 표면).
// 읽기 전용 트리(쓰기 API 없음). 이 라우트는 admin 전용(access.ts STAFF_PATH_PREFIXES 밖).
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "@/lib/api-client";
import { extractHeadings } from "@/lib/markdown-headings";
import { listDocuments, getDocument, type DocumentListItem } from "@/lib/api-client/documents";
import {
  getProjectTree,
  listProjects,
  type ProjectTree,
} from "@/lib/api-client/projects";
import { parseFrontmatter } from "@/lib/frontmatter";
import { MarkdownView } from "@/components/markdown-view";
import { FrontmatterBlock } from "@/components/document-file-modal";
import { ProjectAddModal } from "@/components/project-add-modal";

type FolderKind = "origin" | "baseline" | "spec" | "context";
const FOLDER_ORDER: FolderKind[] = ["origin", "baseline", "spec", "context"];
const FOLDER_LABELS: Record<FolderKind, string> = {
  origin: "origin · 첨부 원본",
  baseline: "baseline · 원본요약",
  spec: "spec · 기능정의서",
  context: "context · 회사 배경지식",
};

// 선택된 리프 식별 — corp + 전체 문서 경로(read-through 키). isBinary=origin(첨부 원본, 본문 없음).
interface SelectedLeaf {
  corp: string;
  path: string;
  name: string;
  isBinary: boolean;
}

/** 회사 루트 앵커 경로 = projects/{corp}/{corp}.md (WORK-013 · BE company_root_path 와 동일 규약). */
function companyRootPath(corp: string): string {
  return `projects/${corp}/${corp}.md`;
}

/** map.md 는 문서 apply 시 자동 재생성되는 MOC(목차) — 트리에서 "(자동)"으로 표시. */
function isAutoMap(name: string): boolean {
  return name === "map.md";
}

/** `.md`/`.docx` 확장자만 떼어 라벨로. */
function fileLabel(name: string): string {
  return name.replace(/\.(md|docx)$/i, "");
}

/** 우측 본문 헤더/렌더용 정규화 메타. */
interface BodyMeta {
  title: string | null;
  documentType: string | null;
  markdownFull: string | null;
}

export default function ProjectsPage() {
  const [corps, setCorps] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);

  // corp 별 트리 캐시(지연 로드). 상태: 트리 객체 / "loading" / "error".
  const [trees, setTrees] = useState<Record<string, ProjectTree | "loading" | "error">>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // 진행 중 fetch 중복 방지(effect 재실행 사이 in-flight 표시).
  const inFlightCorps = useRef<Set<string>>(new Set());

  // path → document id 색인(SPEC-013 read-through). baseline/spec 리프 본문 조회에 쓴다.
  const [docIndex, setDocIndex] = useState<Map<string, DocumentListItem>>(new Map());

  const [selected, setSelected] = useState<SelectedLeaf | null>(null);
  const [bodyMeta, setBodyMeta] = useState<BodyMeta | null>(null);
  const [bodyLoading, setBodyLoading] = useState(false);
  const [bodyError, setBodyError] = useState<string | null>(null);

  // 모바일(<md) 전환형 master-detail.
  const [mobileView, setMobileView] = useState<"tree" | "body">("tree");
  const bodyPaneRef = useRef<HTMLDivElement | null>(null);
  const [activeHeadingId, setActiveHeadingId] = useState<string | null>(null);

  // --- corp 목록 + 문서 색인 로드 ---
  const loadList = useCallback(async () => {
    setLoading(true);
    setListError(null);
    try {
      const [projects, docItems] = await Promise.all([
        listProjects(),
        listDocuments().catch(() => [] as DocumentListItem[]),
      ]);
      setCorps(projects.map((p) => p.corp));
      setDocIndex(new Map(docItems.map((d) => [d.path, d])));
    } catch {
      setCorps([]);
      setListError("프로젝트 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  // corp 펼침 토글 — 처음 펼칠 때 트리를 지연 로드.
  const toggleCorp = useCallback(
    (corp: string) => {
      setExpanded((cur) => {
        const next = new Set(cur);
        if (next.has(corp)) {
          next.delete(corp);
          return next;
        }
        next.add(corp);
        return next;
      });
      setTrees((cur) => {
        if (cur[corp] && cur[corp] !== "error") return cur;
        return { ...cur, [corp]: "loading" };
      });
    },
    [],
  );

  // 펼쳐졌지만 아직 트리가 없는(=loading) corp 를 로드. in-flight 셋으로 중복 fetch 방지.
  useEffect(() => {
    for (const corp of expanded) {
      if (trees[corp] === "loading" && !inFlightCorps.current.has(corp)) {
        inFlightCorps.current.add(corp);
        getProjectTree(corp)
          .then((t) => setTrees((cur) => ({ ...cur, [corp]: t })))
          .catch(() => setTrees((cur) => ({ ...cur, [corp]: "error" })))
          .finally(() => inFlightCorps.current.delete(corp));
      }
    }
  }, [expanded, trees]);

  // 새 프로젝트 생성/합류 후 — 목록 갱신 + 해당 corp 펼침.
  const handleCreated = useCallback(
    (result: { slug: string }) => {
      void loadList();
      setExpanded((cur) => new Set(cur).add(result.slug));
      setTrees((cur) => ({ ...cur, [result.slug]: "loading" }));
    },
    [loadList],
  );

  const selectLeaf = useCallback((leaf: SelectedLeaf) => {
    setSelected(leaf);
    setMobileView("body");
  }, []);

  // --- 본문 로드 (회사 루트·baseline·spec·context; origin 은 비-노드라 본문 없음) ---
  useEffect(() => {
    if (!selected) return;
    const leaf = selected;
    if (leaf.isBinary) {
      setBodyMeta(null);
      setBodyError(null);
      setBodyLoading(false);
      return;
    }
    const doc = docIndex.get(leaf.path);
    if (!doc) {
      setBodyMeta(null);
      setBodyLoading(false);
      setBodyError("문서 본문을 아직 찾을 수 없습니다. 문서화 승인 후 색인되면 열람할 수 있습니다.");
      return;
    }
    let alive = true;
    setBodyLoading(true);
    setBodyError(null);
    setBodyMeta(null);
    getDocument(doc.id)
      .then((m) => {
        if (alive)
          setBodyMeta({
            title: m.title,
            documentType: m.document_type,
            markdownFull: m.markdown_full ?? null,
          });
      })
      .catch((err) => {
        if (alive)
          setBodyError(
            err instanceof ApiError && err.errorCode === "DOCUMENT_NOT_FOUND"
              ? "문서를 찾을 수 없습니다."
              : "문서 본문을 불러오지 못했습니다.",
          );
      })
      .finally(() => {
        if (alive) setBodyLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [selected, docIndex]);

  const raw = bodyMeta?.markdownFull ?? null;
  const parsed = useMemo(() => (raw ? parseFrontmatter(raw) : null), [raw]);
  const body = parsed?.body ?? null;
  const fmFields = parsed?.fields ?? [];

  const headings = useMemo(() => (body ? extractHeadings(body) : []), [body]);
  const showToc = headings.length >= 2;

  const scrollToHeading = useCallback((id: string) => {
    const el = bodyPaneRef.current?.querySelector<HTMLElement>(`[id="${id}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      setActiveHeadingId(id);
    }
  }, []);

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

  const selectedKey = selected ? selected.path : null;

  return (
    <main className="flex h-[calc(100dvh-3.5rem)] w-full flex-col px-4 py-4 md:px-6 md:py-5">
      <div className="mb-4 flex shrink-0 items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">회사 프로젝트</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            회사 루트 <span className="font-mono">{"{corp}"}.md</span> 아래 origin·baseline·spec·context 문서를
            트리로 열람합니다. 프로젝트 추가는 수동·독립 스캐폴딩입니다.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAddOpen(true)}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M12 5v14M5 12h14" />
          </svg>
          프로젝트 추가
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4 md:grid md:grid-cols-[300px_1fr]">
        {/* 트리 pane */}
        <div
          className={`min-w-0 min-h-0 flex-col md:flex ${
            mobileView === "body" ? "hidden" : "flex flex-1"
          }`}
        >
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto rounded-lg border border-border bg-card p-2">
            {loading ? (
              <p className="p-2 text-xs text-muted-foreground">프로젝트 목록을 불러오는 중…</p>
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
            ) : corps.length === 0 ? (
              <p className="p-2 text-xs text-muted-foreground">
                아직 회사 프로젝트가 없습니다. 상단 &ldquo;프로젝트 추가&rdquo;로 만들어 주세요.
              </p>
            ) : (
              <ul className="text-sm">
                {corps.map((corp) => {
                  const open = expanded.has(corp);
                  const tree = trees[corp];
                  return (
                    <li key={corp}>
                      <button
                        type="button"
                        onClick={() => toggleCorp(corp)}
                        aria-expanded={open}
                        style={{ paddingLeft: "8px" }}
                        className="flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left text-foreground/90 hover:bg-secondary/60"
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
                        <span className="truncate font-medium">{corp}/</span>
                      </button>
                      {open && (
                        <div>
                          {tree === "loading" || tree === undefined ? (
                            <p className="px-8 py-1.5 text-xs text-muted-foreground">불러오는 중…</p>
                          ) : tree === "error" ? (
                            <p className="px-8 py-1.5 text-xs text-destructive">트리를 불러오지 못했습니다.</p>
                          ) : (
                            <FolderGroups
                              tree={tree}
                              selectedKey={selectedKey}
                              onSelect={selectLeaf}
                            />
                          )}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        {/* 본문 pane */}
        <div
          className={`min-w-0 min-h-0 flex-col md:flex ${
            mobileView === "tree" ? "hidden" : "flex flex-1"
          }`}
        >
          <button
            type="button"
            onClick={() => setMobileView("tree")}
            className="mb-2 inline-flex shrink-0 items-center gap-1.5 self-start rounded-md border border-border px-2.5 py-1.5 text-xs font-medium hover:bg-secondary md:hidden"
          >
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M19 12H5M12 19l-7-7 7-7" />
            </svg>
            트리
            {selected && (
              <span className="max-w-[55vw] truncate font-normal text-muted-foreground">
                · {fileLabel(selected.name)}
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
            ) : selected.isBinary ? (
              // origin = 첨부 docx 원본(그래프 노드 아님) — 본문 렌더 없이 안내(SPEC-014 Data Contract).
              <div className="grid h-full min-h-[40vh] place-items-center p-6 text-center">
                <div>
                  <p className="text-sm font-medium">{selected.name}</p>
                  <p className="mt-1.5 max-w-sm text-xs leading-relaxed text-muted-foreground">
                    첨부 원본 파일(origin)은 감사·역참조용 raw 파일로 보관되며, 문서 노드가 아니라 본문
                    렌더 대상이 아닙니다. 요약 결과는 baseline·spec 문서에서 확인하세요.
                  </p>
                </div>
              </div>
            ) : bodyLoading ? (
              <p className="p-6 text-xs text-muted-foreground">문서를 불러오는 중…</p>
            ) : bodyError ? (
              <p className="p-6 text-xs text-muted-foreground">{bodyError}</p>
            ) : body !== null ? (
              <div className="px-6 py-6 lg:px-8">
                <div className="mx-auto flex w-full max-w-6xl justify-center gap-10">
                  <article className="min-w-0 w-full max-w-3xl">
                    <div className="mb-4 flex items-center gap-2 border-b border-border pb-3">
                      <h2 className="min-w-0 truncate text-lg font-semibold tracking-tight">
                        {bodyMeta?.title || fileLabel(selected.name)}
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
              <p className="p-6 text-xs text-muted-foreground">문서 본문을 불러오지 못했습니다.</p>
            )}
          </div>
        </div>
      </div>

      <ProjectAddModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onCreated={handleCreated}
      />
    </main>
  );
}

/** corp 트리 — 회사 루트 앵커 `{corp}.md` + origin/baseline/spec/context 폴더 + 항목 렌더(U-3 · WORK-013). */
function FolderGroups({
  tree,
  selectedKey,
  onSelect,
}: {
  tree: ProjectTree;
  selectedKey: string | null;
  onSelect: (leaf: SelectedLeaf) => void;
}) {
  const rootPath = companyRootPath(tree.corp);
  const rootActive = rootPath === selectedKey;
  const foldersEmpty = FOLDER_ORDER.every((f) => (tree.folders[f]?.length ?? 0) === 0);
  return (
    <ul>
      {/* 회사 루트 앵커 — corp 디렉토리 최상단 문서(모든 산출이 up: 로 여기 수렴, WORK-013 D3). */}
      <li>
        <button
          type="button"
          onClick={() =>
            onSelect({ corp: tree.corp, path: rootPath, name: `${tree.corp}.md`, isBinary: false })
          }
          aria-current={rootActive ? "true" : undefined}
          title={`${tree.corp}.md · 회사 루트`}
          style={{ paddingLeft: "22px" }}
          className={
            rootActive
              ? "flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left text-[13px] font-medium text-secondary-foreground bg-secondary"
              : "flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left text-[13px] font-medium text-foreground/90 hover:bg-secondary/60"
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
            <path d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-4" />
          </svg>
          <span className="min-w-0 flex-1 truncate">{tree.corp}.md</span>
          <span className="shrink-0 rounded-full border border-border px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground">
            회사 루트
          </span>
        </button>
      </li>

      {foldersEmpty && (
        <li>
          <p className="px-8 py-1.5 text-xs text-muted-foreground">
            폴더는 스캐폴드만 있고 문서는 아직 없습니다.
          </p>
        </li>
      )}

      {!foldersEmpty && FOLDER_ORDER.map((folder) => {
        const items = tree.folders[folder] ?? [];
        return (
          <li key={folder}>
            <div
              style={{ paddingLeft: "22px" }}
              className="flex items-center gap-1.5 py-1.5 pr-2 text-[11px] font-medium text-muted-foreground"
            >
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
              <span className="truncate">{FOLDER_LABELS[folder]}</span>
            </div>
            {items.length === 0 ? (
              <p style={{ paddingLeft: "44px" }} className="py-1 pr-2 text-[11px] text-muted-foreground/70">
                (비어 있음)
              </p>
            ) : (
              <ul>
                {[...items]
                  .sort((a, b) => a.localeCompare(b))
                  .map((name) => {
                    const path = `projects/${tree.corp}/${folder}/${name}`;
                    const active = path === selectedKey;
                    const auto = isAutoMap(name);
                    return (
                      <li key={name}>
                        <button
                          type="button"
                          onClick={() =>
                            onSelect({
                              corp: tree.corp,
                              path,
                              name,
                              isBinary: folder === "origin",
                            })
                          }
                          aria-current={active ? "true" : undefined}
                          title={name}
                          style={{ paddingLeft: "44px" }}
                          className={
                            active
                              ? "flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left text-[13px] font-medium text-secondary-foreground bg-secondary"
                              : "flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left text-[13px] text-foreground/90 hover:bg-secondary/60"
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
                          </svg>
                          <span className="min-w-0 flex-1 truncate">{fileLabel(name)}</span>
                          {auto && (
                            <span className="shrink-0 rounded-full border border-border px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground">
                              자동
                            </span>
                          )}
                        </button>
                      </li>
                    );
                  })}
              </ul>
            )}
          </li>
        );
      })}
    </ul>
  );
}
