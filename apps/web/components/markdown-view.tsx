// 읽기 전용 마크다운 렌더러 (PLAN-009-T-002 · 타이포 폴리싱 PLAN-012-T-008).
// body_markdown 같은 장문 마크다운 문자열을 prose 스타일로 렌더한다.
// Tailwind prose 플러그인이 없어서 element 별 최소 타이포를 컴포넌트 내에서 직접 지정한다
// (소제목/목록/인용/코드/표 가독성 확보 · 범위 밖 전역 CSS 개편 없음).
// GFM(표·체크박스·취소선 등) 지원을 위해 remark-gfm 사용.
// headingIds=true 일 때만 h1~h3 에 안정 id 를 부여한다(문서 라이브러리 TOC 전용 opt-in) —
// 기본은 false 라 다른 사용처(문서 모달·gate-history·stale-documents) 렌더는 무변경.
"use client";

import { isValidElement, useMemo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { slugify } from "@/lib/markdown-headings";

/** react node 트리에서 텍스트만 추출(heading slug 계산용). */
function nodeText(node: ReactNode): string {
  if (node == null || node === false || node === true) return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (isValidElement(node)) {
    return nodeText((node.props as { children?: ReactNode }).children);
  }
  return "";
}

// heading 을 뺀 공통 element 스타일 — id 유무와 무관하게 재사용.
const BODY_COMPONENTS: Components = {
  p: ({ children }) => (
    <p className="my-3 text-sm leading-7 text-foreground/90">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="my-3 list-disc space-y-1.5 pl-5 text-sm leading-7 text-foreground/90 marker:text-muted-foreground">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="my-3 list-decimal space-y-1.5 pl-5 text-sm leading-7 text-foreground/90 marker:text-muted-foreground">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="pl-1 [&>ul]:my-1.5 [&>ol]:my-1.5">{children}</li>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="font-medium text-primary underline decoration-primary/40 underline-offset-2 transition-colors hover:decoration-primary"
    >
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-4 border-l-2 border-primary/40 bg-secondary/25 py-1 pl-4 pr-3 text-sm leading-7 italic text-muted-foreground [&>p]:my-1.5">
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
      <code className="rounded border border-border/60 bg-secondary px-1.5 py-0.5 font-mono text-[12.5px] text-foreground">
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="scroll-thin my-4 max-h-[360px] overflow-x-auto rounded-lg border border-border bg-secondary/40 p-3.5 font-mono text-[12px] leading-relaxed text-foreground/90">
      {children}
    </pre>
  ),
  hr: () => <hr className="my-6 border-border" />,
  table: ({ children }) => (
    <div className="scroll-thin my-4 overflow-x-auto rounded-lg border border-border">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-secondary/50">{children}</thead>,
  th: ({ children }) => (
    <th className="border-b border-border px-3 py-2 text-left text-[13px] font-semibold text-foreground">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-border/60 px-3 py-2 align-top text-[13px] leading-6 text-foreground/90">
      {children}
    </td>
  ),
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  img: ({ src, alt }) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={typeof src === "string" ? src : undefined} alt={alt ?? ""} className="my-3 max-w-full rounded-md border border-border" />
  ),
};

// heading 클래스(위계 뚜렷 — 사이즈/굵기/여백/보더). id 유무와 공유.
const H1_CLS = "mb-3 mt-7 border-b border-border pb-2 text-xl font-bold tracking-tight first:mt-0";
const H2_CLS = "mb-2.5 mt-7 border-b border-border/50 pb-1.5 text-lg font-semibold tracking-tight first:mt-0";
const H3_CLS = "mb-2 mt-5 text-base font-semibold first:mt-0";
const H4_CLS = "mb-1.5 mt-4 text-sm font-semibold text-foreground/90 first:mt-0";

// id 없는 기본 heading(다른 사용처와 동일 동작).
const PLAIN_HEADINGS: Components = {
  h1: ({ children }) => <h1 className={H1_CLS}>{children}</h1>,
  h2: ({ children }) => <h2 className={H2_CLS}>{children}</h2>,
  h3: ({ children }) => <h3 className={H3_CLS}>{children}</h3>,
  h4: ({ children }) => <h4 className={H4_CLS}>{children}</h4>,
};

const PLAIN_COMPONENTS: Components = { ...BODY_COMPONENTS, ...PLAIN_HEADINGS };

export function MarkdownView({
  markdown,
  className,
  headingIds = false,
}: {
  markdown: string;
  className?: string;
  /** true 면 h1~h3 에 안정 id 부여(TOC 스크롤 타깃). 기본 false — 다른 사용처 무변경. */
  headingIds?: boolean;
}) {
  // heading id = 텍스트만의 순수 함수(slugify) — 렌더 횟수/순서와 무관하게 결정적이라
  // StrictMode 이중 렌더에도 안전하다. 중복 heading 은 같은 id, TOC 클릭은 첫 위치로 점프.
  const components = useMemo<Components>(() => {
    if (!headingIds) return PLAIN_COMPONENTS;
    // scroll-mt: TOC 클릭 스크롤 시 heading 이 pane 상단에 딱 붙지 않게 여백.
    return {
      ...BODY_COMPONENTS,
      h1: ({ children }) => (
        <h1 id={slugify(nodeText(children))} className={`scroll-mt-4 ${H1_CLS}`}>
          {children}
        </h1>
      ),
      h2: ({ children }) => (
        <h2 id={slugify(nodeText(children))} className={`scroll-mt-4 ${H2_CLS}`}>
          {children}
        </h2>
      ),
      h3: ({ children }) => (
        <h3 id={slugify(nodeText(children))} className={`scroll-mt-4 ${H3_CLS}`}>
          {children}
        </h3>
      ),
      h4: ({ children }) => <h4 className={H4_CLS}>{children}</h4>,
    };
  }, [headingIds]);

  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
