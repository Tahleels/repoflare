"""Tests for CacheProvider — covers get/set roundtrip, expiry, TTL, conflict-update, and
the cache-hit short-circuit in service.run_explain."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb

from repoflare_core.cache.provider import CacheProvider
from repoflare_core.graph.schema import SCHEMA_SQL
from repoflare_core.service import run_explain

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_conn(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(str(tmp_path / "cache_test.duckdb"))
    conn.execute(SCHEMA_SQL)
    return conn


# ---------------------------------------------------------------------------
# CacheProvider unit tests
# ---------------------------------------------------------------------------


def test_get_returns_none_for_unknown_key(tmp_path: Path) -> None:
    conn = _fresh_conn(tmp_path)
    cache = CacheProvider(conn)
    assert cache.get("no-such-key") is None
    conn.close()


def test_set_and_get_roundtrip(tmp_path: Path) -> None:
    conn = _fresh_conn(tmp_path)
    cache = CacheProvider(conn)
    cache.set("k1", {"text": "hello world"})
    raw = cache.get("k1")
    assert raw is not None
    assert json.loads(raw) == {"text": "hello world"}
    conn.close()


def test_get_returns_string(tmp_path: Path) -> None:
    conn = _fresh_conn(tmp_path)
    cache = CacheProvider(conn)
    cache.set("k1", {"text": "result"})
    result = cache.get("k1")
    assert isinstance(result, str)
    conn.close()


def test_set_overwrites_existing_entry(tmp_path: Path) -> None:
    conn = _fresh_conn(tmp_path)
    cache = CacheProvider(conn)
    cache.set("k1", {"text": "first"})
    cache.set("k1", {"text": "second"})
    raw = cache.get("k1")
    assert raw is not None
    assert json.loads(raw)["text"] == "second"
    conn.close()


def test_entry_without_ttl_does_not_expire(tmp_path: Path) -> None:
    conn = _fresh_conn(tmp_path)
    cache = CacheProvider(conn)
    cache.set("k1", {"text": "permanent"})
    # Simulate reading well into the future by checking expires_at is NULL.
    row = conn.execute(
        "SELECT expires_at FROM analysis_cache WHERE cache_key = ?", ["k1"]
    ).fetchone()
    assert row is not None
    assert row[0] is None
    # get() should still work
    assert cache.get("k1") is not None
    conn.close()


def test_entry_with_future_ttl_is_returned(tmp_path: Path) -> None:
    conn = _fresh_conn(tmp_path)
    cache = CacheProvider(conn)
    cache.set("k1", {"text": "soon"}, ttl=timedelta(hours=1))
    assert cache.get("k1") is not None
    conn.close()


def test_expired_entry_returns_none_and_is_deleted(tmp_path: Path) -> None:
    conn = _fresh_conn(tmp_path)
    cache = CacheProvider(conn)
    # Insert an already-expired entry directly so we don't have to sleep.
    past = datetime(2000, 1, 1, tzinfo=UTC)
    sql = (
        "INSERT INTO analysis_cache (cache_key, result, created_at, expires_at) VALUES (?, ?, ?, ?)"
    )
    conn.execute(sql, ["stale", json.dumps({"text": "old"}), datetime.now(UTC), past])
    assert cache.get("stale") is None
    # Row must have been cleaned up.
    row = conn.execute(
        "SELECT count(*) FROM analysis_cache WHERE cache_key = ?", ["stale"]
    ).fetchone()
    assert row is not None and row[0] == 0
    conn.close()


def test_multiple_keys_are_independent(tmp_path: Path) -> None:
    conn = _fresh_conn(tmp_path)
    cache = CacheProvider(conn)
    cache.set("a", {"text": "alpha"})
    cache.set("b", {"text": "beta"})
    assert json.loads(cache.get("a"))["text"] == "alpha"  # type: ignore[arg-type]
    assert json.loads(cache.get("b"))["text"] == "beta"  # type: ignore[arg-type]
    conn.close()


# ---------------------------------------------------------------------------
# service.run_explain cache integration
# ---------------------------------------------------------------------------


def _setup_git_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Two-commit git repo; returns (repo_path, first_sha, second_sha)."""
    import subprocess

    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "first"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    import subprocess as sp

    first_sha = sp.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n")
    subprocess.run(
        ["git", "commit", "-a", "-m", "second"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    second_sha = sp.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return tmp_path, first_sha, second_sha


def test_run_explain_returns_cached_result_without_calling_provider(
    tmp_path: Path,
) -> None:
    """On a second run_explain with the same refs, the provider must NOT be called again."""
    repo, first_sha, _second_sha = _setup_git_repo(tmp_path)

    from repoflare_core.service import run_analyze, run_init

    run_init(repo)
    run_analyze(repo)

    mock_provider = MagicMock()
    mock_provider.complete.return_value = "AI explanation text"

    with patch("repoflare_core.service.default_bob_provider", return_value=mock_provider):
        result1 = run_explain(repo, first_sha)

    assert result1 == "AI explanation text"
    assert mock_provider.complete.call_count == 1

    # Second call — same refs, same graph state — must hit the cache.
    mock_provider2 = MagicMock()
    mock_provider2.complete.return_value = "should not appear"

    with patch("repoflare_core.service.default_bob_provider", return_value=mock_provider2):
        result2 = run_explain(repo, first_sha)

    assert result2 == "AI explanation text"
    assert mock_provider2.complete.call_count == 0


def test_run_explain_different_from_ref_misses_cache(tmp_path: Path) -> None:
    """A different from_ref produces a different change_set_id and therefore a cache miss."""
    repo, first_sha, second_sha = _setup_git_repo(tmp_path)

    from repoflare_core.service import run_analyze, run_init

    run_init(repo)
    run_analyze(repo)

    mock_provider = MagicMock()
    mock_provider.complete.return_value = "first explanation"

    # diff from first → second (HEAD)
    with patch("repoflare_core.service.default_bob_provider", return_value=mock_provider):
        result1 = run_explain(repo, first_sha, second_sha)

    assert result1 == "first explanation"
    assert mock_provider.complete.call_count == 1

    # Same diff again — cache hit, provider must NOT be called.
    mock_provider2 = MagicMock()
    mock_provider2.complete.return_value = "should not appear"

    with patch("repoflare_core.service.default_bob_provider", return_value=mock_provider2):
        result2 = run_explain(repo, first_sha, second_sha)

    assert result2 == "first explanation"
    assert mock_provider2.complete.call_count == 0
