"""GovernanceContextPackage: a bounded evidence payload for Bob governance checks.

This is governance's equivalent of AIContextPackage in the code-intelligence layer.
It bundles the PR metadata, diff statistics, review discussion, and related test evidence
that the three Bob-powered checks (plan_before_ship, spaghetti, hitl) need — without
sending the entire repository.

The builder pulls from GitHub and the existing RepoFlare graph when a local snapshot is
available (snapshot_id + store are optional — governance checks degrade gracefully when
only GitHub data is available).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GovernanceContextPackage:
    """The bounded evidence package handed to a Bob governance prompt.

    Never the whole repository — see the parent ContextRetriever's docstring for the
    "targeted context" philosophy that governs both layers.
    """

    # PR identity
    pr_number: int
    pr_title: str
    pr_description: str
    pr_url: str
    author: str

    # Commit / diff statistics
    commit_messages: list[str] = field(default_factory=list)
    changed_file_count: int = 0
    additions: int = 0
    deletions: int = 0
    changed_files: list[dict[str, Any]] = field(default_factory=list)
    """Each dict: {filename, status, additions, deletions, patch (first 300 chars)}"""

    # Review signals
    review_comments: list[dict[str, Any]] = field(default_factory=list)
    """Each dict: {author, body, state}"""
    issue_comments: list[dict[str, Any]] = field(default_factory=list)
    """Each dict: {author, body}"""

    # Graph-derived test evidence (populated when a local snapshot is available)
    relevant_tests: list[str] = field(default_factory=list)
    """Node IDs or file paths of test nodes linked to the changed files."""
    test_edge_count: int = 0

    # Repository graph stats (optional enrichment)
    direct_dependents_count: int = 0


def build_governance_context(
    owner: str,
    repo: str,
    pr_number: int,
    adapter: Any,  # GitHubAdapter — typed as Any to avoid circular imports
) -> GovernanceContextPackage:
    """Build a GovernanceContextPackage from GitHub API data for a single PR.

    This is intentionally a free function (not a class) so tests can assemble a package
    directly without touching GitHub.
    """
    pr = adapter.get_pr(owner, repo, pr_number)

    # Commits — derive messages from the PR's head sha tree
    head_sha = pr.get("head", {}).get("sha", "HEAD")
    commits_raw = adapter.list_recent_commits(owner, repo, branch=head_sha, limit=10)
    commit_messages = [
        c.get("commit", {}).get("message", "").split("\n")[0]
        for c in commits_raw
        if c.get("commit", {}).get("message")
    ]

    # Changed files — sample patch text (first 300 chars per file to stay bounded)
    files_raw = adapter.list_pr_files(owner, repo, pr_number)
    changed_files = []
    for f in files_raw[:30]:
        patch = (f.get("patch") or "")[:300]
        changed_files.append(
            {
                "filename": f.get("filename", ""),
                "status": f.get("status", ""),
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "patch": patch,
            }
        )

    # Reviews
    reviews_raw = adapter.list_pr_reviews(owner, repo, pr_number)
    review_comments = [
        {
            "author": r.get("user", {}).get("login", "unknown"),
            "body": (r.get("body") or "")[:300],
            "state": r.get("state", ""),
        }
        for r in reviews_raw
    ]

    # Issue comments
    comments_raw = adapter.list_pr_comments(owner, repo, pr_number)
    issue_comments = [
        {
            "author": c.get("user", {}).get("login", "unknown"),
            "body": (c.get("body") or "")[:300],
        }
        for c in comments_raw[:20]
    ]

    return GovernanceContextPackage(
        pr_number=pr_number,
        pr_title=pr.get("title", ""),
        pr_description=(pr.get("body") or "")[:1000],
        pr_url=pr.get("html_url", ""),
        author=pr.get("user", {}).get("login", "unknown"),
        commit_messages=commit_messages,
        changed_file_count=pr.get("changed_files", len(files_raw)),
        additions=pr.get("additions", 0),
        deletions=pr.get("deletions", 0),
        changed_files=changed_files,
        review_comments=review_comments,
        issue_comments=issue_comments,
    )
