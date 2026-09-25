from datetime import UTC, datetime
from pathlib import Path

from repoflare_core.domain.entities import (
    ChangeSet,
    Edge,
    EdgeType,
    ImpactCategory,
    ImpactResult,
    Node,
    NodeKind,
    Repository,
    Snapshot,
)
from repoflare_core.graph.store import GraphStore
from repoflare_core.graph.traversal import GraphTraversalService
from repoflare_core.retrieval.context_retriever import ContextRetriever

SNAPSHOT_ID = "snap1"


def _build_store(tmp_path: Path) -> GraphStore:
    store = GraphStore(tmp_path / "graph.duckdb")
    store.upsert_repository(
        Repository(
            repository_id="repo1",
            root_path=str(tmp_path),
            name="repo",
            created_at=datetime.now(UTC),
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
    store.insert_nodes(
        [
            Node(
                node_id="a_helper",
                snapshot_id=SNAPSHOT_ID,
                kind=NodeKind.SYMBOL,
                name="helper",
                file_path="a.py",
                start_line=1,
                end_line=2,
            ),
            Node(
                node_id="b_entry",
                snapshot_id=SNAPSHOT_ID,
                kind=NodeKind.SYMBOL,
                name="entry",
                file_path="b.py",
                start_line=1,
                end_line=2,
            ),
        ]
    )
    store.insert_edges(
        [
            Edge(
                edge_id="e1",
                snapshot_id=SNAPSHOT_ID,
                src_node_id="b_entry",
                dst_node_id="a_helper",
                edge_type=EdgeType.CALLS,
            )
        ]
    )
    return store


def _direct_result(node_ids: list[str]) -> ImpactResult:
    return ImpactResult(
        impact_id="imp1",
        change_set_id="cs1",
        category=ImpactCategory.DIRECT,
        affected_node_ids=node_ids,
        provenance="graph_traversal",
    )


def test_build_context_includes_snippets_and_graph_path(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def helper():\n    pass\n")
    (tmp_path / "b.py").write_text("def entry():\n    helper()\n")

    with _build_store(tmp_path) as store:
        retriever = ContextRetriever(store, GraphTraversalService(store))
        change_set = ChangeSet(
            change_set_id="cs1", snapshot_to_id=SNAPSHOT_ID, changed_files=["a.py"]
        )

        context = retriever.build_context(change_set, [_direct_result(["b_entry"])], tmp_path)

    assert context.change_set_id == "cs1"
    assert context.direct_dependents == ["b_entry"]
    assert context.graph_paths == [["a_helper", "b_entry"]]
    assert context.snippets["a.py"] == "def helper():\n    pass"
    assert context.snippets["b.py"] == "def entry():\n    helper()"


def test_build_context_empty_impact_still_returns_changed_snippets(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def helper():\n    pass\n")
    (tmp_path / "b.py").write_text("def entry():\n    helper()\n")

    with _build_store(tmp_path) as store:
        retriever = ContextRetriever(store, GraphTraversalService(store))
        change_set = ChangeSet(
            change_set_id="cs1", snapshot_to_id=SNAPSHOT_ID, changed_files=["a.py"]
        )

        context = retriever.build_context(change_set, [], tmp_path)

    assert context.direct_dependents == []
    assert context.graph_paths == []
    assert "a.py" in context.snippets


def test_build_context_missing_file_on_disk_is_skipped_not_crashed(tmp_path: Path) -> None:
    # a.py is registered in the graph but doesn't actually exist on disk anymore
    with _build_store(tmp_path) as store:
        retriever = ContextRetriever(store, GraphTraversalService(store))
        change_set = ChangeSet(
            change_set_id="cs1", snapshot_to_id=SNAPSHOT_ID, changed_files=["a.py"]
        )

        context = retriever.build_context(change_set, [], tmp_path)

    assert context.snippets == {}


def test_context_id_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def helper():\n    pass\n")

    with _build_store(tmp_path) as store:
        retriever = ContextRetriever(store, GraphTraversalService(store))
        change_set = ChangeSet(
            change_set_id="cs1", snapshot_to_id=SNAPSHOT_ID, changed_files=["a.py"]
        )

        first = retriever.build_context(change_set, [], tmp_path)
        second = retriever.build_context(change_set, [], tmp_path)

    assert first.context_id == second.context_id


def test_relevant_tests_is_always_empty_no_test_discovery_yet(tmp_path: Path) -> None:
    with _build_store(tmp_path) as store:
        retriever = ContextRetriever(store, GraphTraversalService(store))
        change_set = ChangeSet(change_set_id="cs1", snapshot_to_id=SNAPSHOT_ID, changed_files=[])

        context = retriever.build_context(change_set, [], tmp_path)

    assert context.relevant_tests == []
