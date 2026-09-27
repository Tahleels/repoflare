"""Dependabot / vulnerability check.

Queries GitHub's Dependabot alerts API for open security vulnerabilities in a repository.
Returns a single GovernanceFinding that:

  * PASS  — no open alerts
  * WARN  — alerts present but none critical/high
  * FAIL  — one or more critical or high severity alerts

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
from repoflare_core.governance.github import GitHubAdapter


def run(owner: str, repo: str, adapter: GitHubAdapter) -> GovernanceFinding:
    """Run the Dependabot vulnerability check for *owner/repo*."""
    alerts = adapter.list_dependabot_alerts(owner, repo, state="open")

    severity_counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for alert in alerts:
        sev = alert.get("security_vulnerability", {}).get("severity", "").lower()
        if sev in severity_counts:
            severity_counts[sev] += 1

    total = len(alerts)

    eb = EvidenceBuilder()
    eb.add("total_open_alerts", total)
    eb.add("severity_breakdown", severity_counts)
    for alert in alerts[:10]:  # cap evidence list to 10 samples
        pkg = alert.get("dependency", {}).get("package", {}).get("name", "unknown")
        sev = alert.get("security_vulnerability", {}).get("severity", "unknown")
        eb.add("alert", {"package": pkg, "severity": sev, "number": alert.get("number")})

    if total == 0:
        status = GovernanceStatus.PASS
        severity = "info"
        title = "No open Dependabot alerts"
        description = f"Repository {repo} has no open Dependabot security alerts."
    elif severity_counts["critical"] > 0 or severity_counts["high"] > 0:
        status = GovernanceStatus.FAIL
        severity = "critical" if severity_counts["critical"] > 0 else "high"
        title = f"{total} open Dependabot alert(s) — critical/high severity present"
        description = (
            f"Repository {repo} has {total} open Dependabot alerts including "
            f"{severity_counts['critical']} critical and {severity_counts['high']} high. "
            "These should be remediated before the next production deployment."
        )
    else:
        status = GovernanceStatus.WARN
        severity = "medium"
        title = f"{total} open Dependabot alert(s) — medium/low only"
        description = (
            f"Repository {repo} has {total} open Dependabot alerts (medium or lower). "
            "Consider scheduling remediation."
        )

    return GovernanceFinding(
        finding_id=stable_id(owner, repo, "DEPENDABOT"),
        repository=f"{owner}/{repo}",
        check=GovernanceCheck.DEPENDABOT,
        status=status,
        severity=severity,
        title=title,
        description=description,
        evidence=eb.build(),
        provenance="github_api",
    )
