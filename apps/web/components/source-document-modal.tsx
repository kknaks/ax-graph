// 요약 초안 문서보기 모달 (AXKG-SPEC-003 U-2 · T-015 개정본).
// summarized source 의 요약 초안(title/summary/keywords/source_type + 원본 메타)을 문서(md) 형태로 렌더하고,
// 사용자가 [피드백](자연어 재요약) 또는 [분류](분류 게이트 진입) 중 하나를 선택한다.
// 요약은 자동으로 분류로 넘어가지 않는다 — summarized 는 사용자 선택 대기 상태.
// 직접 인라인 편집·저장은 이번 범위 아님(피드백=자연어로 AI 재생성). 분류 게이트 화면은 WP3 범위 밖.
"use client";

import { useEffect, useRef, useState } from "react";
import {
  enterClassificationGate,
  summaryFeedback,
  sourceCaseMessage,
  STATUS_LABELS,
  type ClassificationGateEntry,
  type Source,
} from "@/lib/api-client/sources";
import { formatDateTime } from "@/lib/format";

const FEEDBACK_MIN = 10;
const FEEDBACK_MAX = 1000;

/** 요약 초안을 문서 identity(frontmatter) 로 보여주기 위한 md 미리보기 문자열. */
function frontmatter(source: Source): string {
  const s = source.summary_payload;
  const kws = s?.keywords?.length ? `[${s.keywords.join(", ")}]` : "[]";
  return [
    "---",
    "type: source",
    s?.title ? `title: "${s.title}"` : 'title: ""',
    `source_type: ${s?.material_type ?? "unknown"}`,
    `keywords: ${kws}`,
    `source: ${source.source_url}`,
    "---",
  ].join("\n");
}

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[88px_1fr] gap-2 py-1.5">
      <div className="text-[11px] font-medium text-muted-foreground">{label}</div>
      <div className="min-w-0 break-words text-xs">{children}</div>
    </div>
  );
}

export function SourceDocumentModal({
  open,
  source,
  onClose,
  onSummaryUpdated,
  onClassifyEntered,
}: {
  open: boolean;
  source: Source | null;
  onClose: () => void;
  /** [피드백] 성공 → 재요약(summarizing) 이 시작된 Source 를 부모에 전달(목록/상세 갱신). */
  onSummaryUpdated: (source: Source) => void;
  /** [분류] 성공 → 분류 게이트 진입 결과를 부모에 전달(상세 안내/상태 갱신). */
  onClassifyEntered: (source: Source, entry: ClassificationGateEntry) => void;
}) {
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState<"feedback" | "classify" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // 열릴 때/대상 전환 시 입력·에러 초기화
  useEffect(() => {
    if (open) {
      setFeedback("");
      setError(null);
      setBusy(null);
    }
  }, [open, source?.id]);

  // Esc 로 닫기 (진행 중이 아닐 때만)
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busyRef.current) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // busy 를 keydown 핸들러에서 최신값으로 읽기 위한 ref
  const busyRef = useRef<"feedback" | "classify" | null>(null);
  busyRef.current = busy;

  if (!open || !source) return null;

  const summary = source.summary_payload;
  const trimmed = feedback.trim();
  const feedbackTooShort = trimmed.length > 0 && trimmed.length < FEEDBACK_MIN;
  const canFeedback = trimmed.length >= FEEDBACK_MIN && feedback.length <= FEEDBACK_MAX && busy === null;
  const canClassify = busy === null;

  async function handleFeedback() {
    if (!source || !canFeedback) return;
    setBusy("feedback");
    setError(null);
    try {
      const updated = await summaryFeedback(source.id, trimmed);
      onSummaryUpdated(updated);
      onClose();
    } catch (err) {
      setError(sourceCaseMessage(err, "피드백 전송에 실패했습니다. 잠시 후 다시 시도해 주세요."));
      setBusy(null);
    }
  }

  async function handleClassify() {
    if (!source || !canClassify) return;
    setBusy("classify");
    setError(null);
    try {
      const entry = await enterClassificationGate(source.id);
      onClassifyEntered(source, entry);
      onClose();
    } catch (err) {
      setError(sourceCaseMessage(err, "분류 게이트로 보내지 못했습니다. 잠시 후 다시 시도해 주세요."));
      setBusy(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="요약 초안 문서보기"
      onClick={(e) => {
        if (e.target === e.currentTarget && busy === null) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="flex max-h-[88vh] w-full max-w-2xl flex-col rounded-xl border border-border bg-background shadow-xl"
      >
        {/* 헤더 */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <div className="flex items-center gap-2">
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
              <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" />
              <path d="M14 2v5h5M16 13H8M16 17H8M10 9H8" />
            </svg>
            <h3 className="text-sm font-semibold">요약 초안 문서보기</h3>
            <span className="font-mono text-[10px] text-muted-foreground">
              status · {STATUS_LABELS[source.status]}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy !== null}
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

        {/* 문서 본문 (스크롤) */}
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {/* md frontmatter 미리보기 — 요약 초안이 어떤 노트 시드가 되는지 문서 형태로 보여준다 */}
          <pre className="scroll-thin overflow-x-auto whitespace-pre-wrap rounded-md bg-secondary/40 p-3 font-mono text-[10px] leading-relaxed text-foreground/80">
            {frontmatter(source)}
          </pre>

          {/* 렌더된 요약 초안 (읽기용 · 요약 AI ① 산출물) */}
          <div className="mt-4">
            <div className="mb-2 flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
                요약 AI ① · 자동
              </span>
              {summary?.material_type && (
                <span className="font-mono text-[10px] text-muted-foreground">
                  {summary.material_type}
                </span>
              )}
            </div>
            {summary?.title && (
              <h2 className="text-base font-semibold leading-snug">{summary.title}</h2>
            )}
            {summary?.summary ? (
              <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-foreground/90">
                {summary.summary}
              </p>
            ) : (
              <p className="mt-2 text-xs text-muted-foreground">요약 본문이 아직 없습니다.</p>
            )}
            {summary?.keywords && summary.keywords.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {summary.keywords.map((kw) => (
                  <span
                    key={kw}
                    className="rounded-md bg-secondary px-2 py-0.5 text-[10px] text-secondary-foreground"
                  >
                    #{kw}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* 원본 메타 */}
          <div className="mt-4 border-t border-border pt-3">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              원본 메타
            </div>
            <div className="divide-y divide-border">
              <MetaRow label="원본 URL">
                <a
                  href={source.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="break-all font-mono text-[11px] text-foreground underline-offset-2 hover:underline"
                >
                  {source.source_url}
                </a>
              </MetaRow>
              <MetaRow label="수신 채널">
                <span className="font-mono text-[11px]">{source.source_channel}</span>
                {source.slack_channel && (
                  <span className="ml-1 font-mono text-[11px] text-muted-foreground">
                    · {source.slack_channel}
                  </span>
                )}
              </MetaRow>
              <MetaRow label="제출자">
                <span className="font-mono text-[11px]">{source.submitted_by ?? "—"}</span>
              </MetaRow>
              <MetaRow label="수신 시각">
                <span className="font-mono text-[11px]">
                  {formatDateTime(source.submitted_at) || "—"}
                </span>
              </MetaRow>
            </div>
          </div>

          {/* 피드백 입력 — 자연어로 AI 재요약(세션 resume). 직접 편집·저장은 범위 아님 */}
          <div className="mt-4 border-t border-border pt-3">
            <label
              htmlFor="summary-feedback"
              className="text-[11px] font-medium text-muted-foreground"
            >
              요약이 아쉬우면 원하는 방향을 적어 다시 요약할 수 있어요 ({FEEDBACK_MIN}자 이상)
            </label>
            <textarea
              id="summary-feedback"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              disabled={busy !== null}
              rows={3}
              maxLength={FEEDBACK_MAX}
              placeholder="예) 핵심 설계 포인트를 더 구체적으로 짚어주세요 / 제목을 사례 중심으로 바꿔주세요"
              className="scroll-thin mt-1 w-full resize-y rounded-md border border-border bg-background px-2.5 py-2 text-xs leading-relaxed text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none disabled:opacity-60"
            />
            <div className="mt-1 flex items-center justify-between">
              {feedbackTooShort ? (
                <span className="text-[10px] text-muted-foreground">
                  {FEEDBACK_MIN}자 이상 적어주세요.
                </span>
              ) : (
                <span className="font-mono text-[10px] text-muted-foreground">
                  {feedback.length}/{FEEDBACK_MAX}
                </span>
              )}
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
        </div>

        {/* 액션 — [피드백](재요약) 또는 [분류](분류 게이트 진입). 자동 분류 없음 */}
        <div className="flex items-center justify-between gap-2 border-t border-border px-5 py-3.5">
          <p className="hidden text-[10px] leading-tight text-muted-foreground sm:block">
            요약이 만족스러우면 <span className="font-medium text-foreground">분류</span>로,
            아니면 피드백으로 다시 요약하세요.
          </p>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={handleFeedback}
              disabled={!canFeedback}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary disabled:opacity-50"
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
                <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" />
              </svg>
              {busy === "feedback" ? "재요약 요청 중…" : "피드백"}
            </button>
            <button
              type="button"
              onClick={handleClassify}
              disabled={!canClassify}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
            >
              <svg
                className="h-3.5 w-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
              {busy === "classify" ? "분류 게이트로 보내는 중…" : "분류"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
