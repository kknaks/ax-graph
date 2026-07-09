"""Markdown root 접근. document-root 상대 경로만 취급, root 밖 접근 거부 (AXKG-DEC-002).

읽기 전용 접근자다 — WP2 rebuild는 Markdown을 쓰지 않는다(DEC-002: cache는 언제든
Markdown에서 재빌드 가능). 경로 안전: 절대경로/`..` 탈출/심볼릭 링크로 root 밖을 가리키는
접근을 모두 거부한다(resolve 후 root 하위인지 검사).
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path


class MarkdownRootError(Exception):
    """markdown root 접근 오류 기본형."""


class PathEscapesRootError(MarkdownRootError):
    """상대 경로가 document root 밖(절대경로/`..`/심볼릭 탈출)을 가리킨다."""

    def __init__(self, rel: str) -> None:
        super().__init__(f"path escapes markdown root: {rel!r}")
        self.rel = rel


class DocumentExistsError(MarkdownRootError):
    """create_markdown 대상 경로에 (내용이 다른) 파일이 이미 있다."""

    def __init__(self, rel: str) -> None:
        super().__init__(f"document already exists: {rel!r}")
        self.rel = rel


def content_hash(text: str) -> str:
    """파일 본문의 sha256 hex — startup scan의 변경분(content_hash) 비교 기준."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MarkdownRoot:
    """document-root 하위 상대 경로만 다루는 읽기 전용 접근자.

    `resolve`는 root 밖으로 벗어나는 모든 경로를 `PathEscapesRootError`로 거부한다.
    운영에서 root는 workspace bind mount, 테스트/실험은 `data/documents`.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def resolve(self, rel: str) -> Path:
        """상대 경로를 root 기준 절대 경로로 안전 변환. 탈출은 거부한다."""
        candidate = Path(rel)
        if candidate.is_absolute():
            raise PathEscapesRootError(rel)
        resolved = (self._root / candidate).resolve()
        if resolved != self._root and self._root not in resolved.parents:
            raise PathEscapesRootError(rel)
        return resolved

    def exists(self, rel: str) -> bool:
        try:
            return self.resolve(rel).is_file()
        except PathEscapesRootError:
            return False

    def is_within(self, rel: str) -> bool:
        """rel이 root 하위 안전 경로인지(쓰기 allowlist 검사용). 탈출이면 False."""
        try:
            self.resolve(rel)
            return True
        except PathEscapesRootError:
            return False

    def read_text(self, rel: str) -> str:
        return self.resolve(rel).read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # writer — Apply Executor 전용 (AXKG-SPEC-004 §5: executor만 Markdown 쓰기)
    # ------------------------------------------------------------------

    def write_new(self, rel: str, content: str) -> str:
        """신규 문서 생성(create_markdown). 이미 있으면 거부하되 내용이 같으면 멱등 통과.

        경로 안전(resolve)을 거쳐 root 하위에만 쓴다. 같은 승인 재실행이 중복을 만들지 않도록,
        동일 내용 파일이 이미 있으면 조용히 통과한다(부분 실패 후 재시도 멱등).
        """
        path = self.resolve(rel)
        if path.is_file():
            if path.read_text(encoding="utf-8") == content:
                return rel
            raise DocumentExistsError(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return rel

    def overwrite(self, rel: str, content: str) -> str:
        """기존 문서 수정(patch_markdown/update_frontmatter 적용 결과 전체 write).

        diff/patch를 우선하되, MVP는 실행측이 만든 최종 본문(draft_markdown)을 전체 write한다.
        경로 안전을 거치고 root 하위에만 쓴다.
        """
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return rel

    def iter_markdown(self) -> Iterator[str]:
        """root 하위 모든 `*.md`의 상대 경로(posix)를 정렬 순서로 yield 한다.

        root 밖을 가리키는 심볼릭 링크 파일은 건너뛴다(경로 안전).
        """
        if not self._root.is_dir():
            return
        for path in sorted(self._root.rglob("*.md")):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved != self._root and self._root not in resolved.parents:
                continue
            yield path.relative_to(self._root).as_posix()
