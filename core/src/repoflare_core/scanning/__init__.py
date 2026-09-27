"""Filesystem scanning: walks a repository and yields candidate source files, respecting
.gitignore."""

from repoflare_core.scanning.scanner import (
    RepositoryScanner,
    RepositoryTooLargeError,
    ScannedFile,
)

__all__ = ["RepositoryScanner", "RepositoryTooLargeError", "ScannedFile"]
