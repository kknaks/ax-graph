"""AXKG-DEC-002 markdown root 경로 안전 단위 테스트 (WP2 Phase 1).

document-root 상대 경로만 허용, 절대경로/`..` 탈출/심볼릭 탈출 거부. 읽기 전용.
"""
from pathlib import Path

import pytest

from axkg.storage.markdown_root import (
    MarkdownRoot,
    PathEscapesRootError,
    content_hash,
)


def _root(tmp_path: Path) -> MarkdownRoot:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "note.md").write_text("# note", encoding="utf-8")
    (tmp_path / "top.md").write_text("# top", encoding="utf-8")
    return MarkdownRoot(tmp_path)


def test_resolve_within_root(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert root.read_text("sub/note.md") == "# note"
    assert root.exists("top.md")


def test_reject_absolute_path(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with pytest.raises(PathEscapesRootError):
        root.resolve("/etc/passwd")


def test_reject_parent_escape(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with pytest.raises(PathEscapesRootError):
        root.resolve("../../secret.md")
    assert root.exists("../../secret.md") is False


def test_iter_markdown_relative_posix(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert list(root.iter_markdown()) == ["sub/note.md", "top.md"]


def test_content_hash_changes_with_content() -> None:
    assert content_hash("a") == content_hash("a")
    assert content_hash("a") != content_hash("b")
