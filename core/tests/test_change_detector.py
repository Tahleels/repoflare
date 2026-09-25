import subprocess
from pathlib import Path

import pytest

from repoflare_core.change.detector import ChangeDetector
from repoflare_core.change.git_adapter import GitAdapter, GitCommandError


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init_repo_with_two_commits(repo: Path) -> tuple[str, str]:
    repo.mkdir(exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")

    (repo / "a.py").write_text("def a():\n    pass\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "first")
    first_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    (repo / "b.py").write_text("def b():\n    pass\n")
    (repo / "a.py").write_text("def a():\n    return 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "second")
    second_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    return first_sha, second_sha


def test_changed_files_between_commits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    first_sha, second_sha = _init_repo_with_two_commits(repo)

    changed = GitAdapter(repo).changed_files(first_sha, second_sha)

    assert set(changed) == {"a.py", "b.py"}


def test_current_commit_sha(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _first_sha, second_sha = _init_repo_with_two_commits(repo)

    assert GitAdapter(repo).current_commit_sha() == second_sha


def test_invalid_ref_raises_git_command_error(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo_with_two_commits(repo)

    with pytest.raises(GitCommandError):
        GitAdapter(repo).changed_files("not-a-real-ref")


def test_change_detector_builds_change_set(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    first_sha, second_sha = _init_repo_with_two_commits(repo)

    detector = ChangeDetector(GitAdapter(repo))
    change_set = detector.detect(
        change_set_id="cs1",
        snapshot_to_id="snap2",
        from_ref=first_sha,
        to_ref=second_sha,
        snapshot_from_id="snap1",
    )

    assert change_set.change_set_id == "cs1"
    assert change_set.snapshot_from_id == "snap1"
    assert change_set.snapshot_to_id == "snap2"
    assert set(change_set.changed_files) == {"a.py", "b.py"}


def test_change_detector_without_snapshot_from_id(tmp_path: Path) -> None:
    """snapshot_from_id is optional — omitting it must still produce a valid ChangeSet."""
    repo = tmp_path / "repo"
    first_sha, second_sha = _init_repo_with_two_commits(repo)

    change_set = ChangeDetector(GitAdapter(repo)).detect(
        change_set_id="cs1",
        snapshot_to_id="snap2",
        from_ref=first_sha,
        to_ref=second_sha,
    )

    assert change_set.snapshot_from_id is None
    assert set(change_set.changed_files) == {"a.py", "b.py"}


def test_empty_diff_yields_empty_changed_files(tmp_path: Path) -> None:
    """Comparing a commit to itself must return an empty file list, not raise."""
    repo = tmp_path / "repo"
    _first_sha, second_sha = _init_repo_with_two_commits(repo)

    change_set = ChangeDetector(GitAdapter(repo)).detect(
        change_set_id="cs-self",
        snapshot_to_id="snap2",
        from_ref=second_sha,
        to_ref=second_sha,
    )

    assert change_set.changed_files == []


def test_git_command_error_message_includes_exit_code(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo_with_two_commits(repo)

    with pytest.raises(GitCommandError, match="exit"):
        GitAdapter(repo).changed_files("totally-invalid-ref-xyz")
