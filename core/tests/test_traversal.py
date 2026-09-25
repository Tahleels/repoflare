"""Builds a small dependency chain a <- b <- c (b calls a, c calls b) and checks reverse
traversal finds the right nodes at the right depths."""

from datetime import UTC, datetime
from pathlib import Path

from repoflare_core.domain.entities import Edge, EdgeType, Node, NodeKind, Repository, Snapshot
from repoflare_core.graph.store import GraphStore
from repoflare_core.graph.traversal import GraphTraversalService


def _build_chain(tmp_path: Path) -> GraphStore:
    store = GraphStore(tmp_path / "graph.duckdb")
    store.upsert_repository(
        Repository(
            repository_id="repo1", root_path="/tmp/repo", name="repo", created_at=datetime.now(UTC)
        )
    )
    store.create_snapshot(
        Snapshot(
            snapshot_id="snap1",
            repository_id="repo1",
            git_commit_sha=None,
            created_at=datetime.now(UTC),
        )
    )
    store.insert_nodes(
        [
            Node(node_id="a", snapshot_id="snap1", kind=NodeKind.SYMBOL, name="a"),
            Node(node_id="b", snapshot_id="snap1", kind=NodeKind.SYMBOL, name="b"),
            Node(node_id="c", snapshot_id="snap1", kind=NodeKind.SYMBOL, name="c"),
        ]
    )
    # b CALLS a, c CALLS b  =>  a's dependents are b (direct) and c (indirect)
    store.insert_edges(
        [
            Edge(
                edge_id="e1",
                snapshot_id="snap1",
                src_node_id="b",
                dst_node_id="a",
                edge_type=EdgeType.CALLS,
            ),
            Edge(
                edge_id="e2",
                snapshot_id="snap1",
                src_node_id="c",
                dst_node_id="b",
                edge_type=EdgeType.CALLS,
            ),
        ]
    )
    return store


def test_direct_dependents(tmp_path: Path) -> None:
    with _build_chain(tmp_path) as store:
        traversal = GraphTraversalService(store)
        assert traversal.direct_dependents("snap1", "a") == ["b"]
        assert traversal.direct_dependents("snap1", "b") == ["c"]
        assert traversal.direct_dependents("snap1", "c") == []


def test_reverse_impact_depths(tmp_path: Path) -> None:
    with _build_chain(tmp_path) as store:
        traversal = GraphTraversalService(store)
        hops = {h.node_id: h.min_depth for h in traversal.reverse_impact("snap1", "a")}

    assert hops == {"b": 1, "c": 2}


def test_reverse_impact_respects_max_depth(tmp_path: Path) -> None:
    with _build_chain(tmp_path) as store:
        traversal = GraphTraversalService(store)
        hops = {h.node_id: h.min_depth for h in traversal.reverse_impact("snap1", "a", max_depth=1)}

    assert hops == {"b": 1}


def test_direct_dependents_with_edge_type_filter(tmp_path: Path) -> None:
    """edge_type filter must restrict to only edges of that type."""
    with _build_chain(tmp_path) as store:
        traversal = GraphTraversalService(store)
        # chain only has CALLS edges; filtering on IMPORTS must return nothing
        assert traversal.direct_dependents("snap1", "a", edge_type=EdgeType.IMPORTS) == []
        # filtering on the correct type must still work
        assert traversal.direct_dependents("snap1", "a", edge_type=EdgeType.CALLS) == ["b"]


def test_reverse_impact_max_depth_zero_returns_empty(tmp_path: Path) -> None:
    """max_depth=0 means the seed node itself only (depth > 0 filter excludes it)."""
    with _build_chain(tmp_path) as store:
        traversal = GraphTraversalService(store)
        hops = traversal.reverse_impact("snap1", "a", max_depth=0)

    assert hops == []


def test_reverse_impact_leaf_node_returns_empty(tmp_path: Path) -> None:
    """c has no incoming edges in the chain, so its reverse impact is empty."""
    with _build_chain(tmp_path) as store:
        traversal = GraphTraversalService(store)
        hops = traversal.reverse_impact("snap1", "c")

    assert hops == []


def test_shortest_reverse_path_reconstructs_chain(tmp_path: Path) -> None:
    with _build_chain(tmp_path) as store:
        traversal = GraphTraversalService(store)

        assert traversal.shortest_reverse_path("snap1", "a", "b") == ["a", "b"]
        assert traversal.shortest_reverse_path("snap1", "a", "c") == ["a", "b", "c"]


def test_shortest_reverse_path_same_node_is_trivial(tmp_path: Path) -> None:
    with _build_chain(tmp_path) as store:
        traversal = GraphTraversalService(store)

        assert traversal.shortest_reverse_path("snap1", "a", "a") == ["a"]


def test_shortest_reverse_path_unreachable_returns_none(tmp_path: Path) -> None:
    with _build_chain(tmp_path) as store:
        traversal = GraphTraversalService(store)

        # c has no dependents in the chain, so nothing is reachable from c
        assert traversal.shortest_reverse_path("snap1", "c", "a") is None


def test_shortest_reverse_path_respects_max_depth(tmp_path: Path) -> None:
    with _build_chain(tmp_path) as store:
        traversal = GraphTraversalService(store)

        assert traversal.shortest_reverse_path("snap1", "a", "c", max_depth=1) is None


def test_reverse_impact_very_deep_chain_bounded_by_max_depth(tmp_path: Path) -> None:
    """A chain longer than max_depth must be cut off at max_depth hops."""
    store = GraphStore(tmp_path / "graph.duckdb")
    store.upsert_repository(
        Repository(
            repository_id="repo1", root_path="/tmp/r", name="r", created_at=datetime.now(UTC)
        )
    )
    store.create_snapshot(
        Snapshot(
            snapshot_id="snap1",
            repository_id="repo1",
            git_commit_sha=None,
            created_at=datetime.now(UTC),
        )
    )
    # Build chain: n0 <- n1 <- n2 <- ... <- n9  (10 nodes, 9 edges)
    chain_ids = [f"n{i}" for i in range(10)]
    store.insert_nodes(
        [
            Node(node_id=nid, snapshot_id="snap1", kind=NodeKind.SYMBOL, name=nid)
            for nid in chain_ids
        ]
    )
    store.insert_edges(
        [
            Edge(
                edge_id=f"e{i}",
                snapshot_id="snap1",
                src_node_id=chain_ids[i + 1],
                dst_node_id=chain_ids[i],
                edge_type=EdgeType.CALLS,
            )
            for i in range(9)
        ]
    )

    with store:
        traversal = GraphTraversalService(store)
        hops = traversal.reverse_impact("snap1", "n0", max_depth=3)

    depths = {h.node_id: h.min_depth for h in hops}
    # Only n1, n2, n3 should appear (depths 1, 2, 3); n4 through n9 must be absent
    assert set(depths.keys()) == {"n1", "n2", "n3"}
    assert depths["n1"] == 1
    assert depths["n3"] == 3
