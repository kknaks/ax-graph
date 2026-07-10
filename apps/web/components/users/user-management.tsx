// 유저 관리 화면 (AXKG-SPEC-008 U-3, WP6 FE-6) — admin 전용.
// 목록(이름·이메일·role·활성) · 생성(기본비번 1234 안내) · 역할 변경 · 활성 토글.
// 시안(21-html) 부재 → 설정 화면(page-settings) 톤 차용(사용자 확정). Select/ConfirmDialog 재사용.
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createUser,
  listUsers,
  setUserActive,
  updateUserRole,
  type ManagedUser,
} from "@/lib/api-client/users";
import { caseMessage, type UserRole } from "@/lib/api-client";
import { Select } from "@/components/ui/select";
import { ConfirmDialog } from "@/components/settings/confirm-dialog";

const ROLE_OPTIONS = [
  { value: "staff", label: "staff" },
  { value: "admin", label: "admin" },
];

const DEFAULT_PASSWORD = "1234";

interface CreateDraft {
  email: string;
  display_name: string;
  role: UserRole;
}

const EMPTY_DRAFT: CreateDraft = { email: "", display_name: "", role: "staff" };

export function UserManagement() {
  const [users, setUsers] = useState<ManagedUser[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // 행 단위 busy (role 변경·활성 토글 중복 클릭 방지)
  const [rowBusy, setRowBusy] = useState<Record<string, boolean>>({});
  const [rowError, setRowError] = useState<string | null>(null);

  // 생성 모달
  const [createOpen, setCreateOpen] = useState(false);
  const [draft, setDraft] = useState<CreateDraft>(EMPTY_DRAFT);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // 비활성화 확인
  const [deactivateUser, setDeactivateUser] = useState<ManagedUser | null>(null);
  const [deactivateBusy, setDeactivateBusy] = useState(false);
  const [deactivateError, setDeactivateError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await listUsers();
      setUsers(list);
      setLoadError(null);
    } catch (err) {
      setLoadError(caseMessage(err, "유저 목록을 불러오지 못했습니다."));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const setBusy = useCallback((id: string, busy: boolean) => {
    setRowBusy((prev) => ({ ...prev, [id]: busy }));
  }, []);

  const sorted = useMemo(() => {
    if (!users) return null;
    // admin 먼저, 그다음 이름/이메일 순.
    return [...users].sort((a, b) => {
      if (a.role !== b.role) return a.role === "admin" ? -1 : 1;
      return (a.display_name ?? a.email).localeCompare(b.display_name ?? b.email);
    });
  }, [users]);

  async function changeRole(u: ManagedUser, role: UserRole) {
    if (role === u.role) return;
    setBusy(u.id, true);
    setRowError(null);
    try {
      const next = await updateUserRole(u.id, role);
      setUsers((prev) => prev?.map((x) => (x.id === u.id ? next : x)) ?? prev);
    } catch (err) {
      setRowError(caseMessage(err, "역할을 변경하지 못했습니다."));
    } finally {
      setBusy(u.id, false);
    }
  }

  async function toggleActive(u: ManagedUser) {
    // 활성화는 즉시, 비활성화는 확인 후 (로그인 차단이므로).
    if (u.is_active) {
      setDeactivateError(null);
      setDeactivateUser(u);
      return;
    }
    setBusy(u.id, true);
    setRowError(null);
    try {
      const next = await setUserActive(u.id, true);
      setUsers((prev) => prev?.map((x) => (x.id === u.id ? next : x)) ?? prev);
    } catch (err) {
      setRowError(caseMessage(err, "활성 상태를 변경하지 못했습니다."));
    } finally {
      setBusy(u.id, false);
    }
  }

  async function confirmDeactivate() {
    if (!deactivateUser) return;
    setDeactivateBusy(true);
    setDeactivateError(null);
    try {
      const next = await setUserActive(deactivateUser.id, false);
      setUsers((prev) => prev?.map((x) => (x.id === deactivateUser.id ? next : x)) ?? prev);
      setDeactivateUser(null);
    } catch (err) {
      setDeactivateError(caseMessage(err, "비활성화하지 못했습니다."));
    } finally {
      setDeactivateBusy(false);
    }
  }

  async function submitCreate() {
    if (!draft.email.trim()) {
      setCreateError("이메일을 입력해 주세요.");
      return;
    }
    setCreateBusy(true);
    setCreateError(null);
    try {
      const created = await createUser({
        email: draft.email.trim(),
        display_name: draft.display_name.trim() || null,
        role: draft.role,
      });
      setUsers((prev) => (prev ? [...prev, created] : [created]));
      setCreateOpen(false);
      setDraft(EMPTY_DRAFT);
    } catch (err) {
      setCreateError(caseMessage(err, "유저를 생성하지 못했습니다."));
    } finally {
      setCreateBusy(false);
    }
  }

  return (
    <main className="w-full px-6 py-6">
      <div className="mb-4 flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">유저 관리</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            생성·역할 변경·활성 토글은 admin 전용입니다. 새 계정 기본 비밀번호는{" "}
            <span className="font-mono">{DEFAULT_PASSWORD}</span> 입니다.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setCreateError(null);
            setDraft(EMPTY_DRAFT);
            setCreateOpen(true);
          }}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path d="M5 12h14M12 5v14" />
          </svg>
          유저 추가
        </button>
      </div>

      {rowError && (
        <p className="mb-3 rounded-md px-3 py-2 text-xs text-destructive" style={{ background: "hsl(var(--destructive) / .08)" }}>
          {rowError}
        </p>
      )}

      <section className="rounded-lg border border-border bg-card shadow-sm">
        <div className="grid grid-cols-[1.2fr_1.6fr_.9fr_.9fr] gap-2 border-b border-border px-4 py-2.5 text-[11px] font-medium text-muted-foreground">
          <div>이름</div>
          <div>이메일</div>
          <div>역할</div>
          <div className="text-right">활성</div>
        </div>

        {loadError ? (
          <p className="px-4 py-8 text-center text-xs text-destructive">{loadError}</p>
        ) : sorted == null ? (
          <p className="px-4 py-8 text-center text-xs text-muted-foreground">불러오는 중…</p>
        ) : sorted.length === 0 ? (
          <p className="px-4 py-8 text-center text-xs text-muted-foreground">유저가 없습니다.</p>
        ) : (
          <div className="divide-y divide-border">
            {sorted.map((u) => {
              const busy = !!rowBusy[u.id];
              return (
                <div
                  key={u.id}
                  className="grid grid-cols-[1.2fr_1.6fr_.9fr_.9fr] items-center gap-2 px-4 py-2.5 text-sm"
                >
                  <span className="truncate font-medium" title={u.display_name ?? "-"}>
                    {u.display_name ?? "-"}
                  </span>
                  <span className="truncate font-mono text-xs text-muted-foreground" title={u.email}>
                    {u.email}
                  </span>
                  <div className="max-w-[120px]">
                    <Select
                      value={u.role}
                      onValueChange={(v) => void changeRole(u, v as UserRole)}
                      options={ROLE_OPTIONS}
                      disabled={busy}
                      ariaLabel={`${u.email} 역할`}
                    />
                  </div>
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={() => void toggleActive(u)}
                      disabled={busy}
                      className={
                        u.is_active
                          ? "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium disabled:opacity-60"
                          : "inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-[11px] font-medium text-muted-foreground disabled:opacity-60"
                      }
                      style={
                        u.is_active
                          ? { borderColor: "hsl(var(--tier-ok) / .4)", color: "hsl(var(--tier-ok))" }
                          : undefined
                      }
                      title={u.is_active ? "클릭하면 비활성화" : "클릭하면 활성화"}
                    >
                      <span
                        className="h-1.5 w-1.5 rounded-full"
                        style={{ background: u.is_active ? "hsl(var(--tier-ok))" : "hsl(var(--muted-foreground))" }}
                      />
                      {u.is_active ? "활성" : "비활성"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* 유저 생성 모달 */}
      {createOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="유저 추가"
          onClick={(e) => {
            if (e.target === e.currentTarget && !createBusy) setCreateOpen(false);
          }}
        >
          <div className="w-full max-w-md rounded-xl border border-border bg-background p-5 shadow-xl">
            <h3 className="text-sm font-semibold">유저 추가</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              기본 비밀번호 <span className="font-mono">{DEFAULT_PASSWORD}</span> 로 생성됩니다. 최초
              로그인 후 본인이 변경합니다(강제 아님).
            </p>

            <label htmlFor="cu-email" className="mt-4 block text-[11px] font-medium text-muted-foreground">
              이메일
            </label>
            <input
              id="cu-email"
              type="email"
              autoComplete="off"
              value={draft.email}
              onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))}
              disabled={createBusy}
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
              placeholder="name@medisolveai.com"
            />

            <label htmlFor="cu-name" className="mt-3 block text-[11px] font-medium text-muted-foreground">
              이름
            </label>
            <input
              id="cu-name"
              type="text"
              autoComplete="off"
              value={draft.display_name}
              onChange={(e) => setDraft((d) => ({ ...d, display_name: e.target.value }))}
              disabled={createBusy}
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60"
              placeholder="이름 (선택)"
            />

            <span className="mt-3 block text-[11px] font-medium text-muted-foreground">역할</span>
            <div className="mt-1 max-w-[160px]">
              <Select
                value={draft.role}
                onValueChange={(v) => setDraft((d) => ({ ...d, role: v as UserRole }))}
                options={ROLE_OPTIONS}
                disabled={createBusy}
                ariaLabel="역할"
              />
            </div>

            {createError && (
              <p className="mt-3 rounded-md px-2.5 py-2 text-[11px] text-destructive" style={{ background: "hsl(var(--destructive) / .08)" }}>
                {createError}
              </p>
            )}

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => (createBusy ? undefined : setCreateOpen(false))}
                disabled={createBusy}
                className="rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-secondary disabled:opacity-50"
              >
                취소
              </button>
              <button
                type="button"
                onClick={() => void submitCreate()}
                disabled={createBusy}
                className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
              >
                {createBusy ? "생성 중…" : "생성"}
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={deactivateUser != null}
        title="유저 비활성화"
        body={
          deactivateUser ? (
            <>
              <span className="font-medium">{deactivateUser.display_name ?? deactivateUser.email}</span> 계정을
              비활성화합니다. 비활성 계정은 로그인할 수 없습니다.
            </>
          ) : null
        }
        confirmLabel="비활성화"
        tone="danger"
        busy={deactivateBusy}
        error={deactivateError}
        onConfirm={() => void confirmDeactivate()}
        onClose={() => (deactivateBusy ? undefined : setDeactivateUser(null))}
      />
    </main>
  );
}
