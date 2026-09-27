"""Analysing repositories that live somewhere else (a public GitHub URL) rather than on the
caller's disk — what the hosted HTTP API needs and what the CLI/extension deliberately don't
(see api/ and docs/DECISIONS.md).

`workspace.py` owns the clone lifecycle; service.py owns the orchestration that uses it.
"""

from repoflare_core.remote.workspace import (
    RemoteRepoError,
    RepoRef,
    cloned_workspace,
    parse_public_github_ref,
)

__all__ = ["RepoRef", "RemoteRepoError", "cloned_workspace", "parse_public_github_ref"]
