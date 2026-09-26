from datetime import UTC, datetime
from pathlib import Path

from repoflare_core.domain.entities import Edge, EdgeType, Node, NodeKind, Repository, Snapshot
from repoflare_core.graph.store import GraphStore


def _snapshot(snapshot_id: str = "snap1", repository_id: str = "repo1") -> Snapshot:
    return Snapshot(
        snapshot_id=snapshot_id,
        repository_id=repository_id,
        git_commit_sha=None,
        created_at=datetime.now(UTC),
    )


def test_roundtrip_node_with_properties(tmp_path: Path) -> None:
    with GraphStore(tmp_path / "graph.duckdb") as store:
        store.upsert_repository(
            Repository(
                repository_id="repo1",
                root_path="/tmp/repo",
                name="repo",
                created_at=datetime.now(UTC),
            )
        )
        store.create_snapshot(_snapshot())
        node = Node(
            node_id="n1",
            snapshot_id="snap1",
            kind=NodeKind.SYMBOL,
            name="f",
            qualified_name="mod.f",
            file_path="mod.py",
            start_line=1,
            end_line=2,
            content_hash="abc",
            properties={"symbol_kind": "FUNCTION"},
        )
        store.insert_nodes([node])

        fetched = store.get_node("n1")

    assert fetched is not None
    assert fetched.qualified_name == "mod.f"
    assert fetched.properties == {"symbol_kind": "FUNCTION"}


def test_find_by_qualified_name(tmp_path: Path) -> None:
    with GraphStore(tmp_path / "graph.duckdb") as store:
        store.upsert_repository(
            Repository(
                repository_id="repo1",
                root_path="/tmp/repo",
                name="repo",
                created_at=datetime.now(UTC),
            )
        )
        store.create_snapshot(_snapshot())
        store.insert_nodes(
            [
                Node(
                    node_id="n1",
                    snapshot_id="snap1",
                    kind=NodeKind.SYMBOL,
                    name="f",
                    qualified_name="mod.f",
                )
            ]
        )

        found = store.find_by_qualified_name("snap1", "mod.f")
        missing = store.find_by_qualified_name("snap1", "mod.does_not_exist")

    assert found is not None and found.node_id == "n1"
    assert missing is None


def test_current_snapshot_tracks_latest(tmp_path: Path) -> None:
    with GraphStore(tmp_path / "graph.duckdb") as store:
        store.upsert_repository(
            Repository(
                repository_id="repo1",
                root_path="/tmp/repo",
                name="repo",
                created_at=datetime.now(UTC),
            )
        )
        store.create_snapshot(_snapshot("snap1"))
        store.create_snapshot(_snapshot("snap2"))

        current = store.current_snapshot_id("repo1")

    assert current == "snap2"


def test_insert_edges_and_query_via_raw_connection(tmp_path: Path) -> None:
    with GraphStore(tmp_path / "graph.duckdb") as store:
        store.upsert_repository(
            Repository(
                repository_id="repo1",
                root_path="/tmp/repo",
                name="repo",
                created_at=datetime.now(UTC),
            )
        )
        store.create_snapshot(_snapshot())
        store.insert_nodes(
            [
                Node(node_id="a", snapshot_id="snap1", kind=NodeKind.FILE, name="a.py"),
                Node(
                    node_id="b",
                    snapshot_id="snap1",
                    kind=NodeKind.SYMBOL,
                    name="f",
                    qualified_name="a.f",
                ),
            ]
        )
        store.insert_edges(
            [
                Edge(
                    edge_id="e1",
                    snapshot_id="snap1",
                    src_node_id="a",
                    dst_node_id="b",
                    edge_type=EdgeType.CONTAINS,
                )
            ]
        )

        count = (
            store.raw_connection()
            .execute("SELECT count(*) FROM edges WHERE snapshot_id = ?", ["snap1"])
            .fetchone()[0]
        )

    assert count == 1


def test_insert_nodes_empty_list_is_noop(tmp_path: Path) -> None:
    with GraphStore(tmp_path / "graph.duckdb") as store:
        store.insert_nodes([])  # must not raise


def test_insert_edges_empty_list_is_noop(tmp_path: Path) -> None:
    with GraphStore(tmp_path / "graph.duckdb") as store:
        store.insert_edges([])  # must not raise


def test_get_node_returns_none_for_unknown_id(tmp_path: Path) -> None:
    with GraphStore(tmp_path / "graph.duckdb") as store:
        assert store.get_node("does-not-exist") is None


def test_current_snapshot_id_returns_none_when_no_snapshot(tmp_path: Path) -> None:
    with GraphStore(tmp_path / "graph.duckdb") as store:
        store.upsert_repository(
            Repository(
                repository_id="repo1",
                root_path="/tmp/repo",
                name="repo",
                created_at=datetime.now(UTC),
            )
        )

        assert store.current_snapshot_id("repo1") is None


def test_upsert_repository_updates_existing_fields(tmp_path: Path) -> None:
    with GraphStore(tmp_path / "graph.duckdb") as store:
        store.upsert_repository(
            Repository(
                repository_id="repo1",
                root_path="/old/path",
                name="old-name",
                created_at=datetime.now(UTC),
            )
        )
        store.upsert_repository(
            Repository(
                repository_id="repo1",
                root_path="/new/path",
                name="new-name",
                created_at=datetime.now(UTC),
            )
        )

        row = (
            store.raw_connection()
            .execute("SELECT root_path, name FROM repositories WHERE repository_id = ?", ["repo1"])
            .fetchone()
        )

    assert row is not None
    assert row[0] == "/new/path"
    assert row[1] == "new-name"


def test_duplicate_node_insert_is_ignored(tmp_path: Path) -> None:
    """ON CONFLICT DO NOTHING: inserting the same node_id twice must not raise or change
    the stored row."""
    with GraphStore(tmp_path / "graph.duckdb") as store:
        store.upsert_repository(
            Repository(
                repository_id="repo1",
                root_path="/tmp/repo",
                name="repo",
                created_at=datetime.now(UTC),
            )
        )
        store.create_snapshot(_snapshot())
        node = Node(node_id="n1", snapshot_id="snap1", kind=NodeKind.FILE, name="first.py")
        store.insert_nodes([node])
        store.insert_nodes(
            [Node(node_id="n1", snapshot_id="snap1", kind=NodeKind.FILE, name="second.py")]
        )

        fetched = store.get_node("n1")

    assert fetched is not None
    assert fetched.name == "first.py"


def test_nodes_for_file_returns_matching_nodes(tmp_path: Path) -> None:
    with GraphStore(tmp_path / "graph.duckdb") as store:
        store.upsert_repository(
            Repository(
                repository_id="repo1",
                root_path="/tmp/repo",
                name="repo",
                created_at=datetime.now(UTC),
            )
        )
        store.create_snapshot(_snapshot())
        store.insert_nodes(
            [
                Node(
                    node_id="f1",
                    snapshot_id="snap1",
                    kind=NodeKind.FILE,
                    name="a.py",
                    file_path="a.py",
                ),
                Node(
                    node_id="s1",
                    snapshot_id="snap1",
                    kind=NodeKind.SYMBOL,
                    name="func",
                    file_path="a.py",
                ),
                Node(
                    node_id="f2",
                    snapshot_id="snap1",
                    kind=NodeKind.FILE,
                    name="b.py",
                    file_path="b.py",
                ),
            ]
        )

        a_nodes = store.nodes_for_file("snap1", "a.py")
        b_nodes = store.nodes_for_file("snap1", "b.py")
        c_nodes = store.nodes_for_file("snap1", "c.py")

    assert {n.node_id for n in a_nodes} == {"f1", "s1"}
    assert {n.node_id for n in b_nodes} == {"f2"}
    assert c_nodes == []


def _repo_and_snapshot(store: GraphStore, snap_id: str = "snap1") -> None:
    """Helper: insert a minimal repository + snapshot so FK constraints are satisfied."""
    from datetime import UTC, datetime

    from repoflare_core.domain.entities import Repository, Snapshot

    store.upsert_repository(
        Repository(repository_id="repo1", root_path="/r", name="r", created_at=datetime.now(UTC))
    )
    store.create_snapshot(
        Snapshot(
            snapshot_id=snap_id,
            repository_id="repo1",
            git_commit_sha=None,
            created_at=datetime.now(UTC),
        )
    )


def test_all_nodes_respects_limit(tmp_path: Path) -> None:
    with GraphStore(tmp_path / "g.duckdb") as store:
        _repo_and_snapshot(store)
        nodes = [
            Node(node_id=f"n{i}", snapshot_id="snap1", kind=NodeKind.SYMBOL, name=f"sym{i}")
            for i in range(5)
        ]
        store.insert_nodes(nodes)

        result = store.all_nodes("snap1", limit=3)

    assert len(result) == 3


def test_all_nodes_orders_by_degree_highest_first(tmp_path: Path) -> None:
    """Node 'hub' is connected to all others; it must appear first in the limited view."""
    with GraphStore(tmp_path / "g.duckdb") as store:
        _repo_and_snapshot(store)
        store.insert_nodes(
            [
                Node(node_id="hub", snapshot_id="snap1", kind=NodeKind.SYMBOL, name="hub"),
                Node(node_id="a", snapshot_id="snap1", kind=NodeKind.SYMBOL, name="a"),
                Node(node_id="b", snapshot_id="snap1", kind=NodeKind.SYMBOL, name="b"),
                Node(node_id="c", snapshot_id="snap1", kind=NodeKind.SYMBOL, name="c"),
            ]
        )
        store.insert_edges(
            [
                Edge(
                    edge_id="e1",
                    snapshot_id="snap1",
                    src_node_id="a",
                    dst_node_id="hub",
                    edge_type=EdgeType.CALLS,
                ),
                Edge(
                    edge_id="e2",
                    snapshot_id="snap1",
                    src_node_id="b",
                    dst_node_id="hub",
                    edge_type=EdgeType.CALLS,
                ),
                Edge(
                    edge_id="e3",
                    snapshot_id="snap1",
                    src_node_id="c",
                    dst_node_id="hub",
                    edge_type=EdgeType.CALLS,
                ),
            ]
        )

        result = store.all_nodes("snap1", limit=4)

    assert result[0].node_id == "hub"


def test_edges_among_only_returns_internal_edges(tmp_path: Path) -> None:
    """edges_among must exclude edges where one endpoint is outside the given set."""
    with GraphStore(tmp_path / "g.duckdb") as store:
        _repo_and_snapshot(store)
        store.insert_nodes(
            [
                Node(node_id="a", snapshot_id="snap1", kind=NodeKind.SYMBOL, name="a"),
                Node(node_id="b", snapshot_id="snap1", kind=NodeKind.SYMBOL, name="b"),
                Node(node_id="c", snapshot_id="snap1", kind=NodeKind.SYMBOL, name="c"),
            ]
        )
        store.insert_edges(
            [
                Edge(
                    edge_id="ab",
                    snapshot_id="snap1",
                    src_node_id="a",
                    dst_node_id="b",
                    edge_type=EdgeType.CALLS,
                ),
                Edge(
                    edge_id="ac",
                    snapshot_id="snap1",
                    src_node_id="a",
                    dst_node_id="c",
                    edge_type=EdgeType.CALLS,
                ),
            ]
        )

        # Only ask for nodes a and b — edge ac must not appear
        result = store.edges_among("snap1", ["a", "b"])

    assert len(result) == 1
    assert result[0].edge_id == "ab"


def test_edges_among_empty_node_list_returns_empty(tmp_path: Path) -> None:
    with GraphStore(tmp_path / "g.duckdb") as store:
        assert store.edges_among("snap1", []) == []
