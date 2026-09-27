"""Unresolved conflict check.

A PR has an unresolved conflict when GitHub's `mergeable_state` is 'dirty' (the branch
cannot be automatically merged because of conflicting changes) or 'behind' (the branch is
behind the base branch and would need a rebase before merging cleanly).

The check fetches each open PR's full object (which includes `mergeable_state`) to
determine conflict status.  Because the full-PR endpoint is one request per PR, this check
caps processing to the first 30 open PRs to stay inside reasonable rate-limit budgets.

`mergeable_state` values used:
  'clean'     — no conflicts, good to merge
  'dirty'     — merge conflict exists
  'behind'    — branch is behind base (not a hard conflict but risky)
  'blocked'   — failing status checks (not a conflict — ignored here)
  'unstable'  — passing but with warnings (ignored here)
  'unknown'   — GitHub hasn't computed this yet (treated as UNKNOWN)

Provenance: 'github_api'
"""

from __future__ import annotations

from repoflare_core.domain.entities import (
    GovernanceCheck,
    GovernanceFinding,
    GovernanceStatus,
)
from repoflare_core.domain.ids import stable_id
from repoflare_core.governance.evidence import EvidenceBuilder
from repoflare_core.governance.github import GitHubAdapter, GitHubAPIError

_PR_CAP = 30  # max PRs to deep-inspect per repo (rate-limit guard)
_CONFLICT_STATES = {"dirty"}
_BEHIND_STATES = {"behind"}


def run(owner: str, repo: str, adapter: GitHubAdapter) -> list[GovernanceFinding]:
    """Run the unresolved-conflict check for *owner/repo*.

    Returns a list of findings — empty when no conflicts or behind-PRs are found.
    """
    open_prs = adapter.list_open_prs(owner, repo)[:_PR_CAP]
    findings: list[GovernanceFinding] = []

    for pr_stub in open_prs:
        pr_number = pr_stub.get("number")
        if pr_number is None:
            continue
        try:
            pr = adapter.get_pr(owner, repo, pr_number)
        except GitHubAPIError:
            continue

        mergeable_state = (pr.get("mergeable_state") or "unknown").lower()

        if mergeable_state in _CONFLICT_STATES:
            _emit_conflict(findings, owner, repo, pr, mergeable_state)
        elif mergeable_state in _BEHIND_STATES:
            _emit_behind(findings, owner, repo, pr)

    return findings


def _emit_conflict(
    findings: list[GovernanceFinding],
    owner: str,
    repo: str,
    pr: dict,  # type: ignore[type-arg]
    state: str,
) -> None:
    number = pr.get("number")
    title = pr.get("title", "")[:80]
    eb = EvidenceBuilder()
    eb.add("pr_number", number)
    eb.add("mergeable_state", state)
    eb.add("head_ref", pr.get("head", {}).get("ref", ""))
    eb.add("base_ref", pr.get("base", {}).get("ref", ""))
    eb.add("url", pr.get("html_url", ""))
    eb.add("author", pr.get("user", {}).get("login", "unknown"))

    findings.append(
        GovernanceFinding(
            finding_id=stable_id(owner, repo, "CONFLICT", str(number)),
            repository=f"{owner}/{repo}",
            check=GovernanceCheck.CONFLICT,
            status=GovernanceStatus.FAIL,
            severity="high",
            title=f"Merge conflict in PR #{number}: {title}",
            description=(
                f"PR #{number} in {repo} has an unresolved merge conflict "
                f"(mergeable_state='{state}'). The branch cannot be automatically merged "
                "until conflicts are resolved."
            ),
            evidence=eb.build(),
            provenance="github_api",
        )
    )


def _emit_behind(
    findings: list[GovernanceFinding],
    owner: str,
    repo: str,
    pr: dict,  # type: ignore[type-arg]
) -> None:
    number = pr.get("number")
    title = pr.get("title", "")[:80]
    eb = EvidenceBuilder()
    eb.add("pr_number", number)
    eb.add("mergeable_state", "behind")
    eb.add("head_ref", pr.get("head", {}).get("ref", ""))
    eb.add("base_ref", pr.get("base", {}).get("ref", ""))
    eb.add("url", pr.get("html_url", ""))

    findings.append(
        GovernanceFinding(
            finding_id=stable_id(owner, repo, "CONFLICT", str(number), "behind"),
            repository=f"{owner}/{repo}",
            check=GovernanceCheck.CONFLICT,
            status=GovernanceStatus.WARN,
            severity="medium",
            title=f"PR #{number} is behind base: {title}",
            description=(
                f"PR #{number} in {repo} is behind its base branch. "
                "It should be rebased or merged-up before landing to avoid hidden conflicts."
            ),
            evidence=eb.build(),
            provenance="github_api",
        )
    )
