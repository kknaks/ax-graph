"""문서 경로 조립·정규화 SSOT 단위 테스트 (PLAN-009-T-040).

AI는 파일명/대상 stem만 내고 디렉토리는 시스템이 조립한다 — 순수 함수 커버.
"""
from axkg.services.document_paths import (
    DERIVED_DIR_BY_TYPE,
    MAIN_DIR_BY_TYPE,
    assemble_derived_create_path,
    assemble_main_path,
    normalize_filename,
)


# ---------------------------------------------------------------------------
# normalize_filename (⑥ 디렉토리/.md 섞여 와도 정규화)
# ---------------------------------------------------------------------------


def test_normalize_plain_stem_gets_md() -> None:
    assert normalize_filename("graph-rag-note") == "graph-rag-note.md"


def test_normalize_already_has_md_kept_once() -> None:
    assert normalize_filename("graph-rag-note.md") == "graph-rag-note.md"


def test_normalize_strips_directory_components() -> None:
    # AI가 실수로 디렉토리를 붙여도 파일명만 남긴다.
    assert normalize_filename("areas/graph-rag-note.md") == "graph-rag-note.md"
    assert normalize_filename("permanent/concepts/foo") == "foo.md"


def test_normalize_empty_or_blank_returns_empty() -> None:
    assert normalize_filename(None) == ""
    assert normalize_filename("") == ""
    assert normalize_filename("   ") == ""


# ---------------------------------------------------------------------------
# 경로 조립 (① main / ③ derived create)
# ---------------------------------------------------------------------------


def test_assemble_main_path_by_type() -> None:
    assert assemble_main_path("reference", "graph-rag-note") == "resources/graph-rag-note.md"
    assert assemble_main_path("permanent", "note.md") == "permanent/note.md"
    assert assemble_main_path("baseline", "b-001") == "projects/b-001.md"


def test_assemble_main_path_absorbs_stray_directory() -> None:
    # filename에 디렉토리/.md가 섞여 와도 시스템 디렉토리로 흡수한다(⑥).
    assert assemble_main_path("reference", "concepts/graph-rag-note.md") == (
        "resources/graph-rag-note.md"
    )


def test_assemble_main_path_unknown_type_or_empty_returns_empty() -> None:
    assert assemble_main_path("mystery", "x") == ""
    assert assemble_main_path("reference", None) == ""


def test_assemble_derived_create_path_by_suggestion_type() -> None:
    assert assemble_derived_create_path("create_new_concept", "zettelkasten") == (
        "permanent/concepts/zettelkasten.md"
    )
    assert assemble_derived_create_path("create_project_baseline", "b-002.md") == (
        "projects/b-002.md"
    )


def test_assemble_derived_create_path_unknown_returns_empty() -> None:
    # supplement는 create 매핑에 없다 — modify는 stem 해소 경로를 쓴다.
    assert assemble_derived_create_path("supplement_existing_concept", "x") == ""


def test_mappings_are_the_ssot_shared_with_executor() -> None:
    # executor가 import하는 것과 동일 정의(중복 정의 금지, T-040 작업 1).
    from axkg.workers.apply_executor import (
        _DERIVED_DIR_BY_TYPE,
        _MAIN_DIR_BY_TYPE,
    )

    assert _MAIN_DIR_BY_TYPE is MAIN_DIR_BY_TYPE
    assert _DERIVED_DIR_BY_TYPE is DERIVED_DIR_BY_TYPE
