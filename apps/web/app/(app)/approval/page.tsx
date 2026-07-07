// 요약·분류 카드 + 분류/문서화 게이트 중앙 세로 스택 (AXKG-SPEC-001/002/004). 골격만 — 기능은 WP3에서 구현.
export default function ApprovalPage() {
  return (
    <main className="w-full px-6 py-5">
      <div className="mb-4">
        <h1 className="text-xl font-semibold tracking-tight">승인 워크플로우</h1>
      </div>

      {/* 중앙 세로 스택: ① 요약·분류 카드 → ② 분류 게이트 → ③ 문서화 승인 게이트 */}
      <div className="mx-auto max-w-4xl space-y-4">
        <section className="rounded-lg border border-border bg-card text-card-foreground shadow-sm">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">
              ① 요약·분류 카드 <span className="font-normal text-muted-foreground">· 요약 AI</span>
            </h2>
          </div>
          <div className="p-3">
            <div className="grid min-h-[140px] place-items-center rounded-md border border-dashed border-border bg-secondary/30 p-4 text-center text-xs leading-relaxed text-muted-foreground">
              제목·요약·태그 (frontmatter 시드) 자리
              <br />
              WP3 · AXKG-SPEC-001
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-border bg-card text-card-foreground shadow-sm">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">
              ② 분류 게이트{" "}
              <span className="font-normal text-muted-foreground">· PARA · v2 | v1 read-only</span>
            </h2>
          </div>
          <div className="p-3">
            <div className="grid min-h-[140px] place-items-center rounded-md border border-dashed border-border bg-secondary/30 p-4 text-center text-xs leading-relaxed text-muted-foreground">
              PARA 후보 + confidence + 피드백/승인 CTA 자리
              <br />
              WP3 · AXKG-SPEC-001/002
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-border bg-card text-card-foreground shadow-sm">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">
              ③ 문서화 승인 게이트{" "}
              <span className="font-normal text-muted-foreground">
                · AI 초안 + 파생지식 + apply plan
              </span>
            </h2>
          </div>
          <div className="p-3">
            <div className="grid min-h-[200px] place-items-center rounded-md border border-dashed border-border bg-secondary/30 p-4 text-center text-xs leading-relaxed text-muted-foreground">
              초안 preview(접기/펴기) + 파생지식 + apply_plan preview 자리
              <br />
              WP3 · AXKG-SPEC-004
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
