"""ParserAdapter: wraps tree-sitter to extract structural symbols (functions/classes/
methods) and CONTAINS edges from a single file's source text.

Scope note: cross-file resolution (CALLS edges to symbols in other files, resolved IMPORTS
targets) is intentionally not implemented here — see AGENTS.md "Next up" for why that's a
separate, well-scoped task rather than something to bolt on half-finished.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode

from repoflare_core.domain.entities import Edge, EdgeType, Node, NodeKind, SymbolKind
from repoflare_core.domain.ids import stable_id
from repoflare_core.scanning.scanner import ScannedFile

_LANGUAGE_TABLE: dict[str, Language] = {
    "python": Language(tspython.language()),
    "typescript": Language(tstypescript.language_typescript()),
}


class _SymbolRef(NamedTuple):
    qualified_name: str
    node_id: str


@dataclass(frozen=True, slots=True)
class ParseResult:
    nodes: list[Node]
    edges: list[Edge]


def module_qualified_name(relative_path: str) -> str:
    """Shared by ParserAdapter (to name the File node) and CallImportResolver's caller (to
    key the snapshot-wide module lookup) — both must agree on this mapping or import/call
    resolution silently fails to match, so it lives in one place."""
    return relative_path.rsplit(".", 1)[0].replace("/", ".")


class ParserAdapter:
    def __init__(self) -> None:
        self._parsers: dict[str, Parser] = {}

    def _parser_for(self, language: str) -> Parser | None:
        ts_language = _LANGUAGE_TABLE.get(language)
        if ts_language is None:
            return None
        if language not in self._parsers:
            self._parsers[language] = Parser(ts_language)
        return self._parsers[language]

    def parse(self, file: ScannedFile, snapshot_id: str) -> ParseResult:
        module_qname = module_qualified_name(file.relative_path)
        file_node = Node(
            node_id=stable_id(snapshot_id, "FILE", file.relative_path),
            snapshot_id=snapshot_id,
            kind=NodeKind.FILE,
            name=file.relative_path.rsplit("/", 1)[-1],
            qualified_name=module_qname,
            file_path=file.relative_path,
            content_hash=file.content_hash,
        )

        nodes: list[Node] = [file_node]
        edges: list[Edge] = []

        parser = self._parser_for(file.language or "")
        if parser is None:
            return ParseResult(nodes=nodes, edges=edges)

        tree = parser.parse(file.content.encode("utf-8"))
        walker = self._walk_python if file.language == "python" else self._walk_typescript
        walker(
            tree.root_node, file, snapshot_id, module_qname, file_node.node_id, None, nodes, edges
        )

        return ParseResult(nodes=nodes, edges=edges)

    # -- Python ---------------------------------------------------------------

    def _walk_python(
        self,
        ts_node: TSNode,
        file: ScannedFile,
        snapshot_id: str,
        module_qname: str,
        file_node_id: str,
        parent: _SymbolRef | None,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        for child in ts_node.children:
            if child.type == "function_definition":
                self._emit_symbol(
                    child,
                    file,
                    snapshot_id,
                    module_qname,
                    file_node_id,
                    parent,
                    SymbolKind.METHOD if parent else SymbolKind.FUNCTION,
                    nodes,
                    edges,
                )
            elif child.type == "class_definition":
                symbol = self._emit_symbol(
                    child,
                    file,
                    snapshot_id,
                    module_qname,
                    file_node_id,
                    parent,
                    SymbolKind.CLASS,
                    nodes,
                    edges,
                )
                body = child.child_by_field_name("body")
                if symbol is not None and body is not None:
                    self._walk_python(
                        body, file, snapshot_id, module_qname, file_node_id, symbol, nodes, edges
                    )
            elif child.child_count > 0:
                self._walk_python(
                    child, file, snapshot_id, module_qname, file_node_id, parent, nodes, edges
                )

    # -- TypeScript / JavaScript ------------------------------------------------

    def _walk_typescript(
        self,
        ts_node: TSNode,
        file: ScannedFile,
        snapshot_id: str,
        module_qname: str,
        file_node_id: str,
        parent: _SymbolRef | None,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        for child in ts_node.children:
            if child.type == "function_declaration":
                self._emit_symbol(
                    child,
                    file,
                    snapshot_id,
                    module_qname,
                    file_node_id,
                    parent,
                    SymbolKind.FUNCTION,
                    nodes,
                    edges,
                )
            elif child.type == "class_declaration":
                symbol = self._emit_symbol(
                    child,
                    file,
                    snapshot_id,
                    module_qname,
                    file_node_id,
                    parent,
                    SymbolKind.CLASS,
                    nodes,
                    edges,
                )
                body = child.child_by_field_name("body")
                if symbol is not None and body is not None:
                    self._walk_typescript(
                        body, file, snapshot_id, module_qname, file_node_id, symbol, nodes, edges
                    )
            elif child.type == "method_definition" and parent is not None:
                self._emit_symbol(
                    child,
                    file,
                    snapshot_id,
                    module_qname,
                    file_node_id,
                    parent,
                    SymbolKind.METHOD,
                    nodes,
                    edges,
                )
            elif child.child_count > 0:
                self._walk_typescript(
                    child, file, snapshot_id, module_qname, file_node_id, parent, nodes, edges
                )

    # -- shared -------------------------------------------------------------------

    @staticmethod
    def _emit_symbol(
        ts_node: TSNode,
        file: ScannedFile,
        snapshot_id: str,
        module_qname: str,
        file_node_id: str,
        parent: _SymbolRef | None,
        kind: SymbolKind,
        nodes: list[Node],
        edges: list[Edge],
    ) -> _SymbolRef | None:
        name_node = ts_node.child_by_field_name("name")
        if name_node is None:
            return None
        name = file.content[name_node.start_byte : name_node.end_byte]
        qualified_name = f"{parent.qualified_name}.{name}" if parent else f"{module_qname}.{name}"
        node_id = stable_id(snapshot_id, "SYMBOL", qualified_name)

        nodes.append(
            Node(
                node_id=node_id,
                snapshot_id=snapshot_id,
                kind=NodeKind.SYMBOL,
                name=name,
                qualified_name=qualified_name,
                file_path=file.relative_path,
                start_line=ts_node.start_point[0] + 1,
                end_line=ts_node.end_point[0] + 1,
                content_hash=stable_id(file.content[ts_node.start_byte : ts_node.end_byte]),
                properties={"symbol_kind": kind.value},
            )
        )
        container_id = parent.node_id if parent else file_node_id
        edges.append(
            Edge(
                edge_id=stable_id(snapshot_id, "CONTAINS", container_id, node_id),
                snapshot_id=snapshot_id,
                src_node_id=container_id,
                dst_node_id=node_id,
                edge_type=EdgeType.CONTAINS,
            )
        )
        return _SymbolRef(qualified_name=qualified_name, node_id=node_id)
