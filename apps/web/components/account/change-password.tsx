// 본인 비밀번호 변경 (AXKG-SPEC-008 U-2 CTA, WP6 FE-7) — staff·admin 공통(본인 자율).
// 현재 비번 + 새 비번(+확인). 최초 로그인 강제 변경 없음. 설정 화면 톤 차용.
"use client";

import { useState } from "react";
import { changePassword } from "@/lib/api-client/users";
import { ApiError, caseMessage } from "@/lib/api-client";

export function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  function reset() {
    setCurrent("");
    setNext("");
    setConfirm("");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;

    setDone(false);
    if (!current || !next) {
      setError("현재 비밀번호와 새 비밀번호를 입력해 주세요.");
      return;
    }
    if (next !== confirm) {
      setError("새 비밀번호가 일치하지 않습니다.");
      return;
    }
    if (next === current) {
      setError("새 비밀번호가 현재 비밀번호와 같습니다.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await changePassword({ current_password: current, new_password: next });
      setDone(true);
      reset();
    } catch (err) {
      // 이 화면의 401은 "현재 비밀번호 불일치"다(세션 만료 아님) — 로그인용 문구 대신 맥락 문구.
      if (err instanceof ApiError && err.errorCode === "INVALID_CREDENTIALS") {
        setError("현재 비밀번호가 올바르지 않습니다.");
      } else {
        setError(caseMessage(err, "비밀번호를 변경하지 못했습니다."));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="w-full px-6 py-6">
      <div className="mb-4">
        <h1 className="text-xl font-semibold tracking-tight">본인 계정</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">비밀번호 변경 (본인 자율)</p>
      </div>

      <section className="max-w-md rounded-lg border border-border bg-card p-5 shadow-sm">
        <h2 className="text-sm font-semibold">비밀번호 변경</h2>
        <form onSubmit={handleSubmit} noValidate className="mt-4">
          <label htmlFor="cp-current" className="text-[11px] font-medium text-muted-foreground">
            현재 비밀번호
          </label>
          <input
            id="cp-current"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            disabled={submitting}
            className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
          />

          <label htmlFor="cp-next" className="mt-3 block text-[11px] font-medium text-muted-foreground">
            새 비밀번호
          </label>
          <input
            id="cp-next"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            disabled={submitting}
            className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
          />

          <label htmlFor="cp-confirm" className="mt-3 block text-[11px] font-medium text-muted-foreground">
            새 비밀번호 확인
          </label>
          <input
            id="cp-confirm"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            disabled={submitting}
            className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
          />

          {error && (
            <p role="alert" className="mt-3 rounded-md px-2.5 py-2 text-[11px] text-destructive" style={{ background: "hsl(var(--destructive) / .08)" }}>
              {error}
            </p>
          )}
          {done && (
            <p className="mt-3 flex items-center gap-1.5 text-[11px]" style={{ color: "hsl(var(--tier-ok))" }}>
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M20 6 9 17l-5-5" />
              </svg>
              비밀번호를 변경했습니다.
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="mt-4 w-full rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
          >
            {submitting ? "변경 중…" : "비밀번호 변경"}
          </button>
        </form>
      </section>
    </main>
  );
}
