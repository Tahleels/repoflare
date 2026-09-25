import subprocess
from pathlib import Path

from typer.testing import CliRunner

from repoflare_core.cli.main import app

runner = CliRunner()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_init_analyze_status_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("def helper():\n    pass\n\ndef entry():\n    helper()\n")

    init_result = runner.invoke(app, ["init", str(tmp_path)])
    assert init_result.exit_code == 0, init_result.output

    analyze_result = runner.invoke(app, ["analyze", str(tmp_path)])
    assert analyze_result.exit_code == 0, analyze_result.output
    assert (
        "Analyzed 1 files, extracted 2 symbols, resolved 1 CALLS/IMPORTS edges."
        in analyze_result.output
    )

    status_result = runner.invoke(app, ["status", str(tmp_path)])
    assert status_result.exit_code == 0, status_result.output
    # 1 file + 2 symbols = 3 nodes; 2 CONTAINS edges + 1 CALLS edge = 3 edges
    assert "Nodes: 3, Edges: 3" in status_result.output


def test_status_before_init_errors(tmp_path: Path) -> None:
    result = runner.invoke(app, ["status", str(tmp_path)])
    assert result.exit_code == 1


def test_analyze_before_init_errors(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(tmp_path)])
    assert result.exit_code == 1


def test_status_after_init_but_before_analyze(tmp_path: Path) -> None:
    """init without analyze must produce an informative message, not an error exit."""
    runner.invoke(app, ["init", str(tmp_path)])

    result = runner.invoke(app, ["status", str(tmp_path)])

    assert result.exit_code == 0
    assert "not yet analyzed" in result.output


def test_repeated_analyze_creates_new_snapshot(tmp_path: Path) -> None:
    """Running analyze twice should succeed both times and each creates a new snapshot."""
    (tmp_path / "main.py").write_text("def f(): pass\n")

    runner.invoke(app, ["init", str(tmp_path)])
    first = runner.invoke(app, ["analyze", str(tmp_path)])
    second = runner.invoke(app, ["analyze", str(tmp_path)])

    assert first.exit_code == 0
    assert second.exit_code == 0
    # Each invocation prints a different snapshot id
    first_snap = next(line for line in first.output.splitlines() if line.startswith("Snapshot:"))
    second_snap = next(line for line in second.output.splitlines() if line.startswith("Snapshot:"))
    assert first_snap != second_snap


def test_init_on_nonexistent_path_errors(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path / "does_not_exist")])
    assert result.exit_code == 1


def test_analyze_empty_repo_succeeds(tmp_path: Path) -> None:
    """A repo with no source files must not crash — just reports 0 files."""
    runner.invoke(app, ["init", str(tmp_path)])

    result = runner.invoke(app, ["analyze", str(tmp_path)])

    assert result.exit_code == 0
    assert "Analyzed 0 files" in result.output


def test_impact_end_to_end(tmp_path: Path) -> None:
    """init -> analyze at commit 1 -> change a file -> commit -> impact --from commit1
    must report the caller of the changed function as DIRECT impact."""
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

    runner.invoke(app, ["init", str(repo)])
    runner.invoke(app, ["analyze", str(repo)])

    (repo / "a.py").write_text("def helper():\n    return 1\n")
    _git(repo, "commit", "-a", "-q", "-m", "second")

    result = runner.invoke(app, ["impact", "--from", first_sha, str(repo)])

    assert result.exit_code == 0, result.output
    assert "Changed files (1): a.py" in result.output
    assert "DIRECT" in result.output


def test_impact_before_analyze_errors(tmp_path: Path) -> None:
    runner.invoke(app, ["init", str(tmp_path)])

    result = runner.invoke(app, ["impact", "--from", "HEAD~1", str(tmp_path)])

    assert result.exit_code == 1


def test_impact_before_init_errors(tmp_path: Path) -> None:
    result = runner.invoke(app, ["impact", "--from", "HEAD~1", str(tmp_path)])
    assert result.exit_code == 1


def test_impact_no_changes_reports_none(tmp_path: Path) -> None:
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

    runner.invoke(app, ["init", str(repo)])
    runner.invoke(app, ["analyze", str(repo)])

    result = runner.invoke(app, ["impact", "--from", sha, "--to", sha, str(repo)])

    assert result.exit_code == 0
    assert "No files changed" in result.output
