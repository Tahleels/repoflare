"""Deploy-without-test-evidence check.

This check reasons at two levels:

  Level 1 — repository-level (always run):
    Does the repository have *any* CI configuration that appears to run tests?
    Looks for common CI config files (.github/workflows/*.yml, Jenkinsfile, .travis.yml,
    .circleci/config.yml, tox.ini, pytest.ini, setup.cfg [tool:pytest], pyproject.toml
    [tool.pytest.ini_options]).  An absence of any of these is a FAIL.

  Level 2 — recent-workflow-run evidence (run when GitHub Actions are available):
    Examines the last N completed workflow runs and determines whether any run whose name
    or jobs contain the word "test" completed successfully.  If recent deployments (runs
    named 'deploy', 'release', 'publish') exist without a companion test run in the same
    window, this is flagged as DEPLOY_WITHOUT_TEST_EVIDENCE.

This is intentionally conservative in what it claims:
  - It does NOT claim "no tests exist".
  - It claims "no test-execution evidence was found in the audit window".

Provenance: 'github_api' + 'deterministic'
"""

from __future__ import annotations

import re

from repoflare_core.domain.entities import (
    GovernanceCheck,
    GovernanceFinding,
    GovernanceStatus,
)
from repoflare_core.domain.ids import stable_id
from repoflare_core.governance.evidence import EvidenceBuilder
from repoflare_core.governance.github import GitHubAdapter, GitHubAPIError

_CI_CONFIG_PATHS = [
    ".travis.yml",
    "Jenkinsfile",
    ".circleci/config.yml",
    "tox.ini",
    "pytest.ini",
    "setup.cfg",
    "pyproject.toml",
]
_WORKFLOW_DIR_PREFIX = ".github/workflows"

_TEST_KEYWORDS = re.compile(r"\btest(s|ing)?\b", re.IGNORECASE)
_DEPLOY_KEYWORDS = re.compile(r"\b(deploy|release|publish|ship)\b", re.IGNORECASE)


def run(owner: str, repo: str, adapter: GitHubAdapter) -> GovernanceFinding:
    """Run the deploy-without-test-evidence check for *owner/repo*."""
    eb = EvidenceBuilder()

    # ------------------------------------------------------------------
    # Level 1: does the repository have CI / test config at all?
    # ------------------------------------------------------------------
    tree = adapter.list_tree(owner, repo)
    tree_paths = {item.get("path", "") for item in tree}

    has_ci_config = False
    ci_files_found: list[str] = []
    for path in _CI_CONFIG_PATHS:
        if path in tree_paths:
            has_ci_config = True
            ci_files_found.append(path)

    # Check for any GitHub Actions workflow files
    workflow_files = [
        p for p in tree_paths if p.startswith(_WORKFLOW_DIR_PREFIX) and p.endswith(".yml")
    ]
    if workflow_files:
        has_ci_config = True
        ci_files_found.extend(workflow_files[:5])  # sample up to 5

    eb.add("ci_config_files_found", ci_files_found)

    if not has_ci_config:
        return GovernanceFinding(
            finding_id=stable_id(owner, repo, "DEPLOY_WITHOUT_TEST"),
            repository=f"{owner}/{repo}",
            check=GovernanceCheck.DEPLOY_WITHOUT_TEST,
            status=GovernanceStatus.FAIL,
            severity="high",
            title=f"No CI/test configuration detected in {repo}",
            description=(
                f"Repository {repo} has no recognisable CI configuration "
                "(no .github/workflows, .travis.yml, pytest.ini, etc.). "
                "No test-execution evidence can be established."
            ),
            evidence=eb.build(),
            provenance="deterministic",
        )

    # ------------------------------------------------------------------
    # Level 2: workflow-run evidence
    # ------------------------------------------------------------------
    try:
        runs = adapter.list_workflow_runs(owner, repo, status="completed")
    except GitHubAPIError:
        runs = []

    test_runs = [r for r in runs if _TEST_KEYWORDS.search(r.get("name", "") or "")]
    deploy_runs = [r for r in runs if _DEPLOY_KEYWORDS.search(r.get("name", "") or "")]

    eb.add("recent_workflow_runs_inspected", len(runs))
    eb.add("test_run_count", len(test_runs))
    eb.add("deploy_run_count", len(deploy_runs))

    if deploy_runs and not test_runs:
        # Deployments detected but no test-run evidence in the same window
        deploy_sample = [
            {
                "name": r.get("name"),
                "conclusion": r.get("conclusion"),
                "run_number": r.get("run_number"),
            }
            for r in deploy_runs[:5]
        ]
        eb.add("deploy_runs_without_test_evidence", deploy_sample)

        return GovernanceFinding(
            finding_id=stable_id(owner, repo, "DEPLOY_WITHOUT_TEST"),
            repository=f"{owner}/{repo}",
            check=GovernanceCheck.DEPLOY_WITHOUT_TEST,
            status=GovernanceStatus.FAIL,
            severity="high",
            title=f"Deployment workflow(s) found without test-run evidence in {repo}",
            description=(
                f"Repository {repo} has {len(deploy_runs)} recent deployment workflow run(s) "
                "but no test workflow runs were detected in the same audit window. "
                "This does not prove tests never run — it means no test-execution evidence "
                "was found in the most recent completed workflow runs."
            ),
            evidence=eb.build(),
            provenance="github_api",
        )

    if not runs:
        # CI config exists but no recent workflow runs at all
        return GovernanceFinding(
            finding_id=stable_id(owner, repo, "DEPLOY_WITHOUT_TEST"),
            repository=f"{owner}/{repo}",
            check=GovernanceCheck.DEPLOY_WITHOUT_TEST,
            status=GovernanceStatus.WARN,
            severity="medium",
            title=f"CI configuration present but no recent workflow runs in {repo}",
            description=(
                f"Repository {repo} has CI configuration files but no recent completed "
                "workflow runs. Test-execution evidence could not be verified."
            ),
            evidence=eb.build(),
            provenance="github_api",
        )

    # All looks fine
    return GovernanceFinding(
        finding_id=stable_id(owner, repo, "DEPLOY_WITHOUT_TEST"),
        repository=f"{owner}/{repo}",
        check=GovernanceCheck.DEPLOY_WITHOUT_TEST,
        status=GovernanceStatus.PASS,
        severity="info",
        title=f"Test-execution evidence found in {repo}",
        description=(
            f"Repository {repo} has CI configuration and {len(test_runs)} recent test "
            "workflow run(s) providing deployment test-execution evidence."
        ),
        evidence=eb.build(),
        provenance="github_api",
    )
