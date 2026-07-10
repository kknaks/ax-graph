// 문서 템플릿 관리 API 클라이언트 (AXKG-SPEC-010 §4 · WP5 Phase 4).
//
// Prompts(SPEC-009) 미러링 — 단, 편집 대상은 문서 뼈대 md(body) 하나뿐(output_schema 없음).
// key 3종: reference / permanent / project_baseline.
//
// BE 계약(spec-010 §4 기준). **주의: 이 작업 시점 apps/api/axkg/api/routes/templates.py 는
// 라우터 stub 만 존재하고 엔드포인트 미구현(T-010 진행 중)**. 아래는 spec-010 §4 계약대로
// 배선하며, T-010 리포트/실제 응답 필드가 확정되면 미세 정합한다(is_active 파생 여부 등).
//
// - GET  /templates                → { templates: [TemplateSummary] }
// - GET  /templates/{key}          → TemplateActive (활성 버전)
// - GET  /templates/{key}/versions → { key, versions: [TemplateVersion] }
// - POST /templates/{key}/versions (body {body}) → 201 TemplateActive (새 버전=활성)
// - POST /templates/{key}/rollback (body {version}) → TemplateActive

import { ApiError, apiFetch, caseMessage } from "./index";

/** MVP 템플릿 key (seed DocumentTemplate) — 문서 타입 기반 4종 (SPEC-010 PLAN-009-T-028).
 * main 3종은 destination 매핑에서 파생, concept 는 파생 원자 개념(destination 없음, 문서화③ 고정 동봉). */
export type TemplateKey = "reference" | "permanent" | "project_baseline" | "concept";

/** key → 사람이 읽는 라벨(리스트 보조 표시). BE가 name을 주면 그걸 우선한다. */
export const TEMPLATE_LABELS: Record<string, string> = {
  reference: "reference",
  permanent: "permanent",
  project_baseline: "project_baseline",
  concept: "concept",
};

/** key → 용도 부제(시안 카피). main 3종은 destination 매핑, concept 는 destination 없이 문서화③ 조립 시 고정 동봉(SPEC-010). */
export const TEMPLATE_FLOW: Record<string, string> = {
  reference: "resource→reference",
  permanent: "area→permanent",
  project_baseline: "project→baseline",
  concept: "파생 · 문서화③ 조립 동봉",
};

export interface TemplateSummary {
  key: string;
  /** BE가 name을 제공하면 사용, 없으면 key/라벨 폴백(계약상 optional). */
  name?: string | null;
  active_version: number | null;
  updated_at: string | null;
}

export interface TemplateListResponse {
  templates: TemplateSummary[];
}

export interface TemplateActive {
  key: string;
  name?: string | null;
  version: number | null;
  body: string | null;
  is_active: boolean;
  updated_at: string | null;
}

export interface TemplateVersion {
  version: number;
  body: string;
  is_active: boolean;
  updated_at: string | null;
}

export interface TemplateVersionListResponse {
  key: string;
  versions: TemplateVersion[];
}

// --- Case Matrix (SPEC-010 §4 — Prompts 미러) ---

export const TEMPLATE_CASE_MESSAGES: Record<string, string> = {
  TEMPLATE_NOT_FOUND: "템플릿을 찾을 수 없습니다.",
  EMPTY_TEMPLATE_BODY: "템플릿 본문을 입력해 주세요.",
  TEMPLATE_VERSION_NOT_FOUND: "롤백할 버전을 찾을 수 없습니다.",
  TEMPLATE_SAVE_FAILED: "템플릿을 저장하지 못했습니다. 다시 시도해 주세요.",
};

export function templateCaseMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && TEMPLATE_CASE_MESSAGES[error.errorCode]) {
    return TEMPLATE_CASE_MESSAGES[error.errorCode];
  }
  return caseMessage(error, fallback);
}

// --- 요청 ---

export interface SaveTemplateRequest {
  body: string;
}

// --- API ---

export async function listTemplates(): Promise<TemplateSummary[]> {
  const payload = await apiFetch<TemplateListResponse>("/templates");
  return payload.templates ?? [];
}

export function getTemplate(key: string): Promise<TemplateActive> {
  return apiFetch<TemplateActive>(`/templates/${encodeURIComponent(key)}`);
}

export async function listTemplateVersions(key: string): Promise<TemplateVersion[]> {
  const payload = await apiFetch<TemplateVersionListResponse>(
    `/templates/${encodeURIComponent(key)}/versions`,
  );
  return payload.versions ?? [];
}

/** POST /templates/{key}/versions — md 뼈대 새 버전 저장(즉시 활성). */
export function saveTemplateVersion(
  key: string,
  body: SaveTemplateRequest,
): Promise<TemplateActive> {
  return apiFetch<TemplateActive>(`/templates/${encodeURIComponent(key)}/versions`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** POST /templates/{key}/rollback — 지정 버전으로 활성 전환(포인터 이동). */
export function rollbackTemplate(key: string, version: number): Promise<TemplateActive> {
  return apiFetch<TemplateActive>(`/templates/${encodeURIComponent(key)}/rollback`, {
    method: "POST",
    body: JSON.stringify({ version }),
  });
}
