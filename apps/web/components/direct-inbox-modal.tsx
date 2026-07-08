// Direct Inbox 모달 (AXKG-SPEC-003 U-3) — URL + 메모 직접 입력 → POST /sources/manual.
// 상태: 닫힘/열림/제출 중/제출 실패/중복 URL. 카피/레이아웃은 21-html 시안 기준.
"use client";

import { useEffect, useState } from "react";
import {
  createManualSource,
  sourceCaseMessage,
  type Source,
} from "@/lib/api-client/sources";
import { ApiError } from "@/lib/api-client";

const NOTE_MAX = 2000;

export function DirectInboxModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  /** 저장 성공 시 새 Source 를 부모에 전달 (목록 갱신·선택). duplicate 는 error 로 처리. */
  onCreated: (source: Source) => void;
}) {
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 열릴 때마다 입력/에러 초기화
  useEffect(() => {
    if (open) {
      setUrl("");
      setNote("");
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  // Esc 로 닫기
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const trimmedUrl = url.trim();
  const noteTooLong = note.length > NOTE_MAX;
  const canSubmit = trimmedUrl.length > 0 && !noteTooLong && !submitting;

  async function handleSubmit() {
    if (!canSubmit) return;
    // 클라이언트 사전 검증 (SPEC-003 Validation: http/https URL)
    if (!/^https?:\/\/.+/i.test(trimmedUrl)) {
      setError("올바른 URL이 아닙니다.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const created = await createManualSource({
        source_url: trimmedUrl,
        raw_text: note.trim() ? note.trim() : undefined,
      });
      onCreated(created);
      onClose();
    } catch (err) {
      // DUPLICATE_SOURCE 는 "기존 항목 연결" 안내로 표시 (Case Matrix)
      setError(sourceCaseMessage(err, "저장에 실패했습니다. 잠시 후 다시 시도해 주세요."));
    } finally {
      setSubmitting(false);
    }
  }

  const isDuplicate = error != null && error.startsWith("이미 받은 URL");

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Inbox에 URL 넣기"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-xl border border-border bg-background p-5 shadow-xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold">Inbox에 URL 넣기</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-secondary"
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

        <label htmlFor="inbox-url" className="text-[11px] font-medium text-muted-foreground">
          URL
        </label>
        <input
          id="inbox-url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSubmit();
          }}
          autoFocus
          className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40"
          placeholder="https://…"
        />

        <label
          htmlFor="inbox-note"
          className="mt-3 block text-[11px] font-medium text-muted-foreground"
        >
          메모 (선택 · 2000자 이하)
        </label>
        <textarea
          id="inbox-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="mt-1 h-16 w-full resize-none rounded-md border border-input bg-background p-2 text-sm outline-none focus:ring-2 focus:ring-ring/40"
          placeholder="왜 담아두는지 한 줄"
        />
        <div className="mt-1 flex items-center justify-between">
          <span
            className={
              noteTooLong ? "text-[10px] text-destructive" : "text-[10px] text-muted-foreground"
            }
          >
            {note.length} / {NOTE_MAX}
          </span>
        </div>

        {error && (
          <p
            className={
              isDuplicate
                ? "mt-2 rounded-md bg-secondary/60 px-2.5 py-2 text-[11px] text-muted-foreground"
                : "mt-2 rounded-md px-2.5 py-2 text-[11px] text-destructive"
            }
            style={
              isDuplicate ? undefined : { background: "hsl(var(--destructive) / .08)" }
            }
          >
            {error}
          </p>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-secondary"
          >
            취소
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
          >
            {submitting ? "저장 중…" : "저장"}
          </button>
        </div>
      </div>
    </div>
  );
}
