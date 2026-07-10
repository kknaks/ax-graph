// 유저 관리 라우트 (AXKG-SPEC-008 U-3, WP6 FE-6) — admin 전용.
// 접근 경계는 AuthGuard(FE, canAccessPath)와 BE 라우트 authz가 이중 강제한다.
import { UserManagement } from "@/components/users/user-management";

export default function UsersPage() {
  return <UserManagement />;
}
