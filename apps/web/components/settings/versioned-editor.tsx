// 버전형 리소스 편집기 — Prompts(SPEC-009)·Templates(SPEC-010) 공통 표면.
// 시안(page-settings.html) 좌측 목록 + 우측 편집기 + 버전 히스토리 + 저장/롤백 확인 모달.
//
// Prompts = 본문(prompt_text) + 출력 스키마(output_schema, JSON) 2필드,
// Templates = 문서 뼈대(body) 1필드. 차이는 `fields` 로만 표현하고 로직은 공유한다.
// JSON 필드는 편집 중 문자열로 다루고 저장 시 parse(무효면 API 전에 인라인 에러).
"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ConfirmDialog } from "./confirm-dialog";

/** 좌측 목록 아이템. usedBy = 시안의 "used by …" 보조 라인. */
export interface ResourceListItem {
  key: string;
  name: string;
  usedBy?: string;
  activeVersion: number | null;
}

/** 버전 히스토리 한 줄 (desc 정렬 가정). */
export interface VersionInfo {
  version: number;
  is_active: boolean;
  updated_at: string | null;
}

/** 활성 view — 필드값 + 현재 version. 필드값 key 는 EditorField.name 과 일치. */
export type ActiveView = Record<string, unknown> & { version: number | null };

export interface EditorField {
  /** 요청 body / 활성 view 의 필드명과 정확히 일치 (예: prompt_text, output_schema, body). */
  name: string;
  label: string;
  /** <input>/<textarea> 아래 힌트 라인. */
  hint?: ReactNode;
  rows: number;
  /** true면 값이 객체(JSON) — 편집은 pretty 문자열, 저장 시 parse. */
  json?: boolean;
}

interface VersionedEditorProps {
  icon: ReactNode;
  heading: string;
  headingNote: ReactNode;
  description: string;
  /** 편집기 상단 배너(템플릿 frontmatter 스탬프 안내 등). */
  banner?: ReactNode;
  listLabel: string;
  listFoot?: ReactNode;
  fields: EditorField[];
  saveLabel: string;
  /** 저장 확인 모달 본문. */
  saveConfirmBody: ReactNode;
  fetchList: () => Promise<ResourceListItem[]>;
  fetchActive: (key: string) => Promise<ActiveView>;
  fetchVersions: (key: string) => Promise<VersionInfo[]>;
  save: (key: string, values: Record<string, unknown>) => Promise<ActiveView>;
  rollback: (key: string, version: number) => Promise<ActiveView>;
  toMessage: (err: unknown, fallback: string) => string;
  /** 저장 전 JSON 필드 parse 실패 시 문구. */
  invalidJsonMessage?: string;
}

/** 활성 view → 편집기 문자열 draft (json 필드는 pretty stringify). */
function toDraft(view: ActiveView, fields: EditorField[]): Record<string, string> {
  const draft: Record<string, string> = {};
  for (const f of fields) {
    const raw = view[f.name];
    if (f.json) {
      draft[f.name] = raw == null ? "{}" : JSON.stringify(raw, null, 2);
    } else {
      draft[f.name] = raw == null ? "" : String(raw);
    }
  }
  return draft;
}

export function VersionedEditor({
  icon,
  heading,
  headingNote,
  description,
  banner,
  listLabel,
  listFoot,
  fields,
  saveLabel,
  saveConfirmBody,
  fetchList,
  fetchActive,
  fetchVersions,
  save,
  rollback,
  toMessage,
  invalidJsonMessage = "올바른 JSON 형식이 아닙니다. 확인 후 다시 저장해 주세요.",
}: VersionedEditorProps) {
  const [items, setItems] = useState<ResourceListItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [activeVersion, setActiveVersion] = useState<number | null>(null);
  const [versions, setVersions] = useState<VersionInfo[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [baseline, setBaseline] = useState<Record<string, string>>({});

  const [listError, setListError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // 확인 모달: 저장 또는 특정 버전 롤백.
  const [confirm, setConfirm] = useState<{ kind: "save" } | { kind: "rollback"; version: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // --- 목록 로드 ---
  useEffect(() => {
    let alive = true;
    fetchList()
      .then((list) => {
        if (!alive) return;
        setItems(list);
        setListError(null);
        setSelected((cur) => cur ?? list[0]?.key ?? null);
      })
      .catch((err) => {
        if (alive) setListError(toMessage(err, "목록을 불러오지 못했습니다."));
      });
    return () => {
      alive = false;
    };
  }, [fetchList, toMessage]);

  // --- 선택 항목 상세 + 버전 로드 ---
  const loadDetail = useCallback(
    (key: string) => {
      setLoadingDetail(true);
      setDetailError(null);
      setToast(null);
      Promise.all([fetchActive(key), fetchVersions(key)])
        .then(([view, vers]) => {
          const next = toDraft(view, fields);
          setDraft(next);
          setBaseline(next);
          setActiveVersion(view.version);
          setVersions(vers);
        })
        .catch((err) => setDetailError(toMessage(err, "내용을 불러오지 못했습니다.")))
        .finally(() => setLoadingDetail(false));
    },
    [fetchActive, fetchVersions, fields, toMessage],
  );

  useEffect(() => {
    if (selected) loadDetail(selected);
  }, [selected, loadDetail]);

  const dirty = useMemo(
    () => fields.some((f) => (draft[f.name] ?? "") !== (baseline[f.name] ?? "")),
    [draft, baseline, fields],
  );

  /** draft(문자열) → 요청 values(json 필드는 parse). 실패 시 null + 인라인 에러. */
  function buildValues(): Record<string, unknown> | null {
    const values: Record<string, unknown> = {};
    for (const f of fields) {
      const raw = draft[f.name] ?? "";
      if (f.json) {
        try {
          values[f.name] = raw.trim() === "" ? {} : JSON.parse(raw);
        } catch {
          setConfirmError(invalidJsonMessage);
          return null;
        }
      } else {
        values[f.name] = raw;
      }
    }
    return values;
  }

  function refreshActiveVersionBadge(view: ActiveView) {
    setItems((prev) =>
      prev.map((it) => (it.key === selected ? { ...it, activeVersion: view.version } : it)),
    );
  }

  async function runSave() {
    if (!selected) return;
    const values = buildValues();
    if (!values) return; // JSON parse 실패 — 모달 유지
    setBusy(true);
    setConfirmError(null);
    try {
      const view = await save(selected, values);
      const next = toDraft(view, fields);
      setDraft(next);
      setBaseline(next);
      setActiveVersion(view.version);
      refreshActiveVersionBadge(view);
      setVersions(await fetchVersions(selected));
      setConfirm(null);
      setToast(`저장 완료 · v${view.version} 활성`);
    } catch (err) {
      setConfirmError(toMessage(err, "저장하지 못했습니다."));
    } finally {
      setBusy(false);
    }
  }

  async function runRollback(version: number) {
    if (!selected) return;
    setBusy(true);
    setConfirmError(null);
    try {
      const view = await rollback(selected, version);
      const next = toDraft(view, fields);
      setDraft(next);
      setBaseline(next);
      setActiveVersion(view.version);
      refreshActiveVersionBadge(view);
      setVersions(await fetchVersions(selected));
      setConfirm(null);
      setToast(`롤백 완료 · v${view.version} 활성`);
    } catch (err) {
      setConfirmError(toMessage(err, "롤백하지 못했습니다."));
    } finally {
      setBusy(false);
    }
  }

  function openConfirm(next: { kind: "save" } | { kind: "rollback"; version: number }) {
    setConfirmError(null);
    setConfirm(next);
  }

  return (
    <section className="rounded-lg border border-border bg-card p-5 text-card-foreground shadow-sm">
      <div className="mb-1 flex items-center gap-2">
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
          {icon}
        </svg>
        <h2 className="text-sm font-semibold">
          {heading} <span className="font-normal text-muted-foreground">{headingNote}</span>
        </h2>
      </div>
      <p className="mb-4 text-xs text-muted-foreground">{description}</p>
      {banner}

      {listError ? (
        <p className="rounded-md border border-dashed border-border bg-secondary/30 p-4 text-center text-xs text-muted-foreground">
          {listError}
        </p>
      ) : (
        <div className="grid grid-cols-[260px_1fr] gap-6">
          {/* 좌측 목록 */}
          <div className="space-y-1.5">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              {listLabel}
            </div>
            {items.map((it) => {
              const active = it.key === selected;
              return (
                <button
                  key={it.key}
                  type="button"
                  onClick={() => setSelected(it.key)}
                  className={
                    active
                      ? "block w-full rounded-md border-2 p-2.5 text-left"
                      : "block w-full rounded-md border border-border px-2.5 py-2 text-left hover:bg-secondary/40"
                  }
                  style={active ? { borderColor: "hsl(var(--ring))" } : undefined}
                >
                  <div className={active ? "text-[11px] font-semibold" : "text-[11px] font-medium"}>
                    {it.name}
                  </div>
                  <div className="mt-0.5 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                    <span className="truncate">{it.usedBy}</span>
                    <span className="whitespace-nowrap font-mono">
                      {it.activeVersion != null ? `활성 v${it.activeVersion}` : "—"}
                    </span>
                  </div>
                </button>
              );
            })}
            {listFoot && <div className="pt-1">{listFoot}</div>}
          </div>

          {/* 우측 편집기 */}
          <div>
            {detailError && (
              <p
                className="mb-3 rounded-md px-2.5 py-2 text-[11px] text-destructive"
                style={{ background: "hsl(var(--destructive) / .08)" }}
              >
                {detailError}
              </p>
            )}

            {fields.map((f, idx) => (
              <div key={f.name} className={idx > 0 ? "mt-3" : undefined}>
                <label
                  htmlFor={`field-${f.name}`}
                  className="block text-[11px] font-medium text-muted-foreground"
                >
                  {f.label}
                </label>
                <textarea
                  id={`field-${f.name}`}
                  value={draft[f.name] ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, [f.name]: e.target.value }))}
                  disabled={loadingDetail || !selected}
                  rows={f.rows}
                  spellCheck={false}
                  className="scroll-thin mt-1 w-full resize-none rounded-md border border-input bg-background p-3 font-mono text-xs leading-relaxed outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
                />
                {f.hint && (
                  <p className="mt-1 font-mono text-[10px] text-muted-foreground">{f.hint}</p>
                )}
              </div>
            ))}

            {/* 버전 히스토리 + 저장 */}
            <div className="mt-3 flex items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Version
                </span>
                {versions.length === 0 && activeVersion != null && (
                  <span
                    className="rounded-full px-1.5 py-0.5 font-mono text-[10px] font-medium"
                    style={{ background: "hsl(var(--tier-ok) / .15)", color: "hsl(var(--tier-ok))" }}
                  >
                    v{activeVersion} 활성
                  </span>
                )}
                {versions.map((v) =>
                  v.version === activeVersion ? (
                    <span
                      key={v.version}
                      className="rounded-full px-1.5 py-0.5 font-mono text-[10px] font-medium"
                      style={{ background: "hsl(var(--tier-ok) / .15)", color: "hsl(var(--tier-ok))" }}
                    >
                      v{v.version} 활성
                    </span>
                  ) : (
                    <button
                      key={v.version}
                      type="button"
                      onClick={() => openConfirm({ kind: "rollback", version: v.version })}
                      disabled={busy || loadingDetail}
                      title={`v${v.version}으로 롤백`}
                      className="rounded-full border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground hover:bg-secondary disabled:opacity-50"
                    >
                      v{v.version}
                    </button>
                  ),
                )}
              </div>
              <button
                type="button"
                onClick={() => openConfirm({ kind: "save" })}
                disabled={!dirty || busy || loadingDetail || !selected}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
              >
                {saveLabel}
              </button>
            </div>

            {toast && (
              <p
                className="mt-2 flex items-center gap-1.5 text-[11px]"
                style={{ color: "hsl(var(--tier-ok))" }}
              >
                <svg
                  className="h-3.5 w-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <path d="M20 6 9 17l-5-5" />
                </svg>
                {toast}
              </p>
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirm?.kind === "save"}
        title="새 버전으로 저장"
        body={saveConfirmBody}
        confirmLabel={saveLabel}
        busy={busy}
        error={confirmError}
        onConfirm={runSave}
        onClose={() => (busy ? undefined : setConfirm(null))}
      />
      <ConfirmDialog
        open={confirm?.kind === "rollback"}
        title="이 버전으로 롤백"
        body={
          confirm?.kind === "rollback" ? (
            <>
              활성 버전을 <span className="font-mono font-medium">v{confirm.version}</span> 으로
              되돌립니다. 버전 내용은 복사되지 않고 활성 포인터만 이동합니다.
            </>
          ) : null
        }
        confirmLabel="롤백"
        busy={busy}
        error={confirmError}
        onConfirm={() => confirm?.kind === "rollback" && runRollback(confirm.version)}
        onClose={() => (busy ? undefined : setConfirm(null))}
      />
    </section>
  );
}
