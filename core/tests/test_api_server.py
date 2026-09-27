"""api/server.py — routing, status codes, argument defaults and error mapping, exercised over a
real listening socket with real HTTP requests (not by calling the handler directly), because
the framing and status handling are precisely what is under test.

The server accepts any `RemoteAnalysisOperations`, so most tests inject a fake: no cloning, no
network. The two end-to-end tests monkeypatch only the repository *reference* parser, so the
entire path — HTTP → ApiOperations → service.py → real git clone → scan/parse/graph → JSON —
actually runs against a throwaway local repository.
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from repoflare_core.ai.factory import BobProviderConfigError
from repoflare_core.ai.provider import BobProviderError
from repoflare_core.api.server import (
    ApiConfig,
    ApiOperations,
    RemoteAnalysisOperations,
    RepoFlareHttpServer,
    _status_for,
)
from repoflare_core.change.git_adapter import GitCommandError
from repoflare_core.remote.workspace import RemoteRepoError, RepoRef
from repoflare_core.scanning.scanner import RepositoryTooLargeError


class _FakeOperations:
    """Records what it was called with, so tests can assert on the HTTP layer's defaults."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        if self.error is not None:
            raise self.error

    def analyze(self, repo: str) -> dict[str, Any]:
        self._record("analyze", repo)
        return {"repo": repo, "node_count": 4}

    def impact(self, repo: str, from_ref: str, to_ref: str) -> dict[str, Any]:
        self._record("impact", repo, from_ref, to_ref)
        return {"repo": repo, "from_ref": from_ref, "to_ref": to_ref}

    def explain(self, repo: str, from_ref: str, to_ref: str) -> dict[str, Any]:
        self._record("explain", repo, from_ref, to_ref)
        return {"explanation": "<cited>text</cited>"}

    def report_html(self, repo: str, from_ref: str | None, to_ref: str) -> str:
        self._record("report_html", repo, from_ref, to_ref)
        return "<!DOCTYPE html><html><body>report</body></html>"


@contextmanager
def _running(operations: RemoteAnalysisOperations) -> Iterator[str]:
    """Serve on an ephemeral port in a background thread for the duration of the block."""
    server = RepoFlareHttpServer(("127.0.0.1", 0), operations)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _request(url: str, method: str = "GET") -> tuple[int, str, str]:
    """Return (status, content-type, body) — including for 4xx/5xx, which urlopen raises on."""
    try:
        with urlopen(Request(url, method=method), timeout=60) as response:
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                response.read().decode(),
            )
    except HTTPError as exc:
        headers = exc.headers
        content_type = headers.get("Content-Type", "") if headers is not None else ""
        return exc.code, content_type, exc.read().decode()


def _make_repo(path: Path, *, commits: int = 2) -> Path:
    """A tiny two-file repository whose last commit changes utils.py, which main.py imports."""
    path.mkdir(parents=True, exist_ok=True)
    for args in (
        ("init",),
        ("config", "user.email", "test@example.com"),
        ("config", "user.name", "RepoFlare Test"),
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    (path / "utils.py").write_text("def calculate_total(items):\n    return sum(items)\n")
    (path / "main.py").write_text(
        "from utils import calculate_total\n\n\ndef run():\n    return calculate_total([1, 2, 3])\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True)
    if commits > 1:
        (path / "utils.py").write_text("def calculate_total(items):\n    return sum(items) * 1.0\n")
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "return a float"], cwd=path, check=True, capture_output=True
        )
    return path


@contextmanager
def _local_clone_operations(
    source: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[RemoteAnalysisOperations]:
    """Real ApiOperations, with only the reference parser redirected at a local path."""
    monkeypatch.setattr(
        "repoflare_core.api.server.parse_public_github_ref",
        lambda _value: RepoRef(slug="local/demo", clone_url=str(source)),
    )
    yield ApiOperations(ApiConfig(clone_depth=5, max_files=50))


# ---------------------------------------------------------------------------
# Routing and status codes
# ---------------------------------------------------------------------------


def test_healthz_is_ok() -> None:
    with _running(_FakeOperations()) as base:
        status, content_type, body = _request(f"{base}/healthz")

    assert status == 200
    assert "application/json" in content_type
    assert json.loads(body) == {"status": "ok"}


def test_landing_page_renders_the_form() -> None:
    with _running(_FakeOperations()) as base:
        status, content_type, body = _request(f"{base}/")

    assert status == 200
    assert "text/html" in content_type
    assert 'action="/report"' in body


def test_trailing_slash_is_tolerated() -> None:
    with _running(_FakeOperations()) as base:
        status, _, _ = _request(f"{base}/healthz/")

    assert status == 200


def test_unknown_route_is_404() -> None:
    with _running(_FakeOperations()) as base:
        status, _, body = _request(f"{base}/nope")

    assert status == 404
    assert json.loads(body)["error"]["type"] == "NotFound"


def test_post_is_rejected_as_read_only() -> None:
    with _running(_FakeOperations()) as base:
        status, _, body = _request(f"{base}/api/v1/analyze", method="POST")

    assert status == 405
    assert json.loads(body)["error"]["type"] == "MethodNotAllowed"


def test_report_without_a_repo_explains_itself_in_html() -> None:
    operations = _FakeOperations()
    with _running(operations) as base:
        status, content_type, body = _request(f"{base}/report")

    assert status == 400
    # A browser gets a usable page, not raw JSON.
    assert "text/html" in content_type
    assert "owner/name" in body
    assert operations.calls == []


def test_json_endpoint_without_a_repo_returns_a_json_error() -> None:
    with _running(_FakeOperations()) as base:
        status, content_type, body = _request(f"{base}/api/v1/analyze")

    assert status == 400
    assert "application/json" in content_type
    assert json.loads(body)["error"]["type"] == "RemoteRepoError"


def test_responses_are_marked_no_store() -> None:
    with (
        _running(_FakeOperations()) as base,
        urlopen(f"{base}/healthz", timeout=60) as response,
    ):
        assert response.headers["Cache-Control"] == "no-store"


# ---------------------------------------------------------------------------
# Argument defaults
# ---------------------------------------------------------------------------


def test_analyze_passes_the_repo_through() -> None:
    operations = _FakeOperations()
    with _running(operations) as base:
        _request(f"{base}/api/v1/analyze?repo=pallets/flask")

    assert operations.calls == [("analyze", ("pallets/flask",))]


def test_impact_defaults_the_ref_range() -> None:
    operations = _FakeOperations()
    with _running(operations) as base:
        _request(f"{base}/api/v1/impact?repo=pallets/flask")

    assert operations.calls == [("impact", ("pallets/flask", "HEAD~1", "HEAD"))]


def test_impact_passes_explicit_refs_through() -> None:
    operations = _FakeOperations()
    with _running(operations) as base:
        _request(f"{base}/api/v1/impact?repo=a/b&from=v1.0&to=v1.1")

    assert operations.calls == [("impact", ("a/b", "v1.0", "v1.1"))]


def test_report_without_from_is_overview_only() -> None:
    """An explicit empty `from` means "no ref range", which is how the CLI's overview-only
    export is expressed over HTTP."""
    operations = _FakeOperations()
    with _running(operations) as base:
        _request(f"{base}/report?repo=a/b&from=")

    assert operations.calls == [("report_html", ("a/b", None, "HEAD"))]


def test_explain_returns_the_explanation() -> None:
    with _running(_FakeOperations()) as base:
        status, _, body = _request(f"{base}/api/v1/explain?repo=a/b&from=X&to=Y")

    assert status == 200
    assert json.loads(body)["explanation"] == "<cited>text</cited>"


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (RemoteRepoError("bad repo"), 400),
        (GitCommandError("bad ref"), 400),
        (RepositoryTooLargeError(400), 413),
        (BobProviderConfigError("no provider"), 503),
        (BobProviderError("upstream failed"), 502),
        (RuntimeError("unexpected"), 500),
    ],
)
def test_exceptions_map_to_status_codes(error: Exception, expected_status: int) -> None:
    assert _status_for(error) == expected_status


def test_client_errors_surface_their_message() -> None:
    with _running(_FakeOperations(RemoteRepoError("could not clone xyz"))) as base:
        status, _, body = _request(f"{base}/api/v1/analyze?repo=a/b")

    assert status == 400
    assert "could not clone xyz" in json.loads(body)["error"]["message"]


def test_server_errors_do_not_leak_internals() -> None:
    with _running(_FakeOperations(RuntimeError("secret internal detail"))) as base:
        status, _, body = _request(f"{base}/api/v1/analyze?repo=a/b")

    assert status == 500
    assert "secret internal detail" not in body
    assert json.loads(body)["error"]["type"] == "RuntimeError"


def test_html_route_errors_stay_html() -> None:
    with _running(_FakeOperations(RemoteRepoError("nope"))) as base:
        status, content_type, body = _request(f"{base}/report?repo=a/b")

    assert status == 400
    assert "text/html" in content_type
    assert "<!DOCTYPE html>" in body


def test_a_failing_request_does_not_kill_the_server() -> None:
    """Regression guard, same failure mode the RPC server had to fix: one bad request must
    never take the listener down for every later caller."""
    with _running(_FakeOperations(RuntimeError("boom"))) as base:
        first, _, _ = _request(f"{base}/api/v1/analyze?repo=a/b")
        second, _, _ = _request(f"{base}/healthz")

    assert first == 500
    assert second == 200


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class _BlockingOperations(_FakeOperations):
    """Holds `analyze` open until released, so another request can be issued meanwhile."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def analyze(self, repo: str) -> dict[str, Any]:
        self.entered.set()
        assert self.release.wait(timeout=30)
        return {"repo": repo}


def test_healthz_answers_while_an_analysis_is_running() -> None:
    """Why this server is threaded rather than serial: an analysis blocks for seconds, and
    Render kills a service whose health check stops answering during that window."""
    operations = _BlockingOperations()
    with _running(operations) as base:
        statuses: list[int] = []
        worker = threading.Thread(
            target=lambda: statuses.append(_request(f"{base}/api/v1/analyze?repo=a/b")[0]),
            daemon=True,
        )
        worker.start()
        assert operations.entered.wait(timeout=30)

        health, _, _ = _request(f"{base}/healthz")

        operations.release.set()
        worker.join(timeout=30)

    assert health == 200
    assert statuses == [200]


# ---------------------------------------------------------------------------
# End to end: HTTP -> ApiOperations -> service.py -> real git clone -> graph -> JSON
# ---------------------------------------------------------------------------


def test_end_to_end_analyze_over_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _make_repo(tmp_path / "source")

    with (
        _local_clone_operations(source, monkeypatch) as operations,
        _running(operations) as base,
    ):
        status, _, body = _request(f"{base}/api/v1/analyze?repo=local/demo")

    assert status == 200
    payload = json.loads(body)
    assert payload["repo"] == "local/demo"
    assert payload["file_count"] == 2
    assert payload["symbol_count"] == 2
    assert payload["node_count"] == 4
    assert payload["head_sha"]


def test_end_to_end_impact_over_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reproduces docs/DEMO_SCRIPT.md's verified result through the HTTP layer: changing
    utils.py puts main.py — which imports it and is itself unchanged — in DIRECT."""
    source = _make_repo(tmp_path / "source", commits=2)

    with (
        _local_clone_operations(source, monkeypatch) as operations,
        _running(operations) as base,
    ):
        status, _, body = _request(f"{base}/api/v1/impact?repo=local/demo&from=HEAD~1&to=HEAD")

    assert status == 200
    payload = json.loads(body)
    assert payload["changed_files"] == ["utils.py"]
    assert [entry["category"] for entry in payload["impact"]] == ["DIRECT"]
    assert payload["impact"][0]["provenance"] == "graph_traversal"


def test_end_to_end_report_over_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _make_repo(tmp_path / "source", commits=2)

    with (
        _local_clone_operations(source, monkeypatch) as operations,
        _running(operations) as base,
    ):
        status, content_type, body = _request(f"{base}/report?repo=local/demo&from=HEAD~1&to=HEAD")

    assert status == 200
    assert "text/html" in content_type
    assert "RepoFlare" in body
    # The impact section is populated from the real graph, not stubbed.
    assert "utils.py" in body
    assert "main" in body
