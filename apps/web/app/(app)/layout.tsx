// 보호 앱 라우트 그룹 — 클라이언트 가드(AXKG-SPEC-008) + 공통 앱 셸.
import { AuthGuard } from "@/components/auth-guard";

export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
