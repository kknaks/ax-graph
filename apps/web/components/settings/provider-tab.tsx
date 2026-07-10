// AI Provider 탭 (AXKG-SPEC-007) — provider 선택 + 디폴트 실행 한도 저장 + task override CRUD + health.
// 시안(page-settings.html §section-spec-007) 레이아웃/카피를 따른다.
// 디폴트 저장(PUT /settings/ai-provider)과 override(PUT/DELETE task-overrides)는 분리된 액션.
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  EFFORTS,
  PROVIDERS,
  PROVIDER_MODELS,
  deleteTaskOverride,
  getAIProvider,
  getProviderHealth,
  putAIProvider,
  putTaskOverride,
  settingsCaseMessage,
  taskPromptKey,
  type AIProviderSettings,
  type Effort,
  type Provider,
  type ProviderHealth,
  type TaskOverride,
} from "@/lib/api-client/settings";
import { Select } from "@/components/ui/select";
import { ConfirmDialog } from "./confirm-dialog";
import { ModelSelect } from "./model-select";
import { OverrideModal, type OverrideDraft } from "./override-modal";

const BOOL_OPTIONS = [
  { value: "false", label: "false" },
  { value: "true", label: "true" },
];

/** provider의 유효 model 목록(null 제외)에 값이 있는지. 빈문자/null은 항상 유효(디폴트). */
function modelValidForProvider(model: string, provider: Provider | string): boolean {
  if (model.trim() === "") return true;
  const options = PROVIDER_MODELS[provider as Provider] ?? [];
  return options.some((o) => o.value === model);
}

interface DefaultDraft {
  provider: Provider | string;
  model: string;
  timeout_sec: string;
  resume: boolean;
  max_turns: string;
  effort: Effort | "";
}

function toDefaultDraft(s: AIProviderSettings): DefaultDraft {
  return {
    provider: s.provider,
    model: s.model ?? "",
    timeout_sec: s.options?.timeout_sec != null ? String(s.options.timeout_sec) : "",
    resume: s.options?.resume ?? false,
    max_turns: s.provider_options?.max_turns != null ? String(s.provider_options.max_turns) : "",
    effort: (s.provider_options?.effort as Effort | undefined) ?? "",
  };
}

const HEALTH_TONE: Record<string, string> = {
  available: "hsl(var(--tier-ok))",
  unavailable: "hsl(var(--tier-risk))",
  unknown: "hsl(var(--muted-foreground))",
};

export function ProviderTab() {
  const [settings, setSettings] = useState<AIProviderSettings | null>(null);
  const [draft, setDraft] = useState<DefaultDraft | null>(null);
  const [baseline, setBaseline] = useState<DefaultDraft | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [savingDefault, setSavingDefault] = useState(false);
  const [defaultError, setDefaultError] = useState<string | null>(null);
  const [defaultSaved, setDefaultSaved] = useState(false);

  const [health, setHealth] = useState<ProviderHealth[] | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [overrideDraft, setOverrideDraft] = useState<OverrideDraft | null>(null);
  const [overrideBusy, setOverrideBusy] = useState(false);
  const [overrideError, setOverrideError] = useState<string | null>(null);

  const [deleteKey, setDeleteKey] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const applySettings = useCallback((s: AIProviderSettings) => {
    setSettings(s);
    const d = toDefaultDraft(s);
    setDraft(d);
    setBaseline(d);
  }, []);

  useEffect(() => {
    let alive = true;
    getAIProvider()
      .then((s) => {
        if (alive) {
          applySettings(s);
          setLoadError(null);
        }
      })
      .catch((err) => {
        if (alive) setLoadError(settingsCaseMessage(err, "설정을 불러오지 못했습니다."));
      });
    return () => {
      alive = false;
    };
  }, [applySettings]);

  const dirty = useMemo(() => {
    if (!draft || !baseline) return false;
    return (
      draft.provider !== baseline.provider ||
      draft.model !== baseline.model ||
      draft.timeout_sec !== baseline.timeout_sec ||
      draft.resume !== baseline.resume ||
      draft.max_turns !== baseline.max_turns ||
      draft.effort !== baseline.effort
    );
  }, [draft, baseline]);

  const overrides = useMemo(() => {
    const map = settings?.task_overrides ?? {};
    return Object.entries(map).map(([key, value]) => ({ key, value: value as TaskOverride }));
  }, [settings]);

  async function saveDefault() {
    if (!draft) return;
    setSavingDefault(true);
    setDefaultError(null);
    setDefaultSaved(false);
    try {
      const options: Record<string, unknown> = { resume: draft.resume };
      if (draft.timeout_sec.trim() !== "") options.timeout_sec = Number(draft.timeout_sec);
      const providerOptions: Record<string, unknown> = {};
      if (draft.max_turns.trim() !== "") providerOptions.max_turns = Number(draft.max_turns);
      if (draft.effort) providerOptions.effort = draft.effort;
      const next = await putAIProvider({
        provider: draft.provider,
        model: draft.model.trim() === "" ? null : draft.model.trim(),
        options,
        provider_options: providerOptions,
      });
      applySettings(next);
      setDefaultSaved(true);
    } catch (err) {
      setDefaultError(settingsCaseMessage(err, "저장하지 못했습니다."));
    } finally {
      setSavingDefault(false);
    }
  }

  async function checkHealth() {
    setHealthLoading(true);
    setHealthError(null);
    try {
      const res = await getProviderHealth();
      setHealth(res.providers);
    } catch (err) {
      setHealthError(settingsCaseMessage(err, "연결 상태를 확인하지 못했습니다."));
    } finally {
      setHealthLoading(false);
    }
  }

  async function submitOverride(taskKey: string, value: TaskOverride) {
    setOverrideBusy(true);
    setOverrideError(null);
    try {
      const next = await putTaskOverride(taskKey, {
        model: value.model ?? null,
        options: value.options ?? {},
        provider_options: value.provider_options ?? {},
      });
      applySettings(next);
      setOverrideDraft(null);
    } catch (err) {
      setOverrideError(settingsCaseMessage(err, "override 를 적용하지 못했습니다."));
    } finally {
      setOverrideBusy(false);
    }
  }

  async function confirmDelete() {
    if (!deleteKey) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      const next = await deleteTaskOverride(deleteKey);
      applySettings(next);
      setDeleteKey(null);
    } catch (err) {
      setDeleteError(settingsCaseMessage(err, "override 를 삭제하지 못했습니다."));
    } finally {
      setDeleteBusy(false);
    }
  }

  function adjustMaxTurns(delta: number) {
    setDraft((d) => {
      if (!d) return d;
      const cur = d.max_turns.trim() === "" ? 0 : Number(d.max_turns);
      const nextVal = Math.min(20, Math.max(1, cur + delta));
      return { ...d, max_turns: String(nextVal) };
    });
  }

  if (loadError) {
    return (
      <section className="rounded-lg border border-border bg-card p-5 shadow-sm">
        <p className="rounded-md border border-dashed border-border bg-secondary/30 p-4 text-center text-xs text-muted-foreground">
          {loadError}
        </p>
      </section>
    );
  }

  if (!draft || !settings) {
    return (
      <section className="rounded-lg border border-border bg-card p-5 shadow-sm">
        <p className="p-4 text-center text-xs text-muted-foreground">불러오는 중…</p>
      </section>
    );
  }

  const overrideKeys = overrides.map((o) => o.key);

  return (
    <section className="space-y-3">
      <div className="rounded-lg border border-border bg-card p-4 text-card-foreground shadow-sm">
        <div className="mb-1 flex items-center gap-2">
          <svg className="h-4 w-4 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z" />
          </svg>
          <h2 className="text-sm font-semibold">
            AI Provider Settings <span className="font-normal text-muted-foreground">· SPEC-007</span>
          </h2>
        </div>
        <p className="mb-3 text-xs text-muted-foreground">
          커스텀 디폴트는 디폴트 설정에서 저장하고, task override는 행 단위로 즉시 적용합니다.
        </p>

        {/* Provider 선택 */}
        <span className="text-[11px] font-medium text-muted-foreground">Provider</span>
        <div className="mt-1.5 grid grid-cols-2 gap-3">
          {PROVIDERS.map((p) => {
            const active = draft.provider === p;
            return (
              <button
                key={p}
                type="button"
                onClick={() =>
                  setDraft((d) =>
                    d
                      ? { ...d, provider: p, model: modelValidForProvider(d.model, p) ? d.model : "" }
                      : d,
                  )
                }
                className="rounded-lg border-2 p-3 text-left transition"
                style={
                  active
                    ? { borderColor: "hsl(var(--ring))", boxShadow: "0 0 0 3px hsl(var(--ring) / .12)" }
                    : { borderColor: "hsl(var(--border))" }
                }
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium capitalize">{p}</span>
                  {p === "claude" && (
                    <span
                      className="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                      style={{ background: "hsl(var(--tier-ok) / .15)", color: "hsl(var(--tier-ok))" }}
                    >
                      default
                    </span>
                  )}
                  {active && p !== "claude" && (
                    <span className="rounded-full border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      선택됨
                    </span>
                  )}
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {p === "claude" ? "MVP seed/default provider (AXKG-DEC-003)" : "open-kknaks 지원 provider"}
                </p>
              </button>
            );
          })}
        </div>

        {/* 디폴트 설정 + override */}
        <div className="mt-4 grid grid-cols-[520px_1fr] gap-4">
          {/* 디폴트 설정 */}
          <section className="flex flex-col rounded-lg border border-border bg-secondary/25 p-4">
            <div className="mb-3">
              <h3 className="text-sm font-semibold">디폴트 설정</h3>
              <p className="mt-0.5 text-[11px] text-muted-foreground">새 AI task 기본 실행값</p>
            </div>
            <div className="grid flex-1 grid-cols-2 gap-3">
              <div className="col-span-2 rounded-md border border-border bg-background p-3">
                <label htmlFor="def-model" className="text-[11px] font-medium text-muted-foreground">model</label>
                <div className="mt-2">
                  <ModelSelect
                    provider={draft.provider as Provider}
                    value={draft.model || null}
                    onChange={(v) => setDraft((d) => (d ? { ...d, model: v ?? "" } : d))}
                  />
                </div>
              </div>
              <div className="rounded-md border border-border bg-background p-3">
                <label htmlFor="def-timeout" className="text-[11px] font-medium text-muted-foreground">options.timeout_sec</label>
                <input
                  id="def-timeout"
                  inputMode="numeric"
                  value={draft.timeout_sec}
                  onChange={(e) => setDraft((d) => (d ? { ...d, timeout_sec: e.target.value } : d))}
                  className="mt-2 w-full rounded-md border border-input bg-background px-3 py-1.5 font-mono text-xs outline-none focus:ring-2 focus:ring-ring/40"
                />
              </div>
              <div className="rounded-md border border-border bg-background p-3">
                <span className="text-[11px] font-medium text-muted-foreground">options.resume</span>
                <div className="mt-2">
                  <Select
                    value={draft.resume ? "true" : "false"}
                    onValueChange={(v) => setDraft((d) => (d ? { ...d, resume: v === "true" } : d))}
                    options={BOOL_OPTIONS}
                    ariaLabel="options.resume"
                  />
                </div>
              </div>
              <div className="rounded-md border border-border bg-background p-3">
                <span className="text-[11px] font-medium text-muted-foreground">provider_options.max_turns</span>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <button type="button" onClick={() => adjustMaxTurns(-1)} title="감소" className="grid h-7 w-7 place-items-center rounded-md border border-border text-muted-foreground hover:bg-secondary">
                    <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M5 12h14" /></svg>
                  </button>
                  <input
                    inputMode="numeric"
                    value={draft.max_turns}
                    onChange={(e) => setDraft((d) => (d ? { ...d, max_turns: e.target.value } : d))}
                    className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-center font-mono text-xs outline-none focus:ring-2 focus:ring-ring/40"
                  />
                  <button type="button" onClick={() => adjustMaxTurns(1)} title="증가" className="grid h-7 w-7 place-items-center rounded-md border border-border text-muted-foreground hover:bg-secondary">
                    <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M5 12h14M12 5v14" /></svg>
                  </button>
                </div>
                <p className="mt-1 font-mono text-[10px] text-muted-foreground">range 1-20</p>
              </div>
              <div className="rounded-md border border-border bg-background p-3">
                <span className="text-[11px] font-medium text-muted-foreground">provider_options.effort</span>
                <div className="mt-2 grid grid-cols-3 overflow-hidden rounded-md border border-border text-center text-[11px]">
                  {EFFORTS.map((e) => (
                    <button
                      key={e}
                      type="button"
                      onClick={() => setDraft((d) => (d ? { ...d, effort: e } : d))}
                      className={
                        draft.effort === e
                          ? "bg-primary px-2 py-1.5 font-medium text-primary-foreground"
                          : "px-2 py-1.5 text-muted-foreground hover:bg-secondary"
                      }
                    >
                      {e}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            {defaultError && (
              <p className="mt-3 rounded-md px-2.5 py-2 text-[11px] text-destructive" style={{ background: "hsl(var(--destructive) / .08)" }}>
                {defaultError}
              </p>
            )}
            <div className="mt-3 flex items-center justify-between">
              {defaultSaved && !dirty ? (
                <p className="flex items-center gap-1.5 text-[11px]" style={{ color: "hsl(var(--tier-ok))" }}>
                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M20 6 9 17l-5-5" /></svg>
                  저장 완료
                </p>
              ) : (
                <span />
              )}
              <button
                type="button"
                onClick={saveDefault}
                disabled={!dirty || savingDefault}
                className="whitespace-nowrap rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
              >
                {savingDefault ? "저장 중…" : "저장"}
              </button>
            </div>
          </section>

          {/* override */}
          <section className="rounded-lg border border-border bg-secondary/25 p-4">
            <div className="mb-2 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold">override</h3>
                <p className="mt-0.5 text-[11px] text-muted-foreground">task별 즉시 적용</p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setOverrideError(null);
                  setOverrideDraft({ taskKey: "", edit: false });
                }}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-[11px] font-medium hover:bg-secondary/60"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M5 12h14M12 5v14" /></svg>
                override 추가
              </button>
            </div>

            <div className="grid grid-cols-[1.1fr_.9fr_.7fr_.6fr_.5fr_.55fr_.65fr_.7fr] gap-2 text-[10px] font-medium text-muted-foreground">
              <div>task_type</div>
              <div>prompt_key</div>
              <div>model</div>
              <div>timeout</div>
              <div>resume</div>
              <div>turns</div>
              <div>effort</div>
              <div className="text-right">actions</div>
            </div>

            {overrides.length === 0 ? (
              <p className="mt-2 rounded-md border border-dashed border-border bg-background/60 px-3 py-4 text-center text-[11px] text-muted-foreground">
                등록된 override 가 없습니다. 우측 상단 “override 추가”로 task별 실행 한도를 지정하세요.
              </p>
            ) : (
              <div className="mt-1 space-y-1.5">
                {overrides.map(({ key, value }) => (
                  <div
                    key={key}
                    className="grid grid-cols-[1.1fr_.9fr_.7fr_.6fr_.5fr_.55fr_.65fr_.7fr] items-center gap-2 rounded-md border border-border bg-background px-2.5 py-2 text-[11px]"
                  >
                    <span className="truncate font-mono" title={key}>{key}</span>
                    <span className="truncate font-mono text-muted-foreground">{taskPromptKey(key) ?? "-"}</span>
                    <span className="font-mono text-muted-foreground">{value.model ?? "-"}</span>
                    <span className="font-mono text-muted-foreground">{value.options?.timeout_sec ?? "-"}</span>
                    <span className="font-mono text-muted-foreground">{value.options?.resume != null ? String(value.options.resume) : "-"}</span>
                    <span className="font-mono text-muted-foreground">{value.provider_options?.max_turns ?? "-"}</span>
                    <span className="rounded-md bg-secondary px-2 py-0.5 text-center font-mono text-[10px]">{value.provider_options?.effort ?? "-"}</span>
                    <span className="flex justify-end gap-1">
                      <button
                        type="button"
                        onClick={() => {
                          setOverrideError(null);
                          setOverrideDraft({ taskKey: key, initial: value, edit: true });
                        }}
                        className="rounded-md px-2 py-1 text-[10px] font-medium hover:bg-secondary"
                      >
                        수정
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setDeleteError(null);
                          setDeleteKey(key);
                        }}
                        className="rounded-md px-2 py-1 text-[10px] font-medium text-muted-foreground hover:bg-secondary"
                      >
                        삭제
                      </button>
                    </span>
                  </div>
                ))}
              </div>
            )}
            <p className="mt-2 font-mono text-[10px] text-muted-foreground">
              PUT/DELETE /settings/ai-provider/task-overrides/{"{task_key}"}
            </p>
          </section>
        </div>

        {/* health */}
        <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
          {healthError && <span className="mr-auto text-[11px] text-destructive">{healthError}</span>}
          {health && (
            <div className="mr-auto flex flex-wrap items-center gap-2 text-[11px]">
              {health.map((h) => (
                <span key={h.provider} className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1" style={{ color: HEALTH_TONE[h.status] ?? "inherit" }} title={h.message ?? undefined}>
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: HEALTH_TONE[h.status] ?? "hsl(var(--muted-foreground))" }} />
                  <span className="font-medium capitalize text-foreground">{h.provider}</span> {h.status}
                </span>
              ))}
            </div>
          )}
          <button
            type="button"
            onClick={checkHealth}
            disabled={healthLoading}
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary/60 disabled:opacity-60"
          >
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>
            {healthLoading ? "확인 중…" : "연결 확인"}
          </button>
        </div>
      </div>

      <OverrideModal
        open={overrideDraft != null}
        draft={overrideDraft}
        provider={(baseline?.provider ?? draft.provider) as Provider}
        existingKeys={overrideKeys}
        busy={overrideBusy}
        error={overrideError}
        onClose={() => (overrideBusy ? undefined : setOverrideDraft(null))}
        onSubmit={submitOverride}
      />

      <ConfirmDialog
        open={deleteKey != null}
        title="override 삭제"
        body={
          deleteKey ? (
            <>
              <span className="font-mono font-medium">{deleteKey}</span> 의 task override 를 삭제합니다.
              이후 이 task 는 디폴트 실행 한도를 사용합니다.
            </>
          ) : null
        }
        confirmLabel="삭제"
        tone="danger"
        busy={deleteBusy}
        error={deleteError}
        onConfirm={confirmDelete}
        onClose={() => (deleteBusy ? undefined : setDeleteKey(null))}
      />
    </section>
  );
}
