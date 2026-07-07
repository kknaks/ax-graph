// 보호 라우트 클라이언트 가드 (AXKG-SPEC-008 Protected Routes).
// token 없음 → /login?reason=missing_token
// token 무효(/auth/me 401) → token 삭제 후 /login?reason=invalid_token
"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, clearToken, getToken, me, type ApiUser } from "@/lib/api-client";
import { AppShell } from "@/components/app-shell";

type GuardState =
  | { status: "checking" }
  | { status: "authenticated"; user: ApiUser }
  | { status: "error"; message: string };

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [state, setState] = useState<GuardState>({ status: "checking" });

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
    return <AppShell user={state.user}>{children}</AppShell>;
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
