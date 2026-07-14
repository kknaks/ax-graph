// Source Inbox 큐 목록 + 상태별 필터 (AXKG-SPEC-003 U-1). 레이아웃/카피는 21-html 시안 기준.
"use client";

import {
  inboxDisplay,
  type InboxDisplay,
  type Source,
} from "@/lib/api-client/sources";
import { formatTime } from "@/lib/format";

/** 문서함 4탭: inbox(게이트 전) | 승인(게이트 진입 후 대기) | 재검토(stale 전용) | 완료(documented).
 * 재검토는 source 상태가 아니라 concept 갱신으로 영향 가능성이 붙은 permanent 문서 뷰다(SPEC-004 E). */
export type StatusFilter = "inbox" | "approval" | "review" | "documented";

// 파생 라벨 tone → 시안 tier 색 (배지 inline style).
const TONE_STYLE: Record<InboxDisplay["tone"], React.CSSProperties> = {
  ok: { background: "hsl(var(--tier-ok) / .15)", color: "hsl(var(--tier-ok))" },
  progress: { background: "hsl(var(--tier-caution) / .15)", color: "hsl(var(--tier-caution))" },
  danger: { background: "hsl(var(--tier-caution) / .15)", color: "hsl(var(--tier-caution))" },
  neutral: { background: "hsl(var(--secondary))", color: "hsl(var(--secondary-foreground))" },
};

/** 파이프라인 단계 배지 — inbox_label(파생) 우선 한국어. summarized 가 "요약 완료"에 머물지 않고 "분류 완료"로 진행 표시. */
function StageBadge({ source }: { source: Source }) {
  const { text, tone } = inboxDisplay(source);
  return (
    <span
      className="shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium"
      style={TONE_STYLE[tone]}
    >
      {text}
    </span>
  );
}

const FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "inbox", label: "inbox" },
  { value: "approval", label: "승인" },
  { value: "review", label: "재검토" },
  { value: "documented", label: "완료" },
];

/** 문서함 탭 바 — SourceList(inbox/승인/완료 좌열)와 StaleList(재검토 좌열)가 공유한다.
 * 재검토 탭에는 stale 문서 수 카운트 배지를 붙인다(0건이어도 탭 유지). */
export function DocboxTabs({
  filter,
  reviewCount,
  onFilterChange,
}: {
  filter: StatusFilter;
  /** 재검토 탭 배지 카운트(stale 문서 수). 0 이면 배지 생략. */
  reviewCount: number;
  onFilterChange: (filter: StatusFilter) => void;
}) {
  return (
    <div className="grid grid-cols-4 gap-1 border-b border-border p-2">
      {FILTERS.map((f) => {
        const active = filter === f.value;
        const showBadge = f.value === "review" && reviewCount > 0;
        return (
          <button
            key={f.value}
            type="button"
            onClick={() => onFilterChange(f.value)}
            aria-pressed={active}
            className={
              active
                ? "inline-flex items-center justify-center gap-1 rounded-md border border-ring bg-secondary px-2 py-1.5 text-[11px] font-medium text-secondary-foreground"
                : "inline-flex items-center justify-center gap-1 rounded-md border border-border px-2 py-1.5 text-[11px] font-medium text-muted-foreground hover:bg-secondary/60"
            }
          >
            {f.label}
            {showBadge && (
              <span
                className="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                style={{
                  background: "hsl(var(--tier-caution) / .15)",
                  color: "hsl(var(--tier-caution))",
                }}
              >
                {reviewCount}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** 탭 분류: documented=완료, inbox_label 있으면 승인 게이트 대기, 없으면 아직 인박스.
 * review 는 source 탭이 아니라 stale 문서 뷰 — SourceList 는 이 필터로 렌더되지 않는다(방어적 false). */
function inTab(source: Source, filter: StatusFilter): boolean {
  if (filter === "review") return false;
  if (filter === "documented") return source.status === "documented";
  if (source.status === "documented") return false;
  const inGate = !!source.inbox_label;
  return filter === "approval" ? inGate : !inGate;
}

/** 수신 채널 문구 (시안: "slack · #ax-links" / "manual" / "upload" / "chat"). */
function channelLabel(source: Source): string {
  if (source.source_channel === "slack") {
    return source.slack_channel ? `slack · ${source.slack_channel}` : "slack";
  }
  return source.source_channel;
}

export function SourceList({
  sources,
  selectedId,
  filter,
  reviewCount,
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
  /** 재검토 탭 배지 카운트(stale 문서 수) — 어느 탭에서든 보이게 부모가 전달. */
  reviewCount: number;
  loading: boolean;
  error: string | null;
  onSelect: (source: Source) => void;
  onFilterChange: (filter: StatusFilter) => void;
  onOpenModal: () => void;
  onRetry: (source: Source, note?: string) => void;
}) {
  // 서버는 visible 목록 전체를 주고, inbox/승인 구분은 inbox_label 로 클라이언트에서 나눈다.
  const visible = sources.filter((s) => inTab(s, filter));
  return (
    <section className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-card text-card-foreground shadow-sm">
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
          <h2 className="text-sm font-semibold">문서함</h2>
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
          inbox
        </button>
      </div>

      {/* 상태별 필터 (U-1 상태별 필터) — 재검토 탭 포함 공유 탭 바 */}
      <DocboxTabs filter={filter} reviewCount={reviewCount} onFilterChange={onFilterChange} />

      <div className="scroll-thin min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
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

        {!loading && !error && visible.length === 0 && (
          <p className="rounded-md border border-dashed border-border bg-secondary/30 px-3 py-8 text-center text-xs leading-relaxed text-muted-foreground">
            {filter === "documented" ? (
              <>
                문서화 완료된 항목이 없습니다.
                <br />
                게이트를 <span className="font-mono text-[10px]">승인</span>하면 여기에서 확정 문서를 확인할 수 있어요.
              </>
            ) : filter === "approval" ? (
              <>
                승인 게이트에 대기 중인 항목이 없습니다.
                <br />
                요약 완료 후 <span className="font-mono text-[10px]">분류</span>를 시작하면 여기로 옮겨집니다.
              </>
            ) : (
              <>
                문서함이 비어 있습니다.
                <br />
                <span className="font-mono text-[10px]">inbox</span>로 URL을 담아보세요.
              </>
            )}
          </p>
        )}

        {!loading &&
          !error &&
          visible.map((source) => {
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
                  <StageBadge source={source} />
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
