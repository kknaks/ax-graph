// 마크다운 heading 추출 + 안정 slug 유틸 (PLAN-012-T-008) — 문서 라이브러리 우측 목차(TOC)용.
// 본문 마크다운(frontmatter 제거 후)의 ATX heading(`#`~`###`)만 문서 순서로 뽑아 TOC 항목을 만들고,
// 같은 slug 알고리즘을 MarkdownView 가 렌더 heading id 에 재사용해 TOC ↔ 본문 id 를 일치시킨다.
// 신규 의존성(github-slugger 등) 없이 최소 구현 — 코드펜스 안의 `#` 는 heading 으로 오인하지 않는다.

export interface HeadingItem {
  /** heading 레벨 1~3. */
  depth: number;
  /** 표시 텍스트(인라인 마크다운 제거 후). */
  text: string;
  /** 렌더 heading 과 일치하는 안정 id(중복 시 -N suffix). */
  id: string;
}

/** 인라인 마크다운 껍데기 제거 — 링크/이미지는 텍스트만 남겨 react-markdown 렌더 텍스트와 맞춘다. */
function stripInline(s: string): string {
  return s
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1") // 이미지 → alt
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1") // 링크 → 텍스트
    .replace(/`([^`]+)`/g, "$1") // 인라인 코드
    .replace(/[*_~]+/g, "") // 강조 마커
    .replace(/\s+/g, " ")
    .trim();
}

/** 텍스트 → slug base. 문자/숫자(유니코드, 한글 포함)와 하이픈만 남기고 공백은 하이픈으로. */
export function slugify(text: string): string {
  const base = text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "");
  return base || "section";
}

/** 본문 마크다운에서 h1~maxDepth heading 을 문서 순서로 추출(코드펜스 내부 제외).
 * id 는 텍스트만의 순수 함수(slugify) — 렌더 쪽 heading id 와 동일 규칙이라 항상 일치한다.
 * 중복 heading 은 같은 id 가 되며 클릭 시 첫 위치로 점프한다(카운터 미사용 — 렌더 횟수와 무관). */
export function extractHeadings(markdown: string, maxDepth = 3): HeadingItem[] {
  const out: HeadingItem[] = [];
  let inFence = false;
  let fenceChar = "";
  for (const line of markdown.split(/\r?\n/)) {
    const fence = line.match(/^\s*(```+|~~~+)/);
    if (fence) {
      const ch = fence[1][0];
      if (!inFence) {
        inFence = true;
        fenceChar = ch;
      } else if (ch === fenceChar) {
        inFence = false;
      }
      continue;
    }
    if (inFence) continue;
    const m = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
    if (!m) continue;
    const depth = m[1].length;
    if (depth > maxDepth) continue;
    const text = stripInline(m[2]);
    if (!text) continue;
    out.push({ depth, text, id: slugify(text) });
  }
  return out;
}
