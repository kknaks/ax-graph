"""문서 SoT git 동기화 (AXKG-DEC-010 / AXKG-SPEC-015).

`GitClient`는 mediness-app `back/app/services/publish/git_client.py` 미러다:
subprocess 기반, 모든 git 명령에 `-c safe.directory=<repo>` prepend(root 소유 bind mount 대응),
PAT는 커맨드마다 remote URL에 주입하고 `.git/config`에 영속하지 않는다(권한/유출 회피).

전략 A(commit-then-rebase-push, AXKG-DEC-010): apply()가 확정 파일을 이미 쓴 뒤 background로
`add documents/ → commit → fetch → rebase → push`. push 실패는 **비치명**(커밋은 로컬에 남아
다음 승인에 재시도, 파일 유실 없음). rebase 충돌(같은 파일 AI+사람 동시수정)은 abort + 경고.

사람 교정은 `pull_reindex_loop`가 주기적으로 fetch→ff pull 후 그래프 재빌드(run_startup_scan)로
반영한다(AXKG-SPEC-015 §6). qmd 검색 인덱스는 사이드카 주기 증분이 자동 흡수.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from axkg.config import settings

logger = logging.getLogger("axkg.git_sync")

# 모든 git 작업 직렬화 (mediness publish_lock 미러). 단일 api 컨테이너 전제(DEC-010 OQ-003).
_git_lock = asyncio.Lock()


class GitError(Exception):
    """git 명령 실패."""

    def __init__(self, cmd: list[str], returncode: int, stderr: str) -> None:
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            f"git {cmd[1] if len(cmd) > 1 else ''} failed ({returncode}): {stderr[:200]}"
        )


class GitClient:
    """repo_root(.git 위치)에서 documents 서브트리를 다루는 thin git CLI 래퍼."""

    def __init__(
        self,
        repo_root: str,
        subdir: str,
        *,
        token: str,
        remote: str,
        branch: str,
        author_name: str,
        author_email: str,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.subdir = subdir  # 예: "documents"
        self.token = token
        self.remote = remote
        self.branch = branch
        self.author_name = author_name
        self.author_email = author_email

    # ── internal ──────────────────────────────────────────────────────────
    def _remote_with_token(self) -> str:
        # https://github.com/kknaks/ax-graph.git → https://x-access-token:TOKEN@github.com/...
        scheme, _, rest = self.remote.partition("://")
        return f"{scheme}://x-access-token:{self.token}@{rest}"

    def _run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
        env = {
            "GIT_AUTHOR_NAME": self.author_name,
            "GIT_AUTHOR_EMAIL": self.author_email,
            "GIT_COMMITTER_NAME": self.author_name,
            "GIT_COMMITTER_EMAIL": self.author_email,
        }
        # host bind mount owner(uid) ≠ 컨테이너 user 로 인한 "dubious ownership" 거부 방지.
        if args and args[0] == "git":
            args = [args[0], "-c", f"safe.directory={self.repo_root}", *args[1:]]
        result = subprocess.run(
            args,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            env={**os.environ, **env},
        )
        if check and result.returncode != 0:
            raise GitError(args, result.returncode, result.stderr)
        return result

    # ── push side (승인, 전략 A) ────────────────────────────────────────────
    def commit_rebase_push(self, message: str) -> str | None:
        """add subdir → commit → fetch → rebase → push. 변경 없으면 None.

        rebase 충돌 시 abort 후 GitError(커밋은 로컬 유지). push 실패도 GitError(비치명 처리는 caller).
        """
        self._run(["git", "add", "-A", "--", self.subdir])
        # staged 변경 없으면 no-op (예: 멱등 재승인, 파일 동일).
        if self._run(["git", "diff", "--cached", "--quiet"], check=False).returncode == 0:
            return None
        self._run([
            "git",
            "-c", f"user.name={self.author_name}",
            "-c", f"user.email={self.author_email}",
            "commit", "-m", message,
        ])
        # 사람 교정 흡수 — origin/branch 위로 우리 커밋 replay.
        self._run(["git", "fetch", self._remote_with_token(), self.branch])
        rebase = self._run(["git", "rebase", "FETCH_HEAD"], check=False)
        if rebase.returncode != 0:
            self._run(["git", "rebase", "--abort"], check=False)
            raise GitError(["git", "rebase"], rebase.returncode, rebase.stderr)
        self._run(["git", "push", self._remote_with_token(), f"HEAD:{self.branch}"])
        return self._run(["git", "rev-parse", "HEAD"]).stdout.strip()

    # ── pull side (사람 교정, 읽기 전용 루프) ────────────────────────────────
    def fetch_ff(self) -> bool:
        """origin 최신을 fetch 후 fast-forward. 실제 변경이 반영됐으면 True.

        미푸시 로컬 커밋으로 diverge면 skip(다음 승인 push+rebase가 조정) → False.
        """
        self._run(["git", "fetch", self._remote_with_token(), self.branch])
        head = self._run(["git", "rev-parse", "HEAD"]).stdout.strip()
        remote = self._run(["git", "rev-parse", "FETCH_HEAD"]).stdout.strip()
        if head == remote:
            return False
        if self._run(
            ["git", "merge-base", "--is-ancestor", "HEAD", "FETCH_HEAD"], check=False
        ).returncode != 0:
            logger.warning(
                "docs pull skipped: local ahead/diverged (unpushed commits) — approval push will reconcile"
            )
            return False
        self._run(["git", "merge", "--ff-only", "FETCH_HEAD"])
        return True


def _client() -> GitClient:
    root = settings.axkg_docs_git_repo_root or str(
        Path(settings.axkg_markdown_root).resolve().parent
    )
    subdir = Path(settings.axkg_markdown_root).name  # "documents"
    return GitClient(
        root,
        subdir,
        token=settings.axkg_docs_git_token,
        remote=settings.axkg_docs_git_remote,
        branch=settings.axkg_docs_git_branch,
        author_name=settings.axkg_docs_git_author_name,
        author_email=settings.axkg_docs_git_author_email,
    )


async def sync_after_approval(message: str) -> None:
    """승인 확정 후 background: 변경 문서 commit→rebase→push. 비치명 — 절대 raise 안 함."""
    if not settings.axkg_docs_git_sync_enabled:
        return
    client = _client()
    async with _git_lock:
        try:
            sha = await asyncio.to_thread(client.commit_rebase_push, message)
            if sha:
                logger.info("docs git sync pushed: %s (%s)", sha, message)
        except GitError:
            # 전략 A: 워킹트리 복구/reset 안 함 — 커밋은 로컬에 남아 다음 승인에 재시도.
            logger.warning(
                "docs git sync failed (non-fatal, retries next approval): %s", message,
                exc_info=True,
            )


async def pull_reindex_loop(session_factory) -> None:
    """주기적 fetch→ff pull 후 그래프 재빌드로 사람 교정 반영 (AXKG-SPEC-015 §6)."""
    if not settings.axkg_docs_git_sync_enabled:
        return
    from axkg.workers.graph_rebuild import run_startup_scan

    client = _client()
    interval = settings.axkg_docs_git_pull_interval_seconds
    logger.info("docs pull+reindex loop started (interval=%ds)", interval)
    while True:
        try:
            async with _git_lock:
                changed = await asyncio.to_thread(client.fetch_ff)
            if changed:
                logger.info("docs pulled external changes → graph reindex")
                await run_startup_scan(session_factory=session_factory)
        except Exception:  # noqa: BLE001 — 루프는 한 번 실패로 죽지 않는다.
            logger.warning("docs pull/reindex iteration failed", exc_info=True)
        await asyncio.sleep(interval)
