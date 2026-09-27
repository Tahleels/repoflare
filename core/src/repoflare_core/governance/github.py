"""GitHubAdapter: thin HTTP wrapper around the GitHub REST API v3.

Every governance check that needs live GitHub data goes through this adapter — not because
we need a full SDK, but because:

  1. Token management belongs in one place.
  2. Rate-limit handling (simple 429/403 back-off) is centralised.
  3. Tests can inject a fake adapter without mocking httpx globally.

Only the endpoints actually used by the governance checks are implemented.  Unused REST
surface is intentionally omitted — governance.checks.* tells us what we need.

All methods return plain Python dicts/lists (the raw JSON parsed by httpx) so the checks
can stay decoupled from this adapter's type system.

Authentication:
  Pass ``token`` explicitly, or set the ``GITHUB_TOKEN`` environment variable.
  Unauthenticated requests are allowed but severely rate-limited (60 req/hr); the adapter
  logs a warning when no token is present.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.github.com"
_DEFAULT_TIMEOUT = 20.0
_RATE_LIMIT_SLEEP = 5.0  # seconds to wait after a 429 before one retry


class GitHubAPIError(RuntimeError):
    """Raised when a GitHub API call fails and cannot be retried."""

    def __init__(self, status_code: int, url: str, message: str) -> None:
        super().__init__(f"GitHub API {status_code} at {url}: {message}")
        self.status_code = status_code


class GitHubAdapter:
    """Thin synchronous GitHub REST adapter used by governance checks."""

    def __init__(self, token: str | None = None, timeout: float = _DEFAULT_TIMEOUT) -> None:
        resolved_token = token or os.environ.get("GITHUB_TOKEN")
        if not resolved_token:
            logger.warning("No GITHUB_TOKEN found — unauthenticated requests are limited to 60/hr.")
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if resolved_token:
            headers["Authorization"] = f"Bearer {resolved_token}"
        self._client = httpx.Client(
            base_url=_BASE,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # Organisation / repository listing
    # ------------------------------------------------------------------

    def list_org_repos(self, org: str, per_page: int = 100) -> list[dict[str, Any]]:
        """Return all non-archived repositories for *org* (pages automatically)."""
        results: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._get(
                f"/orgs/{org}/repos",
                params={"per_page": per_page, "page": page, "type": "all"},
            )
            if not isinstance(data, list):
                break
            results.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return [r for r in results if not r.get("archived", False)]

    # ------------------------------------------------------------------
    # Security / Dependabot
    # ------------------------------------------------------------------

    def list_dependabot_alerts(
        self, owner: str, repo: str, state: str = "open"
    ) -> list[dict[str, Any]]:
        """Return open Dependabot vulnerability alerts for *owner/repo*."""
        try:
            data = self._get(
                f"/repos/{owner}/{repo}/dependabot/alerts",
                params={"state": state, "per_page": 100},
            )
        except GitHubAPIError as exc:
            # 403/404 means Dependabot isn't enabled or the token lacks the security scope.
            if exc.status_code in (403, 404):
                logger.debug("Dependabot alerts unavailable for %s/%s: %s", owner, repo, exc)
                return []
            raise
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # Pull requests
    # ------------------------------------------------------------------

    def list_open_prs(self, owner: str, repo: str) -> list[dict[str, Any]]:
        """Return all open PRs for *owner/repo*."""
        results: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._get(
                f"/repos/{owner}/{repo}/pulls",
                params={"state": "open", "per_page": 100, "page": page},
            )
            if not isinstance(data, list):
                break
            results.extend(data)
            if len(data) < 100:
                break
            page += 1
        return results

    def get_pr(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
        """Return the full PR object for a single PR (includes `mergeable_state`)."""
        pr: dict[str, Any] = self._get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        return pr

    def list_pr_reviews(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """Return all review objects for a PR."""
        data = self._get(f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews")
        return data if isinstance(data, list) else []

    def list_pr_comments(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """Return all issue comments on a PR (not inline review comments)."""
        data = self._get(f"/repos/{owner}/{repo}/issues/{pr_number}/comments")
        return data if isinstance(data, list) else []

    def list_pr_files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """Return the files changed by a PR."""
        data = self._get(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
            params={"per_page": 100},
        )
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # Commits / CI
    # ------------------------------------------------------------------

    def list_recent_commits(
        self, owner: str, repo: str, branch: str = "main", limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return the *limit* most recent commits on *branch*."""
        data = self._get(
            f"/repos/{owner}/{repo}/commits",
            params={"sha": branch, "per_page": limit},
        )
        return data if isinstance(data, list) else []

    def list_check_runs_for_ref(self, owner: str, repo: str, ref: str) -> list[dict[str, Any]]:
        """Return all CI check runs for a commit SHA or branch ref."""
        data = self._get(f"/repos/{owner}/{repo}/commits/{ref}/check-runs")
        if not isinstance(data, dict):
            return []
        check_runs: list[dict[str, Any]] = data.get("check_runs", [])
        return check_runs

    def list_workflow_runs(
        self, owner: str, repo: str, status: str = "completed"
    ) -> list[dict[str, Any]]:
        """Return recent workflow runs filtered by *status*."""
        data = self._get(
            f"/repos/{owner}/{repo}/actions/runs",
            params={"status": status, "per_page": 30},
        )
        if not isinstance(data, dict):
            return []
        workflow_runs: list[dict[str, Any]] = data.get("workflow_runs", [])
        return workflow_runs

    # ------------------------------------------------------------------
    # Repository content (for PII / sprawl checks)
    # ------------------------------------------------------------------

    def get_readme(self, owner: str, repo: str) -> str:
        """Return the README text, or '' if not found."""
        try:
            data = self._get(f"/repos/{owner}/{repo}/readme")
        except GitHubAPIError as exc:
            if exc.status_code == 404:
                return ""
            raise
        if not isinstance(data, dict):
            return ""
        import base64

        content = data.get("content", "")
        encoding = data.get("encoding", "base64")
        if encoding == "base64":
            try:
                return base64.b64decode(content.replace("\n", "")).decode("utf-8", errors="replace")
            except Exception:
                return ""
        return str(content)

    def get_file_contents(self, owner: str, repo: str, path: str) -> str:
        """Return the decoded text of a file, or '' on 404."""
        try:
            data = self._get(f"/repos/{owner}/{repo}/contents/{path}")
        except GitHubAPIError as exc:
            if exc.status_code == 404:
                return ""
            raise
        if not isinstance(data, dict):
            return ""
        import base64

        content = data.get("content", "")
        encoding = data.get("encoding", "base64")
        if encoding == "base64":
            try:
                return base64.b64decode(content.replace("\n", "")).decode("utf-8", errors="replace")
            except Exception:
                return ""
        return str(content)

    def list_tree(self, owner: str, repo: str, tree_sha: str = "HEAD") -> list[dict[str, Any]]:
        """Return the recursive file tree for a repository."""
        try:
            data = self._get(
                f"/repos/{owner}/{repo}/git/trees/{tree_sha}",
                params={"recursive": "1"},
            )
        except GitHubAPIError as exc:
            if exc.status_code == 404:
                return []
            raise
        if not isinstance(data, dict):
            return []
        tree: list[dict[str, Any]] = data.get("tree", [])
        return tree

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = path
        response = self._client.get(url, params=params)
        if response.status_code == 429 or (
            response.status_code == 403 and "rate limit" in response.text.lower()
        ):
            logger.warning("GitHub rate limit hit — waiting %.0fs before retry", _RATE_LIMIT_SLEEP)
            time.sleep(_RATE_LIMIT_SLEEP)
            response = self._client.get(url, params=params)

        if response.status_code >= 400:
            raise GitHubAPIError(
                status_code=response.status_code,
                url=str(response.url),
                message=response.text[:200],
            )
        return response.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GitHubAdapter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
