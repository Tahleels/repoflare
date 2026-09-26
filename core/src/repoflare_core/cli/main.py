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
from rich.console import Console
from rich.table import Table

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

app = typer.Typer(
    name="repoflare",
    help="Repository intelligence: structure, graph, and change impact.",
    no_args_is_help=True,
)

_REPO_ROOT_ARG = typer.Argument(Path("."), help="Repository root.")
_EXPORT_FROM_OPT = typer.Option(
    None, "--from", help="Git ref to diff from. Omit for an overview-only report."
)
_EXPORT_OUTPUT_OPT = typer.Option(
    None, "--output", "-o", help="Output file. Defaults to <repo>/.repoflare/report.html."
)

# Console shared by all commands — highlight=False keeps output deterministic in tests
# (rich auto-disables markup when stdout isn't a real TTY, so test assertions on plain
# text strings remain unaffected regardless of this setting).
_console = Console(highlight=False)

# Impact category → rich color (used in `impact` output only).
_CATEGORY_COLOR = {
    "DIRECT": "bold red",
    "INDIRECT": "bold yellow",
    "RELATED": "bold blue",
    "POSSIBLE": "bold green",
}


@app.command()
def init(path: Path = _REPO_ROOT_ARG) -> None:
    """Create the .repoflare directory and register this repository."""
    root = path.resolve()
    try:
        result = run_init(root)
    except NotADirectoryError:
        typer.echo(f"error: {root} is not a directory", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Initialized RepoFlare at {result.db_path}")


@app.command()
def analyze(path: Path = _REPO_ROOT_ARG) -> None:
    """Scan the repository, parse known-language files, and build a new graph snapshot."""
    root = path.resolve()
    try:
        result = run_analyze(root)
    except NotInitializedError:
        typer.echo("error: not initialized — run 'repoflare init' first", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(
        f"Analyzed {result.file_count} files, extracted {result.symbol_count} symbols "
        f"({result.test_count} tests), resolved {result.resolved_edge_count} CALLS/IMPORTS "
        f"edges and {result.test_edge_count} TESTED_BY edges."
    )
    typer.echo(f"Snapshot: {result.snapshot_id}")


@app.command()
def status(path: Path = _REPO_ROOT_ARG) -> None:
    """Show the current snapshot and basic graph statistics."""
    root = path.resolve()
    try:
        result = run_status(root)
    except NotInitializedError:
        typer.echo("Not initialized — run 'repoflare init' first.")
        raise typer.Exit(code=1) from None

    if result.snapshot_id is None:
        typer.echo("Initialized, but not yet analyzed — run 'repoflare analyze'.")
        return

    typer.echo(f"Repository: {root}")
    typer.echo(f"Current snapshot: {result.snapshot_id}")

    # Rich table for the counts — plain two-column layout, no decoration.
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2, 0, 0))
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    table.add_row("Nodes", str(result.node_count))
    table.add_row("Edges", str(result.edge_count))
    _console.print(table)


@app.command()
def impact(
    from_ref: str = typer.Option(..., "--from", help="Git ref to diff from."),
    to_ref: str = typer.Option("HEAD", "--to", help="Git ref to diff to."),
    path: Path = _REPO_ROOT_ARG,
) -> None:
    """Show what the change between two git refs affects, categorized by confidence."""
    root = path.resolve()
    try:
        summary = run_impact(root, from_ref, to_ref)
    except NotInitializedError:
        typer.echo("error: not initialized — run 'repoflare init' first", err=True)
        raise typer.Exit(code=1) from None
    except NotAnalyzedError:
        typer.echo("Initialized, but not yet analyzed — run 'repoflare analyze'.")
        raise typer.Exit(code=1) from None
    except GitCommandError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not summary.changed_files:
        typer.echo(f"No files changed between {from_ref} and {to_ref}.")
        return

    typer.echo(f"Changed files ({len(summary.changed_files)}): {', '.join(summary.changed_files)}")
    if not summary.results:
        typer.echo("No downstream impact found in the graph.")
        return

    category_order = {c.value: i for i, c in enumerate(type(summary.results[0].category))}
    for result in sorted(summary.results, key=lambda r: category_order[r.category.value]):
        color = _CATEGORY_COLOR.get(result.category.value, "bold")
        _console.print(
            f"[{color}]{result.category.value}[/{color}] ({len(result.affected_node_ids)}):"
        )
        for node_id in result.affected_node_ids:
            node_summary = summary.node_summaries[node_id]
            location = f" ({node_summary.file_path})" if node_summary.file_path else ""
            typer.echo(f"  {node_summary.label}{location}")


@app.command()
def explain(
    from_ref: str = typer.Option(..., "--from", help="Git ref to diff from."),
    to_ref: str = typer.Option("HEAD", "--to", help="Git ref to diff to."),
    path: Path = _REPO_ROOT_ARG,
) -> None:
    """Explain what a change affects in plain language: deterministic impact analysis
    first, then AI reasoning over a targeted context package — never the whole repo."""
    root = path.resolve()
    try:
        explanation = run_explain(root, from_ref, to_ref)
    except NotInitializedError:
        typer.echo("error: not initialized — run 'repoflare init' first", err=True)
        raise typer.Exit(code=1) from None
    except NotAnalyzedError:
        typer.echo("Initialized, but not yet analyzed — run 'repoflare analyze'.")
        raise typer.Exit(code=1) from None
    except GitCommandError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except BobProviderConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except BobProviderError as exc:
        typer.echo(f"error: AI reasoning unavailable ({exc})", err=True)
        raise typer.Exit(code=1) from exc

    if explanation is None:
        typer.echo(f"No files changed between {from_ref} and {to_ref}.")
        return
    typer.echo(explanation)


@app.command()
def export_html(
    from_ref: str | None = _EXPORT_FROM_OPT,
    to_ref: str = typer.Option("HEAD", "--to", help="Git ref to diff to."),
    output: Path | None = _EXPORT_OUTPUT_OPT,
    path: Path = _REPO_ROOT_ARG,
) -> None:
    """Render a self-contained static HTML report (repository overview, plus an impact
    view if --from is given). Not a web app — a one-command shareable snapshot of what the
    CLI already computes, meant to be hosted as a plain static file."""
    root = path.resolve()
    try:
        status_result = run_status(root)
    except NotInitializedError:
        typer.echo("error: not initialized — run 'repoflare init' first", err=True)
        raise typer.Exit(code=1) from None

    impact_summary = None
    impact_refs = None
    if from_ref is not None:
        try:
            impact_summary = run_impact(root, from_ref, to_ref)
            impact_refs = (from_ref, to_ref)
        except NotAnalyzedError:
            typer.echo("Initialized, but not yet analyzed — run 'repoflare analyze'.")
            raise typer.Exit(code=1) from None
        except GitCommandError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    html = render_html(str(root), status_result, impact_summary, impact_refs)

    output_path = output if output is not None else root / ".repoflare" / "report.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    typer.echo(f"Wrote report to {output_path}")


if __name__ == "__main__":
    app()
