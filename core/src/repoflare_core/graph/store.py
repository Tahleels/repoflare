"""GraphStore: persistence (create/read/write) for repositories, snapshots, nodes, and edges.

Read-side traversal (reverse dependents, k-hop impact) lives in graph/traversal.py — kept
separate from this module so persistence and query concerns don't tangle (single
responsibility: this file answers "how do I store a graph," traversal.py answers "how do I
ask questions about it").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from repoflare_core.domain.entities import Edge, Node, Repository, Snapshot
from repoflare_core.graph.schema import SCHEMA_SQL


def _dump_properties(properties: dict[str, Any]) -> str:
    return json.dumps(properties)


def _load_properties(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    loaded: dict[str, Any] = json.loads(raw)
    return loaded


class GraphStore:
    """Owns a single DuckDB connection to one repository's `.repoflare/graph.duckdb` file.

    Not thread-safe by design — DuckDB's embedded model assumes single-writer discipline
    (see docs/ARCHITECTURE.md §6). Callers coordinate access at the process boundary.
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        self._conn.execute(SCHEMA_SQL)

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._conn.close()

    def __enter__(self) -> GraphStore:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # -- repositories ---------------------------------------------------

    def upsert_repository(self, repository: Repository) -> None:
        """Insert or update a repository record (root_path and name are mutable)."""
        self._conn.execute(
            """
            INSERT INTO repositories (repository_id, root_path, name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (repository_id) DO UPDATE SET
                root_path = excluded.root_path,
                name = excluded.name
            """,
            [
                repository.repository_id,
                repository.root_path,
                repository.name,
                repository.created_at,
            ],
        )

    # -- snapshots --------------------------------------------------------

    def create_snapshot(self, snapshot: Snapshot) -> None:
        """Persist a new snapshot and mark it as the current one, retiring all prior snapshots."""
        self._conn.execute(
            "UPDATE snapshots SET is_current = false WHERE repository_id = ?",
            [snapshot.repository_id],
        )
        self._conn.execute(
            """
            INSERT INTO snapshots
                (snapshot_id, repository_id, git_commit_sha, created_at, is_current)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                snapshot.snapshot_id,
                snapshot.repository_id,
                snapshot.git_commit_sha,
                snapshot.created_at,
                snapshot.is_current,
            ],
        )

    def current_snapshot_id(self, repository_id: str) -> str | None:
        """Return the snapshot_id currently marked is_current for this repository, or None."""
        row = self._conn.execute(
            "SELECT snapshot_id FROM snapshots WHERE repository_id = ? AND is_current = true",
            [repository_id],
        ).fetchone()
        return row[0] if row else None

    # -- nodes --------------------------------------------------------------

    def insert_nodes(self, nodes: list[Node]) -> None:
        """Bulk-insert nodes, silently ignoring any that already exist (same node_id)."""
        if not nodes:
            return
        self._conn.executemany(
            """
            INSERT INTO nodes
                (node_id, snapshot_id, kind, name, qualified_name, file_path,
                 start_line, end_line, content_hash, properties)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (node_id) DO NOTHING
            """,
            [
                [
                    n.node_id,
                    n.snapshot_id,
                    n.kind.value,
                    n.name,
                    n.qualified_name,
                    n.file_path,
                    n.start_line,
                    n.end_line,
                    n.content_hash,
                    _dump_properties(n.properties),
                ]
                for n in nodes
            ],
        )

    def get_node(self, node_id: str) -> Node | None:
        """Fetch a single node by id, or None if it does not exist."""
        row = self._conn.execute(
            """
            SELECT node_id, snapshot_id, kind, name, qualified_name, file_path,
                   start_line, end_line, content_hash, properties
            FROM nodes WHERE node_id = ?
            """,
            [node_id],
        ).fetchone()
        return self._row_to_node(row) if row else None

    def find_by_qualified_name(self, snapshot_id: str, qualified_name: str) -> Node | None:
        """Return the node with the given qualified_name in this snapshot, or None."""
        row = self._conn.execute(
            """
            SELECT node_id, snapshot_id, kind, name, qualified_name, file_path,
                   start_line, end_line, content_hash, properties
            FROM nodes WHERE snapshot_id = ? AND qualified_name = ?
            """,
            [snapshot_id, qualified_name],
        ).fetchone()
        return self._row_to_node(row) if row else None

    def nodes_for_file(self, snapshot_id: str, file_path: str) -> list[Node]:
        """Return all nodes (FILE + SYMBOLs) whose file_path matches in this snapshot."""
        rows = self._conn.execute(
            """
            SELECT node_id, snapshot_id, kind, name, qualified_name, file_path,
                   start_line, end_line, content_hash, properties
            FROM nodes WHERE snapshot_id = ? AND file_path = ?
            """,
            [snapshot_id, file_path],
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    @staticmethod
    def _row_to_node(row: tuple[Any, ...]) -> Node:
        from repoflare_core.domain.entities import NodeKind

        return Node(
            node_id=row[0],
            snapshot_id=row[1],
            kind=NodeKind(row[2]),
            name=row[3],
            qualified_name=row[4],
            file_path=row[5],
            start_line=row[6],
            end_line=row[7],
            content_hash=row[8],
            properties=_load_properties(row[9]),
        )

    # -- edges --------------------------------------------------------------

    def insert_edges(self, edges: list[Edge]) -> None:
        """Bulk-insert edges, silently ignoring any that already exist (same edge_id)."""
        if not edges:
            return
        self._conn.executemany(
            """
            INSERT INTO edges
                (edge_id, snapshot_id, src_node_id, dst_node_id, edge_type, properties)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (edge_id) DO NOTHING
            """,
            [
                [
                    e.edge_id,
                    e.snapshot_id,
                    e.src_node_id,
                    e.dst_node_id,
                    e.edge_type.value,
                    _dump_properties(e.properties),
                ]
                for e in edges
            ],
        )

    def all_nodes(self, snapshot_id: str, limit: int) -> list[Node]:
        """Return up to `limit` nodes ordered by degree (fan-in + fan-out, highest first).

        Degree ordering ensures a truncated view still shows the most-connected, most-
        interesting nodes rather than an arbitrary slice — important because the graph view
        caps at 150 nodes by default on large repositories.
        """
        rows = self._conn.execute(
            """
            SELECT n.node_id, n.snapshot_id, n.kind, n.name, n.qualified_name, n.file_path,
                   n.start_line, n.end_line, n.content_hash, n.properties
            FROM nodes n
            LEFT JOIN (
                SELECT node_id, count(*) AS degree FROM (
                    SELECT src_node_id AS node_id FROM edges WHERE snapshot_id = ?
                    UNION ALL
                    SELECT dst_node_id AS node_id FROM edges WHERE snapshot_id = ?
                ) combined GROUP BY node_id
            ) d ON n.node_id = d.node_id
            WHERE n.snapshot_id = ?
            ORDER BY COALESCE(d.degree, 0) DESC
            LIMIT ?
            """,
            [snapshot_id, snapshot_id, snapshot_id, limit],
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def edges_among(self, snapshot_id: str, node_ids: list[str]) -> list[Edge]:
        """Return edges where both src_node_id and dst_node_id are in node_ids.

        Only edges with both endpoints in the given set are returned, so callers can safely
        render the edges without needing to check for dangling references.
        """
        if not node_ids:
            return []
        # Build a VALUES table inline — no temp table needed, and DuckDB handles the IN
        # list efficiently on typical graph sizes (≤150 node ids after the cap applied in
        # all_nodes).
        placeholders = ", ".join("?" for _ in node_ids)
        rows = self._conn.execute(
            f"""
            SELECT edge_id, snapshot_id, src_node_id, dst_node_id, edge_type, properties
            FROM edges
            WHERE snapshot_id = ?
              AND src_node_id IN ({placeholders})
              AND dst_node_id IN ({placeholders})
            """,
            [snapshot_id, *node_ids, *node_ids],
        ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    @staticmethod
    def _row_to_edge(row: tuple[Any, ...]) -> Edge:
        from repoflare_core.domain.entities import EdgeType

        return Edge(
            edge_id=row[0],
            snapshot_id=row[1],
            src_node_id=row[2],
            dst_node_id=row[3],
            edge_type=EdgeType(row[4]),
            properties=_load_properties(row[5]),
        )

    def raw_connection(self) -> duckdb.DuckDBPyConnection:
        """Escape hatch for graph/traversal.py, which needs read-only ad-hoc queries
        (recursive CTEs) that don't warrant a dedicated method on this class."""
        return self._conn
