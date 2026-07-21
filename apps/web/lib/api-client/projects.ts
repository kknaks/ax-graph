// 회사 프로젝트 API 클라이언트 (AXKG-SPEC-014 §4 Interface Contract, WP11 Phase 5).
//
// "프로젝트 추가"(수동·독립 스캐폴드)와 corp 트리 열람. BE 계약은
// apps/api/axkg/api/routes/projects.py · schemas/projects.py 를 그대로 소비한다(추측 없음).
//
// 엔드포인트(admin 전용 — main.py _ADMIN_ROUTERS 로 require_admin):
// - GET  /projects:slug-preview?name=   회사명 → slug 미리보기 + 충돌 여부 (U-1)
// - POST /projects                       회사 프로젝트 스캐폴드 생성/합류/신규 분기 (U-1/U-2)
// - GET  /projects                       회사 프로젝트 목록(트리 루트) (U-3)
// - GET  /projects/{corp}                한 corp 의 origin/baseline/spec 트리 (U-3)

import { ApiError, apiFetch, caseMessage } from "./index";

// --- 요청/응답 스키마 (schemas/projects.py 와 1:1) ---

/** GET /projects:slug-preview 응답 — slugify 결과 + 기존 프로젝트 충돌 여부. */
export interface SlugPreview {
  slug: string;
  conflict: boolean;
}

/** POST /projects 요청 body. on_conflict 는 충돌 시에만 필수(merge=합류 / create_new=suffix 신규). */
export type OnConflict = "merge" | "create_new";
export interface CreateProjectRequest {
  name: string;
  on_conflict?: OnConflict | null;
}

/** POST /projects 응답 — created(신규/suffix 신규) 또는 merged(합류). */
export interface CreateProjectResult {
  slug: string;
  created?: boolean;
  merged?: boolean;
}

/** GET /projects 응답 항목 — 회사 프로젝트 루트 식별자. */
export interface ProjectSummary {
  corp: string;
}
export interface ProjectListResponse {
  projects: ProjectSummary[];
}

/** GET /projects/{corp} 응답 — 3층 폴더별 항목명 목록(origin=원본 파일, baseline/spec=문서명). */
export interface ProjectFolders {
  origin: string[];
  baseline: string[];
  spec: string[];
}
export interface ProjectTree {
  corp: string;
  folders: ProjectFolders;
}

// --- Case Matrix (SPEC-014 §4) — error_code → 프론트 문구 ---

export const PROJECT_CASE_MESSAGES: Record<string, string> = {
  EMPTY_CORP_NAME: "회사명을 입력해 주세요.",
  SLUG_CONFLICT: "이미 같은 이름의 프로젝트가 있습니다. 합류/새 프로젝트를 선택해 주세요.",
  INVALID_ON_CONFLICT: "처리 방식을 다시 선택해 주세요.",
  PROJECT_NOT_FOUND: "대상 프로젝트를 찾을 수 없습니다.",
};

export function projectCaseMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && PROJECT_CASE_MESSAGES[error.errorCode]) {
    return PROJECT_CASE_MESSAGES[error.errorCode];
  }
  return caseMessage(error, fallback);
}

// --- API ---

/** GET /projects:slug-preview?name= — 회사명 slug 미리보기 + 충돌 여부(U-1 실시간 표시). */
export function previewSlug(name: string): Promise<SlugPreview> {
  return apiFetch<SlugPreview>(
    `/projects:slug-preview?name=${encodeURIComponent(name)}`,
  );
}

/** POST /projects — 회사 프로젝트 스캐폴드 생성. 충돌 시 on_conflict 로 합류/신규 분기(U-1/U-2).
 * on_conflict 미지정 + slug 충돌이면 서버가 409 SLUG_CONFLICT → U-2 모달로 재요청한다. */
export function createProject(
  body: CreateProjectRequest,
): Promise<CreateProjectResult> {
  return apiFetch<CreateProjectResult>("/projects", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** GET /projects — 회사 프로젝트 목록(트리 루트, U-3). */
export async function listProjects(): Promise<ProjectSummary[]> {
  const payload = await apiFetch<ProjectListResponse>("/projects");
  return payload.projects ?? [];
}

/** GET /projects/{corp} — 한 corp 의 origin/baseline/spec 트리(U-3). */
export function getProjectTree(corp: string): Promise<ProjectTree> {
  return apiFetch<ProjectTree>(`/projects/${encodeURIComponent(corp)}`);
}
