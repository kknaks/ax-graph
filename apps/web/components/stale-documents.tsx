// 재검토 탭 (stale · 영향 가능성) — 좌 목록 + 우 상세 (AXKG-SPEC-004 E · AXKG-DEC-005 E · PLAN-009-T-033).
// concept 새 버전 승인으로 그 concept 를 [[ ]] 참조하는 permanent 에 "구성 개념 갱신됨 · 영향 가능성"
// 배지가 붙는다. 배지는 "수정 필요" 확정이 아니라 사용자 판단 대상이다(E-1).
//   - StaleList   : 재검토 탭 좌열. stale 문서를 선택 가능한 목록으로. (source-list 선택 패턴 재사용)
//   - StaleDetail : 재검토 탭 우열. 선택 문서의 유발 마크 카드 + 현재 본문(접기) + 액션 2개.
// 항목당 2개 액션: [판단 유효 · 배지 해제](dismiss) / [재검토 · 재생성](regenerate → 승인 탭 이동,
// 기존 게이트 스택 재사용). 부모(source-inbox)가 API/탭전환을 배선한다.
"use client";

import { useEffect, useState } from "react";
import {
  documentBody,
  getDocument,
  documentCaseMessage,
  type DocumentDetail,
  type StaleDocument,
} from "@/lib/api-client/documents";
import { DocboxTabs, type StatusFilter } from "@/components/source-list";
import { MarkdownView } from "@/components/markdown-view";
import { formatDateTime } from "@/lib/format";

// caution tone — "영향 가능성"(수정 필요 확정 아님)을 진행/주의 색으로 표시.
const STALE_BADGE_STYLE: React.CSSProperties = {
  background: "hsl(var(--tier-caution) / .15)",
  color: "hsl(var(--tier-caution))",
};

function AlertIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <path d="M12 9v4M12 17h.01" />
    </svg>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      className={`h-3.5 w-3.5 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="m9 18 6-6-6-6" />
    </svg>
  );
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function RegenerateIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
      <path d="M21 3v5h-5" />
      <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
      <path d="M3 21v-5h5" />
    </svg>
  );
}

/** 유발 concept 요약: [[stem]] + 복수면 "외 N개". 목록 행/헤더에서 공용. */
function conceptSummary(doc: StaleDocument) {
  const marks = doc.stale_marks ?? [];
  const first = marks[0];
  const extra = marks.length - 1;
  return { first, extra };
}

// ===== 재검토 탭 좌열: stale 문서 선택 목록 (source-list 프레임/선택 패턴 재사용) =====

export function StaleList({
  items,
  selectedId,
  filter,
  loading,
  error,
  onSelect,
  onFilterChange,
  onOpenModal,
}: {
  items: StaleDocument[];
  selectedId: string | null;
  filter: StatusFilter;
  loading: boolean;
  error: string | null;
  onSelect: (doc: StaleDocument) => void;
  onFilterChange: (filter: StatusFilter) => void;
  /** +inbox — Direct Inbox 모달 열기(SourceList 헤더와 동일 진입점). */
  onOpenModal: () => void;
}) {
  return (
    <section className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-card text-card-foreground shadow-sm">
      {/* 헤더 — 재검토 제목 + Direct Inbox 모달 열기(+inbox) */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <AlertIcon className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">재검토 · 영향 가능성</h2>
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

      {/* 공유 탭 바 (재검토 배지 카운트 = stale 문서 수) */}
      <DocboxTabs filter={filter} reviewCount={items.length} onFilterChange={onFilterChange} />

      <div className="scroll-thin min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {loading && (
          <p className="px-1 py-6 text-center text-xs text-muted-foreground">불러오는 중…</p>
        )}

        {!loading && error && (
          <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-xs text-destructive">
            {error}
          </p>
        )}

        {!loading && !error && items.length === 0 && (
          <p className="rounded-md border border-dashed border-border bg-secondary/30 px-3 py-8 text-center text-xs leading-relaxed text-muted-foreground">
            재검토할 문서가 없습니다 — 구성 개념이 갱신되면 여기에 표시됩니다.
          </p>
        )}

        {!loading &&
          !error &&
          items.map((doc) => {
            const active = doc.document_id === selectedId;
            const { first, extra } = conceptSummary(doc);
            return (
              <button
                key={doc.document_id}
                type="button"
                onClick={() => onSelect(doc)}
                aria-current={active ? "true" : undefined}
                className={
                  active
                    ? "w-full rounded-md border border-ring bg-secondary p-2.5 text-left transition"
                    : "w-full rounded-md border border-border p-2.5 text-left transition hover:bg-secondary/40"
                }
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-xs font-medium">{doc.title}</span>
                  <span
                    className="shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                    style={STALE_BADGE_STYLE}
                  >
                    영향 가능성
                  </span>
                </div>
                <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
                  {doc.document_type}
                  {first && (
                    <>
                      {" · 유발 "}
                      <span className="text-foreground">[[{first.concept_stem}]]</span>
                      {extra > 0 ? ` 외 ${extra}개` : ""}
                    </>
                  )}
                </div>
              </button>
            );
          })}
      </div>
    </section>
  );
}

// ===== 재검토 탭 우열: 선택 문서 상세 (유발 마크 + 현재 본문 + 액션) =====

export function StaleDetail({
  doc,
  busyId,
  onDismiss,
  onRegenerate,
}: {
  /** 선택된 stale 문서. null 이면 안내 플레이스홀더. */
  doc: StaleDocument | null;
  /** dismiss/regenerate 진행 중인 document_id (버튼 비활성). */
  busyId: string | null;
  onDismiss: (doc: StaleDocument) => void;
  onRegenerate: (doc: StaleDocument) => void;
}) {
  // 현재 문서 본문(GET /documents/{id}) — 선택 전환 시 재로드. 접기/펴기.
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [bodyOpen, setBodyOpen] = useState(false);

  const documentId = doc?.document_id ?? null;

  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    setBodyOpen(false);
    if (!documentId) return;
    let alive = true;
    setDetailLoading(true);
    getDocument(documentId)
      .then((d) => {
        if (alive) setDetail(d);
      })
      .catch((err) => {
        if (alive) setDetailError(documentCaseMessage(err, "문서 상세를 불러오지 못했습니다."));
      })
      .finally(() => {
        if (alive) setDetailLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [documentId]);

  if (!doc) {
    return (
      <section className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-card text-card-foreground shadow-sm">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">재검토 상세</h2>
        </div>
        <div className="grid min-h-0 flex-1 place-items-center p-4 text-center text-xs leading-relaxed text-muted-foreground">
          왼쪽에서 재검토할 문서를 선택하면
          <br />
          유발된 구성 개념 갱신과 현재 본문이 여기에 표시됩니다.
        </div>
      </section>
    );
  }

  const marks = doc.stale_marks ?? [];
  const busy = busyId === doc.document_id;
  const body = detail ? documentBody(detail) : null;

  return (
    <section className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-card text-card-foreground shadow-sm">
      {/* 헤더 — 제목 · 타입 배지 · path · 보조문구 */}
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-start justify-between gap-2">
          <h2 className="min-w-0 truncate text-sm font-semibold">{doc.title}</h2>
          <span
            className="shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium"
            style={STALE_BADGE_STYLE}
          >
            {doc.document_type}
          </span>
        </div>
        {doc.path && (
          <div className="mt-1 break-all font-mono text-[10px] text-muted-foreground">
            {doc.path}
          </div>
        )}
        <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <AlertIcon className="h-3.5 w-3.5 shrink-0" />
          구성 개념 갱신 · 영향 가능성 (수정 필요 확정 아님 · 판단은 사용자)
        </p>
      </div>

      <div className="scroll-thin min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {/* 유발 마크 카드 — 문서 하나가 여러 concept 갱신의 영향을 받을 수 있어 각각 표시(T-030). */}
        {marks.length === 0 && (
          <p className="rounded-md border border-dashed border-border px-3 py-4 text-center text-[11px] text-muted-foreground">
            유발 개념 정보가 제공되지 않았습니다.
          </p>
        )}
        {marks.map((mark, i) => (
          <div
            key={`${mark.concept_stem}-${mark.marked_at}-${i}`}
            className="rounded-md border border-border bg-secondary/40 p-3 text-[11px] leading-relaxed"
          >
            <div className="mb-1 font-medium">
              <span className="text-foreground">[[{mark.concept_stem}]]</span> 갱신됨 · 변경 요지
            </div>
            <p className="whitespace-pre-wrap text-muted-foreground">
              {mark.change_summary || "변경 요지가 제공되지 않았습니다."}
            </p>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-muted-foreground">
              <span>배지 표시 · {formatDateTime(mark.marked_at)}</span>
              {mark.concept_path && <span className="break-all">{mark.concept_path}</span>}
            </div>
          </div>
        ))}

        {/* 현재 문서 본문 — GET /documents/{id} 접기/펴기 ("내 판단이 여전히 유효한가"를 그 자리에서). */}
        <div className="rounded-md border border-border">
          <button
            type="button"
            onClick={() => setBodyOpen((v) => !v)}
            aria-expanded={bodyOpen}
            className="flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left hover:bg-secondary/40"
          >
            <span className="inline-flex items-center gap-1.5 text-[11px] font-medium">
              <ChevronIcon open={bodyOpen} />
              현재 문서 본문 펼치기 / 접기
            </span>
            <span className="font-mono text-[10px] text-muted-foreground">
              GET /documents/{"{id}"}
            </span>
          </button>
          {bodyOpen && (
            <div className="border-t border-border px-3 py-2.5">
              {detailLoading && (
                <p className="py-3 text-center text-[11px] text-muted-foreground">불러오는 중…</p>
              )}
              {!detailLoading && detailError && (
                <p className="rounded-md border border-dashed border-border px-3 py-3 text-center text-[11px] text-destructive">
                  {detailError}
                </p>
              )}
              {!detailLoading && !detailError && body && (
                <div className="scroll-thin max-h-[360px] overflow-y-auto">
                  <MarkdownView markdown={body} />
                </div>
              )}
              {/* seam: 현재 BE DocumentResponse 는 본문을 싣지 않는다(문서 계약). body 가 오면 위에서 렌더,
                  아니면 메타 + 안내로 대체한다. 정합(본문 포함 여부)은 admin. */}
              {!detailLoading && !detailError && !body && (
                <div className="space-y-1.5 text-[11px] text-muted-foreground">
                  <p>
                    현재 문서 본문은 API 응답에 포함되지 않습니다(본문은 Markdown SoT). 아래 메타로 문서를
                    식별하고, 전문은 그래프/SoT에서 확인하세요.
                  </p>
                  {detail && (
                    <div className="rounded-md bg-secondary/40 p-2.5 font-mono text-[10px]">
                      <div className="break-all">path · {detail.path}</div>
                      {detail.tags && detail.tags.length > 0 && (
                        <div>tags · {detail.tags.join(", ")}</div>
                      )}
                      {detail.updated_at && <div>updated · {formatDateTime(detail.updated_at)}</div>}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 액션 — 하단 우측: [판단 유효 · 배지 해제](dismiss) / [재검토 · 재생성](regenerate) */}
      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-4 py-3">
        {busy && (
          <span className="mr-auto font-mono text-[10px] text-muted-foreground">처리 중…</span>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => onDismiss(doc)}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary disabled:opacity-50"
        >
          <CheckIcon className="h-3.5 w-3.5" />
          판단 유효 · 배지 해제
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onRegenerate(doc)}
          className="inline-flex items-center gap-1.5 rounded-md border border-ring bg-secondary px-3 py-1.5 text-xs font-medium hover:bg-secondary/70 disabled:opacity-50"
        >
          <RegenerateIcon className="h-3.5 w-3.5" />
          재검토 · 재생성
        </button>
      </div>
    </section>
  );
}
