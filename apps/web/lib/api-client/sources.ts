// Source Inbox API 클라이언트 (AXKG-SPEC-003 §4 Interface Contract).
//
// BE(profile-be)와 같은 SPEC-003 계약으로 병렬 구현 중이다. 스키마는 스펙 §4를
// 기준으로 작성하고, 라이브 연동 e2e 는 admin 이 후속 확인한다.
//
// 엔드포인트:
// - POST /sources/manual            페이지 직접 입력 URL 저장 (U-3)
// - GET  /sources?status=           Source Inbox 목록 (U-1)
// - GET  /sources/{id}              Source 원본 정보 (U-2)
// - POST /sources/{id}/queue-collection   collection_failed 요약 재시도 (U-2)
// - POST /sources/{id}/summary-feedback   요약 초안 자연어 피드백 → 재요약 (U-2 · T-015 개정본, BE T-016 병렬)
// - POST /sources/{id}/classification-gates  summarized → 분류 게이트 생성(분류기 AI ②) (SPEC-001 §4)
// - GET  /sources/{id}/gates               source 게이트 + revision 목록 (SPEC-002, 우측 스택)
// - POST /gates/{id}/approve|feedback|regenerate|retry  공통 게이트 액션 (SPEC-002 API Contract)

import { ApiError, apiFetch, caseMessage } from "./index";

// --- 상태/채널 enum (SPEC-003 State/Lifecycle · Data Contract) ---

export type SourceStatus =
  | "received"
  | "summarizing"
  | "summarized"
  | "collection_failed"
  | "ignored"
  | "documented"
  | "archived"
  | "deleted";

export type SourceChannel = "slack" | "manual";

/** PARA destination (분류 게이트 form.destination_type, SPEC-001 U-3). */
export type DestinationType = "project" | "area" | "resource" | "archive";

/** Inbox 큐 파생 라벨 (SPEC-001 §Verification 매핑표). DB 미저장 — status + 게이트 상태 조합. */
export type InboxLabel =
  | "classify_pending"
  | "classify_regenerating"
  | "classify_approved"
  | "doc_pending"
  | "doc_regenerating"
  | "doc_approved";

/** 파생 라벨 → 한국어 (SPEC-001 매핑표). 리스트/스택에서 파이프라인 단계를 사람이 읽게 표시. */
export const INBOX_LABEL_LABELS: Record<InboxLabel, string> = {
  classify_pending: "분류 중",
  classify_regenerating: "분류 재생성",
  classify_approved: "분류 완료",
  doc_pending: "문서화 중",
  doc_regenerating: "문서화 재생성",
  doc_approved: "문서화 적용 중",
};

/** 기본 Inbox 목록에서 필터 가능한 상태 (visible_in_inbox=true 흐름). */
export const INBOX_FILTER_STATUSES: SourceStatus[] = [
  "received",
  "summarizing",
  "summarized",
  "collection_failed",
];

/** 상태 → 한국어 라벨 (SPEC-003 U-1 상태 문구). 배지 텍스트는 시안대로 enum 토큰을 쓰고, 이 라벨은 필터/보조 설명에 쓴다. */
export const STATUS_LABELS: Record<SourceStatus, string> = {
  received: "수신됨",
  summarizing: "요약 중",
  summarized: "요약 완료",
  collection_failed: "요약 실패",
  ignored: "무시됨",
  documented: "문서화됨",
  archived: "보관됨",
  deleted: "삭제됨",
};

// --- 요약 결과 payload (work-002 summary_payload · 요약 스테이지 ① 산출물).
// 요약 실행 자체는 Phase 3 범위 — FE 는 payload 유무에 따라 렌더링만 한다. ---

export interface SourceSummaryPayload {
  title?: string | null;
  summary?: string | null;
  keywords?: string[] | null;
  material_type?: string | null;
  // 요약 단계가 추가 산출하는 장문 원문 상세 정리본(PLAN-009 · BE PLAN-009-T-001).
  // 카드 [원문보기] 모달에서 MarkdownView 로 렌더. 기존 payload 하위호환을 위해 optional.
  body_markdown?: string | null;
}

// --- Source 리소스 (SPEC-003 Data Contract) ---

export interface Source {
  id: string;
  source_url: string;
  source_channel: SourceChannel;
  slack_message_ts: string | null;
  submitted_at: string;
  submitted_by: string | null;
  raw_text: string | null;
  status: SourceStatus;
  visible_in_inbox: boolean;
  documented_at: string | null;
  deleted_at: string | null;
  // 상세/요약 렌더링용 (SPEC-003 U-2). BE 계약 확정 전 optional 로 두어 없으면 graceful degrade.
  summary_payload?: SourceSummaryPayload | null;
  /** collection_failed 시 최신 실패 ai_task 의 error_message (SPEC-003 Implementation Rules). */
  error_message?: string | null;
  /** Slack 채널/스레드 링크 등 표시용 metadata (mockup: "slack · #ax-links", Slack 메시지 링크). */
  slack_channel?: string | null;
  slack_permalink?: string | null;
  // --- 분류 파이프라인 파생 필드 (SPEC-001, BE SourceResponse). 게이트 없으면 null. ---
  /** Inbox 큐 파생 라벨 (status + 분류 게이트 상태 조합). 없거나 매핑 밖이면 null. */
  inbox_label?: InboxLabel | null;
  /** 분류 승인으로 확정된 destination (SPEC-001 U-3). */
  destination_type?: DestinationType | null;
  /** 승인된 분류 게이트 id (있으면 destination 확정 상태). */
  approved_classification_gate_id?: string | null;
}

/** 리스트/스택 상태 표시용 — inbox_label(파생) 우선, 없으면 status 라벨로 폴백. */
export interface InboxDisplay {
  text: string;
  tone: "ok" | "progress" | "neutral" | "danger";
}

export function inboxDisplay(source: Source): InboxDisplay {
  const label = source.inbox_label;
  if (label && INBOX_LABEL_LABELS[label]) {
    // *_approved 는 단계 완료(ok), 나머지(진행/재생성)는 progress.
    return { text: INBOX_LABEL_LABELS[label], tone: label.endsWith("approved") ? "ok" : "progress" };
  }
  switch (source.status) {
    case "summarized":
      return { text: STATUS_LABELS.summarized, tone: "ok" };
    case "summarizing":
      return { text: STATUS_LABELS.summarizing, tone: "progress" };
    case "collection_failed":
      return { text: STATUS_LABELS.collection_failed, tone: "danger" };
    case "documented":
      return { text: STATUS_LABELS.documented, tone: "ok" };
    default:
      return { text: STATUS_LABELS[source.status], tone: "neutral" };
  }
}

// --- Case Matrix (SPEC-003 §4) — error_code → 프론트 문구 ---

export const SOURCE_CASE_MESSAGES: Record<string, string> = {
  INVALID_URL: "올바른 URL이 아닙니다.",
  DUPLICATE_SOURCE: "이미 받은 URL입니다. 기존 항목에 연결했습니다.",
  SLACK_METADATA_MISSING: "Slack 메시지 정보를 일부 저장하지 못했습니다.",
  MANUAL_NOTE_TOO_LONG: "메모는 2000자 이하로 입력해 주세요.",
  COLLECTION_RETRY_NOT_ALLOWED: "현재 상태에서는 요약을 재시도할 수 없습니다.",
  // 요약 피드백 / 분류 게이트 진입 (T-015 개정본 · BE T-016 병렬). 최종 코드는 BE 구현과 정합, 없으면 fallback.
  SUMMARY_FEEDBACK_NOT_ALLOWED: "요약이 완료된 항목에만 피드백할 수 있습니다.",
  CLASSIFY_NOT_ALLOWED: "요약이 완료된 항목만 분류로 보낼 수 있습니다.",
  // 공통 게이트 액션 Case Matrix (AXKG-SPEC-002). BE approval_gates 라우트 error_code 와 정합.
  CLASSIFICATION_NOT_ALLOWED: "요약이 완료된 항목만 분류를 시작할 수 있습니다.",
  FEEDBACK_TOO_SHORT: "원하는 수정 방향을 조금 더 구체적으로 적어 주세요.",
  GATE_ALREADY_APPROVED: "이미 승인된 게이트입니다. 최신 상태를 다시 불러왔습니다.",
  STALE_GATE_VERSION: "그 사이 새 버전이 생겼습니다. 최신 상태를 다시 확인해 주세요.",
  RETRY_NOT_ALLOWED: "지금은 재시도할 수 없는 상태입니다.",
  GATE_NOT_FOUND: "게이트를 찾을 수 없습니다. 목록을 새로고침해 주세요.",
  // 문서화 승인 게이트 Case Matrix (AXKG-SPEC-004 §4). approve→Apply Executor 검증 실패 코드 포함.
  NOT_APPROVED_DESTINATION: "문서화 대상이 아닙니다. 먼저 분류를 승인해 주세요.",
  MISSING_NOT_THIS_DESTINATION_REASON: "이 destination이 아닌 이유를 입력해 주세요.",
  // 재분류 재오픈 (SPEC-004 S-3 · BE T-009). 문서화 게이트 → 분류 게이트 재검토 불가 상태.
  RECLASSIFICATION_NOT_ALLOWED: "현재 상태에서는 재분류를 요청할 수 없습니다.",
  DRAFT_NOT_READY: "초안이 아직 준비되지 않았습니다.",
  DRAFT_MARKDOWN_NOT_FOUND: "초안 전문을 불러오지 못했습니다.",
  STALE_DRAFT_VERSION: "최신 초안을 다시 확인해 주세요.",
  DRAFT_RETRY_NOT_ALLOWED: "현재 상태에서는 초안 생성을 재시도할 수 없습니다.",
  // Apply Executor 검증 실패 (SPEC-004 executor 거부 사유).
  BROKEN_WIKILINK: "연결 대상 문서를 찾을 수 없습니다. 초안의 [[ ]] 연결을 확인해 주세요.",
  UP_WITHOUT_BODY_LINK: "up: 연결이 본문 [[ ]]로 뒷받침되지 않았습니다.",
  DUPLICATE_STEM: "같은 이름의 문서가 이미 있습니다. 파일명을 조정해 주세요.",
  PATH_NOT_ALLOWED: "허용되지 않은 경로입니다. 문서 루트 안의 경로만 생성할 수 있습니다.",
};

/** SPEC-003 Case Matrix 문구 우선, 없으면 공통(auth) 매핑 → fallback. */
export function sourceCaseMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && SOURCE_CASE_MESSAGES[error.errorCode]) {
    return SOURCE_CASE_MESSAGES[error.errorCode];
  }
  return caseMessage(error, fallback);
}

// --- 요청/응답 ---

export interface CreateManualSourceRequest {
  source_url: string;
  /** 수동 입력 메모 (선택 · 2000자 이하, SPEC-003 Validation). */
  raw_text?: string;
}

/** 목록 응답은 배열 또는 { sources: [...] } 봉투 어느 쪽이든 허용 (BE 계약 확정 전 방어적). */
type SourceListPayload = Source[] | { sources?: Source[] };

function toSourceList(payload: SourceListPayload): Source[] {
  if (Array.isArray(payload)) return payload;
  return payload?.sources ?? [];
}

/** POST /sources/manual — 페이지 직접 입력 URL 을 received 로 저장 (U-3). */
export function createManualSource(
  body: CreateManualSourceRequest,
): Promise<Source> {
  return apiFetch<Source>("/sources/manual", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** GET /sources?status= — Source Inbox 목록 (U-1). status 미지정 시 기본(visible) 목록. */
export async function listSources(status?: SourceStatus): Promise<Source[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const payload = await apiFetch<SourceListPayload>(`/sources${query}`);
  return toSourceList(payload);
}

/** GET /sources/{id} — Source 원본 정보 (U-2). */
export function getSource(sourceId: string): Promise<Source> {
  return apiFetch<Source>(`/sources/${encodeURIComponent(sourceId)}`);
}

/** POST /sources/{id}/queue-collection — collection_failed 요약 재시도 (U-2).
 * `note`(원문 복붙/요지)를 함께 보내면 메모를 갱신하고 그 메모 기반으로 재요약한다
 * (SPEC-003 §4 개정본 · medium류 collection_failed fallback). note 없이 호출하면 단순 재큐.
 * 어느 쪽이든 새 ai_task 로 실행되고 기존 실패 task 는 보존된다 (SPEC-003 Implementation Rules). */
export function queueCollection(
  sourceId: string,
  note?: string,
): Promise<Source> {
  return apiFetch<Source>(
    `/sources/${encodeURIComponent(sourceId)}/queue-collection`,
    {
      method: "POST",
      ...(note !== undefined ? { body: JSON.stringify({ note }) } : {}),
    },
  );
}

// --- 요약 피드백 / 분류 게이트 진입 (SPEC-003 U-2 T-015 개정본 · SPEC-001 §4) ---
// summarized source 는 자동으로 분류로 넘어가지 않고 사용자 선택을 기다린다.
// [피드백] = 자연어 피드백으로 요약 AI ① 재실행(세션 resume 재요약), [분류] = 분류 게이트 진입.

export interface SummaryFeedbackRequest {
  /** 요약 초안에 대한 자연어 피드백 (원하는 방향). */
  feedback: string;
}

/** POST /sources/{id}/summary-feedback — 요약 초안에 자연어 피드백을 보내 재요약(U-2 · T-015 개정본).
 * BE(T-016) 와 병렬 계약. 응답은 재요약이 시작된 Source(status=summarizing) 이고,
 * 세션 resume 로 완료되면 갱신된 `summary_payload` 로 다시 `summarized` 가 된다. */
export function summaryFeedback(
  sourceId: string,
  feedback: string,
): Promise<Source> {
  return apiFetch<Source>(
    `/sources/${encodeURIComponent(sourceId)}/summary-feedback`,
    {
      method: "POST",
      body: JSON.stringify({ feedback } satisfies SummaryFeedbackRequest),
    },
  );
}

// --- 승인 게이트 (AXKG-SPEC-002 공통 게이트 · SPEC-001 분류 게이트). ---
// approval_gates = 게이트 묶음, approval_gate_revisions = 실제 AI 제안(v1/v2).
// BE 스키마: apps/api/axkg/schemas/gates.py (GateResponse / RevisionResponse).

export type GateKind = "classification" | "documentation";

/** approval_gates.status (SPEC-002). generating/regenerating = AI 실행 중(폴링 대상). */
export type GateStatus =
  | "generating"
  | "regenerating"
  | "review_pending"
  | "feedback_pending"
  | "approved"
  | "failed"
  | "not_started"
  | "cancelled";

/** approval_gate_revisions.status. reviewable = 승인 가능. */
export type RevisionStatus =
  | "drafting"
  | "reviewable"
  | "approved"
  | "superseded"
  | "failed";

/** classification.v1 form (SPEC-002 Approval Gate Payload Schema · BE _FORM_FIELDS). */
export interface ClassificationForm {
  destination_type?: DestinationType;
  destination_reason?: string;
  suggested_title?: string;
  suggested_tags?: string[];
  source_type?: string;
  confidence?: number;
}

/** documentation.v1 form — BE wrap_documentation_output envelope의 form (SPEC-004 Data Contract).
 * BE: apps/api/axkg/services/ai/documentation_gate.py wrap_documentation_output. */
export type SuggestionType =
  | "supplement_existing_concept"
  | "create_new_concept"
  | "create_project_baseline";
export type ChangeKind = "create" | "modify";
// AXKG-SPEC-004 SSOT: 액션은 create_markdown / overwrite_markdown 2종 (patch 없음, BE T-019 개명).
export type FileAction = "create_markdown" | "overwrite_markdown";

export interface DraftLink {
  target?: string;
  edge_type?: string;
  link_reason?: string;
}

/** 문서화 초안 (SPEC-004 DocumentDraft). markdown_full = frontmatter+본문 전문. */
export interface DocumentDraft {
  document_type?: "reference" | "permanent" | "baseline" | string;
  target_path?: string | null;
  filename_candidate?: string | null;
  markdown_full?: string | null;
  frontmatter_preview?: string | null;
  body_preview?: string | null;
  links?: DraftLink[] | null;
}

/** 파생지식 (SPEC-004 DerivedSuggestion) — 초안과 한 덩어리, 개별 승인 없음. */
export interface DerivedSuggestion {
  suggestion_type?: SuggestionType | string;
  change_kind?: ChangeKind;
  target_path?: string | null;
  file_action?: FileAction | string;
  target_document_id?: string | null;
  draft_markdown?: string | null;
  /** modify diff preview. BE 계약 확정 전 문자열/구조 모두 방어적으로 렌더. */
  diff_preview?: string | null;
  link_reason?: string | null;
  summary?: string | null;
}

export interface ApplyPlanFileAction {
  action?: string;
  role?: string;
  target_path?: string | null;
  document_type?: string | null;
  suggestion_type?: string | null;
  change_kind?: string | null;
}

/** apply_plan preview (SPEC-004 U-5) — AI 제안, executor 가 검증 후 적용. */
export interface ApplyPlan {
  schema_version?: string;
  validation_status?: "pending" | "valid" | "invalid" | string;
  db_actions?: unknown[];
  file_actions?: ApplyPlanFileAction[];
}

/** documentation.v1 form. classification form 필드와 겹치지 않아 한 payload 에 공존. */
export interface DocumentationForm {
  destination_type?: DestinationType;
  document_draft?: DocumentDraft;
  derived_suggestions?: DerivedSuggestion[];
  apply_plan?: ApplyPlan;
}

/** revision.payload.form — 분류(ClassificationForm) 또는 문서화(DocumentationForm) 필드 공용. */
export type GateForm = ClassificationForm & DocumentationForm;

/** revision.payload — 공통 envelope(코드가 감싼 부분) + form(AI 출력). */
export interface GateRevisionPayload {
  schema_version?: string;
  gate_kind?: string;
  source_id?: string;
  summary?: {
    title?: string;
    source_url?: string;
    source_summary?: string;
  };
  form?: GateForm;
  confidence?: number | null;
  warnings?: string[];
}

export interface GateRevision {
  id: string;
  gate_id: string;
  version: number;
  status: RevisionStatus;
  payload: GateRevisionPayload;
  form_schema_version: string;
  parent_revision_id: string | null;
  feedback_id: string | null;
  ai_task_id: string | null;
  created_at: string;
  approved_at: string | null;
}

export interface Gate {
  id: string;
  source_id: string;
  gate_kind: GateKind;
  status: GateStatus;
  active_revision_id: string | null;
  approved_revision_id: string | null;
  last_ai_task_id: string | null;
  created_at: string;
  updated_at: string;
  /** 생성/진입 응답(POST)에서만 채워짐. 목록(GET)에서는 revisions 로 유도한다. */
  active_revision?: GateRevision | null;
  /** 목록(GET /sources/{id}/gates)에서 채워짐 — 버전 badge/active revision 유도용. */
  revisions?: GateRevision[] | null;
}

/** 게이트의 현재 active revision — POST 응답의 active_revision 우선, 없으면 revisions 에서 유도. */
export function activeRevisionOf(gate: Gate): GateRevision | null {
  if (gate.active_revision) return gate.active_revision;
  if (gate.revisions && gate.active_revision_id) {
    return gate.revisions.find((r) => r.id === gate.active_revision_id) ?? null;
  }
  return null;
}

/** 게이트가 AI 실행 중(폴링 필요)인지. */
export function isGateRunning(gate: Gate): boolean {
  return gate.status === "generating" || gate.status === "regenerating";
}

/** POST /sources/{id}/classification-gates — summarized source 에서 분류 게이트 생성(분류기 AI ② 트리거, SPEC-001 §4).
 * 201 로 생성된 분류 게이트(active_revision 포함, status=generating→폴링)를 반환한다. */
export function enterClassificationGate(sourceId: string): Promise<Gate> {
  return apiFetch<Gate>(
    `/sources/${encodeURIComponent(sourceId)}/classification-gates`,
    { method: "POST" },
  );
}

/** GET /sources/{id}/gates — source 의 게이트 + revision 목록(SPEC-002, 우측 스택/버전 badge용). */
export async function getSourceGates(sourceId: string): Promise<Gate[]> {
  const payload = await apiFetch<{ gates?: Gate[] }>(
    `/sources/${encodeURIComponent(sourceId)}/gates`,
  );
  return payload.gates ?? [];
}

/** POST /gates/{id}/approve — active revision 승인(destination 확정). revision_id 로 낙관적 동시성 확인(STALE_GATE_VERSION). */
export function approveGate(
  gateId: string,
  revisionId?: string | null,
): Promise<Gate> {
  return apiFetch<Gate>(`/gates/${encodeURIComponent(gateId)}/approve`, {
    method: "POST",
    body: JSON.stringify({ revision_id: revisionId ?? null }),
  });
}

/** POST /gates/{id}/feedback — 자연어 피드백 저장(review_pending→feedback_pending). 10자 미만이면 FEEDBACK_TOO_SHORT. */
export function feedbackGate(gateId: string, body: string): Promise<Gate> {
  return apiFetch<Gate>(`/gates/${encodeURIComponent(gateId)}/feedback`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

/** POST /gates/{id}/feedback (확장, 하위호환) — 문서화 게이트에 "이 destination이 아님" 재분류 요청 (SPEC-004 S-3 · BE T-009).
 * 대상은 문서화 게이트 id. 응답 = 그 문서화 게이트(cancelled → 표시 reclassification_requested).
 * 서버 부수효과: 분류 게이트 approved→regenerating + 새 분류 revision 재생성 + source destination 리셋
 * → 반드시 GET /sources/{id}/gates 재조회로 반영한다. 이유 누락 시 MISSING_NOT_THIS_DESTINATION_REASON(400),
 * 재분류 불가 상태면 RECLASSIFICATION_NOT_ALLOWED(409). */
export function requestReclassification(gateId: string, reason: string): Promise<Gate> {
  return apiFetch<Gate>(`/gates/${encodeURIComponent(gateId)}/feedback`, {
    method: "POST",
    body: JSON.stringify({
      not_this_destination: true,
      not_this_destination_reason: reason,
    }),
  });
}

/** POST /gates/{id}/regenerate — 피드백 기반 새 버전(v2) 생성 + 재생성 실행(feedback_pending→regenerating). */
export function regenerateGate(gateId: string): Promise<Gate> {
  return apiFetch<Gate>(`/gates/${encodeURIComponent(gateId)}/regenerate`, {
    method: "POST",
  });
}

/** POST /gates/{id}/retry — 실패한 게이트 생성/재생성 AI task 재실행(failed→generating/regenerating). */
export function retryGate(gateId: string): Promise<Gate> {
  return apiFetch<Gate>(`/gates/${encodeURIComponent(gateId)}/retry`, {
    method: "POST",
  });
}
