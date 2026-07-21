// 우측 세로 히스토리 스택 (AXKG-SPEC-001/002/004 · 21-html page-approval SSOT).
// 한 화면에서 source 의 파이프라인 단계를 위→아래로 추적한다:
//   ① 요약 초안 카드(section-summary-draft) → ② 분류 게이트(section-spec-001) → ③ 문서화 게이트 placeholder(section-spec-004)
// summarized 가 아닌 상태(수신/요약 중/요약 실패/종료)는 각 상태 카드로 렌더한다.
// 실제 액션(요약 피드백·분류·게이트 피드백/승인/재시도)은 부모(source-inbox)가 배선한다.
"use client";

import { useEffect, useState } from "react";
import { MarkdownView } from "@/components/markdown-view";
import {
  activeRevisionOf,
  isGateRunning,
  STATUS_LABELS,
  type ClassificationForm,
  type DerivedSuggestion,
  type DestinationType,
  type DocumentationForm,
  type DraftLink,
  type Gate,
  type GateRevision,
  type Source,
} from "@/lib/api-client/sources";

// PARA 4후보 표시 순서/색 (시안 grid-cols-4, tier-* 토큰).
const PARA: { key: DestinationType; label: string }[] = [
  { key: "project", label: "project" },
  { key: "area", label: "area" },
  { key: "resource", label: "resource" },
  { key: "archive", label: "archive" },
];
const DEST_VAR: Record<DestinationType, string> = {
  project: "--tier-project",
  area: "--tier-area",
  resource: "--tier-resource",
  archive: "--tier-archive",
};
// 각 destination 의 의미 한 줄 설명 (카드에 노출). 이모지 금지 — 색은 dot/체크가 담당.
const PARA_DESC: Record<DestinationType, string> = {
  project: "목표·마감 있는 지금 진행 중 산출물",
  area: "마감 없이 지속 관리하는 책임/관심 영역",
  resource: "나중에 참고할 외부 자료 (가장 흔함)",
  archive: "지금 안 쓰고 보관 — 문서 안 만듦",
};

function CheckIcon({ className, color }: { className?: string; color?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color ?? "currentColor"}
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function FeedbackIcon() {
  return (
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
  );
}

/** 버전 badge (SPEC-002): 활성 revision = 채워짐, 이전 버전 = read-only 비활성. */
function VersionBadges({ gate }: { gate: Gate }) {
  const revisions = gate.revisions
    ? [...gate.revisions].sort((a, b) => b.version - a.version)
    : [];
  const active = activeRevisionOf(gate);
  if (revisions.length === 0 && active) {
    return (
      <span className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-secondary-foreground">
        v{active.version}
      </span>
    );
  }
  return (
    <div className="flex items-center gap-1">
      {revisions.map((r) => {
        const isActive = r.id === gate.active_revision_id;
        return isActive ? (
          <span
            key={r.id}
            className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-secondary-foreground"
          >
            v{r.version}
          </span>
        ) : (
          <button
            key={r.id}
            type="button"
            disabled
            title="read-only"
            className="cursor-not-allowed rounded-full border border-border px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground opacity-50"
          >
            v{r.version}
          </button>
        );
      })}
    </div>
  );
}

function ConfidenceBadge({ value }: { value?: number | null }) {
  if (value == null) return null;
  const tier = value >= 0.7 ? "--tier-ok" : value >= 0.4 ? "--tier-caution" : "--tier-risk";
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
      style={{ background: `hsl(var(${tier}) / .15)`, color: `hsl(var(${tier}))` }}
    >
      confidence {value.toFixed(2)}
    </span>
  );
}

/** ② 분류 게이트 폼(review_pending) — PARA 후보 + reason/title/tags. */
function ClassificationFormView({
  form,
  active,
}: {
  form: ClassificationForm;
  active: GateRevision | null;
}) {
  const selected = form.destination_type;
  const tags = form.suggested_tags ?? [];
  const confidence = form.confidence ?? active?.payload.confidence ?? null;
  return (
    <>
      <div className="mb-3 flex items-center justify-end">
        <ConfidenceBadge value={confidence} />
      </div>
      {/* PARA 4후보 — 테두리는 검정 유지(선택 시 굵게), PARA 색은 dot(비선택)/체크(선택)에만.
          dot/체크 색 = 그 자료가 그래프에서 가질 노드 색. 각 카드에 destination 의미 한 줄. */}
      <div className="grid grid-cols-4 gap-2">
        {PARA.map(({ key, label }) => {
          const on = key === selected;
          const varName = DEST_VAR[key];
          return (
            <div
              key={key}
              className={
                on
                  ? "rounded-md border-2 border-foreground p-2 text-center"
                  : "rounded-md border border-border p-2 text-center"
              }
            >
              <div className={on ? "text-[11px] font-semibold" : "text-[11px] font-medium"}>
                {label}
              </div>
              {on ? (
                <CheckIcon className="mx-auto mt-1 h-3.5 w-3.5" color={`hsl(var(${varName}))`} />
              ) : (
                <span
                  className="mt-1 inline-block h-1.5 w-1.5 rounded-full"
                  style={{ background: `hsl(var(${varName}))` }}
                />
              )}
              <div className="mt-1 text-[10px] leading-tight text-muted-foreground">
                {PARA_DESC[key]}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-3 space-y-1.5 rounded-md bg-secondary/50 p-2.5 text-[11px]">
        {form.destination_reason && (
          <div>
            <span className="font-medium">destination_reason ·</span> {form.destination_reason}
          </div>
        )}
        {form.suggested_title && (
          <div>
            <span className="font-medium">suggested_title ·</span> {form.suggested_title}
          </div>
        )}
        {tags.length > 0 && (
          <div>
            <span className="font-medium">suggested_tags ·</span> {tags.join(", ")}
          </div>
        )}
      </div>
    </>
  );
}

// ③ 문서화 게이트 파생지식 라벨 (SPEC-004 suggestion_type).
const SUGGESTION_LABELS: Record<string, string> = {
  supplement_existing_concept: "기존 개념 보충",
  create_new_concept: "새 개념 생성",
  create_project_baseline: "프로젝트 baseline",
  // 기업 프로젝트 팬아웃(SPEC-014 U-4) — 원본요약(main) + 기능정의서 N(derived).
  create_feature_spec: "기능정의서 생성",
  supplement_existing_feature: "기능정의서 보강",
};

// ③ 초안이 채택한 연결 edge_type 라벨 (SPEC-005 document-link-graph-contract).
// assoc = 본문 [[ ]] 연관, lineage = frontmatter up: 계보. 색은 DEST_VAR 톤 재사용.
const EDGE_TYPE_LABELS: Record<string, string> = {
  assoc: "assoc · [[ ]] 연관",
  lineage: "lineage · up: 계보",
};

/** U-2 초안이 채택한 연결 1건 — [[target]] + edge_type 배지 + link_reason. */
function DraftLinkItem({ link }: { link: DraftLink }) {
  const edge = link.edge_type ?? "assoc";
  const tier = edge === "lineage" ? "--tier-area" : "--tier-resource";
  return (
    <li className="rounded-md border border-border bg-background px-2.5 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 truncate font-mono text-[11px] text-foreground">
          [[{link.target ?? "—"}]]
        </span>
        <span
          className="shrink-0 rounded-full px-1.5 py-0.5 font-mono text-[10px] font-medium"
          style={{ background: `hsl(var(${tier}) / .15)`, color: `hsl(var(${tier}))` }}
        >
          {EDGE_TYPE_LABELS[edge] ?? edge}
        </span>
      </div>
      {link.link_reason && (
        <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">{link.link_reason}</p>
      )}
    </li>
  );
}

function Chevron() {
  return (
    <svg
      className="draft-chevron h-3.5 w-3.5 text-muted-foreground"
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

/** apply_plan 검증 상태 badge (U-5). pending=중립, valid=ok, invalid=risk. */
function ValidationBadge({ status }: { status?: string }) {
  const tier =
    status === "valid" ? "--tier-ok" : status === "invalid" ? "--tier-risk" : null;
  if (!tier) {
    return (
      <span className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-secondary-foreground">
        validation_status · {status ?? "pending"}
      </span>
    );
  }
  return (
    <span
      className="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
      style={{ background: `hsl(var(${tier}) / .15)`, color: `hsl(var(${tier}))` }}
    >
      validation_status · {status}
    </span>
  );
}

/** 파생지식 1건 (SPEC-004 U-3) — create=생성 markdown preview, modify=변경 요지(diff)+수정 전문. 개별 승인 버튼 없음. */
function DerivedSuggestionItem({ item }: { item: DerivedSuggestion }) {
  const label = SUGGESTION_LABELS[item.suggestion_type ?? ""] ?? item.suggestion_type ?? "파생지식";
  const isModify = item.change_kind === "modify";
  return (
    <details className="draft rounded-md border border-border bg-background">
      <summary className="flex items-center justify-between gap-2 px-2.5 py-2">
        <span className="inline-flex min-w-0 items-center gap-1.5 text-[11px] font-medium">
          <Chevron />
          <span className="truncate">
            {label} · {isModify ? "기존 문서 수정" : "신규 생성"}
          </span>
        </span>
        <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
          {item.file_action ?? (isModify ? "overwrite_markdown" : "create_markdown")} · {item.target_path ?? "—"}
        </span>
      </summary>
      <div className="border-t border-border px-2.5 py-2">
        {item.link_reason && (
          <p className="mb-1.5 text-[11px] leading-relaxed text-muted-foreground">
            <span className="font-medium text-foreground">연결 이유 ·</span> {item.link_reason}
          </p>
        )}
        {isModify ? (
          item.diff_preview || item.draft_markdown ? (
            <>
              {/* 변경 요지(diff_preview)를 먼저, 그 아래 수정 전문(draft_markdown, 신 계약 T-016) 접기/펴기 */}
              {item.diff_preview && (
                <pre className="scroll-thin mb-2 max-h-[200px] overflow-y-auto whitespace-pre-wrap font-mono text-[10px] leading-relaxed text-foreground/80">
                  {String(item.diff_preview)}
                </pre>
              )}
              {item.draft_markdown && (
                <details className="draft rounded-md border border-border bg-background">
                  <summary className="flex items-center justify-between gap-2 px-2.5 py-2">
                    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium">
                      <Chevron />
                      수정 전문 펼치기 / 접기
                    </span>
                    <span className="font-mono text-[10px] text-muted-foreground">draft_markdown</span>
                  </summary>
                  <pre className="scroll-thin max-h-[320px] overflow-y-auto whitespace-pre-wrap border-t border-border px-2.5 py-2 font-mono text-[10px] leading-relaxed text-foreground/80">
                    {item.draft_markdown}
                  </pre>
                </details>
              )}
            </>
          ) : (
            <p className="font-mono text-[10px] text-muted-foreground">
              대상 문서 수정 preview 가 아직 없습니다.
            </p>
          )
        ) : item.draft_markdown ? (
          <pre className="scroll-thin max-h-[200px] overflow-y-auto whitespace-pre-wrap font-mono text-[10px] leading-relaxed text-foreground/80">
            {item.draft_markdown}
          </pre>
        ) : (
          <p className="font-mono text-[10px] text-muted-foreground">
            생성될 markdown preview 가 아직 없습니다.
          </p>
        )}
      </div>
    </details>
  );
}

/** ③ 문서화 승인 게이트 실렌더 (SPEC-004 U-1~U-5, section-spec-004). */
function DocumentationGateView({
  gate,
  source,
  gateBusyId,
  onGateFeedback,
  onApproveGate,
  onRetryGate,
}: {
  gate: Gate;
  source: Source;
  gateBusyId: string | null;
  onGateFeedback: (gate: Gate) => void;
  onApproveGate: (gate: Gate) => void;
  onRetryGate: (gate: Gate) => void;
}) {
  const active = activeRevisionOf(gate);
  const form = (active?.payload.form ?? {}) as DocumentationForm;
  const draft = form.document_draft;
  const derived = form.derived_suggestions ?? [];
  const applyPlan = form.apply_plan;
  const busy = gateBusyId === gate.id;
  const destination = source.destination_type ?? form.destination_type ?? null;
  const reviewable = gate.status === "review_pending" || gate.status === "feedback_pending";

  return (
    <section className="rounded-lg border border-border bg-card text-card-foreground shadow-sm">
      {/* U-1 헤더: 제목 = 확정 destination + 버전 badge */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">문서화 승인 게이트</h2>
          {destination && (
            <span
              className="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
              style={{
                background: `hsl(var(${DEST_VAR[destination]}) / .15)`,
                color: `hsl(var(${DEST_VAR[destination]}))`,
              }}
            >
              destination · {destination}
            </span>
          )}
        </div>
        <VersionBadges gate={gate} />
      </div>

      <div className="space-y-3 p-4">
        {isGateRunning(gate) ? (
          <div className="flex items-center gap-2 rounded-md bg-secondary/40 px-3 py-6 text-xs text-muted-foreground">
            <svg
              className="h-4 w-4 animate-spin"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden
            >
              <path d="M21 12a9 9 0 1 1-6.219-8.56" />
            </svg>
            초안 생성 중… destination 에 맞는 문서 초안과 파생지식을 만들고 있습니다.
          </div>
        ) : gate.status === "failed" ? (
          <div
            className="flex items-center justify-between gap-3 rounded-md border border-dashed p-2.5 text-[11px]"
            style={{
              borderColor: "hsl(var(--tier-caution) / .45)",
              background: "hsl(var(--tier-caution) / .06)",
            }}
          >
            <div>
              <div className="font-medium" style={{ color: "hsl(var(--tier-caution))" }}>
                문서화 초안 생성/재생성 실패
              </div>
              <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                재시도하면 새 ai_task 로 다시 실행됩니다(기존 실패 task 보존).
              </div>
            </div>
            <button
              type="button"
              onClick={() => onRetryGate(gate)}
              disabled={busy}
              className="shrink-0 rounded-md border border-border bg-background px-2.5 py-1 text-[11px] font-medium hover:bg-secondary disabled:opacity-60"
            >
              {busy ? "재시도 중…" : "초안 생성 재시도"}
            </button>
          </div>
        ) : gate.status === "approved" ? (
          <div
            className="rounded-lg border p-3"
            style={{ borderColor: "hsl(var(--tier-ok) / .4)", background: "hsl(var(--tier-ok) / .07)" }}
          >
            <div
              className="flex items-center gap-1.5 text-[11px] font-medium"
              style={{ color: "hsl(var(--tier-ok))" }}
            >
              <CheckIcon className="h-4 w-4" />
              문서화 완료 · status → documented · up:/[[ ]] 그래프 엣지 반영
            </div>
            {draft?.target_path && (
              <div className="mt-1.5 font-mono text-[10px] text-muted-foreground">{draft.target_path}</div>
            )}
          </div>
        ) : gate.status === "cancelled" ? (
          // 재분류 요청됨 (SPEC-004 S-3 · State/Lifecycle reclassification_requested).
          // 이 게이트는 cancelled, 위 분류 게이트(②)가 다시 검토 상태로 열린다.
          <div
            className="rounded-lg border border-dashed p-3"
            style={{
              borderColor: "hsl(var(--tier-caution) / .45)",
              background: "hsl(var(--tier-caution) / .06)",
            }}
          >
            <div
              className="text-[11px] font-medium"
              style={{ color: "hsl(var(--tier-caution))" }}
            >
              재분류 요청됨 · reclassification_requested
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
              이 destination이 아니라는 피드백으로 분류 게이트(②)가 다시 검토 상태로 열렸습니다. 위에서
              새 분류를 검토·승인하면 문서화 게이트가 새로 생성됩니다.
            </p>
          </div>
        ) : draft ? (
          <>
            {/* U-2 AI 초안: 접힘=frontmatter+body preview, 펼침=markdown_full 전문 */}
            <div className="rounded-lg border border-border bg-secondary/30">
              <div className="px-3 py-2.5">
                <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  AI 초안 · {draft.document_type ?? "reference"}{" "}
                  <span className="font-mono lowercase">· create_markdown</span>
                </div>
                {draft.target_path && (
                  <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{draft.target_path}</div>
                )}
              </div>
              <div className="space-y-2 border-t border-border px-3 py-2.5">
                {draft.frontmatter_preview && (
                  <pre className="scroll-thin max-h-[160px] overflow-y-auto whitespace-pre-wrap font-mono text-[10px] leading-relaxed text-foreground/80">
                    {draft.frontmatter_preview}
                  </pre>
                )}
                {draft.body_preview && (
                  <p className="whitespace-pre-wrap text-[11px] leading-relaxed text-foreground/80">
                    {draft.body_preview}
                  </p>
                )}
                {draft.markdown_full && (
                  <details className="draft rounded-md border border-border bg-background">
                    <summary className="flex items-center justify-between gap-2 px-2.5 py-2">
                      <span className="inline-flex items-center gap-1.5 text-[11px] font-medium">
                        <Chevron />
                        초안 전문 펼치기 / 접기
                      </span>
                      <span className="font-mono text-[10px] text-muted-foreground">markdown_full</span>
                    </summary>
                    <pre className="scroll-thin max-h-[320px] overflow-y-auto whitespace-pre-wrap border-t border-border px-2.5 py-2 font-mono text-[10px] leading-relaxed text-foreground/80">
                      {draft.markdown_full}
                    </pre>
                  </details>
                )}
                {(draft.links?.length ?? 0) > 0 && (
                  <div className="rounded-md border border-border bg-background/60 p-2.5">
                    <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                      채택 연결 · 본문 [[ ]] / up: 계보
                    </div>
                    <ul className="space-y-1.5">
                      {draft.links!.map((link, i) => (
                        <DraftLinkItem key={i} link={link} />
                      ))}
                    </ul>
                  </div>
                )}
                <p className="font-mono text-[10px] text-muted-foreground">
                  연결 = 본문 [[ ]] + frontmatter up: (별도 연결 게이트 아님) · 승인 시 그래프 엣지로 반영
                </p>
              </div>
            </div>

            {/* U-3 파생지식: 초안과 한 덩어리, 읽기용 (개별 승인 없음) */}
            {derived.length > 0 && (
              <div className="rounded-lg border border-border p-3">
                <div className="mb-2 flex items-center justify-between">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    파생지식 · 초안과 한 덩어리 (개별 승인 없음)
                  </div>
                  <span className="font-mono text-[10px] text-muted-foreground">gate 승인/피드백에 함께 묶임</span>
                </div>
                <div className="space-y-2">
                  {derived.map((item, i) => (
                    <DerivedSuggestionItem key={i} item={item} />
                  ))}
                </div>
                <p className="mt-2 font-mono text-[10px] text-muted-foreground">
                  부적절하면 개별 보류가 아니라 게이트 피드백으로 초안+파생지식 통째 v2 재생성.
                </p>
              </div>
            )}

            {/* U-5 apply_plan preview */}
            {applyPlan && (applyPlan.file_actions?.length ?? 0) > 0 && (
              <div className="rounded-lg border border-border p-3">
                <div className="mb-2 flex items-center justify-between">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    apply_plan preview · executor 검증 후 적용
                  </div>
                  <ValidationBadge status={applyPlan.validation_status} />
                </div>
                <ul className="space-y-1 font-mono text-[10px] text-muted-foreground">
                  {applyPlan.file_actions!.map((fa, i) => (
                    <li key={i}>
                      {fa.action ?? "file_action"} · {fa.target_path ?? "—"}
                    </li>
                  ))}
                </ul>
                <p className="mt-2 font-mono text-[10px] text-muted-foreground">
                  AI 는 초안 + apply_plan 제안만 만들고, 승인 후 Apply Executor 가 path/state/schema 검증을 통과한
                  action 만 적용합니다.
                </p>
              </div>
            )}

            {/* U-4 게이트 액션: 피드백 · 승인 (초안+파생지식 통째) */}
            {reviewable && (
              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => onGateFeedback(gate)}
                  disabled={busy}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary disabled:opacity-50"
                >
                  <FeedbackIcon />
                  피드백
                </button>
                <button
                  type="button"
                  onClick={() => onApproveGate(gate)}
                  disabled={busy}
                  className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
                >
                  <CheckIcon className="h-3.5 w-3.5" />
                  {busy ? "승인 중…" : "승인 · 문서 생성 + 그래프 연결"}
                </button>
              </div>
            )}
          </>
        ) : (
          <p className="rounded-md bg-secondary/40 px-3 py-6 text-center text-xs text-muted-foreground">
            초안이 아직 준비되지 않았습니다.
          </p>
        )}
      </div>
    </section>
  );
}

export function GateHistoryStack({
  source,
  gates,
  gatesLoading,
  gatesError,
  classifying,
  gateBusyId,
  retrying,
  retryError,
  onSummaryFeedback,
  onClassify,
  onGateFeedback,
  onApproveGate,
  onRetryGate,
  onRetryCollection,
}: {
  source: Source | null;
  gates: Gate[];
  gatesLoading: boolean;
  gatesError: string | null;
  classifying: boolean;
  /** 액션 진행 중인 게이트 id(승인/재시도 버튼 비활성용). */
  gateBusyId: string | null;
  retrying: boolean;
  retryError: string | null;
  onSummaryFeedback: (source: Source) => void;
  onClassify: (source: Source) => void;
  onGateFeedback: (gate: Gate) => void;
  onApproveGate: (gate: Gate) => void;
  onRetryGate: (gate: Gate) => void;
  onRetryCollection: (source: Source, note?: string) => void;
}) {
  // collection_failed 메모(원문/요지) — source 전환 시 초기화.
  const [note, setNote] = useState("");
  // [원문보기] 모달에 띄울 body_markdown(요약 카드 전용) — source 전환 시 닫음.
  const [originalMarkdown, setOriginalMarkdown] = useState<string | null>(null);
  useEffect(() => {
    setNote("");
    setOriginalMarkdown(null);
  }, [source?.id]);
  // 모달 열림 중 ESC 로 닫기.
  useEffect(() => {
    if (originalMarkdown == null) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOriginalMarkdown(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [originalMarkdown]);

  if (!source) {
    return (
      <section className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-card text-card-foreground shadow-sm">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">파이프라인</h2>
        </div>
        <div className="grid min-h-0 flex-1 place-items-center p-4 text-center text-xs leading-relaxed text-muted-foreground">
          왼쪽 목록에서 source를 선택하면
          <br />
          요약 → 분류 → 문서화 단계가 여기 세로로 쌓입니다.
        </div>
      </section>
    );
  }

  const classificationGate = gates.find((g) => g.gate_kind === "classification") ?? null;
  // 재분류 후엔 cancelled(이전) + 새 문서화 게이트가 공존할 수 있다(SPEC-004 S-3).
  // 활성(비-cancelled) 게이트를 우선 렌더하고, 아직 없으면(요청 직후) 최신 것(=cancelled)을 보여준다.
  const documentationGates = gates.filter((g) => g.gate_kind === "documentation");
  const documentationGate =
    documentationGates.find((g) => g.status !== "cancelled") ??
    documentationGates[documentationGates.length - 1] ??
    null;

  // --- collection_failed: 실패 카드 + 메모/재시도 (SPEC-003 U-2 T-014) ---
  if (source.status === "collection_failed") {
    return (
      <div className="scroll-thin h-full min-h-0 space-y-4 overflow-y-auto">
        <section className="rounded-lg border border-border bg-card text-card-foreground shadow-sm">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">요약 실패</h2>
            <span className="font-mono text-[10px] text-muted-foreground">
              status · {STATUS_LABELS.collection_failed}
            </span>
          </div>
          <div className="p-4" style={{ background: "hsl(var(--tier-caution) / .06)" }}>
            <a
              href={source.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all font-mono text-[11px] text-foreground underline-offset-2 hover:underline"
            >
              {source.source_url}
            </a>
            <p className="mt-1 whitespace-pre-wrap font-mono text-[10px] leading-relaxed text-muted-foreground">
              {source.error_message || "요약에 실패했습니다. 다시 시도할 수 있습니다."}
            </p>
          </div>
          {/* 메모 fallback — 원문/요지를 적어 재요약 (medium류 자동수집 실패 대비) */}
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
                onClick={() => onRetryCollection(source, note.trim() ? note.trim() : undefined)}
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
                {retrying ? "다시 요약 중…" : note.trim() ? "저장하고 다시 요약" : "요약 재시도"}
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  // --- received / summarizing: 진행 카드 ---
  if (source.status === "received" || source.status === "summarizing") {
    return (
      <section className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-card text-card-foreground shadow-sm">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">요약 진행</h2>
          <span className="font-mono text-[10px] text-muted-foreground">
            status · {STATUS_LABELS[source.status]}
          </span>
        </div>
        <div className="p-4 text-xs text-muted-foreground">
          {source.status === "summarizing"
            ? "요약 AI가 원문을 수집·요약하고 있습니다…"
            : "수신되었습니다. 곧 요약이 시작됩니다."}
        </div>
      </section>
    );
  }

  // --- documented: 완료 흐름 요약(확정 destination/target_path/그래프 열기) ---
  if (source.status === "documented") {
    const active = documentationGate ? activeRevisionOf(documentationGate) : null;
    const doneDraft = (active?.payload.form as DocumentationForm | undefined)?.document_draft;

    // 재생성 구멍 보정(PLAN-010-T-016): stale 재생성으로 문서화 게이트가 v++ 재열림하면
    // source.status 는 documented 그대로지만 게이트는 regenerating→review_pending 로 돌아온다.
    // 게이트가 approved 가 아니면(=재생성 진행/재승인 대기/실패) 완료 배너 대신 게이트 스택을 렌더해
    // v2 초안 리뷰·승인 표면을 노출한다(기존 DocumentationGateView·handleApproveGate 재사용).
    if (documentationGate && documentationGate.status !== "approved") {
      return (
        <div className="scroll-thin h-full min-h-0 space-y-4 overflow-y-auto">
          <DocumentationGateView
            gate={documentationGate}
            source={source}
            gateBusyId={gateBusyId}
            onGateFeedback={onGateFeedback}
            onApproveGate={onApproveGate}
            onRetryGate={onRetryGate}
          />
        </div>
      );
    }
    return (
      <div className="scroll-thin h-full min-h-0 space-y-4 overflow-y-auto">
        <section className="rounded-lg border border-border bg-card text-card-foreground shadow-sm">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">문서화 완료</h2>
            {source.destination_type && (
              <span
                className="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                style={{
                  background: `hsl(var(${DEST_VAR[source.destination_type]}) / .15)`,
                  color: `hsl(var(${DEST_VAR[source.destination_type]}))`,
                }}
              >
                destination · {source.destination_type}
              </span>
            )}
          </div>
          <div className="space-y-3 p-4">
            <div
              className="rounded-lg border p-3"
              style={{
                borderColor: "hsl(var(--tier-ok) / .4)",
                background: "hsl(var(--tier-ok) / .07)",
              }}
            >
              <div
                className="flex items-center gap-1.5 text-[11px] font-medium"
                style={{ color: "hsl(var(--tier-ok))" }}
              >
                <CheckIcon className="h-4 w-4" />
                문서 생성 완료 · status → documented · 그래프 노드/엣지 반영
              </div>
            </div>
            {doneDraft && (
              <div className="space-y-1 rounded-md border border-border bg-secondary/30 p-3 text-[11px]">
                <div>
                  <span className="font-medium">document_type ·</span>{" "}
                  {doneDraft.document_type ?? "—"}
                </div>
                {doneDraft.target_path && (
                  <div className="break-all font-mono text-[10px] text-muted-foreground">
                    {doneDraft.target_path}
                  </div>
                )}
              </div>
            )}
            <a
              href="/graph"
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary"
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
                <rect x="16" y="16" width="6" height="6" rx="1" />
                <rect x="2" y="16" width="6" height="6" rx="1" />
                <rect x="9" y="2" width="6" height="6" rx="1" />
                <path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3M12 12V8" />
              </svg>
              그래프에서 문서 열기
            </a>
          </div>
        </section>
      </div>
    );
  }

  // --- archived / 그 외 종료 상태 ---
  if (source.status !== "summarized") {
    return (
      <section className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-card text-card-foreground shadow-sm">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">완료</h2>
          <span className="font-mono text-[10px] text-muted-foreground">
            status · {STATUS_LABELS[source.status]}
          </span>
        </div>
        <div className="p-4 text-xs text-muted-foreground">
          이 source 는 {STATUS_LABELS[source.status]} 상태입니다.
        </div>
      </section>
    );
  }

  // ===== summarized: 세로 스택 ① 요약 초안 → ② 분류 게이트 → ③ 문서화 placeholder =====
  const summary = source.summary_payload;
  const classifyDone = classificationGate?.status === "approved";
  const activeRev = classificationGate ? activeRevisionOf(classificationGate) : null;
  const form = activeRev?.payload.form;

  return (
    <div className="scroll-thin h-full min-h-0 space-y-4 overflow-y-auto">
      {/* ① 요약 초안 카드 (SPEC-003 U-2, section-summary-draft) */}
      <section className="rounded-lg border border-border bg-card text-card-foreground shadow-sm">
        <div className="p-4">
          <div className="mb-2 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
                요약 AI ① · 초안
              </span>
              <span className="font-mono text-[11px] text-muted-foreground">status · summarized</span>
            </div>
            <span className="font-mono text-[10px] text-muted-foreground">summary_payload · DB 임시</span>
          </div>
          <h3 className="text-sm font-semibold">{summary?.title || source.source_url}</h3>
          {summary?.summary && (
            <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
              {summary.summary}
            </p>
          )}
          {summary?.keywords && summary.keywords.length > 0 && (
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
          <p className="mt-2 font-mono text-[10px] text-muted-foreground">
            제목·요약·태그 = 생성될 노트 frontmatter 시드 · 확정 md 는 문서화 후(WP3)
          </p>
        </div>
        {/* CTA: [원문보기](body_markdown 모달) · [피드백](재요약) · [분류](분류 게이트 트리거). 분류 완료 후엔 피드백·분류 잠금, 원문보기는 항상 열람 가능. */}
        <div className="flex items-center justify-end gap-2 border-t border-border p-3">
          {summary?.body_markdown && (
            <button
              type="button"
              onClick={() => setOriginalMarkdown(summary.body_markdown ?? null)}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary"
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
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" />
              </svg>
              원문보기
            </button>
          )}
          <button
            type="button"
            onClick={() => onSummaryFeedback(source)}
            disabled={classifying || classifyDone}
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary disabled:opacity-50"
          >
            <FeedbackIcon />
            피드백
          </button>
          <button
            type="button"
            onClick={() => onClassify(source)}
            disabled={classifying || !!classificationGate}
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
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
            {classifying ? "분류 시작 중…" : classificationGate ? "분류 진행 중" : "분류"}
          </button>
        </div>
      </section>

      {/* 게이트 로드 상태 */}
      {gatesLoading && !classificationGate && (
        <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-xs text-muted-foreground">
          게이트 상태를 불러오는 중…
        </p>
      )}
      {gatesError && (
        <p className="rounded-lg border border-dashed border-border px-4 py-4 text-center text-xs text-destructive">
          {gatesError}
        </p>
      )}

      {/* ② 분류 게이트 카드 (SPEC-001 U-3, section-spec-001) */}
      {classificationGate && (
        <section className="rounded-lg border border-border bg-card text-card-foreground shadow-sm">
          <div className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold">
                  분류 게이트 <span className="font-normal text-muted-foreground">· 분류기 AI ②</span>
                </h3>
                <VersionBadges gate={classificationGate} />
              </div>
              {classifyDone && (
                <span
                  className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
                  style={{ background: "hsl(var(--tier-ok) / .15)", color: "hsl(var(--tier-ok))" }}
                >
                  <CheckIcon className="h-3 w-3" />
                  승인됨
                </span>
              )}
            </div>

            {/* 상태별 본문 */}
            {isGateRunning(classificationGate) ? (
              <div className="flex items-center gap-2 rounded-md bg-secondary/40 px-3 py-6 text-xs text-muted-foreground">
                <svg
                  className="h-4 w-4 animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  aria-hidden
                >
                  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                </svg>
                분류 중… 분류기 AI가 목적지를 제안하고 있습니다.
              </div>
            ) : classificationGate.status === "failed" ? (
              <div
                className="flex items-center justify-between gap-3 rounded-md border border-dashed p-2.5 text-[11px]"
                style={{
                  borderColor: "hsl(var(--tier-caution) / .45)",
                  background: "hsl(var(--tier-caution) / .06)",
                }}
              >
                <div>
                  <div className="font-medium" style={{ color: "hsl(var(--tier-caution))" }}>
                    분류 게이트 생성/재생성 실패
                  </div>
                  <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                    재시도하면 새 ai_task 로 다시 실행됩니다.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onRetryGate(classificationGate)}
                  disabled={gateBusyId === classificationGate.id}
                  className="shrink-0 rounded-md border border-border bg-background px-2.5 py-1 text-[11px] font-medium hover:bg-secondary disabled:opacity-60"
                >
                  {gateBusyId === classificationGate.id ? "재시도 중…" : "분류 재시도"}
                </button>
              </div>
            ) : form ? (
              <ClassificationFormView form={form} active={activeRev} />
            ) : (
              <p className="rounded-md bg-secondary/40 px-3 py-6 text-center text-xs text-muted-foreground">
                분류 결과가 아직 없습니다.
              </p>
            )}

            {/* CTA: review_pending/feedback_pending → [피드백][승인] (승인/실행 중/실패 아닐 때) */}
            {(classificationGate.status === "review_pending" ||
              classificationGate.status === "feedback_pending") &&
              form && (
                <div className="mt-3 flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => onGateFeedback(classificationGate)}
                    disabled={gateBusyId === classificationGate.id}
                    className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary disabled:opacity-50"
                  >
                    <FeedbackIcon />
                    피드백
                  </button>
                  <button
                    type="button"
                    onClick={() => onApproveGate(classificationGate)}
                    disabled={gateBusyId === classificationGate.id}
                    className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
                  >
                    <CheckIcon className="h-3.5 w-3.5" />
                    {gateBusyId === classificationGate.id ? "승인 중…" : "승인"}
                  </button>
                </div>
              )}
          </div>
        </section>
      )}

      {/* ③ 문서화 승인 게이트 실렌더 (SPEC-004, section-spec-004) */}
      {documentationGate && (
        <DocumentationGateView
          gate={documentationGate}
          source={source}
          gateBusyId={gateBusyId}
          onGateFeedback={onGateFeedback}
          onApproveGate={onApproveGate}
          onRetryGate={onRetryGate}
        />
      )}

      {/* [원문보기] 모달 — 요약 body_markdown 을 MarkdownView 로 렌더 (읽기 전용, 넓고 스크롤 가능).
          스타일은 gate-feedback-modal 톤과 맞춤(overlay + rounded 카드 + 헤더/닫기). */}
      {originalMarkdown != null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="원문 보기"
          onClick={(e) => {
            if (e.target === e.currentTarget) setOriginalMarkdown(null);
          }}
        >
          <div className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-xl border border-border bg-background shadow-xl">
            <div className="flex items-center justify-between border-b border-border px-5 py-3">
              <h3 className="text-sm font-semibold">원문 상세 · 요약 정리본</h3>
              <button
                type="button"
                onClick={() => setOriginalMarkdown(null)}
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
            <div className="scroll-thin overflow-y-auto px-5 py-4">
              <MarkdownView markdown={originalMarkdown} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
