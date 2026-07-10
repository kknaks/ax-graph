// 유저 관리(admin 전용) · 본인 비밀번호 변경 API 클라이언트 (AXKG-SPEC-008).
//
// BE 계약(확정, WP6 BE-3/BE-4, PLAN-010-T-003):
//   apps/api/axkg/api/routes/users.py · schemas/users.py
//   - GET   /users               → { users: UserAdminResponse[] }
//   - POST  /users               (email/display_name/role) → UserAdminResponse (201, 기본비번 1234)
//   - PATCH /users/{id}/role     ({ role }) → UserAdminResponse
//   - PATCH /users/{id}/active   ({ is_active }) → UserAdminResponse
//   apps/api/axkg/api/routes/auth.py
//   - POST  /auth/password       ({ current_password, new_password }) → { ok }
//
// 권한: 유저 목록/생성/역할 변경/활성 토글 = admin. 비밀번호 변경 = 본인(authenticated).
// 전부 Bearer. 경계 밖 요청은 BE가 403 FORBIDDEN으로 거부한다(실제 방어선).
// 에러 코드: EMAIL_EXISTS(409) · INVALID_ROLE(422) · USER_NOT_FOUND(404) ·
// INVALID_CREDENTIALS(401, 현재 비번 불일치).

import { apiFetch, type UserRole } from "./index";

/** 관리 화면 유저 행 (email·이름·role·활성). password_hash류는 응답에 없다. */
export interface ManagedUser {
  id: string;
  email: string;
  display_name: string | null;
  role: UserRole;
  is_active: boolean;
}

interface UserListResponse {
  users: ManagedUser[];
}

export interface CreateUserRequest {
  email: string;
  display_name?: string | null;
  role: UserRole;
}

/** GET /users — 유저 목록 (admin 전용). */
export async function listUsers(): Promise<ManagedUser[]> {
  const res = await apiFetch<UserListResponse>("/users");
  return res.users;
}

/** POST /users — 유저 생성. 기본 비밀번호 `1234`로 생성된다 (SPEC-008 U-3). */
export function createUser(body: CreateUserRequest): Promise<ManagedUser> {
  return apiFetch<ManagedUser>("/users", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** PATCH /users/{id}/role — 역할 변경 (admin 전용). */
export function updateUserRole(id: string, role: UserRole): Promise<ManagedUser> {
  return apiFetch<ManagedUser>(`/users/${encodeURIComponent(id)}/role`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

/** PATCH /users/{id}/active — 활성/비활성 토글 (admin 전용). */
export function setUserActive(id: string, isActive: boolean): Promise<ManagedUser> {
  return apiFetch<ManagedUser>(`/users/${encodeURIComponent(id)}/active`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: isActive }),
  });
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

/** POST /auth/password — 본인 비밀번호 변경 (강제 아님, SPEC-008). */
export function changePassword(body: ChangePasswordRequest): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>("/auth/password", {
    method: "POST",
    body: JSON.stringify(body),
    redirectOn401: false, // 401=INVALID_CREDENTIALS(현재 비번 불일치) → 화면에서 직접 표시
  });
}
