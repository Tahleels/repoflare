"""RepositoryScanner: walks a repository root, respects .gitignore, and yields files in
languages RepoFlare knows how to parse. Unsupported-language files are filtered here so the
read/hash cost is never paid for files that would produce no symbols anyway."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pathspec

_LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
}

_ALWAYS_IGNORED_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "venv", ".repoflare"}
)


@dataclass(frozen=True, slots=True)
class ScannedFile:
    relative_path: str
    absolute_path: Path
    language: str | None
    content: str
    content_hash: str


class RepositoryScanner:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._gitignore = self._load_gitignore(root)

    @staticmethod
    def _load_gitignore(root: Path) -> pathspec.PathSpec[Any]:
        """Load .gitignore patterns from the repo root, returning an empty spec if absent."""
        gitignore_path = root / ".gitignore"
        lines = (
            gitignore_path.read_text(encoding="utf-8").splitlines()
            if gitignore_path.exists()
            else []
        )
        return pathspec.PathSpec.from_lines("gitignore", lines)

    def scan(self) -> Iterator[ScannedFile]:
        """Yield every known-language file in the repository that is not ignored.

        Files are yielded in sorted path order (deterministic across runs). Files that
        cannot be decoded as UTF-8, or that belong to an always-ignored directory, are
        silently skipped.
        """
        for path in sorted(self._root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self._root)
            if any(part in _ALWAYS_IGNORED_DIRS for part in relative.parts):
                continue
            relative_posix = relative.as_posix()
            if self._gitignore.match_file(relative_posix):
                continue
            language = _LANGUAGE_BY_EXTENSION.get(path.suffix)
            if language is None:
                continue
            try:
                # utf-8-sig transparently strips a leading BOM when present (e.g. files
                # written by Windows PowerShell's `Out-File -Encoding utf8`, which defaults
                # to BOM-prefixed UTF-8) and is otherwise identical to plain utf-8 — a BOM
                # left in place lands as an invisible character before the first line,
                # which silently breaks tree-sitter's parse of that line (commonly the
                # first import statement).
                content = path.read_text(encoding="utf-8-sig")
            except (UnicodeDecodeError, OSError):
                continue
            yield ScannedFile(
                relative_path=relative_posix,
                absolute_path=path,
                language=language,
                content=content,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
