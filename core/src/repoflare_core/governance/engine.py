"""GovernanceEngine: the top-level orchestrator for the RepoFlare Governance Audit subsystem.

Architecture
────────────
The engine works in two tiers, mirroring RepoFlare's existing "deterministic first, AI
second" philosophy from the code-intelligence layer:

  Tier 1 — Deterministic checks (always run, no Bob calls):
    • Dependabot vulnerability alerts      (github_api)
    • Stale PR detection                   (github_api)
    • Unresolved merge conflicts           (github_api)
    • Deploy-without-test-evidence         (github_api + deterministic)
    • PII / secret pattern scan            (deterministic)
    • Repository sprawl detection          (graph_analysis)

  Tier 2 — Bob-powered checks (run only for PRs nominated by Tier 1 / config):
    • Plan-before-ship                     (bob_reasoning)
    • Inflated-diff                        (bob_reasoning)
    • HITL outsourcing detection           (bob_reasoning)

The engine is intentionally stateless: call `run_org()` or `run_repo()` and get a
GovernanceReport back.  No database writes happen here — the report is handed back to the
CLI/service layer to persist or render.

Configuration
─────────────
GovernanceEngineConfig holds all tuneable knobs with sensible defaults so callers that
just want `GovernanceEngine(adapter).run_org("my-org")` get a useful result without any
configuration boilerplate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from repoflare_core.domain.entities import (
    GovernanceFinding,
    GovernanceReport,
)
from repoflare_core.governance.checks import (
    conflicts,
    pii,
    repo_sprawl,
    stale_prs,
    test_coverage,
    vulnerabilities,
)
from repoflare_core.governance.github import GitHubAdapter

logger = logging.getLogger(__name__)


@dataclass
class GovernanceEngineConfig:
    """Tuneable parameters for the GovernanceEngine."""

    stale_days: int = 14
    """A PR is stale when open + idle for more than this many days."""

    run_pii: bool = True
    """Whether to run the PII/secret pattern scan (can be disabled for speed)."""

    run_sprawl: bool = True
    """Whether to run repo-sprawl fingerprint analysis."""

    run_ai_checks: bool = False
    """Whether to run the Tier-2 Bob-powered checks (plan_before_ship, spaghetti, hitl).
    Off by default because each check costs an AI call — enable explicitly with
    ``repoflare audit --ai`` or by setting this flag in code."""

    ai_pr_sample: int = 5
    """Maximum number of PRs to run AI checks on per repository.
    Capped to avoid runaway API/AI costs during an org-wide audit."""

    sprawl_high_threshold: float = 0.80
    sprawl_med_threshold: float = 0.60

    extra_checks: list[Any] = field(default_factory=list)
    """Extension point: inject additional check callables with the same signature as the
    built-in checks.  Each callable receives (owner, repo, adapter) and must return
    a GovernanceFinding or list[GovernanceFinding]."""


class GovernanceEngine:
    """Orchestrates all governance checks for an org or a single repository."""

    def __init__(
        self,
        adapter: GitHubAdapter,
        config: GovernanceEngineConfig | None = None,
        bob_provider: Any | None = None,
    ) -> None:
        """
        Args:
            adapter:      Authenticated GitHubAdapter instance.
            config:       Optional configuration; defaults are used when omitted.
            bob_provider: A BobProvider for Tier-2 AI checks.  Required when
                          ``config.run_ai_checks`` is True; ignored otherwise.
        """
        self._adapter = adapter
        self._config = config or GovernanceEngineConfig()
        self._bob = bob_provider

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_org(self, org: str) -> GovernanceReport:
        """Run the full governance audit for all repositories in *org*.

        Skips archived repositories automatically.
        """
        logger.info("Governance audit: fetching repositories for org %s", org)
        repos = self._adapter.list_org_repos(org)
        repo_names = [r.get("name", "") for r in repos]
        logger.info("  %d active repositories found", len(repos))

        findings: list[GovernanceFinding] = []

        # Tier 1: per-repo deterministic checks
        for repo_meta in repos:
            repo_name = repo_meta.get("name", "")
            if not repo_name:
                continue
            findings.extend(self._run_repo_checks(org, repo_name))

        # Tier 1: cross-repo sprawl check
        if self._config.run_sprawl and len(repos) >= 2:
            logger.info("  Running repo-sprawl check across %d repos", min(len(repos), 10))
            sprawl_findings = repo_sprawl.run(
                owner=org,
                repos=repos,
                adapter=self._adapter,
                high_threshold=self._config.sprawl_high_threshold,
                med_threshold=self._config.sprawl_med_threshold,
            )
            findings.extend(sprawl_findings)

        return GovernanceReport(
            org=org,
            repositories=repo_names,
            findings=findings,
            generated_at=datetime.now(UTC),
        )

    def run_repo(self, owner: str, repo: str) -> GovernanceReport:
        """Run the full governance audit for a single *owner/repo*."""
        findings = self._run_repo_checks(owner, repo)
        return GovernanceReport(
            org=owner,
            repositories=[repo],
            findings=findings,
            generated_at=datetime.now(UTC),
        )

    # ------------------------------------------------------------------
    # Internal orchestration
    # ------------------------------------------------------------------

    def _run_repo_checks(self, owner: str, repo: str) -> list[GovernanceFinding]:
        findings: list[GovernanceFinding] = []
        label = f"{owner}/{repo}"

        # -- Dependabot -------------------------------------------------
        logger.debug("  [%s] running DEPENDABOT check", label)
        try:
            findings.append(vulnerabilities.run(owner, repo, self._adapter))
        except Exception as exc:  # noqa: BLE001
            logger.warning("  [%s] DEPENDABOT check failed: %s", label, exc)

        # -- Stale PRs --------------------------------------------------
        logger.debug("  [%s] running STALE_PR check", label)
        try:
            findings.extend(stale_prs.run(owner, repo, self._adapter, self._config.stale_days))
        except Exception as exc:  # noqa: BLE001
            logger.warning("  [%s] STALE_PR check failed: %s", label, exc)

        # -- Conflicts --------------------------------------------------
        logger.debug("  [%s] running CONFLICT check", label)
        try:
            findings.extend(conflicts.run(owner, repo, self._adapter))
        except Exception as exc:  # noqa: BLE001
            logger.warning("  [%s] CONFLICT check failed: %s", label, exc)

        # -- Deploy without test evidence -------------------------------
        logger.debug("  [%s] running DEPLOY_WITHOUT_TEST check", label)
        try:
            findings.append(test_coverage.run(owner, repo, self._adapter))
        except Exception as exc:  # noqa: BLE001
            logger.warning("  [%s] DEPLOY_WITHOUT_TEST check failed: %s", label, exc)

        # -- PII / secrets ---------------------------------------------
        if self._config.run_pii:
            logger.debug("  [%s] running PII check", label)
            try:
                findings.extend(pii.run(owner, repo, self._adapter))
            except Exception as exc:  # noqa: BLE001
                logger.warning("  [%s] PII check failed: %s", label, exc)

        # -- Tier-2 AI checks ------------------------------------------
        if self._config.run_ai_checks:
            findings.extend(self._run_ai_checks(owner, repo))

        # -- Extension checks ------------------------------------------
        for check_fn in self._config.extra_checks:
            try:
                result = check_fn(owner, repo, self._adapter)
                if isinstance(result, list):
                    findings.extend(result)
                elif result is not None:
                    findings.append(result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("  [%s] extension check %s failed: %s", label, check_fn, exc)

        return findings

    def _run_ai_checks(self, owner: str, repo: str) -> list[GovernanceFinding]:
        """Run Tier-2 Bob-powered checks on a sample of open PRs."""
        from repoflare_core.governance.ai import hitl, plan_before_ship, spaghetti
        from repoflare_core.retrieval.governance_context import build_governance_context

        if self._bob is None:
            logger.warning("AI checks enabled but no BobProvider configured — skipping.")
            return []

        findings: list[GovernanceFinding] = []
        open_prs = self._adapter.list_open_prs(owner, repo)
        sampled = open_prs[: self._config.ai_pr_sample]

        for pr_stub in sampled:
            pr_number = pr_stub.get("number")
            if pr_number is None:
                continue
            try:
                ctx = build_governance_context(owner, repo, pr_number, self._adapter)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "  [%s/%s] AI context build failed for PR #%s: %s",
                    owner,
                    repo,
                    pr_number,
                    exc,
                )
                continue

            # Plan-before-ship
            try:
                findings.append(plan_before_ship.run(owner, repo, ctx, self._bob))
            except Exception as exc:  # noqa: BLE001
                logger.warning("  plan_before_ship failed for PR #%s: %s", pr_number, exc)

            # Inflated diff (skips small PRs internally)
            try:
                result = spaghetti.run(owner, repo, ctx, self._bob)
                if result is not None:
                    findings.append(result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("  spaghetti check failed for PR #%s: %s", pr_number, exc)

            # HITL
            try:
                findings.append(hitl.run(owner, repo, ctx, self._bob))
            except Exception as exc:  # noqa: BLE001
                logger.warning("  hitl check failed for PR #%s: %s", pr_number, exc)

        return findings
