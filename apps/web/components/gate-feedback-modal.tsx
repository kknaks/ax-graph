// 공통 피드백 모달 (AXKG-SPEC-002 U-2) — 요약 초안 ① · 분류 게이트 ② · 문서화 게이트 ③ 공용.
// 대상 라벨 + 현재 버전 badge + 자연어 입력(10자 이상) → [취소] / [재생성].
// 세션 resume 재생성이므로 원문·지침 재전송 없이 피드백만 보낸다(호출은 부모가 배선).
//
// 문서화 게이트(③) 대상일 때만: 보조 옵션 "이 destination이 아님"(SPEC-004 U-4)으로 재분류 모드 전환.
// 재분류 모드는 일반 피드백(초안 재생성)과 UX 를 분리한다 — 이유 필수, 제출 = [재분류 요청].
"use client";

import { useEffect, useRef, useState } from "react";

const FEEDBACK_MIN = 10;
const FEEDBACK_MAX = 4000;
const REASON_MAX = 2000;

/** 모달이 겨냥하는 대상(요약 초안 또는 특정 게이트). 부모가 제출을 배선한다. */
export interface FeedbackTarget {
  /** 대상 라벨 (시안: "요약 초안 ①" / "분류 게이트 ②" / "문서화 승인 게이트 ③"). */
  label: string;
  /** 현재 버전 badge (시안: "v1" / "v2"). */
  version: string;
  /** [재생성] 버튼 문구 (요약=다시 요약, 게이트=재생성). */
  submitLabel: string;
  /** 문서화 게이트(③)만 true — "이 destination이 아님" 보조 옵션 노출(SPEC-004 U-4). */
  allowReclassify?: boolean;
}

export function GateFeedbackModal({
  open,
  target,
  busy,
  error,
  onClose,
  onSubmit,
  onReclassify,
}: {
  open: boolean;
  target: FeedbackTarget | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  /** 유효한 피드백 본문(10자 이상)으로 제출. */
  onSubmit: (body: string) => void;
  /** "이 destination이 아님" 재분류 요청(이유 필수). 문서화 게이트 대상일 때만 호출된다. */
  onReclassify?: (reason: string) => void;
}) {
  const [body, setBody] = useState("");
  const [reason, setReason] = useState("");
  const [mode, setMode] = useState<"feedback" | "reclassify">("feedback");
  const busyRef = useRef(false);
  busyRef.current = busy;

  useEffect(() => {
    if (open) {
      setBody("");
      setReason("");
      setMode("feedback");
    }
  }, [open, target?.label]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busyRef.current) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !target) return null;

  const reclassifyMode = mode === "reclassify";
  const trimmed = body.trim();
  const reasonTrimmed = reason.trim();
  const tooShort = trimmed.length > 0 && trimmed.length < FEEDBACK_MIN;
  const canSubmitFeedback =
    trimmed.length >= FEEDBACK_MIN && body.length <= FEEDBACK_MAX && !busy;
  // 재분류: 이유 필수(SPEC-004 Validation). 비면 클라에서 막아 MISSING_NOT_THIS_DESTINATION_REASON 방지.
  const canSubmitReclassify =
    reasonTrimmed.length > 0 && reason.length <= REASON_MAX && !busy && !!onReclassify;
  const canSubmit = reclassifyMode ? canSubmitReclassify : canSubmitFeedback;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="피드백 남기기"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-xl border border-border bg-background p-5 shadow-xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold">
            {reclassifyMode ? "재분류 요청 · 이 destination이 아님" : "피드백 남기기"}
          </h3>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label="닫기"
            className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-secondary disabled:opacity-50"
          >
            <svg
              className="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* 대상 게이트 / 현재 버전 (시안: data-gate-label / data-gate-version) */}
        <div className="flex items-center gap-2 rounded-md bg-secondary/50 px-2.5 py-1.5 text-[11px]">
          <span className="font-medium text-foreground">대상</span>
          <span className="text-muted-foreground">{target.label}</span>
          <span className="ml-auto rounded-full bg-secondary px-1.5 py-0.5 font-mono text-[10px] font-medium text-secondary-foreground">
            {target.version}
          </span>
        </div>

        {reclassifyMode ? (
          <>
            {/* 재분류 모드 (SPEC-004 S-3): 이유 필수 → 분류 게이트(②) 재검토로 되돌림 */}
            <p className="mt-3 rounded-md border border-dashed border-border bg-secondary/40 px-2.5 py-2 text-[11px] leading-relaxed text-muted-foreground">
              이 destination이 아니라고 판단되면 이유와 함께 재분류를 요청합니다. 분류 게이트(②)가
              다시 검토 상태로 열리고, 이 문서화 게이트는 재분류 요청됨으로 표시됩니다.
            </p>
            <label
              htmlFor="gate-reclassify-reason"
              className="mt-3 block text-[11px] font-medium text-muted-foreground"
            >
              이 destination이 아닌 이유 (필수)
            </label>
            <textarea
              id="gate-reclassify-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={busy}
              rows={4}
              maxLength={REASON_MAX}
              placeholder="예: resource(참고자료)가 아니라 실제 작업 중인 project 문서로 봐야 합니다."
              className="scroll-thin mt-1 w-full resize-none rounded-md border border-input bg-background p-2 text-sm leading-relaxed outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
            />
            <div className="mt-1 flex items-center justify-between">
              {reasonTrimmed.length === 0 ? (
                <span className="text-[10px] text-muted-foreground">
                  재분류 이유를 입력해 주세요.
                </span>
              ) : (
                <span className="font-mono text-[10px] text-muted-foreground">
                  {reason.length}/{REASON_MAX}
                </span>
              )}
              <button
                type="button"
                onClick={() => setMode("feedback")}
                disabled={busy}
                className="text-[10px] font-medium text-muted-foreground hover:text-foreground disabled:opacity-50"
              >
                ← 일반 피드백으로
              </button>
            </div>
          </>
        ) : (
          <>
            <label
              htmlFor="gate-feedback-body"
              className="mt-3 block text-[11px] font-medium text-muted-foreground"
            >
              무엇이 잘못됐나요 · 원하는 방향 ({FEEDBACK_MIN}자 이상)
            </label>
            <textarea
              id="gate-feedback-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              disabled={busy}
              rows={4}
              maxLength={FEEDBACK_MAX}
              placeholder="예: 요약이 핵심을 놓쳤어요, 방법론 위주로 다시 / 도구가 아니라 사례로 분류해 주세요"
              className="scroll-thin mt-1 w-full resize-none rounded-md border border-input bg-background p-2 text-sm leading-relaxed outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
            />

            <div className="mt-1 flex items-center justify-between">
              {tooShort ? (
                <span className="text-[10px] text-muted-foreground">
                  {FEEDBACK_MIN}자 이상 적어주세요.
                </span>
              ) : (
                <span className="font-mono text-[10px] text-muted-foreground">
                  {body.length}/{FEEDBACK_MAX}
                </span>
              )}
            </div>

            {/* SPEC-004 U-4: 문서화 게이트(③)에서만 노출되는 보조 옵션. 분류/요약 모달엔 없음. */}
            {target.allowReclassify && onReclassify && (
              <button
                type="button"
                onClick={() => setMode("reclassify")}
                disabled={busy}
                className="mt-2 rounded-md border border-border px-2 py-1 text-[10px] font-medium text-muted-foreground hover:bg-secondary disabled:opacity-50"
              >
                이 destination이 아님
              </button>
            )}
          </>
        )}

        {error && (
          <p
            className="mt-2 rounded-md px-2.5 py-2 text-[11px] text-destructive"
            style={{ background: "hsl(var(--destructive) / .08)" }}
          >
            {error}
          </p>
        )}

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
            onClick={() => {
              if (!canSubmit) return;
              if (reclassifyMode) onReclassify?.(reasonTrimmed);
              else onSubmit(trimmed);
            }}
            disabled={!canSubmit}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
          >
            {busy ? "요청 중…" : reclassifyMode ? "재분류 요청" : target.submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
