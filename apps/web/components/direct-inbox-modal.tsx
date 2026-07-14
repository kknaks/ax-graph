// Direct Inbox 모달 (AXKG-SPEC-003 U-3) — 같은 모달에서 두 입력 방식:
//  ① URL + 메모 → POST /sources/manual (source_channel=manual)
//  ② md 파일 업로드 → POST /sources/upload (source_channel=upload, WORK-010)
// 상태: 닫힘/열림/제출 중/제출 실패/중복 URL/파일 형식 오류. 카피/레이아웃은 21-html 시안 기준.
// 이 표면은 admin 전용(소스 Inbox 라우트 가드로 보호) — 여기서 별도 권한 분기는 하지 않는다.
"use client";

import { useEffect, useRef, useState } from "react";
import {
  createManualSource,
  createUploadSource,
  isSupportedUploadFile,
  sourceCaseMessage,
  UPLOAD_ACCEPT_EXT,
  type Source,
} from "@/lib/api-client/sources";

const NOTE_MAX = 2000;
const UNSUPPORTED_UPLOAD_MESSAGE = "md 파일만 업로드할 수 있습니다.";

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
  // md 업로드 대상 파일 (선택 시 URL 대신 업로드 경로로 제출). WORK-010.
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // 열릴 때마다 입력/에러 초기화
  useEffect(() => {
    if (open) {
      setUrl("");
      setNote("");
      setFile(null);
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
  // 파일이 선택되면 업로드 경로, 아니면 URL 경로. 둘 중 하나는 유효해야 제출 가능.
  const canSubmit =
    !submitting &&
    (file != null || (trimmedUrl.length > 0 && !noteTooLong));

  // 파일 선택 → 클라 사전 검증(.md). 형식 오류면 파일을 담지 않고 오류 표시(SPEC-003 U-3).
  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    if (!picked) return;
    if (!isSupportedUploadFile(picked)) {
      setFile(null);
      setError(UNSUPPORTED_UPLOAD_MESSAGE);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    setFile(picked);
    setError(null);
  }

  function clearFile() {
    setFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      let created: Source;
      if (file) {
        // ② md 업로드 — 서버도 UNSUPPORTED_UPLOAD_TYPE(422)로 방어.
        created = await createUploadSource(file);
      } else {
        // ① URL 입력 — 클라이언트 사전 검증 (SPEC-003 Validation: http/https URL)
        if (!/^https?:\/\/.+/i.test(trimmedUrl)) {
          setError("올바른 URL이 아닙니다.");
          setSubmitting(false);
          return;
        }
        created = await createManualSource({
          source_url: trimmedUrl,
          raw_text: note.trim() ? note.trim() : undefined,
        });
      }
      onCreated(created);
      onClose();
    } catch (err) {
      // DUPLICATE_SOURCE / UNSUPPORTED_UPLOAD_TYPE 등은 Case Matrix 문구로 표시.
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
      aria-label="Inbox에 넣기"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-xl border border-border bg-background p-5 shadow-xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold">Inbox에 넣기</h3>
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
          disabled={file != null}
          className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-50"
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
          disabled={file != null}
          className="mt-1 h-16 w-full resize-none rounded-md border border-input bg-background p-2 text-sm outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-50"
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

        {/* 구분선 — URL 대신 md 파일 업로드 (WORK-010 U-3) */}
        <div className="my-3 flex items-center gap-2 text-[10px] text-muted-foreground">
          <span className="h-px flex-1 bg-border" />
          또는
          <span className="h-px flex-1 bg-border" />
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept={UPLOAD_ACCEPT_EXT}
          onChange={handleFileChange}
          className="hidden"
        />
        {file ? (
          <div className="flex items-center gap-2 rounded-md border border-input bg-secondary/40 px-3 py-2">
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
              <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" />
              <path d="M14 2v4a2 2 0 0 0 2 2h4" />
            </svg>
            <span className="min-w-0 flex-1 truncate text-sm">{file.name}</span>
            <button
              type="button"
              onClick={clearFile}
              aria-label="파일 선택 취소"
              className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-secondary"
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
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-input px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-secondary/60"
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
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <path d="M17 8l-5-5-5 5" />
              <path d="M12 3v12" />
            </svg>
            md 파일 업로드
          </button>
        )}
        <p className="mt-1 text-[10px] text-muted-foreground">
          허용 형식: {UPLOAD_ACCEPT_EXT} 파일만
        </p>

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
