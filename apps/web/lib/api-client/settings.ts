// AI Provider 설정 API 클라이언트 (AXKG-SPEC-007 §4 · WP5 Phase 4).
//
// BE 계약(확정, apps/api/axkg/api/routes/settings.py · schemas/settings.py):
// - GET    /settings/ai-provider                            → AIProviderSettings
// - PUT    /settings/ai-provider                            (body: 전역 provider/model/options/provider_options) — task_overrides 보존
// - PUT    /settings/ai-provider/task-overrides/{task_key}  (body: model?/options/provider_options) → 전체 설정
// - DELETE /settings/ai-provider/task-overrides/{task_key}  → 전체 설정(멱등)
// - GET    /settings/ai-provider/health                     → { providers: [...] }
//
// 전부 Bearer · owner 스코프. credential류 키는 BE가 응답에서 제거한다(_sanitize).

import { ApiError, apiFetch, caseMessage } from "./index";

// --- 값 도메인 (SPEC-007 Data Contract · service _validate_limits) ---

export type Provider = "claude" | "codex";
export type Effort = "low" | "medium" | "high";

/** SUPPORTED_PROVIDERS (service). 시안 provider 카드 순서. */
export const PROVIDERS: Provider[] = ["claude", "codex"];
export const EFFORTS: Effort[] = ["low", "medium", "high"];

/** 실행 한도 범위 (service _validate_limits — 클라 측 사전 검증에 사용). */
export const TIMEOUT_MIN = 30;
export const TIMEOUT_MAX = 3600;
export const MAX_TURNS_MIN = 1;
export const MAX_TURNS_MAX = 20;

/** options.* — timeout_sec(30~3600) / resume(bool). 부분 override 허용이라 전부 optional. */
export interface ExecutionOptions {
  timeout_sec?: number;
  resume?: boolean;
  [key: string]: unknown;
}

/** provider_options.* — max_turns(1~20) / effort(low|medium|high). */
export interface ProviderOptions {
  max_turns?: number;
  effort?: Effort;
  [key: string]: unknown;
}

/** task_overrides[task_key] 값 (provider는 override 대상 아님 — model/options/provider_options만). */
export interface TaskOverride {
  model?: string | null;
  options?: ExecutionOptions;
  provider_options?: ProviderOptions;
}

export interface AIProviderSettings {
  provider: Provider | string;
  model: string | null;
  options: ExecutionOptions;
  provider_options: ProviderOptions;
  task_overrides: Record<string, TaskOverride>;
  updated_at: string | null;
}

export type ProviderHealthStatus = "available" | "unavailable" | "unknown";

export interface ProviderHealth {
  provider: Provider | string;
  status: ProviderHealthStatus | string;
  message?: string | null;
}

export interface ProviderHealthResponse {
  providers: ProviderHealth[];
}

// --- 등록된 AI task definition (override 대상). ---
// SPEC-007: override는 등록·enabled task definition에만 허용(미등록/disabled = 404 UNKNOWN_TASK_DEFINITION).
// definition 목록 전용 엔드포인트가 없어(task 파일 명시) seed(apps/api/axkg/seeds.py TASK_DEFINITION_SEEDS)와
// 정합하는 알려진 key 목록을 여기 둔다. BE가 definition 목록 API를 노출하면 이 상수를 대체한다.

export interface TaskDefinition {
  key: string;
  label: string;
  promptKey: string;
}

export const TASK_DEFINITIONS: TaskDefinition[] = [
  { key: "collect_source_summary", label: "소스 요약 수집", promptKey: "source_summary" },
  { key: "generate_classification_gate", label: "분류 게이트 생성", promptKey: "classification_gate" },
  { key: "regenerate_classification_gate", label: "분류 게이트 재생성", promptKey: "classification_gate" },
  { key: "generate_documentation_gate", label: "문서화 게이트 생성", promptKey: "documentation_gate" },
  { key: "regenerate_documentation_gate", label: "문서화 게이트 재생성", promptKey: "documentation_gate" },
  { key: "graph_rag_chat", label: "그래프 채팅", promptKey: "graph_rag_chat" },
];

export function taskDefinitionLabel(key: string): string {
  return TASK_DEFINITIONS.find((d) => d.key === key)?.label ?? key;
}

export function taskPromptKey(key: string): string | null {
  return TASK_DEFINITIONS.find((d) => d.key === key)?.promptKey ?? null;
}

// --- Case Matrix (SPEC-007 §4) — error_code → 프론트 문구 ---

export const SETTINGS_CASE_MESSAGES: Record<string, string> = {
  UNSUPPORTED_PROVIDER: "지원하지 않는 provider입니다. claude 또는 codex를 선택해 주세요.",
  INVALID_EXECUTION_LIMIT: "실행 한도 값을 확인해 주세요. (timeout 30~3600초 · max_turns 1~20 · effort low/medium/high)",
  UNKNOWN_TASK_DEFINITION: "등록되지 않았거나 비활성인 작업입니다.",
};

export function settingsCaseMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && SETTINGS_CASE_MESSAGES[error.errorCode]) {
    return SETTINGS_CASE_MESSAGES[error.errorCode];
  }
  return caseMessage(error, fallback);
}

// --- 요청 payload ---

export interface PutAIProviderRequest {
  provider: Provider | string;
  model?: string | null;
  options: ExecutionOptions;
  provider_options: ProviderOptions;
}

export interface PutTaskOverrideRequest {
  model?: string | null;
  options: ExecutionOptions;
  provider_options: ProviderOptions;
}

// --- API ---

/** GET /settings/ai-provider — 현재 설정. 없으면 BE가 MVP 기본값(claude)을 반환. */
export function getAIProvider(): Promise<AIProviderSettings> {
  return apiFetch<AIProviderSettings>("/settings/ai-provider");
}

/** PUT /settings/ai-provider — 전역 디폴트 저장(task_overrides는 보내지 않아 보존). */
export function putAIProvider(body: PutAIProviderRequest): Promise<AIProviderSettings> {
  return apiFetch<AIProviderSettings>("/settings/ai-provider", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

/** PUT /settings/ai-provider/task-overrides/{task_key} — task override 추가/수정(즉시 적용). */
export function putTaskOverride(
  taskKey: string,
  body: PutTaskOverrideRequest,
): Promise<AIProviderSettings> {
  return apiFetch<AIProviderSettings>(
    `/settings/ai-provider/task-overrides/${encodeURIComponent(taskKey)}`,
    { method: "PUT", body: JSON.stringify(body) },
  );
}

/** DELETE /settings/ai-provider/task-overrides/{task_key} — override 삭제(멱등). */
export function deleteTaskOverride(taskKey: string): Promise<AIProviderSettings> {
  return apiFetch<AIProviderSettings>(
    `/settings/ai-provider/task-overrides/${encodeURIComponent(taskKey)}`,
    { method: "DELETE" },
  );
}

/** GET /settings/ai-provider/health — provider 연결 상태. */
export function getProviderHealth(): Promise<ProviderHealthResponse> {
  return apiFetch<ProviderHealthResponse>("/settings/ai-provider/health");
}
