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


def extract_wikilinks(body: str) -> tuple[Wikilink, ...]:
    """본문에서 `[[ ]]`를 순서대로 뽑아 정규화한다. 빈 target은 제외한다."""
    links: list[Wikilink] = []
    for match in _WIKILINK_RE.finditer(body):
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
