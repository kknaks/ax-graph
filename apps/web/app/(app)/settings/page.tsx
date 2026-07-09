// 설정 페이지 (AXKG-SPEC-007/009/010 · WP5 Phase 4).
// 탭 3개(AI Provider / Prompts / Templates) — 각 탭이 전체 폭을 써서 편집기를 넓게 보여준다.
// 기준: products/ax-knowledge-graph/21-html/page-settings.html 시안(탭 레이아웃·한국어 카피).
"use client";

import { useState } from "react";
import { ProviderTab } from "@/components/settings/provider-tab";
import { PromptsTab } from "@/components/settings/prompts-tab";
import { TemplatesTab } from "@/components/settings/templates-tab";

const TABS = [
  { id: "provider", label: "AI Provider" },
  { id: "prompts", label: "Prompts" },
  { id: "templates", label: "Templates" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function SettingsPage() {
  const [active, setActive] = useState<TabId>("provider");

  return (
    <main className="w-full px-6 py-6">
      <div className="mb-4">
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
      </div>

      <div className="mb-6 flex items-center gap-1 border-b border-border" role="tablist" aria-label="설정 섹션">
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

      {/* 탭별 패널 — 마운트 시 각자 데이터를 로드하므로 비활성 탭은 언마운트한다. */}
      <div role="tabpanel">
        {active === "provider" && <ProviderTab />}
        {active === "prompts" && <PromptsTab />}
        {active === "templates" && <TemplatesTab />}
      </div>
    </main>
  );
}
