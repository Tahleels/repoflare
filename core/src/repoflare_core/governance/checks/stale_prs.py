"""Stale PR check.

A PR is considered stale when it has been open longer than `stale_days` (default 14) AND
its most-recent activity (push, comment, review) was more than `stale_days` ago.

Returns one GovernanceFinding per stale PR found, plus an aggregate roll-up finding when
at least one stale PR is present.

Provenance: 'github_api'
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from repoflare_core.domain.entities import (
    GovernanceCheck,
    GovernanceFinding,
    GovernanceStatus,
)
from repoflare_core.domain.ids import stable_id
from repoflare_core.governance.evidence import EvidenceBuilder
from repoflare_core.governance.github import GitHubAdapter

_DEFAULT_STALE_DAYS = 14


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _last_activity(pr: dict) -> datetime | None:  # type: ignore[type-arg]
    """Return the most-recent activity timestamp we can derive from the PR object."""
    candidates = [
        _parse_dt(pr.get("updated_at")),
        _parse_dt(pr.get("created_at")),
    ]
    valid = [c for c in candidates if c is not None]
    return max(valid) if valid else None


def run(
    owner: str, repo: str, adapter: GitHubAdapter, stale_days: int = _DEFAULT_STALE_DAYS
) -> list[GovernanceFinding]:
    """Run the stale-PR check for *owner/repo*.

    Returns a list: either empty (all PRs fresh), or one aggregate finding plus one
    individual finding per stale PR.
    """
    open_prs = adapter.list_open_prs(owner, repo)
    threshold = timedelta(days=stale_days)
    now = datetime.now(UTC)
    findings: list[GovernanceFinding] = []

    stale_prs = []
    for pr in open_prs:
        opened = _parse_dt(pr.get("created_at"))
        last = _last_activity(pr)
        if opened is None:
            continue
        age = now - opened
        idle = (now - last) if last else age
        if age >= threshold and idle >= threshold:
            stale_prs.append(
                {
                    "number": pr.get("number"),
                    "title": pr.get("title", ""),
                    "opened_days_ago": int(age.days),
                    "idle_days_ago": int(idle.days),
                    "url": pr.get("html_url", ""),
                    "author": pr.get("user", {}).get("login", "unknown"),
                }
            )

    if not stale_prs:
        return []

    # Individual finding per stale PR
    for sp in stale_prs:
        eb = EvidenceBuilder()
        eb.add("pr_number", sp["number"])
        eb.add("opened_days_ago", sp["opened_days_ago"])
        eb.add("idle_days_ago", sp["idle_days_ago"])
        eb.add("url", sp["url"])
        eb.add("author", sp["author"])

        findings.append(
            GovernanceFinding(
                finding_id=stable_id(owner, repo, "STALE_PR", str(sp["number"])),
                repository=f"{owner}/{repo}",
                check=GovernanceCheck.STALE_PR,
                status=GovernanceStatus.WARN,
                severity="medium",
                title=f"Stale PR #{sp['number']}: {sp['title'][:80]}",
                description=(
                    f"PR #{sp['number']} has been open for {sp['opened_days_ago']} days "
                    f"with no activity for {sp['idle_days_ago']} days "
                    f"(threshold: {stale_days} days)."
                ),
                evidence=eb.build(),
                provenance="github_api",
            )
        )

    # Aggregate roll-up
    agg_eb = EvidenceBuilder()
    agg_eb.add("stale_pr_count", len(stale_prs))
    agg_eb.add("stale_threshold_days", stale_days)
    agg_eb.add_many([{"key": "stale_pr", "value": sp} for sp in stale_prs])

    findings.append(
        GovernanceFinding(
            finding_id=stable_id(owner, repo, "STALE_PR", "aggregate"),
            repository=f"{owner}/{repo}",
            check=GovernanceCheck.STALE_PR,
            status=GovernanceStatus.WARN,
            severity="medium",
            title=f"{len(stale_prs)} stale PR(s) in {repo}",
            description=(
                f"Repository {repo} has {len(stale_prs)} pull request(s) open for more "
                f"than {stale_days} days with no recent activity. "
                "Stale PRs accumulate merge debt and conflict risk."
            ),
            evidence=agg_eb.build(),
            provenance="github_api",
        )
    )
    return findings
