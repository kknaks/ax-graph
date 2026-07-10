// 보호 라우트 클라이언트 가드 (AXKG-SPEC-008 Protected Routes).
// token 없음 → /login?reason=missing_token
// token 무효(/auth/me 401) → token 삭제 후 /login?reason=invalid_token
// role 경계 밖(staff가 admin 화면 접근) → 기본 진입 화면(/graph)으로 리다이렉트.
// FE 가드는 UX이고, 실제 방어선은 BE 라우트 authz다 (SPEC-008 §5).
"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ApiError, clearToken, getToken, me, type ApiUser } from "@/lib/api-client";
import { canAccessPath, defaultLanding } from "@/lib/access";
import { AppShell } from "@/components/app-shell";

type GuardState =
  | { status: "checking" }
  | { status: "authenticated"; user: ApiUser }
  | { status: "error"; message: string };

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<GuardState>({ status: "checking" });

  // role 경계 밖 화면에 있는 staff는 기본 진입 화면으로 되돌린다 (SPEC-008 §4).
  useEffect(() => {
    if (state.status !== "authenticated") return;
    if (!canAccessPath(state.user.role, pathname)) {
      router.replace(defaultLanding(state.user.role));
    }
  }, [state, pathname, router]);

  const check = useCallback(async () => {
    setState({ status: "checking" });

    const token = getToken();
    if (!token) {
      router.replace("/login?reason=missing_token");
      return;
    }

    try {
      const res = await me({ redirectOn401: false });
      setState({ status: "authenticated", user: res.user });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearToken();
        router.replace("/login?reason=invalid_token");
        return;
      }
      setState({
        status: "error",
        message: "서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.",
      });
    }
  }, [router]);

  useEffect(() => {
    void check();
  }, [check]);

  if (state.status === "authenticated") {
    // 경계 밖이면 위 effect가 리다이렉트하는 동안 admin 화면을 렌더하지 않는다.
    const allowed = canAccessPath(state.user.role, pathname);
    return (
      <AppShell user={state.user}>
        {allowed ? (
          children
        ) : (
          <main className="grid min-h-[60vh] place-items-center">
            <p className="text-sm text-muted-foreground">이동 중…</p>
          </main>
        )}
      </AppShell>
    );
  }

  if (state.status === "error") {
    return (
      <main className="grid min-h-screen place-items-center bg-muted p-4">
        <div className="w-full max-w-sm rounded-xl border border-border bg-card p-6 text-center shadow-sm">
          <p className="text-sm text-destructive">{state.message}</p>
          <button
            type="button"
            onClick={() => void check()}
            className="mt-4 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary"
          >
            다시 시도
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="grid min-h-screen place-items-center bg-muted">
      <p className="text-sm text-muted-foreground">세션 확인 중…</p>
    </main>
  );
}
