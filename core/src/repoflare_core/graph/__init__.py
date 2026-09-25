"""DuckDB-backed graph persistence and traversal. See docs/GRAPH_MODEL.md for the schema
and docs/DECISIONS.md ADR-002 for why DuckDB was chosen over a dedicated graph database."""

from repoflare_core.graph.store import GraphStore
from repoflare_core.graph.traversal import GraphTraversalService

__all__ = ["GraphStore", "GraphTraversalService"]
