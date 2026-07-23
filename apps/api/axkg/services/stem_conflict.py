"""stem 충돌 disambiguate + 링크 재작성 공용 헬퍼 (AXKG-SPEC-014 Feature Dedup / Baseline).

회사 프로젝트 팬아웃에서 같은 stem이 겹칠 때 회피(disambiguate)하고, 그로 인해 바뀐 stem을
가리키는 링크(원본요약 `## 기능 목록`의 `[[ ]]`, 파생 spec의 `up:`/본문 `[[ ]]`)를 새 stem으로
맞추는 순수 함수 모음이다. **spawn 시점(plan_fanout_execution)과 apply 시점(apply_executor)이
동일 규칙을 공유**하도록 여기로 추출했다(중복 구현 금지) — apply 시점은 승인 지연 사이 라이브
DB가 바뀌어 spawn 배정이 무효화되는 TOCTOU를 이 헬퍼로 재해결한다.
"""
from __future__ import annotations

import re

import yaml

from axkg.storage.markdown_parser import normalize_up, split_frontmatter

_WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+?)\]\]")


def disambiguate_stem(orig: str, corp: str | None, taken: set[str]) -> str:
    """충돌 없는 stem을 만든다 — `{corp}-` 프리픽스 우선, 이미 쓰였으면 `-2`… suffix.

    corp 네임스페이스로 전역 concept/reference·타 corp와 원천 비충돌시키고, 그래도 겹치면
    번호 suffix로 유일하게 만든다. `taken`은 인덱스 stem ∪ 이번 배정 stem.
    """
    base = orig if (corp and orig.startswith(f"{corp}-")) else (
        f"{corp}-{orig}" if corp else orig
    )
    if base not in taken and base != orig:
        return base
    root_stem = base if base != orig else orig
    if root_stem not in taken:
        return root_stem
    n = 2
    while f"{root_stem}-{n}" in taken:
        n += 1
    return f"{root_stem}-{n}"


def rewrite_wikilinks(markdown: str, stem_remap: dict) -> str:
    """본문 `[[orig]]`/`[[orig|label]]`를 disambiguate된 `[[final]]`로 재작성한다."""
    if not stem_remap:
        return markdown

    def _repl(match: re.Match) -> str:
        inner = match.group(1)
        target, sep, label = inner.partition("|")
        tstem = target.split("#", 1)[0].strip()
        if tstem in stem_remap:
            new = stem_remap[tstem]
            return f"[[{new}|{label}]]" if sep else f"[[{new}]]"
        return match.group(0)

    return _WIKILINK_RE.sub(_repl, markdown)


def remap_stem_refs(markdown: str, stem_remap: dict) -> str:
    """frontmatter `up:`와 본문 `[[ ]]` 링크의 stem을 stem_remap대로 재작성한다.

    apply 재해결로 main(원본요약) stem이 바뀌면, 그 원본요약을 가리키는 파생 spec의 up:/본문
    링크를 새 stem으로 맞춘다(BROKEN_WIKILINK/UP_WITHOUT_BODY_LINK 방지). 바뀔 게 없으면 원본을
    그대로 돌려준다(불필요한 frontmatter 재포맷 회피).
    """
    if not stem_remap:
        return markdown
    frontmatter, body = split_frontmatter(markdown)
    ups = list(normalize_up(frontmatter.get("up")))
    changed_up = any(u in stem_remap for u in ups)
    new_body = rewrite_wikilinks(body, stem_remap)
    if not changed_up and new_body == body:
        return markdown
    frontmatter = dict(frontmatter)
    if ups:
        frontmatter["up"] = [stem_remap.get(u, u) for u in ups]
    fm_yaml = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
    if not new_body.startswith("\n"):
        new_body = "\n" + new_body
    return f"---\n{fm_yaml}---\n{new_body}"
