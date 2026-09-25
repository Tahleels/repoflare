"""RepoFlare CLI.

Implemented so far: init, analyze, status, impact, explain — the full scan -> graph ->
impact -> targeted AI reasoning vertical slice. `verify` is intentionally not stubbed here;
it depends on VerificationService, which doesn't exist yet (see AGENTS.md "Next up"). A
command that always errors "not implemented" is worse than no command at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from repoflare_core.ai.factory import BobProviderConfigError, default_bob_provider
from repoflare_core.ai.provider import BobProviderError
from repoflare_core.change.detector import ChangeDetector
from repoflare_core.change.git_adapter import GitAdapter, GitCommandError
from repoflare_core.config import graph_db_path
from repoflare_core.domain.entities import NodeKind, Repository, Snapshot
from repoflare_core.domain.ids import stable_id
from repoflare_core.graph.store import GraphStore
from repoflare_core.graph.traversal import GraphTraversalService
from repoflare_core.impact.analyzer import ImpactAnalyzer
from repoflare_core.parsing.adapter import ParserAdapter, module_qualified_name
from repoflare_core.parsing.resolver import CallImportResolver
from repoflare_core.retrieval.context_retriever import ContextRetriever
from repoflare_core.retrieval.prompt import format_explain_prompt
from repoflare_core.scanning.scanner import RepositoryScanner

app = typer.Typer(
    name="repoflare",
    help="Repository intelligence: structure, graph, and change impact.",
    no_args_is_help=True,
)

_REPO_ROOT_ARG = typer.Argument(Path("."), help="Repository root.")


def _repository_id(root: Path) -> str:
    return stable_id(str(root))


def _current_commit_sha_if_git_repo(root: Path) -> str | None:
    """Best-effort: a snapshot analyzed outside a git repo (or with git unavailable) is
    still valid, it just can't be matched to a commit later by `impact`."""
    try:
        return GitAdapter(root).current_commit_sha()
    except GitCommandError:
        return None


def _count(store: GraphStore, table: str, snapshot_id: str) -> int:
    # `table` is always a fixed literal passed by call sites in this module, never user input.
    row = (
        store.raw_connection()
        .execute(f"SELECT count(*) FROM {table} WHERE snapshot_id = ?", [snapshot_id])
        .fetchone()
    )
    assert row is not None  # COUNT(*) always returns exactly one row
    return int(row[0])


@app.command()
def init(path: Path = _REPO_ROOT_ARG) -> None:
    """Create the .repoflare directory and register this repository."""
    root = path.resolve()
    if not root.is_dir():
        typer.echo(f"error: {root} is not a directory", err=True)
        raise typer.Exit(code=1)

    with GraphStore(graph_db_path(root)) as store:
        store.upsert_repository(
            Repository(
                repository_id=_repository_id(root),
                root_path=str(root),
                name=root.name,
                created_at=datetime.now(UTC),
            )
        )
    typer.echo(f"Initialized RepoFlare at {graph_db_path(root)}")


@app.command()
def analyze(path: Path = _REPO_ROOT_ARG) -> None:
    """Scan the repository, parse known-language files, and build a new graph snapshot."""
    root = path.resolve()
    db_path = graph_db_path(root)
    if not db_path.exists():
        typer.echo("error: not initialized — run 'repoflare init' first", err=True)
        raise typer.Exit(code=1)

    repository_id = _repository_id(root)
    snapshot_id = stable_id(str(root), datetime.now(UTC).isoformat())
    git_commit_sha = _current_commit_sha_if_git_repo(root)

    parser = ParserAdapter()
    resolver = CallImportResolver()

    # Two passes: (1) parse every file and insert structural (CONTAINS) nodes/edges, since
    # (2) resolving CALLS/IMPORTS needs a snapshot-wide lookup that isn't available until
    # every file's symbols are known — see parsing/resolver.py's module docstring.
    scanned_files = list(RepositoryScanner(root).scan())
    parsed = [(f, parser.parse(f, snapshot_id)) for f in scanned_files]

    node_id_by_qualified_name = {
        n.qualified_name: n.node_id for _f, r in parsed for n in r.nodes if n.qualified_name
    }
    file_node_id_by_module_qname = {
        n.qualified_name: n.node_id
        for _f, r in parsed
        for n in r.nodes
        if n.kind == NodeKind.FILE and n.qualified_name
    }

    symbol_count = 0
    resolved_edge_count = 0
    with GraphStore(db_path) as store:
        store.create_snapshot(
            Snapshot(
                snapshot_id=snapshot_id,
                repository_id=repository_id,
                git_commit_sha=git_commit_sha,
                created_at=datetime.now(UTC),
            )
        )

        for _scanned_file, result in parsed:
            store.insert_nodes(result.nodes)
            store.insert_edges(result.edges)
            symbol_count += sum(1 for n in result.nodes if n.kind == NodeKind.SYMBOL)

        for scanned_file, _result in parsed:
            module_qname = module_qualified_name(scanned_file.relative_path)
            resolved_edges = resolver.resolve(
                scanned_file,
                snapshot_id,
                module_qname,
                node_id_by_qualified_name,
                file_node_id_by_module_qname,
            )
            store.insert_edges(resolved_edges)
            resolved_edge_count += len(resolved_edges)

    typer.echo(
        f"Analyzed {len(scanned_files)} files, extracted {symbol_count} symbols, "
        f"resolved {resolved_edge_count} CALLS/IMPORTS edges."
    )
    typer.echo(f"Snapshot: {snapshot_id}")


@app.command()
def status(path: Path = _REPO_ROOT_ARG) -> None:
    """Show the current snapshot and basic graph statistics."""
    root = path.resolve()
    db_path = graph_db_path(root)
    if not db_path.exists():
        typer.echo("Not initialized — run 'repoflare init' first.")
        raise typer.Exit(code=1)

    with GraphStore(db_path) as store:
        snapshot_id = store.current_snapshot_id(_repository_id(root))
        if snapshot_id is None:
            typer.echo("Initialized, but not yet analyzed — run 'repoflare analyze'.")
            return
        node_count = _count(store, "nodes", snapshot_id)
        edge_count = _count(store, "edges", snapshot_id)

    typer.echo(f"Repository: {root}")
    typer.echo(f"Current snapshot: {snapshot_id}")
    typer.echo(f"Nodes: {node_count}, Edges: {edge_count}")


@app.command()
def impact(
    from_ref: str = typer.Option(..., "--from", help="Git ref to diff from."),
    to_ref: str = typer.Option("HEAD", "--to", help="Git ref to diff to."),
    path: Path = _REPO_ROOT_ARG,
) -> None:
    """Show what the change between two git refs affects, categorized by confidence."""
    root = path.resolve()
    db_path = graph_db_path(root)
    if not db_path.exists():
        typer.echo("error: not initialized — run 'repoflare init' first", err=True)
        raise typer.Exit(code=1)

    with GraphStore(db_path) as store:
        snapshot_id = store.current_snapshot_id(_repository_id(root))
        if snapshot_id is None:
            typer.echo("Initialized, but not yet analyzed — run 'repoflare analyze'.")
            raise typer.Exit(code=1)

        try:
            change_set = ChangeDetector(GitAdapter(root)).detect(
                change_set_id=stable_id(str(root), from_ref, to_ref),
                snapshot_to_id=snapshot_id,
                from_ref=from_ref,
                to_ref=to_ref,
            )
        except GitCommandError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        results = ImpactAnalyzer(store, GraphTraversalService(store)).analyze(change_set)

        if not change_set.changed_files:
            typer.echo(f"No files changed between {from_ref} and {to_ref}.")
            return

        typer.echo(
            f"Changed files ({len(change_set.changed_files)}): "
            f"{', '.join(change_set.changed_files)}"
        )
        if not results:
            typer.echo("No downstream impact found in the graph.")
            return

        category_order = {c.value: i for i, c in enumerate(type(results[0].category))}
        for result in sorted(results, key=lambda r: category_order[r.category.value]):
            typer.echo(f"{result.category.value} ({len(result.affected_node_ids)}):")
            for node_id in result.affected_node_ids:
                node = store.get_node(node_id)
                label = node.qualified_name or node.name if node else node_id
                location = f" ({node.file_path})" if node and node.file_path else ""
                typer.echo(f"  {label}{location}")


@app.command()
def explain(
    from_ref: str = typer.Option(..., "--from", help="Git ref to diff from."),
    to_ref: str = typer.Option("HEAD", "--to", help="Git ref to diff to."),
    path: Path = _REPO_ROOT_ARG,
) -> None:
    """Explain what a change affects in plain language: deterministic impact analysis
    first, then AI reasoning over a targeted context package — never the whole repo."""
    root = path.resolve()
    db_path = graph_db_path(root)
    if not db_path.exists():
        typer.echo("error: not initialized — run 'repoflare init' first", err=True)
        raise typer.Exit(code=1)

    with GraphStore(db_path) as store:
        snapshot_id = store.current_snapshot_id(_repository_id(root))
        if snapshot_id is None:
            typer.echo("Initialized, but not yet analyzed — run 'repoflare analyze'.")
            raise typer.Exit(code=1)

        try:
            change_set = ChangeDetector(GitAdapter(root)).detect(
                change_set_id=stable_id(str(root), from_ref, to_ref),
                snapshot_to_id=snapshot_id,
                from_ref=from_ref,
                to_ref=to_ref,
            )
        except GitCommandError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        if not change_set.changed_files:
            typer.echo(f"No files changed between {from_ref} and {to_ref}.")
            return

        traversal = GraphTraversalService(store)
        results = ImpactAnalyzer(store, traversal).analyze(change_set)
        context = ContextRetriever(store, traversal).build_context(change_set, results, root)

    try:
        provider = default_bob_provider()
    except BobProviderConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        explanation = provider.complete(format_explain_prompt(context))
    except BobProviderError as exc:
        typer.echo(f"error: AI reasoning unavailable ({exc})", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(explanation)


if __name__ == "__main__":
    app()
