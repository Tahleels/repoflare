"""CallImportResolver: a second pass that resolves CALLS and IMPORTS edges, run after
ParserAdapter has produced structural (CONTAINS) nodes/edges for every file in a snapshot.

Runs as a separate pass — rather than folding into ParserAdapter's single-file walk —
because resolving an import or a call target needs a snapshot-wide lookup (does a module
with this qualified name exist? does a function with this qualified name exist?) that a
single file's own AST can't answer on its own.

Scope, deliberately bounded (see AGENTS.md "Next up" for the rest):
- IMPORTS edges: File -> File, resolved by matching an imported module path against another
  file's module-qualified-name in the same snapshot. Aliased imports (`import x as y`) and
  wildcard imports (`from x import *`) are not resolved.
- CALLS edges: Symbol -> Symbol, only for calls to a plain identifier (`foo()`, not
  `self.foo()` or `obj.foo()`) that resolves to a MODULE-LEVEL function in the same module.
  Cross-file calls and attribute/method calls are not resolved here.
"""

from __future__ import annotations

import tree_sitter_python as tspython
from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode

from repoflare_core.domain.entities import Edge, EdgeType
from repoflare_core.domain.ids import stable_id
from repoflare_core.scanning.scanner import ScannedFile

_PY_LANGUAGE = Language(tspython.language())


class CallImportResolver:
    """Python-only for now, mirroring ParserAdapter's current language coverage."""

    def __init__(self) -> None:
        self._parser = Parser(_PY_LANGUAGE)

    def resolve(
        self,
        file: ScannedFile,
        snapshot_id: str,
        module_qname: str,
        node_id_by_qualified_name: dict[str, str],
        file_node_id_by_module_qname: dict[str, str],
    ) -> list[Edge]:
        if file.language != "python":
            return []
        tree = self._parser.parse(file.content.encode("utf-8"))
        edges: list[Edge] = []
        self._walk(
            tree.root_node,
            file,
            snapshot_id,
            module_qname,
            node_id_by_qualified_name,
            file_node_id_by_module_qname,
            edges,
        )
        return edges

    def _walk(
        self,
        ts_node: TSNode,
        file: ScannedFile,
        snapshot_id: str,
        module_qname: str,
        node_id_by_qualified_name: dict[str, str],
        file_node_id_by_module_qname: dict[str, str],
        edges: list[Edge],
    ) -> None:
        if ts_node.type == "import_statement":
            for child in ts_node.children:
                if child.type == "dotted_name":
                    self._emit_import(
                        child, file, snapshot_id, module_qname, file_node_id_by_module_qname, edges
                    )
        elif ts_node.type == "import_from_statement":
            module_node = ts_node.child_by_field_name("module_name")
            if module_node is not None:
                self._emit_import(
                    module_node,
                    file,
                    snapshot_id,
                    module_qname,
                    file_node_id_by_module_qname,
                    edges,
                )
        elif ts_node.type == "call":
            self._emit_call(
                ts_node, file, snapshot_id, module_qname, node_id_by_qualified_name, edges
            )

        for child in ts_node.children:
            self._walk(
                child,
                file,
                snapshot_id,
                module_qname,
                node_id_by_qualified_name,
                file_node_id_by_module_qname,
                edges,
            )

    @staticmethod
    def _emit_import(
        dotted_name_node: TSNode,
        file: ScannedFile,
        snapshot_id: str,
        module_qname: str,
        file_node_id_by_module_qname: dict[str, str],
        edges: list[Edge],
    ) -> None:
        module_path = file.content[dotted_name_node.start_byte : dotted_name_node.end_byte]
        target_file_id = file_node_id_by_module_qname.get(module_path)
        src_file_id = file_node_id_by_module_qname.get(module_qname)
        if target_file_id is None or src_file_id is None or target_file_id == src_file_id:
            return
        edges.append(
            Edge(
                edge_id=stable_id(snapshot_id, "IMPORTS", src_file_id, target_file_id),
                snapshot_id=snapshot_id,
                src_node_id=src_file_id,
                dst_node_id=target_file_id,
                edge_type=EdgeType.IMPORTS,
            )
        )

    def _emit_call(
        self,
        call_node: TSNode,
        file: ScannedFile,
        snapshot_id: str,
        module_qname: str,
        node_id_by_qualified_name: dict[str, str],
        edges: list[Edge],
    ) -> None:
        function_node = call_node.child_by_field_name("function")
        if function_node is None or function_node.type != "identifier":
            return
        callee_name = file.content[function_node.start_byte : function_node.end_byte]
        caller_qname = self._enclosing_qualified_name(call_node, file, module_qname)
        if caller_qname is None:
            return
        caller_id = node_id_by_qualified_name.get(caller_qname)
        target_id = node_id_by_qualified_name.get(f"{module_qname}.{callee_name}")
        if caller_id is None or target_id is None or caller_id == target_id:
            return
        edges.append(
            Edge(
                edge_id=stable_id(
                    snapshot_id, "CALLS", caller_id, target_id, str(call_node.start_byte)
                ),
                snapshot_id=snapshot_id,
                src_node_id=caller_id,
                dst_node_id=target_id,
                edge_type=EdgeType.CALLS,
            )
        )

    @staticmethod
    def _enclosing_qualified_name(
        ts_node: TSNode, file: ScannedFile, module_qname: str
    ) -> str | None:
        names: list[str] = []
        current = ts_node.parent
        while current is not None:
            if current.type in ("function_definition", "class_definition"):
                name_node = current.child_by_field_name("name")
                if name_node is not None:
                    names.append(file.content[name_node.start_byte : name_node.end_byte])
            current = current.parent
        if not names:
            return None
        names.reverse()
        return f"{module_qname}.{'.'.join(names)}"
