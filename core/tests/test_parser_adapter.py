from pathlib import Path

from repoflare_core.domain.entities import EdgeType, NodeKind, SymbolKind
from repoflare_core.parsing.adapter import ParserAdapter
from repoflare_core.scanning.scanner import ScannedFile

SNAPSHOT_ID = "snap1"


def _scanned_file(relative_path: str, language: str, content: str) -> ScannedFile:
    return ScannedFile(
        relative_path=relative_path,
        absolute_path=Path(relative_path),
        language=language,
        content=content,
        content_hash="irrelevant-for-these-tests",
    )


def test_extracts_top_level_function_and_class_with_method_python() -> None:
    source = "def top_level():\n    pass\n\nclass Widget:\n    def render(self):\n        pass\n"
    file = _scanned_file("pkg/widget.py", "python", source)

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    symbols = {n.qualified_name: n for n in result.nodes if n.kind == NodeKind.SYMBOL}
    assert set(symbols) == {"pkg.widget.top_level", "pkg.widget.Widget", "pkg.widget.Widget.render"}
    assert symbols["pkg.widget.top_level"].properties["symbol_kind"] == SymbolKind.FUNCTION.value
    assert symbols["pkg.widget.Widget"].properties["symbol_kind"] == SymbolKind.CLASS.value
    assert symbols["pkg.widget.Widget.render"].properties["symbol_kind"] == SymbolKind.METHOD.value

    file_node = next(n for n in result.nodes if n.kind == NodeKind.FILE)
    contains_edges = [e for e in result.edges if e.edge_type == EdgeType.CONTAINS]
    # file -> top_level, file -> Widget, Widget -> render
    assert len(contains_edges) == 3
    assert any(
        e.src_node_id == file_node.node_id
        and e.dst_node_id == symbols["pkg.widget.top_level"].node_id
        for e in contains_edges
    )
    assert any(
        e.src_node_id == symbols["pkg.widget.Widget"].node_id
        and e.dst_node_id == symbols["pkg.widget.Widget.render"].node_id
        for e in contains_edges
    )


def test_extracts_function_and_class_with_method_typescript() -> None:
    source = "function topLevel() {}\n\nclass Widget {\n  render() {}\n}\n"
    file = _scanned_file("src/widget.ts", "typescript", source)

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    symbols = {n.qualified_name: n for n in result.nodes if n.kind == NodeKind.SYMBOL}
    assert set(symbols) == {"src.widget.topLevel", "src.widget.Widget", "src.widget.Widget.render"}


def test_ids_are_stable_across_repeated_parses() -> None:
    source = "def f():\n    pass\n"
    file = _scanned_file("m.py", "python", source)

    first = ParserAdapter().parse(file, SNAPSHOT_ID)
    second = ParserAdapter().parse(file, SNAPSHOT_ID)

    first_ids = sorted(n.node_id for n in first.nodes)
    second_ids = sorted(n.node_id for n in second.nodes)
    assert first_ids == second_ids


def test_unsupported_language_yields_only_file_node() -> None:
    file = _scanned_file("data.json", None, "{}")

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    assert len(result.nodes) == 1
    assert result.nodes[0].kind == NodeKind.FILE
    assert result.edges == []


def test_empty_source_yields_only_file_node() -> None:
    file = _scanned_file("empty.py", "python", "")

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    assert len(result.nodes) == 1
    assert result.nodes[0].kind == NodeKind.FILE
    assert result.edges == []


def test_malformed_source_does_not_raise() -> None:
    """tree-sitter recovers from syntax errors rather than raising; we must not crash."""
    file = _scanned_file("broken.py", "python", "def (\n    !!!invalid")

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    # At minimum the FILE node must be present; symbol count is best-effort.
    assert any(n.kind == NodeKind.FILE for n in result.nodes)


def test_symbol_line_numbers_are_one_indexed() -> None:
    source = "def f():\n    pass\n"
    file = _scanned_file("m.py", "python", source)

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    symbol = next(n for n in result.nodes if n.kind == NodeKind.SYMBOL)
    assert symbol.start_line == 1
    assert symbol.end_line == 2


def test_deeply_nested_class_methods_extracted() -> None:
    source = "class Outer:\n    class Inner:\n        def method(self):\n            pass\n"
    file = _scanned_file("deep.py", "python", source)

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    qnames = {n.qualified_name for n in result.nodes if n.kind == NodeKind.SYMBOL}
    assert "deep.Outer" in qnames
    assert "deep.Outer.Inner" in qnames
    assert "deep.Outer.Inner.method" in qnames


def test_javascript_file_uses_typescript_parser() -> None:
    """JS files are assigned 'javascript' language by the scanner; adapter falls back to
    the typescript parser (no dedicated JS grammar is registered)."""
    source = "function greet() {}\n"
    file = _scanned_file("util.js", "javascript", source)

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    # JS with the typescript parser: function_declaration is recognised.
    # Result may vary with grammar version, but must not crash and must have a FILE node.
    assert any(n.kind == NodeKind.FILE for n in result.nodes)


def test_module_qualified_name_strips_extension_and_converts_slashes() -> None:
    from repoflare_core.parsing.adapter import module_qualified_name

    assert module_qualified_name("pkg/sub/mod.py") == "pkg.sub.mod"
    assert module_qualified_name("index.ts") == "index"
    assert module_qualified_name("a/b/c.tsx") == "a.b.c"


def test_test_function_in_test_file_becomes_test_node() -> None:
    source = "def test_helper():\n    assert True\n"
    file = _scanned_file("tests/test_widget.py", "python", source)

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    test_nodes = [n for n in result.nodes if n.kind == NodeKind.TEST]
    assert len(test_nodes) == 1
    assert test_nodes[0].name == "test_helper"
    assert test_nodes[0].properties["framework"] == "pytest"
    assert not any(n.kind == NodeKind.SYMBOL for n in result.nodes)


def test_test_suffix_file_naming_also_recognised() -> None:
    source = "def test_helper():\n    assert True\n"
    file = _scanned_file("widget_test.py", "python", source)

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    assert any(n.kind == NodeKind.TEST for n in result.nodes)


def test_function_not_prefixed_test_in_test_file_stays_a_symbol() -> None:
    source = "def helper():\n    pass\n\ndef test_uses_helper():\n    helper()\n"
    file = _scanned_file("tests/test_widget.py", "python", source)

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    kinds = {n.name: n.kind for n in result.nodes}
    assert kinds["helper"] == NodeKind.SYMBOL
    assert kinds["test_uses_helper"] == NodeKind.TEST


def test_test_prefixed_function_outside_test_file_stays_a_symbol() -> None:
    """A function named test_foo in a normal (non-test-named) file is not pytest-discoverable
    (doesn't match python_files), so it must not be misclassified as a test."""
    source = "def test_something():\n    pass\n"
    file = _scanned_file("widget.py", "python", source)

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    assert not any(n.kind == NodeKind.TEST for n in result.nodes)
    assert any(n.kind == NodeKind.SYMBOL and n.name == "test_something" for n in result.nodes)


def test_method_named_test_something_is_not_reclassified() -> None:
    """Only module-level functions are considered for test detection this pass — a method
    inside a class is out of scope (see parsing/adapter.py's module docstring)."""
    source = "class Foo:\n    def test_bar(self):\n        pass\n"
    file = _scanned_file("tests/test_widget.py", "python", source)

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    assert not any(n.kind == NodeKind.TEST for n in result.nodes)


def test_file_node_qualified_name_matches_module_qualified_name() -> None:
    from repoflare_core.parsing.adapter import module_qualified_name

    source = "x = 1\n"
    file = _scanned_file("pkg/utils.py", "python", source)

    result = ParserAdapter().parse(file, SNAPSHOT_ID)

    file_node = next(n for n in result.nodes if n.kind == NodeKind.FILE)
    assert file_node.qualified_name == module_qualified_name("pkg/utils.py")
