// Graph RAG 채팅 API 클라이언트 (AXKG-SPEC-006 §4 Interface Contract).
//
// BE(profile-be T-011)의 라이브 계약을 소비한다. 스키마는 apps/api/axkg/schemas/chat.py 를
// grounding 했다. 전부 `/graph` prefix · Bearer · owner 스코프 · 에러봉투 {detail:{error_code,message}}.
//
// 엔드포인트:
// - GET  /graph/chats                              내 채팅 세션 목록 (U-2 세션 목록)
// - POST /graph/chats                              새 채팅 + 첫 질문 run 생성 (queued)
// - GET  /graph/chats/{chat_id}                    채팅 메시지 이력
// - POST /graph/chats/{chat_id}/messages           기존 채팅에 질문 + 새 run 생성 (queued)
// - GET  /graph/chats/{chat_id}/runs/{run_id}      응답 생성 run 폴링
//
// 주의: 현재 BE 는 run 을 queued 로만 생성한다(Phase 2/T-012 가 answer/evidence 를 채움).
// 폴링 응답의 answer/evidence_* 는 대부분 null 이므로 렌더는 전부 null-safe 로 둔다.

import { ApiError, apiFetch, caseMessage } from "./index";

// --- run 상태 (SPEC-006 §4 폴링 status) ---
export type ChatRunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

/** terminal(폴링 종료) 상태인지. succeeded/failed/cancelled 도달 시 폴링을 멈춘다. */
export function isTerminalStatus(status: string): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

// --- 근거/제안 shape (SPEC-006 §4). BE 는 아직 list[Any] — Phase 2 가 확정한다.
// 필드명 미확정이라 흔한 키를 모두 tolerate 하는 방어적 타입으로 둔다. ---

/** Evidence Block 한 줄 (U-3). document_id 로 좌측 그래프 노드와 연동한다.
 * 필드명은 BE seed output_schema(SSOT, T-012 확정)를 그대로 따른다:
 * {document_id, stem, title, document_type, excerpt, reason}. */
export interface EvidenceDocument {
  document_id?: string | null;
  stem?: string | null;
  title?: string | null;
  document_type?: string | null;
  /** 관련 구절 요약 (U-3 "관련 구절 요약"). */
  excerpt?: string | null;
  /** 연결 이유 (U-3 "연결 이유"). */
  reason?: string | null;
}

// --- 메시지/세션 리소스 (schemas/chat.py) ---

export type ChatRole = "user" | "assistant" | "system";

/** GET /graph/chats/{chat_id} messages 아이템. evidence 는 dict[str,Any] (미확정). */
export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  sequence_no: number;
  run_id?: string | null;
  selected_node_id?: string | null;
  /** assistant 메시지의 근거 문서/엣지/경로 snapshot. 키 미확정 → 방어적으로 읽는다. */
  evidence?: Record<string, unknown> | null;
  created_at: string;
}

/** GET /graph/chats 세션 목록 아이템. */
export interface ChatSessionSummary {
  chat_id: string;
  title: string;
  status: string;
  selected_node_id?: string | null;
  last_message_at?: string | null;
  created_at: string;
  updated_at: string;
}

/** GET /graph/chats/{chat_id} 세션 + 이력. */
export interface ChatDetail {
  chat_id: string;
  title: string;
  status: string;
  selected_node_id?: string | null;
  last_message_at?: string | null;
  created_at: string;
  messages: ChatMessage[];
}

/** POST /graph/chats 응답. */
export interface ChatStartResponse {
  chat_id: string;
  run_id: string;
  status: string;
  user_message_id: string;
}

/** POST /graph/chats/{chat_id}/messages 응답. */
export interface ChatMessageResponse {
  run_id: string;
  status: string;
  user_message_id: string;
}

/** GET /graph/chats/{chat_id}/runs/{run_id} 폴링 응답 (SPEC-006 §4). */
export interface ChatRun {
  chat_id: string;
  run_id: string;
  status: string;
  assistant_message?: ChatMessage | null;
  answer?: string | null;
  evidence_documents?: EvidenceDocument[] | null;
  /** {from_stem,to_stem,edge_type,source_syntax,label} (T-012). 시안 미표시 → 현재 렌더 안 함. */
  evidence_edges?: unknown[] | null;
  /** 문서 stem 순서 목록(MVP 문서 trail, T-012). */
  used_paths?: unknown[] | null;
  /** 현재 항상 null(T-012 OQ) — FE 표시 생략. */
  confidence?: number | null;
  /** 근거 부족 시 필요한 자료 (string[], T-012). */
  missing_context?: unknown | null;
  /** 근거 부족 시 제안 (string[], T-012). */
  suggested_actions?: unknown[] | null;
  error_code?: string | null;
  error_message?: string | null;
}

// --- 요청 ---

export interface ChatAskRequest {
  question: string;
  /** 그래프에서 선택한 문서(document_id). 없으면 전체 그래프 검색(S-2). */
  selected_node_id?: string | null;
  filters?: Record<string, unknown>;
}

/** POST /graph/chats/{chat_id}/push-to-inbox 요청 (SPEC-006 §4 · WORK-009 C-1/C-2).
 * `raw_text` = push 시점까지의 채팅 대화 내용 전부(user·assistant, 제시된 방안 포함)를 직렬화한 것.
 * 직렬화 형식·조립 위치(클라 vs 서버 chat_id 조립)는 SPEC-006 §7 OQ — 여기선 클라가 직렬화해 보낸다. */
export interface PushToInboxRequest {
  raw_text: string;
  /** push 시점(대화 컷오프)을 가리키는 run — provenance 기록용(optional). */
  run_id?: string | null;
}

/** POST /graph/chats/{chat_id}/push-to-inbox 응답 — 생성된 source_channel=chat source. */
export interface PushToInboxResponse {
  source_id: string;
  /** 생성된 source 상태(`received`). */
  status: string;
}

// --- Case Matrix (SPEC-006 §4) — error_code → 프론트 문구 ---
export const CHAT_CASE_MESSAGES: Record<string, string> = {
  EMPTY_QUESTION: "질문을 입력해 주세요.",
  NODE_NOT_FOUND: "선택한 문서를 찾지 못했습니다.",
  CHAT_SESSION_NOT_FOUND: "채팅을 찾을 수 없습니다. 목록을 새로고침해 주세요.",
  INSUFFICIENT_GRAPH_CONTEXT: "현재 그래프만으로 답하기 어렵습니다.",
  // 방안 push (SPEC-006 §4 Case Matrix) — push할 대화 내용이 비어 있음.
  EMPTY_PUSH_TEXT: "인박스에 추가할 내용이 비어 있습니다.",
};

export function chatCaseMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && CHAT_CASE_MESSAGES[error.errorCode]) {
    return CHAT_CASE_MESSAGES[error.errorCode];
  }
  return caseMessage(error, fallback);
}

// --- API ---

/** GET /graph/chats — 내 채팅 세션 목록 (U-2). */
export async function listChats(): Promise<ChatSessionSummary[]> {
  const payload = await apiFetch<{ chats?: ChatSessionSummary[] }>("/graph/chats");
  return payload.chats ?? [];
}

/** POST /graph/chats — 새 채팅 + 첫 질문 run 생성. 빈 질문이면 EMPTY_QUESTION(422). */
export function startChat(body: ChatAskRequest): Promise<ChatStartResponse> {
  return apiFetch<ChatStartResponse>("/graph/chats", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** GET /graph/chats/{chat_id} — 세션 + 메시지 이력. */
export function getChat(chatId: string): Promise<ChatDetail> {
  return apiFetch<ChatDetail>(`/graph/chats/${encodeURIComponent(chatId)}`);
}

/** POST /graph/chats/{chat_id}/messages — 기존 채팅에 질문 추가 + 새 run. */
export function sendMessage(
  chatId: string,
  body: ChatAskRequest,
): Promise<ChatMessageResponse> {
  return apiFetch<ChatMessageResponse>(
    `/graph/chats/${encodeURIComponent(chatId)}/messages`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

/** GET /graph/chats/{chat_id}/runs/{run_id} — run 폴링. terminal 까지 반복 호출. */
export function getRun(chatId: string, runId: string): Promise<ChatRun> {
  return apiFetch<ChatRun>(
    `/graph/chats/${encodeURIComponent(chatId)}/runs/${encodeURIComponent(runId)}`,
  );
}

/** POST /graph/chats/{chat_id}/push-to-inbox — 제시된 방안을 Source Inbox로 push (WORK-009).
 * push 대상은 이 채팅의 대화 내용 전부(방안 포함)이며, source_channel=chat source 1건이 received 로 생성된다.
 * 권한은 staff·admin 단일 쓰기 액션 — 이후 인박스 목록/관리 표면 접근은 부여하지 않는다(SPEC-006 §4).
 * 빈 대화면 EMPTY_PUSH_TEXT(422). endpoint 최종 형태는 BE 구현과 정합(SPEC-006 §7 OQ). */
export function pushToInbox(
  chatId: string,
  body: PushToInboxRequest,
): Promise<PushToInboxResponse> {
  return apiFetch<PushToInboxResponse>(
    `/graph/chats/${encodeURIComponent(chatId)}/push-to-inbox`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

/** suggested_actions 중 "Source Inbox에 추가" push 액션인지 판별(라벨 문구 변주 tolerate). */
export function isPushAction(action: string): boolean {
  const a = action.replace(/\s+/g, "");
  return (a.includes("SourceInbox") || a.includes("인박스")) && a.includes("추가");
}

// --- evidence 방어적 파서 (BE 키 미확정 → 흔한 키를 모두 tolerate) ---

/** run 응답 또는 message.evidence dict 에서 근거 문서 목록을 뽑는다. 없으면 []. */
export function readEvidenceDocuments(
  source: ChatRun | Record<string, unknown> | null | undefined,
): EvidenceDocument[] {
  if (!source) return [];
  const obj = source as Record<string, unknown>;
  const raw = obj.evidence_documents ?? obj.documents ?? obj.evidence ?? null;
  return Array.isArray(raw) ? (raw as EvidenceDocument[]) : [];
}

/** unknown[] 를 표시용 문자열 목록으로 정규화. string 은 그대로, 객체는 흔한 라벨 키에서 추출. */
function toLabelList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((v) => {
      if (typeof v === "string") return v;
      if (v && typeof v === "object") {
        const o = v as Record<string, unknown>;
        const label = o.label ?? o.topic ?? o.title ?? o.stem ?? o.url;
        return typeof label === "string" ? label : "";
      }
      return "";
    })
    .filter((s): s is string => s.length > 0);
}

/** run 응답 또는 message.evidence dict 에서 suggested actions 를 뽑는다(string[], T-012). 없으면 []. */
export function readSuggestedActions(
  source: ChatRun | Record<string, unknown> | null | undefined,
): string[] {
  if (!source) return [];
  return toLabelList((source as Record<string, unknown>).suggested_actions);
}

/** run 응답 또는 message.evidence dict 에서 used_paths(문서 stem trail)를 뽑는다. 없으면 []. */
export function readUsedPaths(
  source: ChatRun | Record<string, unknown> | null | undefined,
): string[] {
  if (!source) return [];
  return toLabelList((source as Record<string, unknown>).used_paths);
}
