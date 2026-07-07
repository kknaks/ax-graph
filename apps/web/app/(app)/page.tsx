// Source Inbox 큐 첫 화면 (AXKG-SPEC-003). 골격만 — 기능은 WP1에서 구현.
export default function Home() {
  return (
    <main className="w-full px-6 py-5">
      <div className="mb-4">
        <h1 className="text-xl font-semibold tracking-tight">Source Inbox</h1>
      </div>

      {/* 좌: 큐 목록 (300px) / 우: 선택 source 상세 (1fr) */}
      <div className="grid grid-cols-[300px_1fr] gap-4">
        <section className="rounded-lg border border-border bg-card text-card-foreground shadow-sm">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">Source Inbox</h2>
            <button
              type="button"
              disabled
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium opacity-50"
            >
              Inbox에 넣기
            </button>
          </div>
          <div className="p-3">
            <div className="grid min-h-[480px] place-items-center rounded-md border border-dashed border-border bg-secondary/30 p-4 text-center text-xs leading-relaxed text-muted-foreground">
              큐 목록 자리
              <br />
              WP1 · AXKG-SPEC-003
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-border bg-card text-card-foreground shadow-sm">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">Source 상세</h2>
          </div>
          <div className="p-3">
            <div className="grid min-h-[480px] place-items-center rounded-md border border-dashed border-border bg-secondary/30 p-4 text-center text-xs leading-relaxed text-muted-foreground">
              선택한 source 상세 자리 (요약·상태·메타)
              <br />
              WP1 · AXKG-SPEC-003
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
