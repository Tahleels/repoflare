"""HTTP layer over repoflare_core.service — the hosted demo and JSON API.

This is a third thin front door alongside cli/ and rpc/, and it holds no orchestration of its
own (docs/ARCHITECTURE.md ADR-001): it parses a query string, calls service.py, and encodes
the result. Because a hosted instance cannot read the caller's disk, the only thing it adds is
naming a repository — service.py's `run_remote_*` functions do the cloning.

Endpoints:
  GET /healthz                                    liveness probe (Render's health check)
  GET /                                           the demo page
  GET /report?repo=&from=&to=                     standalone HTML report
  GET /api/v1/analyze?repo=                       snapshot + file/symbol/edge counts
  GET /api/v1/impact?repo=&from=&to=              changed files + affected nodes by category
  GET /api/v1/explain?repo=&from=&to=             grounded AI explanation (needs a provider key)

Status codes: 400 bad request (bad repo reference or bad git ref), 404 unknown path,
405 wrong method, 413 repository too large for a hosted request, 502 AI call failed,
503 no AI provider configured, 500 anything unexpected.

Two deliberate choices worth stating:

* **No web framework.** This repo already hand-rolls its protocol layer (rpc/protocol.py) and
  its HTML (export/html.py) to stay dependency-light, and `uv.lock` must stay byte-identical
  for the frozen `uv sync` Render runs at build time. A router of six routes does not earn a
  framework, and adding one would add its own dependencies to a 512 MB instance.
* **ThreadingHTTPServer, not HTTPServer.** Every interesting request blocks for seconds
  (clone, then parse). A serial server would queue `/healthz` behind a running analysis, and
  Render kills a service whose health check stops answering.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Semaphore
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

from repoflare_core.ai.factory import BobProviderConfigError
from repoflare_core.ai.provider import BobProviderError
from repoflare_core.api.page import render_demo_page
from repoflare_core.change.git_adapter import GitCommandError
from repoflare_core.export.html import render_html
from repoflare_core.remote.workspace import RemoteRepoError, parse_public_github_ref
from repoflare_core.scanning.scanner import RepositoryTooLargeError
from repoflare_core.serialization import to_jsonable
from repoflare_core.service import (
    DEFAULT_REMOTE_CLONE_DEPTH,
    DEFAULT_REMOTE_MAX_FILES,
    run_remote_analysis,
    run_remote_explain,
)

logger = logging.getLogger(__name__)

_DEFAULT_MAX_CONCURRENCY = 2


@dataclass(frozen=True, slots=True)
class ApiConfig:
    """Per-deployment knobs. Defaults are the hosted-safe ones: a bounded clone, a bounded
    file count, and a concurrency cap that keeps two analyses from exhausting a free
    instance's memory at once."""

    clone_depth: int = DEFAULT_REMOTE_CLONE_DEPTH
    max_files: int | None = DEFAULT_REMOTE_MAX_FILES
    max_concurrency: int = _DEFAULT_MAX_CONCURRENCY


class RemoteAnalysisOperations(Protocol):
    """What the HTTP layer requires of the layer beneath it.

    Declared as a Protocol, exactly like ai/provider.py's BobProvider, so tests can hand the
    server a fake and exercise routing, status codes and escaping without cloning anything —
    while the real implementation stays a concrete class with the deployment config in it.
    """

    def analyze(self, repo: str) -> dict[str, Any]: ...

    def impact(self, repo: str, from_ref: str, to_ref: str) -> dict[str, Any]: ...

    def explain(self, repo: str, from_ref: str, to_ref: str) -> dict[str, Any]: ...

    def report_html(self, repo: str, from_ref: str | None, to_ref: str) -> str: ...


class ApiOperations:
    """The service.py calls this layer exposes, and nothing more.

    Substitutable wholesale in tests (see tests/test_api_server.py), the same way
    `RpcServer(handlers=...)` is — so the HTTP contract can be exercised without cloning
    anything or reaching the network.
    """

    def __init__(self, config: ApiConfig | None = None) -> None:
        self._config = config or ApiConfig()
        # Bounds *concurrent* analyses. Each holds a whole repository's parse results in
        # memory at once, so without this two simultaneous requests could exhaust the
        # instance's memory.
        self._slots = Semaphore(self._config.max_concurrency)

    def analyze(self, repo: str) -> dict[str, Any]:
        ref = parse_public_github_ref(repo)
        with self._slots:
            result = run_remote_analysis(
                ref, depth=self._config.clone_depth, max_files=self._config.max_files
            )
        return {
            "repo": result.repo_slug,
            "clone_url": result.clone_url,
            "head_sha": result.head_sha,
            "snapshot_id": result.status.snapshot_id,
            "node_count": result.status.node_count,
            "edge_count": result.status.edge_count,
            "file_count": result.analyze.file_count,
            "symbol_count": result.analyze.symbol_count,
            "test_count": result.analyze.test_count,
            "resolved_edge_count": result.analyze.resolved_edge_count,
            "test_edge_count": result.analyze.test_edge_count,
        }

    def impact(self, repo: str, from_ref: str, to_ref: str) -> dict[str, Any]:
        ref = parse_public_github_ref(repo)
        with self._slots:
            result = run_remote_analysis(
                ref,
                from_ref=from_ref,
                to_ref=to_ref,
                depth=self._config.clone_depth,
                max_files=self._config.max_files,
            )
        if result.impact is None:  # pragma: no cover — from_ref is always passed here
            raise RuntimeError("impact was requested but no ref range was analysed")
        return {
            "repo": result.repo_slug,
            "head_sha": result.head_sha,
            "from_ref": from_ref,
            "to_ref": to_ref,
            "changed_files": result.impact.changed_files,
            "impact": to_jsonable(result.impact.results),
            "nodes": to_jsonable(result.impact.node_summaries),
        }

    def explain(self, repo: str, from_ref: str, to_ref: str) -> dict[str, Any]:
        ref = parse_public_github_ref(repo)
        with self._slots:
            explanation = run_remote_explain(
                ref,
                from_ref,
                to_ref,
                depth=self._config.clone_depth,
                max_files=self._config.max_files,
            )
        # explanation is None when the range contains no changed files. That is a real answer
        # ("nothing changed"), not a failure, so it is returned rather than raised.
        return {
            "repo": ref.slug,
            "from_ref": from_ref,
            "to_ref": to_ref,
            "explanation": explanation,
        }

    def report_html(self, repo: str, from_ref: str | None, to_ref: str) -> str:
        ref = parse_public_github_ref(repo)
        with self._slots:
            result = run_remote_analysis(
                ref,
                from_ref=from_ref,
                to_ref=to_ref,
                depth=self._config.clone_depth,
                max_files=self._config.max_files,
            )
        impact_refs = (from_ref, to_ref) if from_ref is not None else None
        return render_html(
            repository_root=f"{result.clone_url} @ {(result.head_sha or '?')[:8]}",
            status=result.status,
            impact=result.impact,
            impact_refs=impact_refs,
        )


_HTML_ROUTES = frozenset({"/", "/report"})

_MISSING_REPO_NOTICE = (
    "Give a public GitHub repository as owner/name — for example pallets/flask — "
    "or try one of the examples below."
)

# Ordered most-specific-first; the type is also what a caller sees as error.type.
_STATUS_BY_EXCEPTION: tuple[tuple[type[Exception], int], ...] = (
    (RemoteRepoError, 400),
    (GitCommandError, 400),
    (RepositoryTooLargeError, 413),
    (BobProviderConfigError, 503),
    (BobProviderError, 502),
)


def _status_for(exc: Exception) -> int:
    for exc_type, status in _STATUS_BY_EXCEPTION:
        if isinstance(exc, exc_type):
            return status
    return 500


class RepoFlareRequestHandler(BaseHTTPRequestHandler):
    """One route table, six routes, no framework (see the module docstring)."""

    protocol_version = "HTTP/1.1"
    server_version = "RepoFlare"

    @property
    def _operations(self) -> RemoteAnalysisOperations:
        server = self.server
        # Set by RepoFlareHttpServer.__init__; every request is served by that type.
        assert isinstance(server, RepoFlareHttpServer)
        return server.operations

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's naming convention
        self._send_json(
            405,
            {
                "error": {
                    "type": "MethodNotAllowed",
                    "message": "this API is read-only; issue a GET instead",
                }
            },
        )

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's naming convention
        parsed = urlsplit(self.path)
        route = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query, keep_blank_values=True)

        repo = _first(query, "repo")
        # An absent or empty `from` means "overview only" — no ref range, no impact section.
        from_ref = _first(query, "from") or None
        to_ref = _first(query, "to") or "HEAD"
        # The JSON endpoints take a ref range as their whole point, so they default it.
        impact_from = from_ref or "HEAD~1"

        try:
            if route == "/healthz":
                self._send_json(200, {"status": "ok"})
            elif route == "/":
                self._send_html(
                    200, render_demo_page(repo=repo, from_ref=impact_from, to_ref=to_ref)
                )
            elif route == "/report":
                if not repo:
                    self._send_html(400, render_demo_page(notice=_MISSING_REPO_NOTICE))
                else:
                    self._send_html(200, self._operations.report_html(repo, from_ref, to_ref))
            elif route == "/api/v1/analyze":
                self._require_repo(repo)
                self._send_json(200, self._operations.analyze(repo))
            elif route == "/api/v1/impact":
                self._require_repo(repo)
                self._send_json(200, self._operations.impact(repo, impact_from, to_ref))
            elif route == "/api/v1/explain":
                self._require_repo(repo)
                self._send_json(200, self._operations.explain(repo, impact_from, to_ref))
            else:
                self._send_json(
                    404,
                    {"error": {"type": "NotFound", "message": f"no such route: {route}"}},
                )
        except Exception as exc:  # noqa: BLE001 — a request must never take the server down
            self._report_failure(route, repo, impact_from, to_ref, exc)

    @staticmethod
    def _require_repo(repo: str) -> None:
        if not repo:
            raise RemoteRepoError("missing required query parameter: repo=owner/name")

    def _report_failure(
        self, route: str, repo: str, from_ref: str, to_ref: str, exc: Exception
    ) -> None:
        status = _status_for(exc)
        logger.warning("%s %s failed (%s): %s", self.command, self.path, type(exc).__name__, exc)
        # A 5xx means we do not understand the failure well enough to describe it to a public
        # caller; the exception text goes to the logs instead. 4xx messages are ones we chose
        # to produce (bad repo, bad ref, too large) and are exactly what the caller needs.
        message = (
            "the analysis could not be completed — see the service logs"
            if status >= 500
            else str(exc)
        )
        if route in _HTML_ROUTES:
            self._send_html(
                status,
                render_demo_page(repo=repo, from_ref=from_ref, to_ref=to_ref, notice=message),
            )
        else:
            self._send_json(status, {"error": {"type": type(exc).__name__, "message": message}})

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _send_html(self, status: int, html: str) -> None:
        self._send_bytes(status, html.encode("utf-8"), "text/html; charset=utf-8")

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # An analysis is never worth caching: the same URL genuinely means different content
        # as soon as the branch moves, and every response is built live.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            # The caller hung up mid-response (very common once a browser tab is closed while
            # a slow analysis is still running). Nothing to do and nothing to report.
            self.close_connection = True


def _first(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name)
    return values[0].strip() if values else ""


class RepoFlareHttpServer(ThreadingHTTPServer):
    """Threaded on purpose — see the module docstring's note on /healthz."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], operations: RemoteAnalysisOperations) -> None:
        super().__init__(address, RepoFlareRequestHandler)
        self.operations = operations
