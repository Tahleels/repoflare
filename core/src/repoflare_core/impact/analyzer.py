"""ImpactAnalyzer: turns a ChangeSet into categorized ImpactResults.

Maps GraphTraversalService.reverse_impact's depth to ImpactCategory:
  depth 1 -> DIRECT, depth 2 -> INDIRECT, depth 3 -> RELATED, depth >= 4 -> POSSIBLE.
This refines docs/GRAPH_MODEL.md's "RELATED/POSSIBLE = 3+" into two concrete buckets so all
four categories in domain/entities.py::ImpactCategory are actually reachable.

Scope note: a changed FILE is resolved to "the symbols GraphStore.nodes_for_file says this
file directly contains" — not a line-level diff of which specific symbols changed within
that file. A precise line-range-aware version is a follow-on refinement (see AGENTS.md),
not required for a first correct, useful ImpactAnalyzer.
"""

from __future__ import annotations

from repoflare_core.domain.entities import ChangeSet, ImpactCategory, ImpactResult
from repoflare_core.domain.ids import stable_id
from repoflare_core.graph.store import GraphStore
from repoflare_core.graph.traversal import DEFAULT_MAX_DEPTH, GraphTraversalService

_DEPTH_TO_CATEGORY: dict[int, ImpactCategory] = {
    1: ImpactCategory.DIRECT,
    2: ImpactCategory.INDIRECT,
    3: ImpactCategory.RELATED,
}
_CATEGORY_BEYOND_MAPPED_DEPTH = ImpactCategory.POSSIBLE


def _category_for_depth(depth: int) -> ImpactCategory:
    return _DEPTH_TO_CATEGORY.get(depth, _CATEGORY_BEYOND_MAPPED_DEPTH)


class ImpactAnalyzer:
    def __init__(self, store: GraphStore, traversal: GraphTraversalService) -> None:
        self._store = store
        self._traversal = traversal

    def analyze(
        self, change_set: ChangeSet, max_depth: int = DEFAULT_MAX_DEPTH
    ) -> list[ImpactResult]:
        """Return one ImpactResult per non-empty category, each listing the affected node
        ids at that category's depth. Nodes that were themselves directly changed are
        excluded from the results — this reports what the change *affects*, not the change
        itself."""
        changed_node_ids = self._changed_node_ids(change_set)
        min_depth_by_affected_id = self._min_depths(
            change_set.snapshot_to_id, changed_node_ids, max_depth
        )

        by_category: dict[ImpactCategory, list[str]] = {category: [] for category in ImpactCategory}
        for node_id, depth in min_depth_by_affected_id.items():
            by_category[_category_for_depth(depth)].append(node_id)

        return [
            ImpactResult(
                impact_id=stable_id(change_set.change_set_id, category.value),
                change_set_id=change_set.change_set_id,
                category=category,
                affected_node_ids=sorted(node_ids),
                provenance="graph_traversal",
            )
            for category, node_ids in by_category.items()
            if node_ids
        ]

    def _changed_node_ids(self, change_set: ChangeSet) -> set[str]:
        return {
            node.node_id
            for file_path in change_set.changed_files
            for node in self._store.nodes_for_file(change_set.snapshot_to_id, file_path)
        }

    def _min_depths(
        self, snapshot_id: str, changed_node_ids: set[str], max_depth: int
    ) -> dict[str, int]:
        min_depth_by_affected_id: dict[str, int] = {}
        for changed_node_id in changed_node_ids:
            for hop in self._traversal.reverse_impact(snapshot_id, changed_node_id, max_depth):
                if hop.node_id in changed_node_ids:
                    continue
                current = min_depth_by_affected_id.get(hop.node_id)
                if current is None or hop.min_depth < current:
                    min_depth_by_affected_id[hop.node_id] = hop.min_depth
        return min_depth_by_affected_id
