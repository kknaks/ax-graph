"""AXKG-SPEC-005 markdown parser 단위 테스트 (WP2 Phase 1).

Link Syntax Contract(§4) + Required Frontmatter + up 정규화 + links 비엣지 규칙.
파일 I/O 없는 순수 함수 커버.
"""
from axkg.storage.markdown_parser import (
    extract_wikilinks,
    normalize_up,
    normalize_wikilink_target,
    parse_markdown,
    split_frontmatter,
)

# ---------------------------------------------------------------------------
# Link Syntax Contract (§4)
# ---------------------------------------------------------------------------


def test_wikilink_basic() -> None:
    target, label = normalize_wikilink_target("stem")
    assert target == "stem"
    assert label is None


def test_wikilink_with_label_target_ignores_label() -> None:
    target, label = normalize_wikilink_target("stem|표시명")
    assert target == "stem"
    assert label == "표시명"


def test_wikilink_folder_path_normalized_to_stem() -> None:
    target, _ = normalize_wikilink_target("permanent/concepts/graph-rag")
    assert target == "graph-rag"


def test_wikilink_heading_and_extension_stripped() -> None:
    assert normalize_wikilink_target("note#section")[0] == "note"
    assert normalize_wikilink_target("note.md")[0] == "note"
    assert normalize_wikilink_target("folder/note#h|L") == ("note", "L")


def test_extract_wikilinks_order_and_dedup_kept() -> None:
    links = extract_wikilinks("see [[a]] and [[b|B]] and [[a]] again")
    assert [(l.target, l.label) for l in links] == [
        ("a", None),
        ("b", "B"),
        ("a", None),
    ]


def test_empty_wikilink_ignored() -> None:
    assert extract_wikilinks("noise [[]] and [[  ]] end") == ()


# ---------------------------------------------------------------------------
# 코드스팬/코드펜스 안 [[ ]] 제외 (SPEC-005 §7 OQ, 2026-07-10 라이브 실측)
# ---------------------------------------------------------------------------


def test_wikilink_inside_codespan_excluded() -> None:
    # 인라인 코드스팬 안은 링크 문법 예시 — 엣지가 아니다.
    links = extract_wikilinks("링크는 `[[fake]]` 처럼 씁니다.")
    assert links == ()


def test_wikilink_inside_fence_excluded() -> None:
    body = "본문 시작\n```\n[[fake]]\n```\n본문 끝"
    assert extract_wikilinks(body) == ()


def test_mixed_real_and_code_only_real_kept() -> None:
    body = (
        "정상 링크 [[real]] 는 남고,\n"
        "인라인 `[[fake1]]` 과\n"
        "~~~\n[[fake2]]\n~~~\n"
        "코드 안은 빠진다."
    )
    assert [l.target for l in extract_wikilinks(body)] == ["real"]


def test_unclosed_fence_treated_as_code_to_end() -> None:
    body = "앞 [[real]]\n```\n[[fake]]\n여기서 펜스 안 닫힘 [[also-fake]]"
    assert [l.target for l in extract_wikilinks(body)] == ["real"]


# ---------------------------------------------------------------------------
# Required Frontmatter + up + links
# ---------------------------------------------------------------------------


DOC = """---
type: reference
id: REF-1
title: Retriever note
aliases: [grag, ref-one]
tags: [ai, retrieval]
up: [graph-rag]
source: https://example.com/x
links:
  related: ["[[graph-rag]]"]
---
The retriever uses [[graph-rag]] and links to [[inbox-note|inbox]].
"""


def test_parse_required_frontmatter_fields() -> None:
    parsed = parse_markdown(DOC)
    assert parsed.document_type == "reference"
    assert parsed.doc_id == "REF-1"
    assert parsed.title == "Retriever note"
    assert parsed.aliases == ["grag", "ref-one"]
    assert parsed.tags == ["ai", "retrieval"]
    assert parsed.source_url == "https://example.com/x"


def test_parse_body_wikilinks_only() -> None:
    parsed = parse_markdown(DOC)
    targets = [l.target for l in parsed.wikilinks]
    # 본문 [[ ]]만 — frontmatter links.related의 [[graph-rag]]는 포함되면 안 된다.
    assert targets == ["graph-rag", "inbox-note"]


def test_up_normalized() -> None:
    parsed = parse_markdown(DOC)
    assert parsed.up == ("graph-rag",)


def test_normalize_up_accepts_string_and_wikilink_form() -> None:
    assert normalize_up("graph-rag") == ("graph-rag",)
    assert normalize_up(["[[graph-rag]]", "folder/other"]) == ("graph-rag", "other")


def test_frontmatter_links_field_is_not_a_wikilink_edge() -> None:
    parsed = parse_markdown(DOC)
    # links는 frontmatter에 보존되지만 그래프 엣지(body wikilink)로 취급하지 않는다.
    assert "links" in parsed.frontmatter
    assert all(l.target != "graph-rag" or l.raw for l in parsed.wikilinks)


def test_no_frontmatter_returns_empty_dict() -> None:
    fm, body = split_frontmatter("no frontmatter [[a]] here")
    assert fm == {}
    assert "[[a]]" in body
    parsed = parse_markdown("plain [[a]]")
    assert parsed.document_type is None
    assert [l.target for l in parsed.wikilinks] == ["a"]
