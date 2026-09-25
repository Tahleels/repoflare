"""Builds a chain of files a.py <- b.py <- c.py <- d.py <- e.py (each CALLS the previous
one's symbol) and changes a.py, so the four ImpactCategory buckets line up with depth
1/2/3/4+ exactly as documented in impact/analyzer.py."""

from datetime import UTC, datetime
from pathlib import Path

from repoflare_core.domain.entities import (
    ChangeSet,
    Edge,
    EdgeType,
    ImpactCategory,
    Node,
    NodeKind,
    Repository,
    Snapshot,
)
from repoflare_core.graph.store import GraphStore
from repoflare_core.graph.traversal import GraphTraversalService
from repoflare_core.impact.analyzer import ImpactAnalyzer

SNAPSHOT_ID = "snap1"


def _build_chain(tmp_path: Path) -> GraphStore:
    store = GraphStore(tmp_path / "graph.duckdb")
    store.upsert_repository(
        Repository(
            repository_id="repo1", root_path="/tmp/repo", name="repo", created_at=datetime.now(UTC)
        )
    )
    store.create_snapshot(
        Snapshot(
            snapshot_id=SNAPSHOT_ID,
            repository_id="repo1",
            git_commit_sha=None,
            created_at=datetime.now(UTC),
        )
    )

    letters = ["a", "b", "c", "d", "e"]
    store.insert_nodes(
        [
            Node(
                node_id=letter,
                snapshot_id=SNAPSHOT_ID,
                kind=NodeKind.SYMBOL,
                name=letter,
                file_path=f"{letter}.py",
            )
            for letter in letters
        ]
    )
    # b CALLS a, c CALLS b, d CALLS c, e CALLS d  =>  reverse_impact(a) = {b:1, c:2, d:3, e:4}
    store.insert_edges(
        [
            Edge(
                edge_id="e_ba",
                snapshot_id=SNAPSHOT_ID,
                src_node_id="b",
                dst_node_id="a",
                edge_type=EdgeType.CALLS,
            ),
            Edge(
                edge_id="e_cb",
                snapshot_id=SNAPSHOT_ID,
                src_node_id="c",
                dst_node_id="b",
                edge_type=EdgeType.CALLS,
            ),
            Edge(
                edge_id="e_dc",
                snapshot_id=SNAPSHOT_ID,
                src_node_id="d",
                dst_node_id="c",
                edge_type=EdgeType.CALLS,
            ),
            Edge(
                edge_id="e_ed",
                snapshot_id=SNAPSHOT_ID,
                src_node_id="e",
                dst_node_id="d",
                edge_type=EdgeType.CALLS,
            ),
        ]
    )
    return store


def test_categorizes_depths_across_all_four_buckets(tmp_path: Path) -> None:
    with _build_chain(tmp_path) as store:
        analyzer = ImpactAnalyzer(store, GraphTraversalService(store))
        change_set = ChangeSet(
            change_set_id="cs1", snapshot_to_id=SNAPSHOT_ID, changed_files=["a.py"]
        )

        results = {r.category: r.affected_node_ids for r in analyzer.analyze(change_set)}

    assert results[ImpactCategory.DIRECT] == ["b"]
    assert results[ImpactCategory.INDIRECT] == ["c"]
    assert results[ImpactCategory.RELATED] == ["d"]
    assert results[ImpactCategory.POSSIBLE] == ["e"]


def test_changed_node_itself_is_excluded_from_results(tmp_path: Path) -> None:
    with _build_chain(tmp_path) as store:
        analyzer = ImpactAnalyzer(store, GraphTraversalService(store))
        change_set = ChangeSet(
            change_set_id="cs1", snapshot_to_id=SNAPSHOT_ID, changed_files=["a.py"]
        )

        results = analyzer.analyze(change_set)

    all_affected = {node_id for r in results for node_id in r.affected_node_ids}
    assert "a" not in all_affected


def test_unknown_changed_file_yields_no_results(tmp_path: Path) -> None:
    with _build_chain(tmp_path) as store:
        analyzer = ImpactAnalyzer(store, GraphTraversalService(store))
        change_set = ChangeSet(
            change_set_id="cs1", snapshot_to_id=SNAPSHOT_ID, changed_files=["nonexistent.py"]
        )

        assert analyzer.analyze(change_set) == []


def test_empty_changed_files_yields_no_results(tmp_path: Path) -> None:
    with _build_chain(tmp_path) as store:
        analyzer = ImpactAnalyzer(store, GraphTraversalService(store))
        change_set = ChangeSet(change_set_id="cs1", snapshot_to_id=SNAPSHOT_ID, changed_files=[])

        assert analyzer.analyze(change_set) == []


def test_respects_max_depth(tmp_path: Path) -> None:
    with _build_chain(tmp_path) as store:
        analyzer = ImpactAnalyzer(store, GraphTraversalService(store))
        change_set = ChangeSet(
            change_set_id="cs1", snapshot_to_id=SNAPSHOT_ID, changed_files=["a.py"]
        )

        results = {
            r.category: r.affected_node_ids for r in analyzer.analyze(change_set, max_depth=2)
        }

    assert set(results) == {ImpactCategory.DIRECT, ImpactCategory.INDIRECT}
    assert results[ImpactCategory.DIRECT] == ["b"]
    assert results[ImpactCategory.INDIRECT] == ["c"]


def test_result_ids_are_deterministic(tmp_path: Path) -> None:
    with _build_chain(tmp_path) as store:
        analyzer = ImpactAnalyzer(store, GraphTraversalService(store))
        change_set = ChangeSet(
            change_set_id="cs1", snapshot_to_id=SNAPSHOT_ID, changed_files=["a.py"]
        )

        first = analyzer.analyze(change_set)
        second = analyzer.analyze(change_set)

    assert {r.impact_id for r in first} == {r.impact_id for r in second}
