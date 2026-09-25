"""RepoFlare CLI.

Implemented so far: init, analyze, status — the scan -> parse -> graph vertical slice.
`impact`, `explain`, `verify` are intentionally not stubbed here; they depend on
ImpactAnalyzer / ContextRetriever / BobProvider / VerificationService, none of which exist
yet (see AGENTS.md "Next up"). A command that always errors "not implemented" is worse than
no command at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from repoflare_core.config import graph_db_path
from repoflare_core.domain.entities import NodeKind, Repository, Snapshot
from repoflare_core.domain.ids import stable_id
from repoflare_core.graph.store import GraphStore
from repoflare_core.parsing.adapter import ParserAdapter, module_qualified_name
from repoflare_core.parsing.resolver import CallImportResolver
from repoflare_core.scanning.scanner import RepositoryScanner

app = typer.Typer(
    name="repoflare",
    help="Repository intelligence: structure, graph, and change impact.",
    no_args_is_help=True,
)

_REPO_ROOT_ARG = typer.Argument(Path("."), help="Repository root.")


def _repository_id(root: Path) -> str:
    return stable_id(str(root))


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
                git_commit_sha=None,
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


if __name__ == "__main__":
    app()
