// 토큰 로그인 (AXKG-SPEC-008 U-1). WP0 Phase 4.
"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CASE_MESSAGES, caseMessage, getToken, login, setToken } from "@/lib/api-client";
import { defaultLanding } from "@/lib/access";

/** 보호 라우트에서 넘어온 이유 (Case Matrix — App Shell 문구를 로그인 화면에서 안내) */
const REASON_MESSAGES: Record<string, string> = {
  missing_token: CASE_MESSAGES.MISSING_TOKEN,
  invalid_token: CASE_MESSAGES.INVALID_TOKEN,
};

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const reason = searchParams.get("reason");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 로그인 상태에서 /login 접근 시 / 로 (token 유효성은 앱 셸 가드가 검증)
  useEffect(() => {
    if (getToken()) router.replace("/");
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;

    // Validation: email/password 비어 있으면 안 됨 (SPEC-008 Validation)
    if (!email.trim() || !password) {
      setError("이메일과 비밀번호를 입력해 주세요.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const res = await login(email.trim(), password);
      setToken(res.token); // localStorage 저장 (SPEC-008 Token Storage)
      // role 기본 진입 화면으로 이동 (staff=/graph, admin=Source Inbox) — SPEC-008 S-1.
      router.replace(defaultLanding(res.user.role));
    } catch (err) {
      setError(caseMessage(err, "로그인에 실패했습니다. 잠시 후 다시 시도해 주세요."));
      setSubmitting(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-muted p-4">
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-6 shadow-sm">
        <div className="mb-5 flex items-center gap-2">
          <svg
            className="h-6 w-6"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <rect x="9" y="9" width="6" height="6" rx="1" />
            <rect x="3" y="3" width="6" height="6" rx="1" />
            <rect x="15" y="3" width="6" height="6" rx="1" />
            <rect x="3" y="15" width="6" height="6" rx="1" />
            <rect x="15" y="15" width="6" height="6" rx="1" />
            <path d="M6 9v6M18 9v6M9 6h6M9 18h6" />
          </svg>
          <div>
            <div className="text-sm font-semibold tracking-tight">AX Knowledge Graph</div>
            <div className="text-[11px] text-muted-foreground">seed 계정으로 로그인</div>
          </div>
        </div>

        {reason && REASON_MESSAGES[reason] && !error && (
          <p className="mb-3 rounded-md bg-secondary px-3 py-2 text-xs text-secondary-foreground">
            {REASON_MESSAGES[reason]}
          </p>
        )}

        <form onSubmit={handleSubmit} noValidate>
          <label htmlFor="login-email" className="text-[11px] font-medium text-muted-foreground">
            Email
          </label>
          <input
            id="login-email"
            type="email"
            autoComplete="email"
            className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40"
            placeholder="kknaks@medisolveai.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={submitting}
          />
          <label
            htmlFor="login-password"
            className="mt-3 block text-[11px] font-medium text-muted-foreground"
          >
            Password
          </label>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40"
            placeholder="••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={submitting}
          />

          {error && (
            <p
              role="alert"
              className="mt-2 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive"
            >
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="mt-4 w-full rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
          >
            {submitting ? "로그인 중…" : "로그인"}
          </button>
        </form>

        <p className="mt-3 text-center text-[10px] text-muted-foreground">
          MVP seed · <span className="font-mono">kknaks@medisolveai.com / 1234</span> · localStorage
          token
        </p>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
