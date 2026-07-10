"""frontmatter/wikilink/up 파싱 (AXKG-SPEC-005 링크 계약). WP2.

순수 함수 — 파일 I/O와 분리한다(`MarkdownRoot`가 읽고, 여기서 문자열만 파싱).
정규화 규칙(SPEC-005 §4 Link Syntax Contract):
- `[[stem]]`            → target=stem, label=None
- `[[stem|label]]`      → target=stem, label 보존(target에서는 무시)
- `[[folder/stem]]`     → target=stem (경로형은 stem으로 정규화)
- `[[stem#heading]]`    → target=stem (heading/block 참조는 무시)
- frontmatter `up: [x]` → lineage upstream stem 목록(각 항목도 위 규칙으로 정규화)

본문 `[[ ]]`가 그래프 엣지의 단일 소스다(SPEC-005 §5). frontmatter `links`는
사람이 읽는 추적용이며 엣지가 아니다 — 파싱은 하되 wikilink로 취급하지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

_WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n)---\s*(?:\n|$)", re.DOTALL)


@dataclass(frozen=True)
class Wikilink:
    """본문 `[[ ]]` 하나. target은 정규화된 stem, label은 표시명(없으면 None)."""

    target: str
    label: str | None
    raw: str


@dataclass(frozen=True)
class ParsedDocument:
    """파싱된 문서 스냅샷 — frontmatter + 본문 + 정규화된 링크."""

    frontmatter: dict[str, Any]
    body: str
    wikilinks: tuple[Wikilink, ...] = ()
    up: tuple[str, ...] = ()

    @property
    def document_type(self) -> str | None:
        value = self.frontmatter.get("type")
        return str(value) if value is not None else None

    @property
    def doc_id(self) -> str | None:
        value = self.frontmatter.get("id")
        return str(value) if value is not None else None

    @property
    def title(self) -> str | None:
        value = self.frontmatter.get("title")
        return str(value) if value is not None else None

    @property
    def aliases(self) -> list[str]:
        return _as_str_list(self.frontmatter.get("aliases"))

    @property
    def tags(self) -> list[str]:
        return _as_str_list(self.frontmatter.get("tags"))

    @property
    def source_url(self) -> str | None:
        value = self.frontmatter.get("source")
        return str(value) if value is not None else None


def normalize_wikilink_target(inner: str) -> tuple[str, str | None]:
    """`[[ ]]` 안쪽 문자열을 (target stem, label)로 정규화한다.

    `folder/stem#heading|label` 같은 복합형도 stem만 남긴다. target이 비면 ("", label).
    """
    text = inner.strip()
    label: str | None = None
    if "|" in text:
        left, _, right = text.partition("|")
        text = left.strip()
        label = right.strip() or None
    # heading(#)·block(^) 참조 제거
    text = text.split("#", 1)[0].split("^", 1)[0].strip()
    # 경로형 → basename
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    # 확장자 제거
    if text.lower().endswith(".md"):
        text = text[:-3]
    return text.strip(), label


def _fence_regions(body: str) -> list[tuple[int, int]]:
    """코드펜스(``` / ~~~ 3개 이상, 개행 단위) 범위를 (start, end) char offset로.

    여는 펜스와 같은 문자·같거나 긴 run의 줄에서 닫힌다. 안 닫히면 문서 끝까지 코드.
    CommonMark 최소 수준 — info string/과설계는 다루지 않는다.
    """
    regions: list[tuple[int, int]] = []
    fence_char: str | None = None
    fence_len = 0
    start_off = 0
    pos = 0
    for line in body.splitlines(keepends=True):
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        marker: tuple[str, int] | None = None
        if indent <= 3 and stripped[:1] in ("`", "~"):
            ch = stripped[0]
            run = len(stripped) - len(stripped.lstrip(ch))
            if run >= 3:
                marker = (ch, run)
        if fence_char is None:
            if marker is not None:
                fence_char, fence_len = marker
                start_off = pos
        elif marker is not None and marker[0] == fence_char and marker[1] >= fence_len:
            regions.append((start_off, pos + len(line)))
            fence_char = None
        pos += len(line)
    if fence_char is not None:
        regions.append((start_off, len(body)))
    return regions


def _codespan_regions(body: str, fences: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """인라인 코드스팬(같은 길이 backtick run 쌍) 범위. 펜스 안 backtick은 무시한다."""

    def in_fence(i: int) -> bool:
        return any(s <= i < e for s, e in fences)

    regions: list[tuple[int, int]] = []
    n = len(body)
    i = 0
    while i < n:
        if body[i] != "`" or in_fence(i):
            i += 1
            continue
        j = i
        while j < n and body[j] == "`":
            j += 1
        run = j - i
        # 같은 길이의 닫는 backtick run을 찾는다(더 길면 안 닫힘 — CommonMark).
        k = j
        closed: int | None = None
        while k < n:
            if body[k] == "`" and not in_fence(k):
                m = k
                while m < n and body[m] == "`":
                    m += 1
                if m - k == run:
                    closed = m
                    break
                k = m
            else:
                k += 1
        if closed is not None:
            regions.append((i, closed))
            i = closed
        else:
            i = j
    return regions


def _code_regions(body: str) -> list[tuple[int, int]]:
    """코드펜스 + 인라인 코드스팬 범위를 합쳐 반환한다(정렬됨)."""
    fences = _fence_regions(body)
    spans = _codespan_regions(body, fences)
    return sorted(fences + spans)


def extract_wikilinks(body: str) -> tuple[Wikilink, ...]:
    """본문에서 `[[ ]]`를 순서대로 뽑아 정규화한다. 빈 target·코드 영역은 제외한다.

    코드스팬/코드펜스 안의 `[[ID]]`는 링크 문법 **예시**이지 엣지가 아니므로 제외한다
    (SPEC-005 §7 OQ, 2026-07-10 라이브 실측: BROKEN_WIKILINK 오탐 원인).
    """
    code = _code_regions(body)

    def in_code(i: int) -> bool:
        return any(s <= i < e for s, e in code)

    links: list[Wikilink] = []
    for match in _WIKILINK_RE.finditer(body):
        if in_code(match.start()):
            continue
        inner = match.group(1)
        target, label = normalize_wikilink_target(inner)
        if not target:
            continue
        links.append(Wikilink(target=target, label=label, raw=inner.strip()))
    return tuple(links)


def normalize_up(value: Any) -> tuple[str, ...]:
    """frontmatter `up`을 정규화된 stem 튜플로. 문자열/리스트/`[[ ]]` 표기 모두 허용."""
    stems: list[str] = []
    for entry in _as_str_list(value):
        target, _ = normalize_wikilink_target(entry.strip().removeprefix("[[").removesuffix("]]"))
        if target and target not in stems:
            stems.append(target)
    return tuple(stems)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """상단 `--- ... ---` YAML frontmatter와 본문을 분리한다. 없으면 ({}, text)."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return {}, text
    raw = match.group(1)
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        data = None
    frontmatter = data if isinstance(data, dict) else {}
    body = text[match.end():]
    return frontmatter, body


def parse_markdown(text: str) -> ParsedDocument:
    """frontmatter + 본문 wikilink + up을 한 번에 파싱한다(순수 함수)."""
    frontmatter, body = split_frontmatter(text)
    wikilinks = extract_wikilinks(body)
    up = normalize_up(frontmatter.get("up"))
    return ParsedDocument(frontmatter=frontmatter, body=body, wikilinks=wikilinks, up=up)


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v is not None]
    return [str(value)]
