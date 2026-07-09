// 설정 공통 확인 모달 (AXKG-SPEC-007/009/010 U — 저장/롤백은 확인 후 반영).
// 시안(page-settings.html) Dialog 톤을 따른다. Esc/배경 클릭으로 닫힘(busy 중엔 잠금).
"use client";

import { useEffect, useRef, type ReactNode } from "react";

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  busy,
  error,
  tone = "default",
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  busy: boolean;
  error?: string | null;
  tone?: "default" | "danger";
  onConfirm: () => void;
  onClose: () => void;
}) {
  const busyRef = useRef(false);
  busyRef.current = busy;

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busyRef.current) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-xl border border-border bg-background p-5 shadow-xl">
        <h3 className="text-sm font-semibold">{title}</h3>
        <div className="mt-2 text-xs leading-relaxed text-muted-foreground">{body}</div>

        {error && (
          <p
            className="mt-3 rounded-md px-2.5 py-2 text-[11px] text-destructive"
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
            onClick={onConfirm}
            disabled={busy}
            className={
              tone === "danger"
                ? "rounded-md bg-destructive px-3 py-1.5 text-sm font-medium text-destructive-foreground hover:opacity-90 disabled:opacity-60"
                : "rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
            }
          >
            {busy ? "처리 중…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
