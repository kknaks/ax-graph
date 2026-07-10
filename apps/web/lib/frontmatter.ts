// 경량 frontmatter 파서 (PLAN-010-T-007) — 파일 보기 모달 메타 블록 렌더용.
// markdown_full 선두의 YAML frontmatter(`---\n...\n---`)를 분리해 본문과 필드로 나눈다.
// 이 용도(스칼라 · 블록 리스트 `- item` · inline flow `[a, b]` · 얕은 nested map)만 다루는
// 최소 구현 — 신규 yaml 의존성은 도입하지 않는다. 파싱 불가/frontmatter 없음은 안전 fallback한다.

export type FrontmatterValue =
  | { kind: "scalar"; text: string }
  | { kind: "list"; items: string[] };

export interface FrontmatterField {
  key: string;
  value: FrontmatterValue;
}

export interface ParsedMarkdown {
  /** frontmatter 필드(순서 보존). frontmatter 없거나 파싱 실패 시 빈 배열. */
  fields: FrontmatterField[];
  /** frontmatter를 제거한 본문. fallback 시 원문 그대로. */
  body: string;
}

/** 양끝 따옴표 제거. */
function unquote(s: string): string {
  const t = s.trim();
  if (t.length >= 2 && ((t[0] === '"' && t.endsWith('"')) || (t[0] === "'" && t.endsWith("'")))) {
    return t.slice(1, -1);
  }
  return t;
}

/** inline flow list `[a, b, c]` → 항목 배열. flow가 아니면 null. */
function parseFlowList(s: string): string[] | null {
  const t = s.trim();
  if (!(t.startsWith("[") && t.endsWith("]"))) return null;
  const inner = t.slice(1, -1).trim();
  if (inner === "") return [];
  return inner.split(",").map((x) => unquote(x)).filter((x) => x !== "");
}

const TOP_KEY = /^([A-Za-z0-9_][A-Za-z0-9_-]*):(.*)$/;

/**
 * markdown_full에서 선두 frontmatter를 분리한다.
 * 선두가 `---` 라인으로 시작하고 닫는 `---`가 있을 때만 파싱, 아니면 body=원문·fields=[] fallback.
 */
export function parseFrontmatter(raw: string): ParsedMarkdown {
  // \r\n 정규화(윈도우 개행 방어). 원문 body는 정규화본을 쓴다(렌더 동일).
  const text = raw.replace(/\r\n/g, "\n");
  const lines = text.split("\n");

  if (lines[0]?.trim() !== "---") return { fields: [], body: raw };

  // 닫는 `---` 찾기.
  let end = -1;
  for (let i = 1; i < lines.length; i++) {
    if (lines[i].trim() === "---") {
      end = i;
      break;
    }
  }
  if (end === -1) return { fields: [], body: raw };

  const fmLines = lines.slice(1, end);
  const body = lines.slice(end + 1).join("\n").replace(/^\n+/, "");

  const fields: FrontmatterField[] = [];
  for (let i = 0; i < fmLines.length; i++) {
    const line = fmLines[i];
    if (line.trim() === "") continue;
    // 최상위 키만 필드 시작으로 본다(들여쓰기 라인은 부모의 lookahead가 소비).
    if (/^\s/.test(line)) continue;
    const m = line.match(TOP_KEY);
    if (!m) continue;

    const key = m[1];
    const rest = m[2].trim();

    if (rest === "") {
      // 다음 들여쓰기 블록 수집: `- item`(리스트) 또는 `child: val`(nested map).
      const items: string[] = [];
      let j = i + 1;
      for (; j < fmLines.length; j++) {
        const next = fmLines[j];
        if (next.trim() === "") continue;
        if (!/^\s/.test(next)) break; // 들여쓰기 끝 → 다음 최상위 키
        const listItem = next.match(/^\s*-\s+(.*)$/);
        if (listItem) {
          items.push(unquote(listItem[1]));
          continue;
        }
        const nested = next.trim().match(TOP_KEY);
        if (nested) {
          const nv = nested[2].trim();
          items.push(nv === "" ? nested[1] : `${nested[1]}: ${unquote(nv)}`);
          continue;
        }
        items.push(next.trim());
      }
      i = j - 1;
      fields.push({ key, value: { kind: "list", items } });
      continue;
    }

    const flow = parseFlowList(rest);
    if (flow) {
      fields.push({ key, value: { kind: "list", items: flow } });
      continue;
    }

    fields.push({ key, value: { kind: "scalar", text: unquote(rest) } });
  }

  return { fields, body };
}
