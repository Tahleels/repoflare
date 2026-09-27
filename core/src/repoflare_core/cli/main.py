"""RepoFlare CLI — a thin interface over repoflare_core.service. No orchestration logic
lives here; every command formats/prints what the service layer returns and translates its
exceptions into exit codes. The RPC server (rpc/) is the other interface over the same
service layer — see service.py's module docstring.

Implemented so far: init, analyze, status, impact, explain — the full scan -> graph ->
impact -> targeted AI reasoning vertical slice. `verify` is intentionally not stubbed here;
it depends on VerificationService, which doesn't exist yet (see AGENTS.md "Next up"). A
command that always errors "not implemented" is worse than no command at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from repoflare_core.ai.factory import BobProviderConfigError
from repoflare_core.ai.provider import BobProviderError
from repoflare_core.change.git_adapter import GitCommandError
from repoflare_core.export.html import render_html
from repoflare_core.service import (
    NotAnalyzedError,
    NotInitializedError,
    run_analyze,
    run_explain,
    run_impact,
    run_init,
    run_status,
)

# AI-generated explanations routinely contain non-ASCII characters (em-dashes, curly
# quotes). Windows consoles often default stdout/stderr to a legacy codepage that can't
# encode them, corrupting output instead of erroring — force UTF-8 with a safe fallback so
# `explain` is never garbled mid-demo. No-op on platforms already using UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# ── Palette ───────────────────────────────────────────────────────────────────
# Warm orange/amber brand color, cool blue accent, and muted grey for secondary text.
_BRAND = "bold color(214)"  # amber-orange  — matches the flame in the logo
_ACCENT = "bold color(75)"  # sky blue
_DIM = "color(244)"  # muted grey
_SUCCESS = "bold color(83)"  # bright green
_WARN = "bold color(220)"  # yellow
_ERR = "bold color(196)"  # red

# ── ASCII banner ─────────────────────────────────────────────────────────────
_BANNER = r"""
  ██████╗ ███████╗██████╗  ██████╗ ███████╗██╗      █████╗ ██████╗ ███████╗
  ██╔══██╗██╔════╝██╔══██╗██╔═══██╗██╔════╝██║     ██╔══██╗██╔══██╗██╔════╝
  ██████╔╝█████╗  ██████╔╝██║   ██║█████╗  ██║     ███████║██████╔╝█████╗
  ██╔══██╗██╔══╝  ██╔═══╝ ██║   ██║██╔══╝  ██║     ██╔══██║██╔══██╗██╔══╝
  ██║  ██║███████╗██║     ╚██████╔╝██║     ███████╗██║  ██║██║  ██║███████╗
  ╚═╝  ╚═╝╚══════╝╚═╝      ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝
""".rstrip()

# ── Console & app ────────────────────────────────────────────────────────────
# highlight=False keeps output deterministic in tests.
_console = Console(highlight=False)

app = typer.Typer(
    name="repoflare",
    help="Repository intelligence: structure, graph, and change impact.",
    no_args_is_help=False,
    invoke_without_command=True,
    rich_markup_mode="rich",
    add_completion=False,
)

_REPO_ROOT_ARG = typer.Argument(Path("."), help="Repository root.")
_EXPORT_FROM_OPT = typer.Option(
    None, "--from", help="Git ref to diff from. Omit for an overview-only report."
)
_EXPORT_OUTPUT_OPT = typer.Option(
    None, "--output", "-o", help="Output file. Defaults to <repo>/.repoflare/report.html."
)

# Impact category → rich styles (foreground + background pill).
_CATEGORY_STYLE: dict[str, tuple[str, str]] = {
    "DIRECT": ("#ff6b6b", "bold color(196)"),
    "INDIRECT": ("#ffd93d", "bold color(220)"),
    "RELATED": ("#74b9ff", "bold color(75)"),
    "POSSIBLE": ("#55efc4", "bold color(83)"),
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _print_banner() -> None:
    banner_text = Text(_BANNER, style=_BRAND)
    tagline = Text(
        "  Repository intelligence  •  Graph-powered change impact  •  AI reasoning",
        style=_DIM,
        justify="center",
    )
    _console.print()
    _console.print(Align.center(banner_text))
    _console.print(Align.center(tagline))
    _console.print()


def _rule(title: str = "") -> None:
    _console.print(Rule(title, style=_DIM))


def _ok(msg: str) -> None:
    _console.print(f"  [{_SUCCESS}]✔[/{_SUCCESS}]  {msg}")


def _err(msg: str) -> None:
    _console.print(f"\n  [{_ERR}]✖[/{_ERR}]  {msg}")


def _hint(msg: str) -> None:
    _console.print(f"  [{_DIM}]→[/{_DIM}]  [{_DIM}]{msg}[/{_DIM}]")


def _category_pill(category: str) -> Text:
    _, style = _CATEGORY_STYLE.get(category, ("#aaa", "bold"))
    t = Text()
    t.append(f" {category} ", style=f"on {style.split()[-1]} bold white")
    return t


# ── Commands ──────────────────────────────────────────────────────────────────


@app.command()
def init(path: Path = _REPO_ROOT_ARG) -> None:
    """Create the [bold].repoflare[/bold] directory and register this repository."""
    _print_banner()
    root = path.resolve()
    _console.print(f"  Initializing at [{_ACCENT}]{root}[/{_ACCENT}]…\n")
    try:
        result = run_init(root)
    except NotADirectoryError:
        _err(f"{root} is not a directory.")
        raise typer.Exit(code=1) from None

    _ok("RepoFlare initialized!")
    _hint(f"Database: {result.db_path}")
    _console.print()
    _rule()
    _console.print(
        Panel(
            "  Next step → run [bold color(214)]repoflare analyze[/bold color(214)] "
            "to scan the repository and build the dependency graph.\n",
            title="[bold]Quick Start[/bold]",
            border_style=_DIM,
            padding=(1, 2),
        )
    )
    _console.print()


@app.command()
def analyze(path: Path = _REPO_ROOT_ARG) -> None:
    """Scan every Python/TypeScript/JavaScript file and build a fresh dependency graph."""
    _print_banner()
    root = path.resolve()
    _console.print(f"  Scanning [{_ACCENT}]{root}[/{_ACCENT}]…\n")
    try:
        result = run_analyze(root)
    except NotInitializedError:
        _err("Repository not initialized.")
        _hint("Run  repoflare init  first.")
        raise typer.Exit(code=1) from None

    # ── Summary table ────────────────────────────────────────────────────────
    tbl = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style=f"bold {_ACCENT.split()[-1]}",
        border_style=_DIM,
        padding=(0, 2),
        expand=False,
    )
    tbl.add_column("Metric", style="bold", min_width=22)
    tbl.add_column("Count", justify="right", style=_SUCCESS)

    tbl.add_row("Files scanned", str(result.file_count))
    tbl.add_row("Symbols extracted", str(result.symbol_count))
    tbl.add_row("Tests detected", str(result.test_count))
    tbl.add_row("CALLS/IMPORTS edges", str(result.resolved_edge_count))
    tbl.add_row("TESTED_BY edges", str(result.test_edge_count))

    _ok("Analysis complete!\n")
    _console.print(Align.left(tbl, pad=True))
    _hint(f"Snapshot  {result.snapshot_id}")
    _console.print()
    _rule()
    _console.print(
        Panel(
            "  Use [bold color(214)]repoflare impact --from <ref>[/bold color(214)] "
            "to see what a change affects.\n"
            "  Use [bold color(214)]repoflare explain --from <ref>[/bold color(214)] "
            "for an AI-powered explanation.",
            title="[bold]What's next?[/bold]",
            border_style=_DIM,
            padding=(1, 2),
        )
    )
    _console.print()


@app.command()
def status(path: Path = _REPO_ROOT_ARG) -> None:
    """Show the current snapshot and basic graph statistics."""
    _print_banner()
    root = path.resolve()
    try:
        result = run_status(root)
    except NotInitializedError:
        _err("Repository not initialized.")
        _hint("Run  repoflare init  first.")
        raise typer.Exit(code=1) from None

    if result.snapshot_id is None:
        _console.print(
            Panel(
                "  This repository has been initialized but not yet analyzed.\n\n"
                "  Run [bold color(214)]repoflare analyze[/bold color(214)] to build the "
                "dependency graph.",
                title="[bold]Status[/bold]",
                border_style=_WARN.split()[-1],
                padding=(1, 2),
            )
        )
        _console.print()
        return

    # ── Stats cards ──────────────────────────────────────────────────────────
    tbl = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style=f"bold {_ACCENT.split()[-1]}",
        border_style=_DIM,
        padding=(0, 3),
        expand=False,
    )
    tbl.add_column("Metric", style="bold", min_width=20)
    tbl.add_column("Value", justify="right", style=_SUCCESS)
    tbl.add_row("Repository", str(root))
    tbl.add_row("Snapshot ID", result.snapshot_id[:16] + "…")
    tbl.add_row("Nodes in graph", str(result.node_count))
    tbl.add_row("Edges in graph", str(result.edge_count))

    _console.print(
        Panel(
            Align.left(tbl),
            title="[bold]Repository Status[/bold]",
            border_style=_ACCENT.split()[-1],
            padding=(1, 2),
        )
    )
    _console.print()


@app.command()
def impact(
    from_ref: str = typer.Option(..., "--from", help="Git ref to diff from."),
    to_ref: str = typer.Option("HEAD", "--to", help="Git ref to diff to."),
    path: Path = _REPO_ROOT_ARG,
) -> None:
    """Show what changed between two git refs and which parts of the codebase are affected."""
    _print_banner()
    root = path.resolve()
    _console.print(
        f"  Analyzing impact of [{_ACCENT}]{from_ref}[/{_ACCENT}] → "
        f"[{_ACCENT}]{to_ref}[/{_ACCENT}]…\n"
    )
    try:
        summary = run_impact(root, from_ref, to_ref)
    except NotInitializedError:
        _err("Repository not initialized.")
        _hint("Run  repoflare init  first.")
        raise typer.Exit(code=1) from None
    except NotAnalyzedError:
        _err("Repository not yet analyzed.")
        _hint("Run  repoflare analyze  first.")
        raise typer.Exit(code=1) from None
    except GitCommandError as exc:
        _err(f"Git error: {exc}")
        raise typer.Exit(code=1) from exc

    if not summary.changed_files:
        _console.print(
            Panel(
                f"  No files changed between [bold]{from_ref}[/bold] and [bold]{to_ref}[/bold].",
                border_style=_DIM,
                padding=(1, 2),
            )
        )
        _console.print()
        return

    # ── Changed files ────────────────────────────────────────────────────────
    _console.print(
        Panel(
            "\n".join(f"  [bold]{f}[/bold]" for f in summary.changed_files),
            title=f"[bold]Changed Files[/bold] ({len(summary.changed_files)})",
            border_style=_WARN.split()[-1],
            padding=(1, 2),
        )
    )

    if not summary.results:
        _console.print(f"\n  [{_DIM}]No downstream impact found in the graph.[/{_DIM}]\n")
        return

    _console.print()

    # ── Affected nodes table ─────────────────────────────────────────────────
    tbl = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style=f"bold {_ACCENT.split()[-1]}",
        border_style=_DIM,
        padding=(0, 2),
        expand=True,
    )
    tbl.add_column("Impact", min_width=12)
    tbl.add_column("Symbol / File", style="bold", min_width=28)
    tbl.add_column("Location", style=f"italic {_DIM}")

    category_order = {c.value: i for i, c in enumerate(type(summary.results[0].category))}
    for result in sorted(summary.results, key=lambda r: category_order[r.category.value]):
        for node_id in result.affected_node_ids:
            node_summary = summary.node_summaries[node_id]
            location = node_summary.file_path or ""
            pill = _category_pill(result.category.value)
            tbl.add_row(pill, node_summary.label, location)

    _console.print(
        Panel(
            tbl,
            title="[bold]Impact Analysis[/bold]",
            border_style=_ERR.split()[-1],
            padding=(1, 2),
        )
    )
    _console.print()
    _rule()
    _console.print(
        f"\n  [{_DIM}]Tip: run [bold color(214)]repoflare explain "
        f"--from {from_ref}[/bold color(214)] "
        f"for an AI-powered plain-language explanation.[/{_DIM}]\n"
    )


@app.command()
def explain(
    from_ref: str = typer.Option(..., "--from", help="Git ref to diff from."),
    to_ref: str = typer.Option("HEAD", "--to", help="Git ref to diff to."),
    path: Path = _REPO_ROOT_ARG,
) -> None:
    """Ask AI to explain a change's impact in plain language (graph-first, AI-second)."""
    _print_banner()
    root = path.resolve()
    _console.print(
        f"  Running impact analysis then AI reasoning for "
        f"[{_ACCENT}]{from_ref}[/{_ACCENT}] → [{_ACCENT}]{to_ref}[/{_ACCENT}]…\n"
    )
    try:
        explanation = run_explain(root, from_ref, to_ref)
    except NotInitializedError:
        _err("Repository not initialized.")
        _hint("Run  repoflare init  first.")
        raise typer.Exit(code=1) from None
    except NotAnalyzedError:
        _err("Repository not yet analyzed.")
        _hint("Run  repoflare analyze  first.")
        raise typer.Exit(code=1) from None
    except GitCommandError as exc:
        _err(f"Git error: {exc}")
        raise typer.Exit(code=1) from exc
    except BobProviderConfigError as exc:
        _err(f"AI not configured: {exc}")
        _hint("Set GEMINI_API_KEY or OPENROUTER_API_KEY in your environment.")
        raise typer.Exit(code=1) from exc
    except BobProviderError as exc:
        _err(f"AI call failed: {exc}")
        raise typer.Exit(code=1) from exc

    if explanation is None:
        _console.print(
            Panel(
                f"  No files changed between [bold]{from_ref}[/bold] and [bold]{to_ref}[/bold].",
                border_style=_DIM,
                padding=(1, 2),
            )
        )
        _console.print()
        return

    _console.print(
        Panel(
            explanation,
            title=f"[bold]AI Explanation[/bold]  [{_DIM}]{from_ref} → {to_ref}[/{_DIM}]",
            border_style=_ACCENT.split()[-1],
            padding=(1, 3),
        )
    )
    _console.print()


@app.command()
def export_html(
    from_ref: str | None = _EXPORT_FROM_OPT,
    to_ref: str = typer.Option("HEAD", "--to", help="Git ref to diff to."),
    output: Path | None = _EXPORT_OUTPUT_OPT,
    path: Path = _REPO_ROOT_ARG,
) -> None:
    """Export a self-contained HTML report (overview + optional impact view)."""
    _print_banner()
    root = path.resolve()
    try:
        status_result = run_status(root)
    except NotInitializedError:
        _err("Repository not initialized.")
        _hint("Run  repoflare init  first.")
        raise typer.Exit(code=1) from None

    impact_summary = None
    impact_refs = None
    if from_ref is not None:
        try:
            impact_summary = run_impact(root, from_ref, to_ref)
            impact_refs = (from_ref, to_ref)
        except NotAnalyzedError:
            _err("Repository not yet analyzed.")
            _hint("Run  repoflare analyze  first.")
            raise typer.Exit(code=1) from None
        except GitCommandError as exc:
            _err(f"Git error: {exc}")
            raise typer.Exit(code=1) from exc

    html = render_html(str(root), status_result, impact_summary, impact_refs)

    output_path = output if output is not None else root / ".repoflare" / "report.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    _ok("Report written!")
    _hint(f"Path: {output_path}")
    _console.print()


@app.callback()
def main(ctx: typer.Context) -> None:
    """RepoFlare — Repository intelligence CLI."""
    if ctx.invoked_subcommand is not None:
        return

    _print_banner()
    c = "bold color(214)"
    _console.print("  [bold]What would you like to do?[/bold]\n")
    _console.print(f"  [{c}]1[/{c}]  ⚡ [bold]init[/bold]         Initialize RepoFlare")
    _console.print(f"  [{c}]2[/{c}]  🔍 [bold]analyze[/bold]      Build / update code graph")
    _console.print(f"  [{c}]3[/{c}]  📊 [bold]status[/bold]       Show repository snapshot & stats")
    _console.print(f"  [{c}]4[/{c}]  💥 [bold]impact[/bold]       Analyze downstream change impact")
    _console.print(f"  [{c}]5[/{c}]  🤖 [bold]explain[/bold]      AI-powered impact analysis")
    _console.print(
        f"  [{c}]6[/{c}]  📄 [bold]export-html[/bold]  Generate self-contained HTML report"
    )
    _console.print("  [bold color(244)]q[/bold color(244)]  🚪 [dim]Exit[/dim]\n")

    choice = typer.prompt("Select an option [1-6]", default="2", show_default=False)
    choice = choice.strip().lower()

    root = Path(".").resolve()
    if choice in ("1", "init"):
        init(root)
    elif choice in ("2", "analyze"):
        analyze(root)
    elif choice in ("3", "status"):
        status(root)
    elif choice in ("4", "impact"):
        from_ref = typer.prompt("Git ref to compare from", default="HEAD~1")
        impact(from_ref=from_ref, to_ref="HEAD", path=root)
    elif choice in ("5", "explain"):
        from_ref = typer.prompt("Git ref to compare from", default="HEAD~1")
        explain(from_ref=from_ref, to_ref="HEAD", path=root)
    elif choice in ("6", "export-html"):
        export_html(from_ref=None, to_ref="HEAD", output=None, path=root)
    elif choice in ("q", "quit", "exit"):
        _console.print("  [dim]Goodbye![/dim]\n")
    else:
        _err(f"Invalid option '{choice}'")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
