// task override 추가/수정 모달 (AXKG-SPEC-007 U-3 · 시안 override Dialog).
// 생성/수정 즉시 PUT /settings/ai-provider/task-overrides/{task_key} 로 적용된다
// (디폴트 설정 저장과 무관). provider는 override 대상이 아니라 model/options/provider_options만.
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  EFFORTS,
  TASK_DEFINITIONS,
  taskPromptKey,
  type Effort,
  type Provider,
  type TaskOverride,
} from "@/lib/api-client/settings";
import { Select } from "@/components/ui/select";
import { ModelSelect } from "./model-select";

// resume은 3-상태: "" = 상속(override에 안 넣음) / "true" / "false".
const RESUME_OPTIONS = [
  { value: "", label: "상속" },
  { value: "false", label: "false" },
  { value: "true", label: "true" },
];

export interface OverrideDraft {
  taskKey: string;
  /** 수정 모드면 기존 override 값(폼 프리필). */
  initial?: TaskOverride;
  /** true면 task 선택 불가(수정). */
  edit: boolean;
}

/** 상속(미설정) 필드 placeholder에 보여줄 전역 기본값(효과값의 FE-가시 부분). */
export interface OverrideDefaults {
  timeout_sec?: number | null;
  max_turns?: number | null;
}

type ResumeState = "" | "true" | "false";

/** 상속 placeholder 문구 — 전역 기본이 있으면 값과 함께, 없으면 "상속". */
function inheritHint(value: number | null | undefined): string {
  return value != null ? `상속 (전역 ${value})` : "상속";
}

export function OverrideModal({
  open,
  draft,
  provider,
  existingKeys,
  defaults,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  open: boolean;
  draft: OverrideDraft | null;
  /** 전역(저장된) provider — override는 provider를 못 바꾸므로 model 목록 필터에 사용. */
  provider: Provider;
  /** 이미 override 가 있는 task_key(추가 모드에서 제외). */
  existingKeys: string[];
  /** 상속 필드 placeholder용 전역 기본값(선택). */
  defaults?: OverrideDefaults;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (taskKey: string, value: TaskOverride) => void;
}) {
  const [taskKey, setTaskKey] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [timeout, setTimeoutSec] = useState("");
  const [resume, setResume] = useState<ResumeState>("");
  const [maxTurns, setMaxTurns] = useState("");
  const [effort, setEffort] = useState<Effort | "">("");
  const busyRef = useRef(false);
  busyRef.current = busy;

  // 추가 모드에서 선택 가능한 task(아직 override 없는 것).
  const available = useMemo(
    () => TASK_DEFINITIONS.filter((d) => !existingKeys.includes(d.key)),
    [existingKeys],
  );

  useEffect(() => {
    if (!open || !draft) return;
    const initialKey = draft.edit ? draft.taskKey : draft.taskKey || available[0]?.key || "";
    setTaskKey(initialKey);
    // 저장돼 있던 키만 값으로, 없던 키는 상속(빈 상태)으로 프리필 — 편집이 미설정 필드를
    // 효과값으로 굳혀 저장하는 사고를 막는다(PLAN-010-T-014).
    const ov = draft.initial;
    setModel(ov?.model ?? null);
    setTimeoutSec(ov?.options?.timeout_sec != null ? String(ov.options.timeout_sec) : "");
    setResume(ov?.options?.resume != null ? (ov.options.resume ? "true" : "false") : "");
    setMaxTurns(ov?.provider_options?.max_turns != null ? String(ov.provider_options.max_turns) : "");
    setEffort((ov?.provider_options?.effort as Effort | undefined) ?? "");
  }, [open, draft, available]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busyRef.current) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !draft) return null;

  const promptKey = taskPromptKey(taskKey);
  const canSubmit = !!taskKey && !busy && (draft.edit || available.length > 0);

  function handleSubmit() {
    if (!taskKey) return;
    // 사용자가 명시적으로 설정한 필드만 담는다 — 미설정(상속) 필드는 키/래퍼 자체를 제외한다.
    // resolution `_merge`가 키 단위라 담긴 키만 definition/global을 덮으므로, 이렇게 해야
    // 안 만진 필드가 definition 값(예: 문서화 timeout 600)을 덮어쓰지 않는다(PLAN-010-T-014).
    const options: Record<string, unknown> = {};
    if (timeout.trim() !== "") options.timeout_sec = Number(timeout);
    if (resume !== "") options.resume = resume === "true";
    const providerOptions: Record<string, unknown> = {};
    if (maxTurns.trim() !== "") providerOptions.max_turns = Number(maxTurns);
    if (effort) providerOptions.effort = effort;

    const value: TaskOverride = {};
    if (model && model.trim() !== "") value.model = model.trim();
    if (Object.keys(options).length > 0) value.options = options;
    if (Object.keys(providerOptions).length > 0) value.provider_options = providerOptions;
    onSubmit(taskKey, value);
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={draft.edit ? "override 수정" : "override 생성"}
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div className="w-full max-w-2xl rounded-xl border border-border bg-background p-5 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold">{draft.edit ? "override 수정" : "override 생성"}</h3>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {draft.edit
                ? "설정한 필드만 override로 저장됩니다. 비운 필드는 상속(전역→definition)합니다."
                : "설정한 필드만 override됩니다. 비운 필드는 상속(전역→definition)합니다."}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label="닫기"
            className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-secondary disabled:opacity-50"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {!draft.edit && available.length === 0 ? (
          <p className="rounded-md border border-dashed border-border bg-secondary/40 px-3 py-4 text-center text-xs text-muted-foreground">
            모든 등록된 task 에 이미 override 가 있습니다. 기존 override 행에서 수정하세요.
          </p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="ov-task" className="text-[11px] font-medium text-muted-foreground">
                  task definition
                </label>
                {draft.edit ? (
                  <div className="mt-1 rounded-md border border-input bg-secondary/50 px-3 py-2 font-mono text-xs">
                    {taskKey}
                  </div>
                ) : (
                  <div className="mt-1">
                    <Select
                      value={taskKey}
                      onValueChange={setTaskKey}
                      options={available.map((d) => ({ value: d.key, label: d.key }))}
                      disabled={busy}
                      ariaLabel="task definition"
                      className="font-mono"
                    />
                  </div>
                )}
              </div>
              <div>
                <label className="text-[11px] font-medium text-muted-foreground">prompt</label>
                <div className="mt-1 rounded-md border border-input bg-secondary/50 px-3 py-2 font-mono text-xs text-muted-foreground">
                  {promptKey ?? "—"}
                </div>
              </div>
              <div className="col-span-2">
                <label htmlFor="ov-model" className="text-[11px] font-medium text-muted-foreground">
                  model override (비우면 디폴트 사용)
                </label>
                <div className="mt-1">
                  <ModelSelect
                    provider={provider}
                    value={model}
                    onChange={setModel}
                    disabled={busy}
                  />
                </div>
              </div>
              <div>
                <label htmlFor="ov-timeout" className="text-[11px] font-medium text-muted-foreground">
                  options.timeout_sec (30~3600)
                </label>
                <input
                  id="ov-timeout"
                  inputMode="numeric"
                  value={timeout}
                  onChange={(e) => setTimeoutSec(e.target.value)}
                  disabled={busy}
                  placeholder={inheritHint(defaults?.timeout_sec)}
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs outline-none placeholder:font-sans placeholder:text-muted-foreground focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
                />
              </div>
              <div>
                <span className="text-[11px] font-medium text-muted-foreground">
                  options.resume
                </span>
                <div className="mt-1">
                  <Select
                    value={resume}
                    onValueChange={(v) => setResume(v as ResumeState)}
                    options={RESUME_OPTIONS}
                    disabled={busy}
                    ariaLabel="options.resume"
                  />
                </div>
              </div>
              <div>
                <label htmlFor="ov-maxturns" className="text-[11px] font-medium text-muted-foreground">
                  provider_options.max_turns (1~20)
                </label>
                <input
                  id="ov-maxturns"
                  inputMode="numeric"
                  value={maxTurns}
                  onChange={(e) => setMaxTurns(e.target.value)}
                  disabled={busy}
                  placeholder={inheritHint(defaults?.max_turns)}
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs outline-none placeholder:font-sans placeholder:text-muted-foreground focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
                />
              </div>
              <div>
                <span className="text-[11px] font-medium text-muted-foreground">
                  provider_options.effort
                </span>
                <div className="mt-1 grid grid-cols-3 overflow-hidden rounded-md border border-border text-center text-[11px]">
                  {EFFORTS.map((e) => (
                    <button
                      key={e}
                      type="button"
                      onClick={() => setEffort(effort === e ? "" : e)}
                      disabled={busy}
                      className={
                        effort === e
                          ? "bg-primary px-2 py-1.5 font-medium text-primary-foreground"
                          : "px-2 py-1.5 text-muted-foreground hover:bg-secondary disabled:opacity-60"
                      }
                    >
                      {e}
                    </button>
                  ))}
                </div>
                <p className="mt-1 text-[10px] text-muted-foreground">미선택 = 상속 (다시 눌러 해제)</p>
              </div>
            </div>

            {error && (
              <p
                className="mt-3 rounded-md px-2.5 py-2 text-[11px] text-destructive"
                style={{ background: "hsl(var(--destructive) / .08)" }}
              >
                {error}
              </p>
            )}

            <p className="mt-3 font-mono text-[10px] text-muted-foreground">
              PUT /settings/ai-provider/task-overrides/{taskKey || "{task_key}"} — 저장 즉시 적용됩니다.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={busy}
                className="rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-secondary disabled:opacity-50"
              >
                취소
              </button>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!canSubmit}
                className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
              >
                {busy ? "적용 중…" : draft.edit ? "override 수정" : "override 생성"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
