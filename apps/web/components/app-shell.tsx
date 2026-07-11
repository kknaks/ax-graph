// 보호 앱 공통 셸 (AXKG-SPEC-008 U-2) — 상단 네비 + 사용자 표시 + 로그아웃.
// 레이아웃/톤은 21-html 시안의 헤더(Tabs형 네비) 구조를 따른다.
"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { logout, type ApiUser, type UserRole } from "@/lib/api-client";
import { defaultLanding } from "@/lib/access";

// 내비 항목별 최소 role (AXKG-SPEC-008 Access Boundary Matrix).
// staff = 그래프만. admin = 소스/그래프/설정/유저 관리 전부.
const NAV_ITEMS: {
  href: string;
  label: string;
  minRole: UserRole;
  icon: React.ReactNode;
}[] = [
  {
    href: "/",
    label: "Source Inbox",
    minRole: "admin",
    icon: (
      <path d="M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
    ),
  },
  {
    href: "/graph",
    label: "그래프",
    minRole: "staff",
    icon: (
      <>
        <rect x="16" y="16" width="6" height="6" rx="1" />
        <rect x="2" y="16" width="6" height="6" rx="1" />
        <rect x="9" y="2" width="6" height="6" rx="1" />
        <path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3M12 12V8" />
      </>
    ),
  },
  {
    href: "/settings",
    label: "설정",
    minRole: "admin",
    icon: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
      </>
    ),
  },
  {
    href: "/users",
    label: "유저 관리",
    minRole: "admin",
    icon: (
      <>
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
      </>
    ),
  },
];

/** staff는 minRole=staff 항목만, admin은 전부 본다 (SPEC-008 §4). */
function visibleNav(role: UserRole) {
  return NAV_ITEMS.filter((item) => role === "admin" || item.minRole === "staff");
}

export function AppShell({ user, children }: { user: ApiUser; children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);
  // 모바일(<md) 햄버거 드로어 열림 상태. 라우팅되면 자동으로 닫는다.
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  async function handleLogout() {
    if (loggingOut) return;
    setLoggingOut(true);
    await logout(); // 서버 revoke + localStorage token 삭제 (S-2)
    router.replace("/login");
  }

  const initial = (user.display_name ?? user.email).charAt(0).toUpperCase();

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 h-14 border-b border-border bg-background/95 backdrop-blur">
        <div className="flex h-full w-full items-center gap-4 px-4 md:gap-6 md:px-6">
          <Link
            href={defaultLanding(user.role)}
            className="flex items-center gap-2 font-semibold tracking-tight"
          >
            <svg
              className="h-5 w-5"
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
            <span>AX Knowledge Graph</span>
          </Link>

          <nav className="ml-2 hidden items-center gap-1 text-sm md:flex" aria-label="주요 화면">
            {visibleNav(user.role).map((item) => {
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={
                    active
                      ? "inline-flex items-center gap-1.5 rounded-md bg-secondary px-3 py-1.5 font-medium text-secondary-foreground"
                      : "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-muted-foreground hover:bg-secondary/60"
                  }
                >
                  <svg
                    className="h-4 w-4"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden
                  >
                    {item.icon}
                  </svg>
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto hidden items-center gap-3 md:flex">
            <div className="flex items-center gap-2 text-sm">
              <span className="grid h-7 w-7 place-items-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                {initial}
              </span>
              <span className="text-muted-foreground">{user.email}</span>
              <span className="rounded-full border border-border px-1.5 py-0.5 text-[10px] font-medium capitalize text-muted-foreground">
                {user.role}
              </span>
            </div>
            <Link
              href="/account"
              aria-current={pathname.startsWith("/account") ? "page" : undefined}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary"
            >
              <svg
                className="h-3.5 w-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              비밀번호 변경
            </Link>
            <button
              type="button"
              onClick={handleLogout}
              disabled={loggingOut}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary disabled:opacity-60"
            >
              <svg
                className="h-3.5 w-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
              </svg>
              {loggingOut ? "로그아웃 중…" : "로그아웃"}
            </button>
          </div>

          {/* 모바일 햄버거 — 네비/사용자 클러스터를 드로어로 접는다 (<md). */}
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="메뉴"
            aria-expanded={menuOpen}
            className="ml-auto inline-flex h-9 w-9 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-secondary md:hidden"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              {menuOpen ? <path d="M18 6 6 18M6 6l12 12" /> : <path d="M4 6h16M4 12h16M4 18h16" />}
            </svg>
          </button>
        </div>

        {/* 모바일 드로어(풀폭 드롭다운) — 네비 + 사용자/비밀번호 변경/로그아웃 (<md). */}
        {menuOpen && (
          <div className="absolute inset-x-0 top-14 z-30 border-b border-border bg-background shadow-lg md:hidden">
            <nav className="flex flex-col p-2" aria-label="주요 화면">
              {visibleNav(user.role).map((item) => {
                const active =
                  item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    onClick={() => setMenuOpen(false)}
                    className={
                      active
                        ? "inline-flex items-center gap-2 rounded-md bg-secondary px-3 py-2.5 text-sm font-medium text-secondary-foreground"
                        : "inline-flex items-center gap-2 rounded-md px-3 py-2.5 text-sm text-muted-foreground hover:bg-secondary/60"
                    }
                  >
                    <svg
                      className="h-4 w-4"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden
                    >
                      {item.icon}
                    </svg>
                    {item.label}
                  </Link>
                );
              })}
            </nav>
            <div className="border-t border-border p-3">
              <div className="flex items-center gap-2 px-1 text-sm">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                  {initial}
                </span>
                <span className="min-w-0 truncate text-muted-foreground">{user.email}</span>
                <span className="shrink-0 rounded-full border border-border px-1.5 py-0.5 text-[10px] font-medium capitalize text-muted-foreground">
                  {user.role}
                </span>
              </div>
              <div className="mt-2 flex flex-col gap-1.5">
                <Link
                  href="/account"
                  onClick={() => setMenuOpen(false)}
                  aria-current={pathname.startsWith("/account") ? "page" : undefined}
                  className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-xs font-medium hover:bg-secondary"
                >
                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  비밀번호 변경
                </Link>
                <button
                  type="button"
                  onClick={handleLogout}
                  disabled={loggingOut}
                  className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-xs font-medium hover:bg-secondary disabled:opacity-60"
                >
                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
                  </svg>
                  {loggingOut ? "로그아웃 중…" : "로그아웃"}
                </button>
              </div>
            </div>
          </div>
        )}
      </header>

      {children}
    </div>
  );
}
