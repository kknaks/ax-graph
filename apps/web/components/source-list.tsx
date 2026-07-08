// Source Inbox 큐 목록 + 상태별 필터 (AXKG-SPEC-003 U-1). 레이아웃/카피는 21-html 시안 기준.
"use client";

import {
  INBOX_FILTER_STATUSES,
  STATUS_LABELS,
  type Source,
  type SourceStatus,
} from "@/lib/api-client/sources";
import { formatTime } from "@/lib/format";
import { SourceStatusBadge } from "@/components/source-status-badge";

export type StatusFilter = "all" | SourceStatus;

const FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "전체" },
  ...INBOX_FILTER_STATUSES.map((s) => ({ value: s, label: STATUS_LABELS[s] })),
];

/** 수신 채널 문구 (시안: "slack · #ax-links" / "manual"). */
function channelLabel(source: Source): string {
  if (source.source_channel === "slack") {
    return source.slack_channel ? `slack · ${source.slack_channel}` : "slack";
  }
  return "manual";
}

export function SourceList({
  sources,
  selectedId,
  filter,
  loading,
  error,
  onSelect,
  onFilterChange,
  onOpenModal,
  onRetry,
}: {
  sources: Source[];
  selectedId: string | null;
  filter: StatusFilter;
  loading: boolean;
  error: string | null;
  onSelect: (source: Source) => void;
  onFilterChange: (filter: StatusFilter) => void;
  onOpenModal: () => void;
  onRetry: (source: Source, note?: string) => void;
}) {
  return (
    <section className="h-fit rounded-lg border border-border bg-card text-card-foreground shadow-sm">
      {/* 헤더 — 제목 + Direct Inbox 모달 열기 (U-3) */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
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
            <path d="M22 12h-6l-2 3h-4l-2-3H2" />
            <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
          </svg>
          <h2 className="text-sm font-semibold">Source Inbox</h2>
        </div>
        <button
          type="button"
          onClick={onOpenModal}
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium hover:bg-secondary/60"
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
            <path d="M5 12h14M12 5v14" />
          </svg>
          Inbox에 넣기
        </button>
      </div>

      {/* 상태별 필터 (U-1 상태별 필터, GET /sources?status=) */}
      <div className="scroll-thin flex items-center gap-1 overflow-x-auto border-b border-border px-3 py-2">
        {FILTERS.map((f) => {
          const active = filter === f.value;
          return (
            <button
              key={f.value}
              type="button"
              onClick={() => onFilterChange(f.value)}
              aria-pressed={active}
              className={
                active
                  ? "shrink-0 rounded-full bg-secondary px-2.5 py-1 text-[11px] font-medium text-secondary-foreground"
                  : "shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium text-muted-foreground hover:bg-secondary/60"
              }
            >
              {f.label}
            </button>
          );
        })}
      </div>

      <div className="scroll-thin max-h-[640px] space-y-2 overflow-y-auto p-3">
        {loading && (
          <p className="px-1 py-6 text-center text-xs text-muted-foreground">
            불러오는 중…
          </p>
        )}

        {!loading && error && (
          <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-xs text-destructive">
            {error}
          </p>
        )}

        {!loading && !error && sources.length === 0 && (
          <p className="rounded-md border border-dashed border-border bg-secondary/30 px-3 py-8 text-center text-xs leading-relaxed text-muted-foreground">
            받은 소스가 없습니다.
            <br />
            <span className="font-mono text-[10px]">Inbox에 넣기</span>로 URL을 담아보세요.
          </p>
        )}

        {!loading &&
          !error &&
          sources.map((source) => {
            const active = source.id === selectedId;
            const failed = source.status === "collection_failed";
            return (
              <button
                key={source.id}
                type="button"
                onClick={() => onSelect(source)}
                aria-current={active ? "true" : undefined}
                className={
                  active
                    ? "row w-full rounded-md border border-ring bg-secondary p-2.5 text-left transition"
                    : "row w-full rounded-md border border-border p-2.5 text-left transition hover:bg-secondary/40"
                }
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[10px] font-medium text-muted-foreground">
                    {channelLabel(source)}
                  </span>
                  <SourceStatusBadge status={source.status} />
                </div>
                <div className="mt-1 truncate text-xs font-medium">
                  {source.summary_payload?.title || source.source_url}
                </div>
                <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
                  {source.submitted_by ? `submitted_by ${source.submitted_by}` : "submitted_by —"}
                  {source.submitted_at ? ` · ${formatTime(source.submitted_at)}` : ""}
                </div>

                {/* collection_failed — 재시도 CTA 인라인 (시안 재현) */}
                {failed && (
                  <div className="mt-2 flex items-center justify-between gap-2 rounded-md bg-secondary/50 px-2 py-1">
                    <span className="truncate font-mono text-[10px] text-muted-foreground">
                      요약 실패 · 재시도 가능
                    </span>
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(e) => {
                        e.stopPropagation();
                        onRetry(source);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          e.stopPropagation();
                          onRetry(source);
                        }
                      }}
                      className="shrink-0 cursor-pointer rounded-md border border-border bg-background px-2 py-0.5 text-[10px] font-medium hover:bg-secondary"
                    >
                      요약 재시도
                    </span>
                  </div>
                )}
              </button>
            );
          })}
      </div>
    </section>
  );
}
