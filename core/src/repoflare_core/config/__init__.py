"""Repository-local configuration: where RepoFlare's state lives for a given repo root.

Kept as its own tiny module (rather than a constant duplicated in cli/ and rpc/) because
both the CLI and the future RPC server need to agree on the same path.
"""

from pathlib import Path

REPOFLARE_DIR_NAME = ".repoflare"
GRAPH_DB_FILENAME = "graph.duckdb"


def repoflare_dir(root: Path) -> Path:
    """Return the `.repoflare` directory path for the given repository root."""
    return root / REPOFLARE_DIR_NAME


def graph_db_path(root: Path) -> Path:
    """Return the path to the DuckDB graph database for the given repository root."""
    return repoflare_dir(root) / GRAPH_DB_FILENAME
