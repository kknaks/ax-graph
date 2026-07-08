// Source 상세 (AXKG-SPEC-003 U-2) — 원본 정보 + 요약 상태 + 요약 카드/실패 사유 + 요약 재시도.
// 요약 실행 자체는 Phase 3 범위 — 여기서는 status/summary_payload 유무에 따른 렌더링과
// queue-collection 재시도 API 배선까지만 한다.
"use client";

import { useEffect, useState } from "react";
import type { Source } from "@/lib/api-client/sources";
import { STATUS_LABELS } from "@/lib/api-client/sources";
import { formatDateTime } from "@/lib/format";
import { SourceStatusBadge } from "@/components/source-status-badge";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[96px_1fr] gap-2 px-4 py-2.5">
      <div className="text-[11px] font-medium text-muted-foreground">{label}</div>
      <div className="min-w-0 break-words text-xs">{children}</div>
    </div>
  );
}

export function SourceDetail({
  source,
  retrying,
  retryError,
  onRetry,
  onOpenDocument,
  classifyNotice,
}: {
  source: Source | null;
  retrying: boolean;
  retryError: string | null;
  onRetry: (source: Source, note?: string) => void;
  /** summarized 상세의 [문서보기] → 요약 초안 문서보기 모달 열기 (U-2 · T-015 개정본). */
  onOpenDocument: (source: Source) => void;
  /** [분류] 진입 후 안내 문구(분류 게이트 화면은 WP3). 없으면 표시 안 함. */
  classifyNotice: string | null;
}) {
  // collection_failed 항목 메모(원문 복붙/요지) 입력값. source 전환 시 초기화한다.
  const [note, setNote] = useState("");
  useEffect(() => {
    setNote("");
  }, [source?.id]);

  if (!source) {
    return (
      <section className="rounded-lg border border-border bg-card text-card-foreground shadow-sm">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">Source 상세</h2>
        </div>
        <div className="grid min-h-[480px] place-items-center p-4 text-center text-xs leading-relaxed text-muted-foreground">
          왼쪽 목록에서 source를 선택하면
          <br />
          원본 정보와 요약 상태를 볼 수 있습니다.
        </div>
      </section>
    );
  }

  const failed = source.status === "collection_failed";
  const summarized = source.status === "summarized";
  const summary = source.summary_payload;

  return (
    <section className="rounded-lg border border-border bg-card text-card-foreground shadow-sm">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Source 상세</h2>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-muted-foreground">
            {STATUS_LABELS[source.status]}
          </span>
          <SourceStatusBadge status={source.status} />
        </div>
      </div>

      {/* 요약 카드 (U-2) — summarized 이고 payload 가 있을 때만 */}
      {summarized && summary && (summary.title || summary.summary) && (
        <div className="border-b border-border bg-secondary/20 p-4">
          <div className="mb-1.5 flex items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
              요약 AI ① · 자동
            </span>
            {summary.material_type && (
              <span className="font-mono text-[10px] text-muted-foreground">
                {summary.material_type}
              </span>
            )}
          </div>
          {summary.title && (
            <h3 className="text-sm font-semibold">{summary.title}</h3>
          )}
          {summary.summary && (
            <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
              {summary.summary}
            </p>
          )}
          {summary.keywords && summary.keywords.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
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
          {/* [문서보기] (U-2 · T-015 개정본) — 요약 초안을 문서 형태로 보고 피드백/분류를 선택.
              요약은 자동으로 분류로 넘어가지 않는다 — 여기서 사용자가 다음 동작을 고른다. */}
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={() => onOpenDocument(source)}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-secondary"
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
                <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" />
                <path d="M14 2v5h5M16 13H8M16 17H8M10 9H8" />
              </svg>
              문서보기
            </button>
          </div>
        </div>
      )}

      {/* [분류] 진입 안내 — 분류 게이트 화면 자체는 WP3. 진입 호출까지만 하고 안내만 표시. */}
      {summarized && classifyNotice && (
        <div
          className="border-b border-border px-4 py-2.5 text-[11px]"
          style={{ background: "hsl(var(--tier-ok) / .07)", color: "hsl(var(--tier-ok))" }}
        >
          {classifyNotice}
        </div>
      )}

      {/* summarizing — 진행 중 안내 */}
      {source.status === "summarizing" && (
        <div className="border-b border-border bg-secondary/20 px-4 py-3 text-xs text-muted-foreground">
          요약 AI가 원문을 수집·요약하고 있습니다…
        </div>
      )}

      {/* 실패 사유 (U-2) — collection_failed 최신 실패 task error_message */}
      {failed && (
        <div
          className="border-b border-border p-4"
          style={{ background: "hsl(var(--tier-caution) / .06)" }}
        >
          <div
            className="text-[11px] font-medium"
            style={{ color: "hsl(var(--tier-caution))" }}
          >
            요약 실패
          </div>
          <p className="mt-1 whitespace-pre-wrap font-mono text-[10px] leading-relaxed text-muted-foreground">
            {source.error_message || "요약에 실패했습니다. 다시 시도할 수 있습니다."}
          </p>
        </div>
      )}

      {/* 원본 정보 (U-2 문구: 원본 URL, Slack 메시지 링크, raw text, 제출자, 수신 시각) */}
      <div className="divide-y divide-border">
        <Field label="원본 URL">
          <a
            href={source.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="break-all font-mono text-[11px] text-foreground underline-offset-2 hover:underline"
          >
            {source.source_url}
          </a>
        </Field>
        <Field label="수신 채널">
          <span className="font-mono text-[11px]">{source.source_channel}</span>
          {source.slack_channel && (
            <span className="ml-1 font-mono text-[11px] text-muted-foreground">
              · {source.slack_channel}
            </span>
          )}
        </Field>
        {source.source_channel === "slack" && (
          <Field label="Slack 링크">
            {source.slack_permalink ? (
              <a
                href={source.slack_permalink}
                target="_blank"
                rel="noopener noreferrer"
                className="break-all font-mono text-[11px] text-foreground underline-offset-2 hover:underline"
              >
                Slack 메시지 열기
              </a>
            ) : (
              <span className="font-mono text-[11px] text-muted-foreground">
                {source.slack_message_ts ? `ts ${source.slack_message_ts}` : "—"}
              </span>
            )}
          </Field>
        )}
        <Field label="제출자">
          <span className="font-mono text-[11px]">{source.submitted_by ?? "—"}</span>
        </Field>
        <Field label="수신 시각">
          <span className="font-mono text-[11px]">
            {formatDateTime(source.submitted_at) || "—"}
          </span>
        </Field>
        <Field label="raw text">
          {source.raw_text ? (
            <pre className="scroll-thin max-h-[200px] overflow-y-auto whitespace-pre-wrap rounded-md bg-secondary/40 p-2 font-mono text-[10px] leading-relaxed text-foreground/80">
              {source.raw_text}
            </pre>
          ) : (
            <span className="text-[11px] text-muted-foreground">없음</span>
          )}
        </Field>
      </div>

      {/* 메모 fallback (U-2) — collection_failed 항목에 원문/요지를 적어 재요약.
          medium류는 원문 자동 수집이 안 되므로 메모를 넣어 다시 요약할 수 있다.
          저장 = 메모 갱신 + 재요약 한 번(queue-collection + note). MVP라 메모 기반 구분 배지는 두지 않는다. */}
      {failed && (
        <div className="flex flex-col gap-2 border-t border-border px-4 py-3">
          <label
            htmlFor="collection-failed-note"
            className="text-[11px] font-medium text-muted-foreground"
          >
            원문을 붙여넣거나 요지를 적어 다시 요약할 수 있어요
          </label>
          <textarea
            id="collection-failed-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={retrying}
            rows={4}
            maxLength={2000}
            placeholder="예) 원문 전체를 붙여넣거나, 핵심 내용을 요약해 적어주세요."
            className="scroll-thin w-full resize-y rounded-md border border-border bg-background px-2.5 py-2 text-xs leading-relaxed text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none disabled:opacity-60"
          />
          <div className="flex items-center justify-between gap-2">
            {retryError ? (
              <span className="text-[11px] text-destructive">{retryError}</span>
            ) : (
              <span className="font-mono text-[10px] text-muted-foreground">
                {note.length}/2000
              </span>
            )}
            <button
              type="button"
              onClick={() => onRetry(source, note.trim() ? note.trim() : undefined)}
              disabled={retrying}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
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
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
              </svg>
              {retrying
                ? "다시 요약 중…"
                : note.trim()
                  ? "저장하고 다시 요약"
                  : "요약 재시도"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
