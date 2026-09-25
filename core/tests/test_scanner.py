import sys
from pathlib import Path

import pytest

from repoflare_core.scanning.scanner import RepositoryScanner


def test_scan_finds_known_language_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def f(): pass\n")
    (tmp_path / "b.ts").write_text("function f() {}\n")
    (tmp_path / "readme.md").write_text("not a source file\n")

    files = {f.relative_path for f in RepositoryScanner(tmp_path).scan()}

    assert files == {"a.py", "b.ts"}


def test_scan_respects_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored/\n")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "a.py").write_text("def f(): pass\n")
    (tmp_path / "kept.py").write_text("def g(): pass\n")

    files = {f.relative_path for f in RepositoryScanner(tmp_path).scan()}

    assert files == {"kept.py"}


def test_scan_skips_always_ignored_dirs(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("module.exports = {};\n")
    (tmp_path / "kept.js").write_text("function f() {}\n")

    files = {f.relative_path for f in RepositoryScanner(tmp_path).scan()}

    assert files == {"kept.js"}


def test_scanned_file_carries_content_and_hash(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")

    [scanned] = list(RepositoryScanner(tmp_path).scan())

    assert scanned.content == "x = 1\n"
    assert scanned.language == "python"
    assert len(scanned.content_hash) == 64  # sha256 hex digest


def test_empty_repo_yields_no_files(tmp_path: Path) -> None:
    files = list(RepositoryScanner(tmp_path).scan())

    assert files == []


def test_repo_without_gitignore_still_scans(tmp_path: Path) -> None:
    """A missing .gitignore must not raise — scanner treats it as empty."""
    (tmp_path / "x.py").write_text("pass\n")

    files = list(RepositoryScanner(tmp_path).scan())

    assert len(files) == 1


def test_jsx_and_tsx_map_to_correct_languages(tmp_path: Path) -> None:
    (tmp_path / "comp.jsx").write_text("function C() { return null; }\n")
    (tmp_path / "typed.tsx").write_text("function C(): JSX.Element { return null; }\n")

    results = {f.relative_path: f.language for f in RepositoryScanner(tmp_path).scan()}

    assert results == {"comp.jsx": "javascript", "typed.tsx": "typescript"}


def test_scan_skips_all_always_ignored_dirs(tmp_path: Path) -> None:
    for dirname in ("__pycache__", ".venv", "venv", ".git", ".repoflare"):
        (tmp_path / dirname).mkdir()
        (tmp_path / dirname / "f.py").write_text("pass\n")
    (tmp_path / "real.py").write_text("pass\n")

    files = {f.relative_path for f in RepositoryScanner(tmp_path).scan()}

    assert files == {"real.py"}


def test_scan_produces_sorted_output(tmp_path: Path) -> None:
    """scan() guarantees deterministic ordering via sorted(rglob(...))."""
    for name in ("z.py", "a.py", "m.py"):
        (tmp_path / name).write_text("pass\n")

    paths = [f.relative_path for f in RepositoryScanner(tmp_path).scan()]

    assert paths == sorted(paths)


def test_scan_skips_binary_files(tmp_path: Path) -> None:
    """Files that cannot be decoded as UTF-8 must be silently skipped."""
    binary = tmp_path / "bad.py"
    binary.write_bytes(b"\xff\xfe def broken(): pass")

    files = list(RepositoryScanner(tmp_path).scan())

    assert files == []


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlinks require elevated privileges on Windows"
)
def test_scan_follows_symlinked_files(tmp_path: Path) -> None:
    real = tmp_path / "real.py"
    real.write_text("pass\n")
    link = tmp_path / "link.py"
    link.symlink_to(real)

    files = {f.relative_path for f in RepositoryScanner(tmp_path).scan()}

    assert {"real.py", "link.py"} == files
