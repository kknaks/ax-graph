// Direct Inbox 모달 (AXKG-SPEC-003 U-3 · SPEC-014 intake) — 탭형 intake:
//  [url]  URL + 메모 → POST /sources/manual (source_channel=manual)
//  [md]   .md 파일 업로드 → POST /sources/upload (source_channel=upload)
//  [docx] .docx 파일 업로드 → POST /sources/upload (docx 텍스트 추출, SPEC-014 팬아웃 입력)
// 메모(회사명 등)는 탭 무관 항상 표시 · 항상 요약 컨텍스트로 동반된다(SPEC-003 intake, SPEC-014 corp 바인딩).
// 상태: 닫힘/열림/제출 중/제출 실패/중복 URL/파일 형식 오류. 카피/레이아웃은 21-html 시안 기준.
// 이 표면은 admin 전용(소스 Inbox 라우트 가드로 보호) — 여기서 별도 권한 분기는 하지 않는다.
"use client";

import { useEffect, useRef, useState } from "react";
import {
  createManualSource,
  createUploadSource,
  sourceCaseMessage,
  type Source,
} from "@/lib/api-client/sources";

const NOTE_MAX = 2000;

// 탭 정의 — url(수동 URL) / md / docx. md·docx 는 확장자만 다르고 같은 업로드 경로.
type IntakeTab = "url" | "md" | "docx";
const TABS: { key: IntakeTab; label: string; ext?: string }[] = [
  { key: "url", label: "URL" },
  { key: "md", label: "md 파일", ext: ".md" },
  { key: "docx", label: "docx 파일", ext: ".docx" },
];
const UNSUPPORTED_UPLOAD_MESSAGE = "선택한 탭 형식의 파일만 업로드할 수 있습니다.";

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
  const [tab, setTab] = useState<IntakeTab>("url");
  const [url, setUrl] = useState("");
  // 메모(회사명 등) — 탭 공통, 전환해도 유지한다(SPEC-014 corp 바인딩 컨텍스트).
  const [note, setNote] = useState("");
  // 업로드 대상 파일(md·docx 탭). 탭 전환 시 초기화.
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // 열릴 때마다 입력/에러 초기화
  useEffect(() => {
    if (open) {
      setTab("url");
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

  const activeTab = TABS.find((t) => t.key === tab)!;
  const isUpload = tab === "md" || tab === "docx";
  const trimmedUrl = url.trim();
  const noteTooLong = note.length > NOTE_MAX;
  const canSubmit =
    !submitting &&
    !noteTooLong &&
    (isUpload ? file != null : trimmedUrl.length > 0);

  // 탭 전환 — 파일/URL/에러는 리셋, 메모(회사명 등)는 유지.
  function switchTab(next: IntakeTab) {
    if (next === tab) return;
    setTab(next);
    setFile(null);
    setError(null);
    if (next === "url") setUrl("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  // 파일 선택 → 클라 사전 검증(활성 탭 확장자). 형식 오류면 파일을 담지 않고 오류 표시.
  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    if (!picked) return;
    const ext = activeTab.ext;
    if (ext && !picked.name.toLowerCase().endsWith(ext)) {
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
      if (isUpload && file) {
        // md·docx 업로드 — 메모(회사명 등)를 note 로 동반. 서버도 UNSUPPORTED_UPLOAD_TYPE(422)로 방어.
        created = await createUploadSource(file, note);
      } else {
        // URL 입력 — 클라이언트 사전 검증 (SPEC-003 Validation: http/https URL)
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

        {/* 탭 스위처 — url · md · docx (SPEC-003 U-3 탭형 intake) */}
        <div
          role="tablist"
          aria-label="intake 방식"
          className="mb-3 inline-flex w-full rounded-md border border-border bg-secondary/40 p-0.5"
        >
          {TABS.map((t) => {
            const on = t.key === tab;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => switchTab(t.key)}
                className={
                  on
                    ? "flex-1 rounded-[5px] bg-background px-3 py-1.5 text-xs font-medium text-foreground shadow-sm"
                    : "flex-1 rounded-[5px] px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
                }
              >
                {t.label}
              </button>
            );
          })}
        </div>

        {/* URL 탭 입력 */}
        {tab === "url" && (
          <>
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
          </>
        )}

        {/* md·docx 업로드 탭 */}
        {isUpload && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept={activeTab.ext}
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
                {activeTab.ext} 파일 업로드
              </button>
            )}
            <p className="mt-1 text-[10px] text-muted-foreground">
              허용 형식: {activeTab.ext} 파일만
              {tab === "docx" && " · 본문 텍스트만 추출됩니다"}
            </p>
          </>
        )}

        {/* 메모(회사명 등) — 탭 공통, 항상 표시. 요약 컨텍스트로 동반된다(SPEC-003/014). */}
        <label
          htmlFor="inbox-note"
          className="mt-3 block text-[11px] font-medium text-muted-foreground"
        >
          메모 (회사명 등 · 선택 · 2000자 이하)
        </label>
        <textarea
          id="inbox-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="mt-1 h-16 w-full resize-none rounded-md border border-input bg-background p-2 text-sm outline-none focus:ring-2 focus:ring-ring/40"
          placeholder="회사명 등 — 요약·분류에 함께 참고됩니다 (예: 더에스씨)"
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
