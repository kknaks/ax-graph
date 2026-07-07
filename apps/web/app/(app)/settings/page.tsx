// AI Provider / Prompts / Templates 설정 (AXKG-SPEC-007/009/010). 골격만 — 기능은 WP5에서 구현.
"use client";

import { useState } from "react";

const TABS = [
  {
    id: "provider",
    label: "AI Provider",
    placeholder: "provider 선택 · timeout / max_turns / effort 설정 자리",
    wp: "WP5 · AXKG-SPEC-007",
  },
  {
    id: "prompts",
    label: "프롬프트",
    placeholder: "요약/분류/문서화 프롬프트 편집기 자리",
    wp: "WP5 · AXKG-SPEC-009",
  },
  {
    id: "templates",
    label: "템플릿",
    placeholder: "destination별 문서 템플릿 편집기 자리",
    wp: "WP5 · AXKG-SPEC-010",
  },
] as const;

export default function SettingsPage() {
  const [active, setActive] = useState<(typeof TABS)[number]["id"]>("provider");

  return (
    <main className="w-full px-6 py-6">
      <div className="mb-4">
        <h1 className="text-xl font-semibold tracking-tight">설정</h1>
      </div>

      {/* 섹션별 탭 — 각 탭이 전체 폭 사용 */}
      <div className="mb-6 flex items-center gap-1 border-b border-border" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={active === tab.id}
            onClick={() => setActive(tab.id)}
            className={
              active === tab.id
                ? "-mb-px border-b-2 border-primary px-4 py-2.5 text-sm font-medium text-foreground"
                : "-mb-px border-b-2 border-transparent px-4 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground"
            }
          >
            {tab.label}
          </button>
        ))}
      </div>

      {TABS.map((tab) => (
        <section
          key={tab.id}
          role="tabpanel"
          hidden={active !== tab.id}
          className="rounded-lg border border-border bg-card p-5 text-card-foreground shadow-sm"
        >
          <h2 className="text-sm font-semibold">{tab.label}</h2>
          <div className="mt-3 grid min-h-[320px] place-items-center rounded-md border border-dashed border-border bg-secondary/30 p-4 text-center text-xs leading-relaxed text-muted-foreground">
            {tab.placeholder}
            <br />
            {tab.wp}
          </div>
        </section>
      ))}
    </main>
  );
}
