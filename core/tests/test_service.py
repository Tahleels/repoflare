"""Direct (non-CLI) exercise of the service layer — the RPC server will call these
functions exactly like this, so it matters that they work without going through Typer."""

import subprocess
from pathlib import Path

import pytest

from repoflare_core.domain.entities import ImpactCategory
from repoflare_core.service import (
    NotAnalyzedError,
    NotInitializedError,
    run_analyze,
    run_explain,
    run_impact,
    run_init,
    run_status,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_run_init_creates_db(tmp_path: Path) -> None:
    result = run_init(tmp_path)

    assert result.db_path.exists()


def test_run_init_nonexistent_path_raises() -> None:
    with pytest.raises(NotADirectoryError):
        run_init(Path("/definitely/does/not/exist/xyz"))


def test_run_analyze_before_init_raises(tmp_path: Path) -> None:
    with pytest.raises(NotInitializedError):
        run_analyze(tmp_path)


def test_run_status_before_init_raises(tmp_path: Path) -> None:
    with pytest.raises(NotInitializedError):
        run_status(tmp_path)


def test_run_analyze_and_status_roundtrip(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def helper():\n    pass\n\ndef entry():\n    helper()\n")
    run_init(tmp_path)

    analyze_result = run_analyze(tmp_path)
    status_result = run_status(tmp_path)

    assert analyze_result.symbol_count == 2
    assert status_result.snapshot_id == analyze_result.snapshot_id
    assert status_result.node_count == 3  # 1 file + 2 symbols
    assert status_result.edge_count == 3  # 2 CONTAINS + 1 CALLS


def test_run_impact_before_analyze_raises(tmp_path: Path) -> None:
    run_init(tmp_path)
    with pytest.raises(NotAnalyzedError):
        run_impact(tmp_path, from_ref="HEAD~1")


def test_run_impact_end_to_end(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "a.py").write_text("def helper():\n    pass\n")
    (repo / "b.py").write_text("from a import helper\n\ndef entry():\n    helper()\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "first")
    first_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    run_init(repo)
    run_analyze(repo)
    (repo / "a.py").write_text("def helper():\n    return 1\n")
    _git(repo, "commit", "-a", "-q", "-m", "second")

    summary = run_impact(repo, from_ref=first_sha)

    assert summary.changed_files == ["a.py"]
    direct = next(r for r in summary.results if r.category == ImpactCategory.DIRECT)
    (affected_id,) = direct.affected_node_ids
    assert summary.node_summaries[affected_id].file_path == "b.py"


def test_run_explain_no_changes_returns_none(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "a.py").write_text("def f():\n    pass\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "first")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    run_init(repo)
    run_analyze(repo)

    assert run_explain(repo, from_ref=sha, to_ref=sha) is None
