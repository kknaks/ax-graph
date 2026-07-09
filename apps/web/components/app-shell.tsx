// 보호 앱 공통 셸 (AXKG-SPEC-008 U-2) — 상단 네비 + 사용자 표시 + 로그아웃.
// 레이아웃/톤은 21-html 시안의 헤더(Tabs형 네비) 구조를 따른다.
"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { logout, type ApiUser } from "@/lib/api-client";

const NAV_ITEMS = [
  {
    href: "/",
    label: "Source Inbox",
    icon: (
      <path d="M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
    ),
  },
  {
    href: "/graph",
    label: "그래프",
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
    icon: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
      </>
    ),
  },
];

export function AppShell({ user, children }: { user: ApiUser; children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

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
        <div className="flex h-full w-full items-center gap-6 px-6">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
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

          <nav className="ml-2 flex items-center gap-1 text-sm" aria-label="주요 화면">
            {NAV_ITEMS.map((item) => {
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

          <div className="ml-auto flex items-center gap-3">
            <div className="flex items-center gap-2 text-sm">
              <span className="grid h-7 w-7 place-items-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                {initial}
              </span>
              <span className="text-muted-foreground">{user.email}</span>
            </div>
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
        </div>
      </header>

      {children}
    </div>
  );
}
