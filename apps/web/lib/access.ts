// FE 접근 경계 (AXKG-SPEC-008 §4 Access Boundary Matrix).
// 이 매트릭스가 제품 전체 접근 경계 SSOT이며, FE 가드(UX)와 BE 라우트 authz(방어선)
// 양쪽에서 이중 강제한다 — FE 가드만으로 신뢰하지 않는다.
//
// staff 접근 가능: 그래프+채팅④(`/graph`) · 문서 라이브러리(`/documents`, AXKG-SPEC-013 §7
// 사용자 확정 2026-07-11: admin+staff 허용) · 본인 계정(`/account`).
// 소스 inbox·게이트·설정·유저 관리는 admin 전용.
import type { UserRole } from "@/lib/api-client";

/** staff에게 열려 있는 경로 prefix (그 외 전부 admin 전용). */
const STAFF_PATH_PREFIXES = ["/graph", "/documents", "/account"];

/** role이 해당 pathname에 접근 가능한지. admin은 전부 허용. */
export function canAccessPath(role: UserRole, pathname: string): boolean {
  if (role === "admin") return true;
  return STAFF_PATH_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
}

/** role 분기 후 기본 진입 화면 (staff는 `/graph`, admin은 Source Inbox). */
export function defaultLanding(role: UserRole): string {
  return role === "staff" ? "/graph" : "/";
}
