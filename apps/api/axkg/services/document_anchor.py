"""회사 루트 up: 체인 배선 (AXKG-DEC-009 D3 / WORK-013 P4·P5).

회사 프로젝트 산출 문서에 시스템이 **document_type + `up:` frontmatter + 본문 `[[up_target]]`
링크**를 주입해 그래프를 회사 루트로 수렴시킨다:
- baseline(원본요약)·context → `up: [{corp}]`(회사 루트 stem)
- spec(기능정의서) → `up: [원본요약 stem]`(→ 원본요약이 `up: [{corp}]`이므로 2단 체인)

그래프 엣지의 단일 소스는 본문 `[[ ]]`이므로(AXKG-SPEC-005), up: frontmatter에 넣은 stem은
본문에도 `[[ ]]`로 반드시 있어야 한다 — 없으면 `## 연결`/`## 8. 연결` 섹션에 자동 추가한다
(빈 `[[ ]]` 금지). document_type도 시스템이 권위 있게 세팅한다(AI 출력 드리프트 방어).
"""
from __future__ import annotations

import yaml

from axkg.storage.markdown_parser import (
    extract_wikilinks,
    normalize_up,
    split_frontmatter,
)

# 연결 섹션 헤더 후보(spec은 `## 8. 연결`, baseline/context는 `## 연결`).
_CONNECTION_HEADERS = ("## 8. 연결", "## 연결")
_ANCHOR_REASON = "회사 루트"


def _find_header(lines: list[str], header: str) -> int | None:
    for i, line in enumerate(lines):
        if line.strip() == header:
            return i
    return None


def _ensure_body_link(body: str, target: str) -> str:
    """본문에 `[[target]]`가 없으면 연결 섹션에 불릿으로 추가한다(있으면 그대로)."""
    if target in {w.target for w in extract_wikilinks(body)}:
        return body
    bullet = f"- [[{target}]] — {_ANCHOR_REASON}"
    lines = body.split("\n")
    for header in _CONNECTION_HEADERS:
        idx = _find_header(lines, header)
        if idx is not None:
            lines.insert(idx + 1, bullet)
            return "\n".join(lines)
    # 연결 섹션이 없으면 문서 끝에 새로 만든다.
    return body.rstrip("\n") + f"\n\n## 연결\n{bullet}\n"


def apply_document_anchor(
    markdown: str, *, document_type: str | None = None, up_target: str | None = None
) -> str:
    """생성 문서에 document_type/up:/본문 [[up_target]]를 주입한 markdown을 돌려준다.

    - document_type: 주어지면 frontmatter `type`을 그 값으로 강제(시스템 권위).
    - up_target: 주어지면 frontmatter `up:`에 추가(중복 방지) + 본문 `[[up_target]]` 보장.
    frontmatter가 없으면 새로 만든다. 순수 함수(파일 I/O 없음).
    """
    frontmatter, body = split_frontmatter(markdown)
    frontmatter = dict(frontmatter)
    if document_type:
        frontmatter["type"] = document_type
    if up_target:
        ups = list(normalize_up(frontmatter.get("up")))
        if up_target not in ups:
            ups.append(up_target)
        frontmatter["up"] = ups
        body = _ensure_body_link(body, up_target)
    fm_yaml = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
    if not body.startswith("\n"):
        body = "\n" + body
    return f"---\n{fm_yaml}---\n{body}"
