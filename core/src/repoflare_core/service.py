"""Application service layer: the actual orchestration behind init/analyze/status/impact/
explain — shared verbatim between the CLI and the RPC server (see docs/ARCHITECTURE.md
ADR-001 and the project brief's "no duplicated business logic across CLI and extension"
principle). Neither interface layer holds orchestration logic of its own; they only
format/print (CLI) or JSON-encode (RPC) what this module returns, and translate the
exceptions defined here into their own error conventions (exit codes vs. JSON-RPC error
objects).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from repoflare_core.ai.factory import default_bob_provider
from repoflare_core.cache.provider import CacheProvider
from repoflare_core.change.detector import ChangeDetector
from repoflare_core.change.git_adapter import GitAdapter, GitCommandError
from repoflare_core.config import graph_db_path
from repoflare_core.domain.entities import ImpactResult, NodeKind, Repository, Snapshot
from repoflare_core.domain.ids import stable_id
from repoflare_core.graph.store import GraphStore
from repoflare_core.graph.traversal import GraphTraversalService
from repoflare_core.impact.analyzer import ImpactAnalyzer
from repoflare_core.parsing.adapter import ParserAdapter, module_qualified_name
from repoflare_core.parsing.resolver import CallImportResolver
from repoflare_core.parsing.test_resolver import TestLinkResolver
from repoflare_core.retrieval.context_retriever import ContextRetriever
from repoflare_core.retrieval.prompt import format_explain_prompt
from repoflare_core.scanning.scanner import RepositoryScanner


class NotInitializedError(RuntimeError):
    """Raised when an operation needs .repoflare/ but `init` hasn't run yet."""


class NotAnalyzedError(RuntimeError):
    """Raised when an operation needs a graph snapshot but `analyze` hasn't run yet."""


def repository_id(root: Path) -> str:
    return stable_id(str(root))


def _current_commit_sha_if_git_repo(root: Path) -> str | None:
    """Best-effort: a snapshot analyzed outside a git repo (or with git unavailable) is
    still valid, it just can't be matched to a commit later by `impact`/`explain`."""
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


@dataclass(frozen=True, slots=True)
class InitResult:
    db_path: Path


def run_init(root: Path) -> InitResult:
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    db_path = graph_db_path(root)
    with GraphStore(db_path) as store:
        store.upsert_repository(
            Repository(
                repository_id=repository_id(root),
                root_path=str(root),
                name=root.name,
                created_at=datetime.now(UTC),
            )
        )
    return InitResult(db_path=db_path)


@dataclass(frozen=True, slots=True)
class AnalyzeResult:
    snapshot_id: str
    file_count: int
    symbol_count: int
    test_count: int
    resolved_edge_count: int
    test_edge_count: int


def run_analyze(root: Path) -> AnalyzeResult:
    db_path = graph_db_path(root)
    if not db_path.exists():
        raise NotInitializedError(str(root))

    repo_id = repository_id(root)
    snapshot_id = stable_id(str(root), datetime.now(UTC).isoformat())
    git_commit_sha = _current_commit_sha_if_git_repo(root)

    parser = ParserAdapter()
    resolver = CallImportResolver()

    # Two passes: (1) parse every file and insert structural (CONTAINS) nodes/edges, since
    # (2) resolving CALLS/IMPORTS/TESTED_BY needs a snapshot-wide lookup that isn't
    # available until every file's symbols are known — see parsing/resolver.py.
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
    test_count = 0
    resolved_edge_count = 0
    with GraphStore(db_path) as store:
        store.create_snapshot(
            Snapshot(
                snapshot_id=snapshot_id,
                repository_id=repo_id,
                git_commit_sha=git_commit_sha,
                created_at=datetime.now(UTC),
            )
        )

        for _scanned_file, result in parsed:
            store.insert_nodes(result.nodes)
            store.insert_edges(result.edges)
            symbol_count += sum(1 for n in result.nodes if n.kind == NodeKind.SYMBOL)
            test_count += sum(1 for n in result.nodes if n.kind == NodeKind.TEST)

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

        all_nodes = [n for _f, r in parsed for n in r.nodes]
        test_edges = TestLinkResolver().resolve(snapshot_id, all_nodes)
        store.insert_edges(test_edges)

    return AnalyzeResult(
        snapshot_id=snapshot_id,
        file_count=len(scanned_files),
        symbol_count=symbol_count,
        test_count=test_count,
        resolved_edge_count=resolved_edge_count,
        test_edge_count=len(test_edges),
    )


@dataclass(frozen=True, slots=True)
class StatusResult:
    snapshot_id: str | None
    node_count: int
    edge_count: int


def run_status(root: Path) -> StatusResult:
    db_path = graph_db_path(root)
    if not db_path.exists():
        raise NotInitializedError(str(root))
    with GraphStore(db_path) as store:
        snapshot_id = store.current_snapshot_id(repository_id(root))
        if snapshot_id is None:
            return StatusResult(snapshot_id=None, node_count=0, edge_count=0)
        node_count = _count(store, "nodes", snapshot_id)
        edge_count = _count(store, "edges", snapshot_id)
    return StatusResult(snapshot_id=snapshot_id, node_count=node_count, edge_count=edge_count)


@dataclass(frozen=True, slots=True)
class NodeSummary:
    node_id: str
    label: str
    file_path: str | None


@dataclass(frozen=True, slots=True)
class ImpactSummary:
    changed_files: list[str]
    results: list[ImpactResult]
    node_summaries: dict[str, NodeSummary]
    """Populated only for node ids appearing in `results`, so callers can render a label
    without a second round-trip to the store."""


def _node_summaries(store: GraphStore, results: list[ImpactResult]) -> dict[str, NodeSummary]:
    summaries: dict[str, NodeSummary] = {}
    for result in results:
        for node_id in result.affected_node_ids:
            if node_id in summaries:
                continue
            node = store.get_node(node_id)
            label = (node.qualified_name or node.name) if node else node_id
            file_path = node.file_path if node else None
            summaries[node_id] = NodeSummary(node_id=node_id, label=label, file_path=file_path)
    return summaries


def run_impact(root: Path, from_ref: str, to_ref: str = "HEAD") -> ImpactSummary:
    """Raises NotInitializedError, NotAnalyzedError, or GitCommandError (bad ref) as
    appropriate. An empty `changed_files` list is a valid, non-error result."""
    db_path = graph_db_path(root)
    if not db_path.exists():
        raise NotInitializedError(str(root))

    with GraphStore(db_path) as store:
        snapshot_id = store.current_snapshot_id(repository_id(root))
        if snapshot_id is None:
            raise NotAnalyzedError(str(root))

        change_set = ChangeDetector(GitAdapter(root)).detect(
            change_set_id=stable_id(str(root), from_ref, to_ref),
            snapshot_to_id=snapshot_id,
            from_ref=from_ref,
            to_ref=to_ref,
        )
        results = ImpactAnalyzer(store, GraphTraversalService(store)).analyze(change_set)
        node_summaries = _node_summaries(store, results)

    return ImpactSummary(
        changed_files=change_set.changed_files, results=results, node_summaries=node_summaries
    )


def run_explain(root: Path, from_ref: str, to_ref: str = "HEAD") -> str | None:
    """Returns None when there were no changed files (nothing to explain — not an error).
    Raises NotInitializedError, NotAnalyzedError, GitCommandError,
    ai.factory.BobProviderConfigError, or ai.provider.BobProviderError otherwise."""
    db_path = graph_db_path(root)
    if not db_path.exists():
        raise NotInitializedError(str(root))

    with GraphStore(db_path) as store:
        snapshot_id = store.current_snapshot_id(repository_id(root))
        if snapshot_id is None:
            raise NotAnalyzedError(str(root))

        change_set = ChangeDetector(GitAdapter(root)).detect(
            change_set_id=stable_id(str(root), from_ref, to_ref),
            snapshot_to_id=snapshot_id,
            from_ref=from_ref,
            to_ref=to_ref,
        )
        if not change_set.changed_files:
            return None

        traversal = GraphTraversalService(store)
        results = ImpactAnalyzer(store, traversal).analyze(change_set)
        context = ContextRetriever(store, traversal).build_context(change_set, results, root)

        # Keying on the fully-formatted prompt text (not just change_set_id/context_id)
        # means an edit to the prompt template itself changes the key and naturally
        # invalidates old cached answers — no separate template-version bookkeeping needed.
        prompt = format_explain_prompt(context)
        cache = CacheProvider(store.raw_connection())
        cache_key = stable_id(prompt)
        cached = cache.get(cache_key)
        if cached is not None:
            return str(json.loads(cached)["text"])

    provider = default_bob_provider()
    explanation = provider.complete(prompt)

    with GraphStore(db_path) as store:
        CacheProvider(store.raw_connection()).set(cache_key, {"text": explanation})

    return explanation
