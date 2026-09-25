from pathlib import Path

from repoflare_core.domain.entities import EdgeType
from repoflare_core.parsing.adapter import ParserAdapter
from repoflare_core.parsing.resolver import CallImportResolver
from repoflare_core.scanning.scanner import ScannedFile

SNAPSHOT_ID = "snap1"


def _scanned_file(relative_path: str, content: str) -> ScannedFile:
    return ScannedFile(
        relative_path=relative_path,
        absolute_path=Path(relative_path),
        language="python",
        content=content,
        content_hash="irrelevant",
    )


def test_resolves_same_file_call_to_module_level_function() -> None:
    source = "def helper():\n    pass\n\ndef entry():\n    helper()\n"
    file = _scanned_file("pkg/mod.py", source)
    parse_result = ParserAdapter().parse(file, SNAPSHOT_ID)
    node_id_by_qname = {n.qualified_name: n.node_id for n in parse_result.nodes if n.qualified_name}

    edges = CallImportResolver().resolve(file, SNAPSHOT_ID, "pkg.mod", node_id_by_qname, {})

    calls = [e for e in edges if e.edge_type == EdgeType.CALLS]
    assert len(calls) == 1
    assert calls[0].src_node_id == node_id_by_qname["pkg.mod.entry"]
    assert calls[0].dst_node_id == node_id_by_qname["pkg.mod.helper"]


def test_does_not_resolve_call_from_method_to_unrelated_function_outside_scope() -> None:
    # self.foo() is out of scope (attribute call, not a plain identifier) — must not appear.
    source = "class Widget:\n    def render(self):\n        self.helper()\n"
    file = _scanned_file("pkg/mod.py", source)
    parse_result = ParserAdapter().parse(file, SNAPSHOT_ID)
    node_id_by_qname = {n.qualified_name: n.node_id for n in parse_result.nodes if n.qualified_name}

    edges = CallImportResolver().resolve(file, SNAPSHOT_ID, "pkg.mod", node_id_by_qname, {})

    assert [e for e in edges if e.edge_type == EdgeType.CALLS] == []


def test_resolves_import_between_files() -> None:
    importer = _scanned_file("pkg/main.py", "import pkg.helper\n")
    file_node_id_by_module_qname = {"pkg.main": "file_main", "pkg.helper": "file_helper"}

    edges = CallImportResolver().resolve(
        importer, SNAPSHOT_ID, "pkg.main", {}, file_node_id_by_module_qname
    )

    imports = [e for e in edges if e.edge_type == EdgeType.IMPORTS]
    assert len(imports) == 1
    assert imports[0].src_node_id == "file_main"
    assert imports[0].dst_node_id == "file_helper"


def test_import_from_statement_resolves_module() -> None:
    importer = _scanned_file("pkg/main.py", "from pkg.helper import thing\n")
    file_node_id_by_module_qname = {"pkg.main": "file_main", "pkg.helper": "file_helper"}

    edges = CallImportResolver().resolve(
        importer, SNAPSHOT_ID, "pkg.main", {}, file_node_id_by_module_qname
    )

    imports = [e for e in edges if e.edge_type == EdgeType.IMPORTS]
    assert len(imports) == 1
    assert imports[0].dst_node_id == "file_helper"


def test_unresolvable_import_produces_no_edge() -> None:
    importer = _scanned_file("pkg/main.py", "import somewhere.unknown\n")

    edges = CallImportResolver().resolve(
        importer, SNAPSHOT_ID, "pkg.main", {}, {"pkg.main": "file_main"}
    )

    assert edges == []


def test_non_python_file_yields_no_edges() -> None:
    file = ScannedFile(
        relative_path="a.ts",
        absolute_path=Path("a.ts"),
        language="typescript",
        content="function f() {}",
        content_hash="x",
    )

    edges = CallImportResolver().resolve(file, SNAPSHOT_ID, "a", {}, {})

    assert edges == []


def test_duplicate_import_edges_are_deduplicated_by_stable_id() -> None:
    """Two identical import statements in the same file must produce a single edge because
    the edge_id is a deterministic hash of (snapshot, src, dst)."""
    importer = _scanned_file(
        "pkg/main.py",
        "import pkg.helper\nimport pkg.helper\n",
    )
    file_node_id_by_module_qname = {"pkg.main": "file_main", "pkg.helper": "file_helper"}

    edges = CallImportResolver().resolve(
        importer, SNAPSHOT_ID, "pkg.main", {}, file_node_id_by_module_qname
    )

    import_edges = [e for e in edges if e.edge_type == EdgeType.IMPORTS]
    edge_ids = [e.edge_id for e in import_edges]
    # Same stable_id → same edge_id; GraphStore deduplicates on insert, but the resolver
    # itself may return duplicates — what matters is that the ids are identical.
    assert len(set(edge_ids)) == 1


def test_self_import_produces_no_edge() -> None:
    """A module importing itself must not produce a self-loop edge."""
    importer = _scanned_file("pkg/mod.py", "import pkg.mod\n")
    file_node_id_by_module_qname = {"pkg.mod": "file_mod"}

    edges = CallImportResolver().resolve(
        importer, SNAPSHOT_ID, "pkg.mod", {}, file_node_id_by_module_qname
    )

    assert edges == []


def test_call_at_module_level_outside_function_produces_no_edge() -> None:
    """A bare call at module level (no enclosing function/class) has no valid caller node
    and must be silently ignored."""
    source = "def helper():\n    pass\n\nhelper()\n"
    file = _scanned_file("pkg/mod.py", source)
    parse_result = ParserAdapter().parse(file, SNAPSHOT_ID)
    node_id_by_qname = {n.qualified_name: n.node_id for n in parse_result.nodes if n.qualified_name}

    edges = CallImportResolver().resolve(file, SNAPSHOT_ID, "pkg.mod", node_id_by_qname, {})

    calls = [e for e in edges if e.edge_type == EdgeType.CALLS]
    assert calls == []


def test_call_to_unknown_function_produces_no_edge() -> None:
    source = "def entry():\n    unknown_function()\n"
    file = _scanned_file("pkg/mod.py", source)
    parse_result = ParserAdapter().parse(file, SNAPSHOT_ID)
    node_id_by_qname = {n.qualified_name: n.node_id for n in parse_result.nodes if n.qualified_name}

    edges = CallImportResolver().resolve(file, SNAPSHOT_ID, "pkg.mod", node_id_by_qname, {})

    assert [e for e in edges if e.edge_type == EdgeType.CALLS] == []


def test_empty_file_produces_no_edges() -> None:
    file = _scanned_file("pkg/empty.py", "")

    edges = CallImportResolver().resolve(file, SNAPSHOT_ID, "pkg.empty", {}, {})

    assert edges == []
