// 프롬프트 관리 API 클라이언트 (AXKG-SPEC-009 §4 · WP5 Phase 4).
//
// BE 계약(확정, apps/api/axkg/api/routes/prompts.py · schemas/prompts.py):
// - GET  /prompts                → { prompts: [PromptSummary] }
// - GET  /prompts/{key}          → PromptActive (활성 버전; 없으면 404 PROMPT_NOT_FOUND)
// - GET  /prompts/{key}/versions → { key, versions: [PromptVersion] }  (desc)
// - POST /prompts/{key}/versions (body {prompt_text, output_schema}) → 201 PromptActive (새 버전=활성)
// - POST /prompts/{key}/rollback (body {version}) → PromptActive (포인터 이동)
//
// 편집기: 본문(prompt_text) + 출력 스키마(output_schema, JSON) 를 한 버전으로 저장.

import { ApiError, apiFetch, caseMessage } from "./index";

export interface PromptSummary {
  key: string;
  name: string;
  active_version: number | null;
  updated_at: string | null;
}

export interface PromptListResponse {
  prompts: PromptSummary[];
}

/** 활성 버전 view — GET /{key}, POST versions/rollback 반환. */
export interface PromptActive {
  key: string;
  name: string;
  version: number | null;
  prompt_text: string | null;
  output_schema: Record<string, unknown> | null;
  is_active: boolean;
  updated_at: string | null;
}

export interface PromptVersion {
  version: number;
  prompt_text: string;
  output_schema: Record<string, unknown>;
  is_active: boolean;
  updated_at: string | null;
}

export interface PromptVersionListResponse {
  key: string;
  versions: PromptVersion[];
}

// --- Case Matrix (SPEC-009 §4) ---

export const PROMPT_CASE_MESSAGES: Record<string, string> = {
  PROMPT_NOT_FOUND: "프롬프트를 찾을 수 없습니다.",
  EMPTY_PROMPT_BODY: "프롬프트 본문을 입력해 주세요.",
  INVALID_OUTPUT_SCHEMA: "출력 형식(JSON schema)이 올바르지 않습니다.",
  PROMPT_VERSION_NOT_FOUND: "롤백할 버전을 찾을 수 없습니다.",
  PROMPT_SAVE_FAILED: "프롬프트를 저장하지 못했습니다. 다시 시도해 주세요.",
};

export function promptCaseMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && PROMPT_CASE_MESSAGES[error.errorCode]) {
    return PROMPT_CASE_MESSAGES[error.errorCode];
  }
  return caseMessage(error, fallback);
}

// --- 요청 ---

export interface SavePromptRequest {
  prompt_text: string;
  output_schema: Record<string, unknown>;
}

// --- API ---

export async function listPrompts(): Promise<PromptSummary[]> {
  const payload = await apiFetch<PromptListResponse>("/prompts");
  return payload.prompts ?? [];
}

export function getPrompt(key: string): Promise<PromptActive> {
  return apiFetch<PromptActive>(`/prompts/${encodeURIComponent(key)}`);
}

export async function listPromptVersions(key: string): Promise<PromptVersion[]> {
  const payload = await apiFetch<PromptVersionListResponse>(
    `/prompts/${encodeURIComponent(key)}/versions`,
  );
  return payload.versions ?? [];
}

/** POST /prompts/{key}/versions — 본문+스키마 한 쌍으로 새 버전 저장(즉시 활성). */
export function savePromptVersion(
  key: string,
  body: SavePromptRequest,
): Promise<PromptActive> {
  return apiFetch<PromptActive>(`/prompts/${encodeURIComponent(key)}/versions`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** POST /prompts/{key}/rollback — 지정 버전으로 활성 전환(포인터 이동). */
export function rollbackPrompt(key: string, version: number): Promise<PromptActive> {
  return apiFetch<PromptActive>(`/prompts/${encodeURIComponent(key)}/rollback`, {
    method: "POST",
    body: JSON.stringify({ version }),
  });
}
