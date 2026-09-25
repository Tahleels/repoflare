"""TestLinkResolver: emits TESTED_BY edges connecting a NodeKind.TEST node to the
NodeKind.SYMBOL node(s) it appears to test, via a simple-name heuristic
(`test_foo` -> any symbol named `foo`, anywhere in the snapshot — cross-file on purpose,
since tests conventionally live in a different file/directory than what they test).

Scope, deliberately bounded: this is a naming-convention heuristic, not real coverage
analysis — it does not inspect the test body to see what's actually called or asserted. A
test named `test_foo` that doesn't actually exercise a symbol named `foo` still produces an
edge; a test that exercises `foo` under a different name doesn't. See AGENTS.md "Next up"
for real coverage-based linking as a follow-up, not something to half-build here.

Edge direction: src_node_id = test, dst_node_id = symbol under test. This matches the
actor-first convention CALLS/IMPORTS/CONTAINS already use in this codebase (src performs the
action the edge name describes) — read the edge as "[dst] is TESTED_BY [src]."
"""

from __future__ import annotations

from repoflare_core.domain.entities import Edge, EdgeType, Node, NodeKind
from repoflare_core.domain.ids import stable_id

_TEST_NAME_PREFIX = "test_"


class TestLinkResolver:
    def resolve(self, snapshot_id: str, nodes: list[Node]) -> list[Edge]:
        symbol_ids_by_name: dict[str, list[str]] = {}
        for node in nodes:
            if node.kind == NodeKind.SYMBOL:
                symbol_ids_by_name.setdefault(node.name, []).append(node.node_id)

        edges: list[Edge] = []
        for node in nodes:
            if node.kind != NodeKind.TEST or not node.name.startswith(_TEST_NAME_PREFIX):
                continue
            target_name = node.name[len(_TEST_NAME_PREFIX) :]
            for symbol_id in symbol_ids_by_name.get(target_name, []):
                edges.append(
                    Edge(
                        edge_id=stable_id(snapshot_id, "TESTED_BY", node.node_id, symbol_id),
                        snapshot_id=snapshot_id,
                        src_node_id=node.node_id,
                        dst_node_id=symbol_id,
                        edge_type=EdgeType.TESTED_BY,
                    )
                )
        return edges
