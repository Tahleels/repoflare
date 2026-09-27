"""Materialising a remote Git repository into a throwaway local workspace.

RepoFlare's analyzer reads files off disk, so exposing it over HTTP (api/) means fetching the
target repository first. This module is the only place that does so, and it is deliberately
narrow about two things:

1. **What may be cloned.** `parse_public_github_ref` is the validating boundary for anything a
   caller supplies, and it accepts only github.com and only a well-formed `owner/name`. A
   public endpoint that passed its input straight to `git clone` would be a server-side
   request forgery gadget — able to reach internal hosts, `file://` URLs, or (via a leading
   `-`) git's own option parser. `RepoRef` itself is intentionally *unvalidated* so tests can
   point it at a local repository without weakening the HTTP boundary.

2. **How it is cloned.** Shallow and single-branch (bounded download and history), no
   interactive credential prompts (a server has no terminal — a prompt would hang until the
   request timed out), explicit argv with no shell, and unconditional cleanup. Git's own
   timeout here is far larger than change/git_adapter.py's, because cloning a real repository
   over the network is a fundamentally larger operation than diffing a local one.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_CLONE_TIMEOUT_SECONDS = 180.0
_CLONE_URL_TEMPLATE = "https://github.com/{owner}/{name}.git"
_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})

# GitHub's own limits: owners are <=39 chars, alphanumeric and hyphens only; repository names
# allow dots and underscores too. Anchored and hyphen-safe so a leading "-" (which git would
# read as an option) and a ".." path segment can never validate.
_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class RemoteRepoError(RuntimeError):
    """Raised when a remote repository reference is unusable, or cloning it failed."""


@dataclass(frozen=True, slots=True)
class RepoRef:
    """A resolved remote repository. Constructed by `parse_public_github_ref` at the API
    boundary, or directly by tests. `clone_url` is passed to git as a single argv element."""

    slug: str
    clone_url: str


def _validate_owner_and_name(owner: str, name: str) -> tuple[str, str]:
    if name.endswith(".git"):
        name = name[: -len(".git")]
    if not _OWNER_PATTERN.match(owner):
        raise RemoteRepoError(f"not a valid GitHub owner name: {owner!r}")
    if not _NAME_PATTERN.match(name) or name in {".", ".."}:
        raise RemoteRepoError(f"not a valid GitHub repository name: {name!r}")
    return owner, name


def parse_public_github_ref(value: str) -> RepoRef:
    """Turn `owner/name` or `https://github.com/owner/name` into a `RepoRef`.

    Anything else — another host, another scheme, embedded credentials, a path traversal, a
    bare filesystem path — raises RemoteRepoError rather than being coerced into something
    clonable.
    """
    raw = value.strip()
    if not raw:
        raise RemoteRepoError("no repository given; expected owner/name")
    if any(char.isspace() for char in raw) or "\\" in raw:
        raise RemoteRepoError("repository reference must not contain whitespace or backslashes")
    # A local path would otherwise be coerced into a (harmless but baffling) GitHub URL,
    # because "/etc/passwd" parses as the slug "etc/passwd". Say what is actually wrong.
    if raw.startswith(("/", "./", "../", "~")) or re.match(r"^[A-Za-z]:/", raw):
        raise RemoteRepoError(
            f"{raw!r} looks like a local filesystem path — this endpoint analyses public "
            "GitHub repositories only; use the CLI to analyse a local path"
        )

    if "://" in raw:
        parts = urlsplit(raw)
        if parts.scheme != "https":
            raise RemoteRepoError(f"only https GitHub URLs are supported (got {parts.scheme!r})")
        if parts.netloc.lower() not in _GITHUB_HOSTS:
            raise RemoteRepoError(f"only github.com URLs are supported (got {parts.netloc!r})")
        segments = [segment for segment in parts.path.split("/") if segment]
        if len(segments) != 2:
            raise RemoteRepoError("expected a URL of the form https://github.com/<owner>/<name>")
        owner, name = segments
    elif "@" in raw:
        # Checked before the slug branch so user:token@host can never reach git.
        raise RemoteRepoError("credentials embedded in a repository URL are not supported")
    else:
        segments = [segment for segment in raw.split("/") if segment]
        if len(segments) != 2:
            raise RemoteRepoError("expected a repository of the form <owner>/<name>")
        owner, name = segments

    owner, name = _validate_owner_and_name(owner, name)
    return RepoRef(
        slug=f"{owner}/{name}",
        clone_url=_CLONE_URL_TEMPLATE.format(owner=owner, name=name),
    )


def _clone(clone_url: str, destination: Path, *, depth: int, timeout: float) -> None:
    # GIT_TERMINAL_PROMPT/GIT_ASKPASS: fail fast instead of blocking on a credential prompt
    # that no HTTP request can ever answer.
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}
    argv = [
        "git",
        "clone",
        "--depth",
        str(depth),
        "--single-branch",
        "--no-tags",
        "--",
        clone_url,
        str(destination),
    ]
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        raise RemoteRepoError(f"cloning {clone_url} timed out after {timeout:.0f}s") from exc
    except FileNotFoundError as exc:
        raise RemoteRepoError("the `git` executable is not available on this host") from exc

    if result.returncode != 0:
        lines = result.stderr.strip().splitlines()
        reason = lines[-1] if lines else f"git exited {result.returncode}"
        raise RemoteRepoError(f"could not clone {clone_url}: {reason[:300]}")


def _remove_workspace(path: Path) -> None:
    """Delete a checkout, including files git marked read-only.

    Windows marks every file under `.git/objects/` read-only, and rmtree then fails on them
    with WinError 5. Passing `ignore_errors=True` (the obvious thing) would hide exactly that
    failure and leak one abandoned checkout per request — harmless on an ephemeral instance,
    but unbounded on any long-lived machine, including a developer's. Clear the read-only bit
    first, then remove.
    """
    for root, dirs, files in os.walk(path, topdown=False):
        for name in (*files, *dirs):
            with suppress(OSError):
                os.chmod(os.path.join(root, name), stat.S_IWRITE | stat.S_IREAD)
    shutil.rmtree(path, ignore_errors=True)


@contextmanager
def cloned_workspace(
    ref: RepoRef, *, depth: int, timeout: float = _CLONE_TIMEOUT_SECONDS
) -> Iterator[Path]:
    """Yield a directory containing a fresh checkout of `ref`, then delete it.

    Always mktemp-backed: a hosted instance's filesystem is ephemeral and shared across
    concurrent requests, so a fixed checkout path would let two requests corrupt one another.
    """
    if depth < 1:
        raise RemoteRepoError("clone depth must be at least 1")

    workspace_root = Path(tempfile.mkdtemp(prefix="repoflare-remote-"))
    try:
        checkout = workspace_root / "repo"
        _clone(ref.clone_url, checkout, depth=depth, timeout=timeout)
        yield checkout
    finally:
        _remove_workspace(workspace_root)
