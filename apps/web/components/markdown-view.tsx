// 읽기 전용 마크다운 렌더러 (PLAN-009-T-002).
// body_markdown 같은 장문 마크다운 문자열을 prose 스타일로 렌더한다.
// Tailwind prose 플러그인이 없어서 element 별 최소 타이포를 컴포넌트 내에서 직접 지정한다
// (소제목/목록/인용/코드/표 가독성 확보 · 범위 밖 전역 CSS 개편 없음).
// GFM(표·체크박스·취소선 등) 지원을 위해 remark-gfm 사용.
"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const COMPONENTS: Components = {
  h1: ({ children }) => (
    <h1 className="mb-3 mt-5 border-b border-border pb-1.5 text-lg font-semibold first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-2 mt-5 text-base font-semibold first:mt-0">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-2 mt-4 text-sm font-semibold first:mt-0">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="mb-1.5 mt-3 text-sm font-medium first:mt-0">{children}</h4>
  ),
  p: ({ children }) => (
    <p className="my-2.5 text-sm leading-relaxed text-foreground/90">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="my-2.5 list-disc space-y-1 pl-5 text-sm leading-relaxed text-foreground/90">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="my-2.5 list-decimal space-y-1 pl-5 text-sm leading-relaxed text-foreground/90">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="pl-0.5">{children}</li>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary underline underline-offset-2 hover:opacity-80"
    >
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-border pl-3 text-sm italic text-muted-foreground">
      {children}
    </blockquote>
  ),
  code: ({ className, children }) => {
    // 인라인 코드 vs 코드블록 — 코드블록은 pre 가 감싼다(아래 pre 스타일).
    const isBlock = className?.includes("language-");
    if (isBlock) {
      return <code className={`${className ?? ""} font-mono text-[12px]`}>{children}</code>;
    }
    return (
      <code className="rounded bg-secondary px-1 py-0.5 font-mono text-[12px] text-foreground">
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="scroll-thin my-3 max-h-[360px] overflow-x-auto rounded-md border border-border bg-secondary/40 p-3 font-mono text-[12px] leading-relaxed text-foreground/90">
      {children}
    </pre>
  ),
  hr: () => <hr className="my-4 border-border" />,
  table: ({ children }) => (
    <div className="scroll-thin my-3 overflow-x-auto">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="border-b border-border">{children}</thead>,
  th: ({ children }) => (
    <th className="border border-border px-2.5 py-1.5 text-left text-[13px] font-semibold">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border border-border px-2.5 py-1.5 text-[13px] text-foreground/90">
      {children}
    </td>
  ),
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  img: ({ src, alt }) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={typeof src === "string" ? src : undefined} alt={alt ?? ""} className="my-3 max-w-full rounded-md" />
  ),
};

export function MarkdownView({ markdown, className }: { markdown: string; className?: string }) {
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
