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
  type TaskOverride,
} from "@/lib/api-client/settings";

export interface OverrideDraft {
  taskKey: string;
  /** 수정 모드면 기존 override 값(폼 프리필). */
  initial?: TaskOverride;
  /** true면 task 선택 불가(수정). */
  edit: boolean;
}

export function OverrideModal({
  open,
  draft,
  existingKeys,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  open: boolean;
  draft: OverrideDraft | null;
  /** 이미 override 가 있는 task_key(추가 모드에서 제외). */
  existingKeys: string[];
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (taskKey: string, value: TaskOverride) => void;
}) {
  const [taskKey, setTaskKey] = useState("");
  const [model, setModel] = useState("");
  const [timeout, setTimeoutSec] = useState("");
  const [resume, setResume] = useState(false);
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
    const ov = draft.initial;
    setModel(ov?.model ?? "");
    setTimeoutSec(ov?.options?.timeout_sec != null ? String(ov.options.timeout_sec) : "");
    setResume(ov?.options?.resume ?? false);
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
    // 부분 override 허용 — 비운 필드는 보내지 않는다(BE가 값 있는 필드만 검증).
    const options: Record<string, unknown> = {};
    if (timeout.trim() !== "") options.timeout_sec = Number(timeout);
    options.resume = resume;
    const providerOptions: Record<string, unknown> = {};
    if (maxTurns.trim() !== "") providerOptions.max_turns = Number(maxTurns);
    if (effort) providerOptions.effort = effort;

    const value: TaskOverride = { options, provider_options: providerOptions };
    if (model.trim() !== "") value.model = model.trim();
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
                ? "task별 실행 한도를 즉시 갱신합니다."
                : "등록된 task definition 중 override가 없는 항목을 선택합니다."}
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
                  <select
                    id="ov-task"
                    value={taskKey}
                    onChange={(e) => setTaskKey(e.target.value)}
                    disabled={busy}
                    className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
                  >
                    {available.map((d) => (
                      <option key={d.key} value={d.key}>
                        {d.key}
                      </option>
                    ))}
                  </select>
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
                <input
                  id="ov-model"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  disabled={busy}
                  placeholder="비워둠 (디폴트 사용)"
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
                />
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
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
                />
              </div>
              <div>
                <label htmlFor="ov-resume" className="text-[11px] font-medium text-muted-foreground">
                  options.resume
                </label>
                <select
                  id="ov-resume"
                  value={resume ? "true" : "false"}
                  onChange={(e) => setResume(e.target.value === "true")}
                  disabled={busy}
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-xs outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
                >
                  <option value="false">false</option>
                  <option value="true">true</option>
                </select>
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
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
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
