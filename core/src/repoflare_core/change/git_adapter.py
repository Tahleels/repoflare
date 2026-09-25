"""Thin, safe wrapper around the `git` CLI. Isolated behind this class so ChangeDetector
never shells out directly — see docs/ARCHITECTURE.md's failure-handling boundaries and the
project brief's requirement that any git/subprocess execution be carefully controlled.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_GIT_TIMEOUT_SECONDS = 30


class GitCommandError(RuntimeError):
    """Raised when the underlying `git` invocation fails. Never swallowed silently."""


class GitAdapter:
    """Safe wrapper around the `git` CLI subprocess.

    All calls go through `_run`, which uses an explicit argv list (no shell=True) and a
    fixed timeout, so there is no command-injection surface regardless of ref content.
    """

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def _run(self, *args: str) -> str:
        # Explicit argv, no shell=True — refs/paths are never interpolated into a shell
        # string, so there is no command-injection surface here regardless of ref content.
        result = subprocess.run(
            ["git", *args],
            cwd=self._repo_root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode != 0:
            raise GitCommandError(
                f"git {' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()}"
            )
        return result.stdout

    def changed_files(self, from_ref: str, to_ref: str = "HEAD") -> list[str]:
        """Return relative paths of files changed between from_ref and to_ref.

        Paths use forward slashes and match ScannedFile.relative_path. An empty list means
        the two refs are identical (no changes).
        """
        output = self._run("diff", "--name-only", f"{from_ref}..{to_ref}")
        return [line for line in output.splitlines() if line]

    def current_commit_sha(self) -> str:
        """Return the full SHA of the current HEAD commit."""
        return self._run("rev-parse", "HEAD").strip()
