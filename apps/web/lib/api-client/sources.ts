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
// - POST /sources/{id}/classification-gates  summarized → 분류 게이트 진입 (SPEC-001 §4, 화면은 WP3)

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

/** 분류 게이트 진입 응답(최소) — 분류 게이트 화면·md 변환은 WP3 범위 밖이라 진입 성공만 확인한다.
 * BE 계약 확정 전 방어적으로 모두 optional 로 둔다. */
export interface ClassificationGateEntry {
  gate_id?: string;
  /** 진입으로 갱신된 source (있으면 목록/상세에 반영). */
  source?: Source | null;
}

/** POST /sources/{id}/classification-gates — summarized source 를 분류 게이트로 진입(분류기 AI ② 트리거, SPEC-001 §4).
 * 분류 게이트 화면·md 변환 자체는 WP3 소관 — 여기서는 진입 호출까지만 한다. */
export function enterClassificationGate(
  sourceId: string,
): Promise<ClassificationGateEntry> {
  return apiFetch<ClassificationGateEntry>(
    `/sources/${encodeURIComponent(sourceId)}/classification-gates`,
    { method: "POST" },
  );
}
