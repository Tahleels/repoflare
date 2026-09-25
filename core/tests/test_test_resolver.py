from repoflare_core.domain.entities import EdgeType, Node, NodeKind
from repoflare_core.parsing.test_resolver import TestLinkResolver

SNAPSHOT_ID = "snap1"


def _symbol(node_id: str, name: str) -> Node:
    return Node(node_id=node_id, snapshot_id=SNAPSHOT_ID, kind=NodeKind.SYMBOL, name=name)


def _test(node_id: str, name: str) -> Node:
    return Node(node_id=node_id, snapshot_id=SNAPSHOT_ID, kind=NodeKind.TEST, name=name)


def test_links_test_to_matching_symbol_by_name() -> None:
    nodes = [_symbol("sym1", "helper"), _test("t1", "test_helper")]

    edges = TestLinkResolver().resolve(SNAPSHOT_ID, nodes)

    assert len(edges) == 1
    assert edges[0].src_node_id == "t1"
    assert edges[0].dst_node_id == "sym1"
    assert edges[0].edge_type == EdgeType.TESTED_BY


def test_links_across_files_by_name_only() -> None:
    """No file-path or qualified-name matching required — same-name-anywhere is the
    documented heuristic, since tests conventionally live in a different file than what
    they test."""
    nodes = [
        Node(
            node_id="sym1",
            snapshot_id=SNAPSHOT_ID,
            kind=NodeKind.SYMBOL,
            name="helper",
            file_path="src/a.py",
        ),
        Node(
            node_id="t1",
            snapshot_id=SNAPSHOT_ID,
            kind=NodeKind.TEST,
            name="test_helper",
            file_path="tests/test_a.py",
        ),
    ]

    edges = TestLinkResolver().resolve(SNAPSHOT_ID, nodes)

    assert len(edges) == 1


def test_no_match_yields_no_edge() -> None:
    nodes = [_symbol("sym1", "helper"), _test("t1", "test_something_else")]

    edges = TestLinkResolver().resolve(SNAPSHOT_ID, nodes)

    assert edges == []


def test_multiple_symbols_with_same_name_all_linked() -> None:
    """Ambiguity is real with a naming heuristic — all candidates are linked, not just one."""
    nodes = [_symbol("sym1", "helper"), _symbol("sym2", "helper"), _test("t1", "test_helper")]

    edges = TestLinkResolver().resolve(SNAPSHOT_ID, nodes)

    dst_ids = {e.dst_node_id for e in edges}
    assert dst_ids == {"sym1", "sym2"}


def test_non_test_prefixed_test_node_is_ignored() -> None:
    """A TEST node whose name somehow doesn't start with test_ (shouldn't happen given how
    ParserAdapter emits them, but the resolver must not crash or misbehave if it did)."""
    nodes = [_symbol("sym1", "helper"), _test("t1", "helper_fixture")]

    edges = TestLinkResolver().resolve(SNAPSHOT_ID, nodes)

    assert edges == []


def test_edge_ids_are_deterministic() -> None:
    nodes = [_symbol("sym1", "helper"), _test("t1", "test_helper")]

    first = TestLinkResolver().resolve(SNAPSHOT_ID, nodes)
    second = TestLinkResolver().resolve(SNAPSHOT_ID, nodes)

    assert first[0].edge_id == second[0].edge_id
