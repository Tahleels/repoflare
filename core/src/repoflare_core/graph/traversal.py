"""Read-side graph queries: reverse dependents and bounded k-hop impact traversal.

Kept separate from GraphStore (persistence) per docs/ARCHITECTURE.md's module boundary
table — this class only reads.
"""

from __future__ import annotations

from dataclasses import dataclass

from repoflare_core.domain.entities import EdgeType
from repoflare_core.graph.store import GraphStore

DEFAULT_MAX_DEPTH = 5
"""Bounded traversal depth — see docs/GRAPH_MODEL.md 'Bounded k-hop impact traversal'.
Unbounded traversal on a large repository graph is exactly the kind of full-scan the
project brief calls out to avoid (docs/CLAUDE_CODE_MASTER_PROMPT.md §15)."""


@dataclass(frozen=True, slots=True)
class ImpactHop:
    node_id: str
    min_depth: int


class GraphTraversalService:
    def __init__(self, store: GraphStore) -> None:
        self._store = store

    def direct_dependents(
        self, snapshot_id: str, node_id: str, edge_type: EdgeType | None = None
    ) -> list[str]:
        """Return node ids with a direct (1-hop) edge pointing at node_id.

        When edge_type is given, only edges of that type are considered. Uses the
        idx_edges_dst index, not a full scan.
        """
        conn = self._store.raw_connection()
        if edge_type is None:
            rows = conn.execute(
                "SELECT DISTINCT src_node_id FROM edges WHERE snapshot_id = ? AND dst_node_id = ?",
                [snapshot_id, node_id],
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT DISTINCT src_node_id FROM edges
                WHERE snapshot_id = ? AND dst_node_id = ? AND edge_type = ?
                """,
                [snapshot_id, node_id, edge_type.value],
            ).fetchall()
        return [r[0] for r in rows]

    def shortest_reverse_path(
        self,
        snapshot_id: str,
        from_node_id: str,
        to_node_id: str,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> list[str] | None:
        """Reconstruct one shortest reverse-dependency path from `from_node_id` back to
        `to_node_id` (inclusive of both ends), or None if unreachable within max_depth.

        BFS in Python rather than a single recursive-CTE query — reverse_impact already
        answers "is X reachable and how far," which is what ImpactAnalyzer needs; this
        method exists separately for retrieval/ContextRetriever, which needs the actual
        path (for AIContextPackage.graph_paths), not just the distance. Each BFS layer is
        still one indexed query via direct_dependents, so it stays bounded and cheap for
        the max_depth this product uses (see DEFAULT_MAX_DEPTH).
        """
        if from_node_id == to_node_id:
            return [from_node_id]

        predecessor: dict[str, str] = {}
        frontier = [from_node_id]
        visited = {from_node_id}
        for _depth in range(max_depth):
            next_frontier: list[str] = []
            for node_id in frontier:
                for dependent in self.direct_dependents(snapshot_id, node_id):
                    if dependent in visited:
                        continue
                    visited.add(dependent)
                    predecessor[dependent] = node_id
                    if dependent == to_node_id:
                        return self._reconstruct_path(predecessor, from_node_id, to_node_id)
                    next_frontier.append(dependent)
            frontier = next_frontier
            if not frontier:
                break
        return None

    @staticmethod
    def _reconstruct_path(
        predecessor: dict[str, str], from_node_id: str, to_node_id: str
    ) -> list[str]:
        path = [to_node_id]
        while path[-1] != from_node_id:
            path.append(predecessor[path[-1]])
        path.reverse()
        return path

    def reverse_impact(
        self, snapshot_id: str, node_id: str, max_depth: int = DEFAULT_MAX_DEPTH
    ) -> list[ImpactHop]:
        """Bounded reverse traversal: everything that (transitively, up to max_depth hops)
        depends on `node_id`. depth=1 is a direct dependent, depth>=2 is indirect/related —
        see docs/GRAPH_MODEL.md for how ImpactAnalyzer maps depth to ImpactCategory."""
        conn = self._store.raw_connection()
        rows = conn.execute(
            """
            WITH RECURSIVE impact(node_id, depth) AS (
                SELECT ?::TEXT AS node_id, 0 AS depth
                UNION ALL
                SELECT e.src_node_id, impact.depth + 1
                FROM edges e
                JOIN impact ON e.dst_node_id = impact.node_id
                WHERE e.snapshot_id = ? AND impact.depth < ?
            )
            SELECT node_id, MIN(depth) AS min_depth
            FROM impact
            WHERE depth > 0
            GROUP BY node_id
            ORDER BY min_depth
            """,
            [node_id, snapshot_id, max_depth],
        ).fetchall()
        return [ImpactHop(node_id=r[0], min_depth=r[1]) for r in rows]
