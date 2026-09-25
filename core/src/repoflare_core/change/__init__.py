"""Git-diff-based change detection: turns two refs into a ChangeSet of changed files."""

from repoflare_core.change.detector import ChangeDetector
from repoflare_core.change.git_adapter import GitAdapter, GitCommandError

__all__ = ["ChangeDetector", "GitAdapter", "GitCommandError"]
