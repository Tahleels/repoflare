"""ChangeDetector: turns a git diff into a domain ChangeSet.

Deliberately doesn't know about snapshot ids beyond what its caller passes in — mapping
git commits to RepoFlare snapshot ids is a graph-store concern, not a git concern (see
docs/ARCHITECTURE.md's module boundary table: change/ depends on domain + graph, not the
other way around).
"""

from __future__ import annotations

from repoflare_core.change.git_adapter import GitAdapter
from repoflare_core.domain.entities import ChangeSet


class ChangeDetector:
    """Converts a git diff between two refs into a domain ChangeSet."""

    def __init__(self, git: GitAdapter) -> None:
        self._git = git

    def detect(
        self,
        change_set_id: str,
        snapshot_to_id: str,
        from_ref: str,
        to_ref: str = "HEAD",
        snapshot_from_id: str | None = None,
    ) -> ChangeSet:
        """Build a ChangeSet from the diff between from_ref and to_ref.

        snapshot_from_id is optional — callers that do not yet have a prior snapshot
        (e.g. first-time analysis) may omit it.
        """
        changed_files = self._git.changed_files(from_ref, to_ref)
        return ChangeSet(
            change_set_id=change_set_id,
            snapshot_to_id=snapshot_to_id,
            changed_files=changed_files,
            snapshot_from_id=snapshot_from_id,
        )
