"""remote/workspace.py — the boundary that decides what a public endpoint may clone, and the
checkout lifecycle around it.

Clones here are made from *local paths*, which git supports natively. That is deliberate: it
exercises the real clone/populate/cleanup path without depending on the network or on GitHub
being reachable, and it is why `RepoRef` is constructible directly instead of only through
`parse_public_github_ref` (validation belongs at the HTTP boundary, not in the cloner).
"""

import subprocess
from pathlib import Path

import pytest

from repoflare_core.remote.workspace import (
    RemoteRepoError,
    RepoRef,
    cloned_workspace,
    parse_public_github_ref,
)


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for args in (
        ("init",),
        ("config", "user.email", "test@example.com"),
        ("config", "user.name", "RepoFlare Test"),
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    (path / "utils.py").write_text("def helper():\n    return 1\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True)
    return path


def _local_ref(path: Path) -> RepoRef:
    return RepoRef(slug="local/demo", clone_url=str(path))


@pytest.mark.parametrize(
    ("value", "expected_slug"),
    [
        ("pallets/flask", "pallets/flask"),
        ("  pallets/flask  ", "pallets/flask"),
        ("pallets/flask.git", "pallets/flask"),
        ("https://github.com/pallets/flask", "pallets/flask"),
        ("https://github.com/pallets/flask.git", "pallets/flask"),
        ("https://github.com/pallets/flask/", "pallets/flask"),
        ("https://www.github.com/pallets/flask", "pallets/flask"),
    ],
)
def test_accepts_slug_and_github_url_forms(value: str, expected_slug: str) -> None:
    ref = parse_public_github_ref(value)

    assert ref.slug == expected_slug
    # Never the caller's string: the only URL this can ever produce is a github.com one.
    assert ref.clone_url == "https://github.com/pallets/flask.git"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "flask",
        "a/b/c",
        "https://gitlab.com/a/b",
        "https://bitbucket.org/a/b",
        "http://github.com/a/b",
        "git@github.com:a/b.git",
        "ssh://git@github.com/a/b.git",
        "file:///etc/passwd",
        "/etc/passwd",
        "./local/repo",
        "../sibling",
        "~/.ssh",
        "C:/Users/x/repo",
        "user:pw@github.com/a/b",
        "a/b c",
        "a\\b",
        "https://github.com/a",
        "https://github.com/a/b/c",
    ],
)
def test_rejects_anything_that_is_not_a_public_github_repo(value: str) -> None:
    """Regression guard for the SSRF surface: a public endpoint that forwards this straight to
    `git clone` could otherwise be pointed at an internal host or a local file."""
    with pytest.raises(RemoteRepoError):
        parse_public_github_ref(value)


def test_workspace_yields_a_checkout_then_removes_it(tmp_path: Path) -> None:
    source = _make_repo(tmp_path / "source")

    with cloned_workspace(_local_ref(source), depth=5) as checkout:
        assert checkout.is_dir()
        assert (checkout / "utils.py").is_file()
        assert (checkout / ".git").is_dir()
        captured = checkout

    # Removed even on Windows, where git's packed objects are read-only and a plain rmtree
    # fails with WinError 5.
    assert not captured.exists()
    assert not captured.parent.exists()


def test_workspace_is_removed_when_the_body_raises(tmp_path: Path) -> None:
    source = _make_repo(tmp_path / "source")
    captured: list[Path] = []

    with (
        pytest.raises(ValueError, match="boom"),
        cloned_workspace(_local_ref(source), depth=5) as checkout,
    ):
        captured.append(checkout)
        raise ValueError("boom")

    assert not captured[0].exists()


def test_depth_below_one_is_rejected_before_cloning(tmp_path: Path) -> None:
    with (
        pytest.raises(RemoteRepoError, match="depth"),
        cloned_workspace(_local_ref(tmp_path), depth=0),
    ):
        pass


def test_unclonable_reference_raises_remote_repo_error(tmp_path: Path) -> None:
    missing = RepoRef(slug="local/missing", clone_url=str(tmp_path / "does-not-exist"))

    with (
        pytest.raises(RemoteRepoError, match="could not clone"),
        cloned_workspace(missing, depth=1),
    ):
        pass
