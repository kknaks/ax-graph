// 그래프 탐색 + Graph RAG chat (AXKG-SPEC-005/006). 골격만 — 기능은 WP2/WP4에서 구현.
export default function GraphPage() {
  return (
    <main className="flex h-[calc(100vh-3.5rem)] w-full flex-col px-6 py-5">
      <div className="mb-4">
        <h1 className="text-xl font-semibold tracking-tight">그래프 탐색 + Graph RAG 채팅</h1>
      </div>

      {/* [graph] | [chat] split view */}
      <div className="grid min-h-0 flex-1 grid-cols-[1fr_460px] gap-4">
        <section className="flex h-full flex-col rounded-lg border border-border bg-card text-card-foreground shadow-sm">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">문서 그래프</h2>
          </div>
          <div className="relative min-h-0 flex-1 overflow-hidden rounded-b-lg bg-[radial-gradient(hsl(var(--border))_1px,transparent_1px)] [background-size:22px_22px]">
            <div className="grid h-full place-items-center text-center text-xs leading-relaxed text-muted-foreground">
              그래프 캔버스 자리 (노드/엣지 · assoc [[ ]] · lineage up:)
              <br />
              WP2 · AXKG-SPEC-005
            </div>
          </div>
        </section>

        <section className="flex h-full flex-col rounded-lg border border-border bg-card text-card-foreground shadow-sm">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">Graph RAG 채팅</h2>
          </div>
          <div className="min-h-0 flex-1 p-3">
            <div className="grid h-full place-items-center rounded-md border border-dashed border-border bg-secondary/30 p-4 text-center text-xs leading-relaxed text-muted-foreground">
              chat 패널 자리 (질문 → evidence document 노출)
              <br />
              WP4 · AXKG-SPEC-006
            </div>
          </div>
          <div className="border-t border-border p-3">
            <input
              disabled
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm opacity-50"
              placeholder="그래프에 질문하기 (WP4)"
            />
          </div>
        </section>
      </div>
    </main>
  );
}
