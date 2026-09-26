"""CacheProvider: content-hash-keyed result cache backed by the analysis_cache DuckDB table.

Not functools.lru_cache — that evicts by LRU count and has no content-hash invalidation
mechanism. Here the key is derived from the stable ids of the inputs (change_set_id,
context_id, etc.) so a cached entry is valid for as long as those inputs don't change;
expiry is time-based when the caller supplies a TTL, otherwise entries live indefinitely.

Callers hold the GraphStore open while doing cache lookups — CacheProvider takes the raw
DuckDB connection to avoid opening a second connection to the same file (DuckDB's embedded
model: one writer at a time).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb


class CacheProvider:
    """Read/write cache for analysis results in the analysis_cache DuckDB table.

    Args:
        conn: An open DuckDB connection (from GraphStore.raw_connection()). The caller
              is responsible for keeping the connection alive for the duration of any
              get/set calls and for closing it when done.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def get(self, cache_key: str) -> str | None:
        """Return the cached result string for cache_key if present and not expired.

        Returns None when the key is absent or has passed its expires_at timestamp.
        Expired entries are pruned on access so the table doesn't grow unboundedly.
        """
        row = self._conn.execute(
            """
            SELECT result, expires_at
            FROM analysis_cache
            WHERE cache_key = ?
            """,
            [cache_key],
        ).fetchone()

        if row is None:
            return None

        raw_result, expires_at = row

        if expires_at is not None and _to_utc(expires_at) <= datetime.now(UTC):
            self._conn.execute("DELETE FROM analysis_cache WHERE cache_key = ?", [cache_key])
            return None

        # DuckDB may return JSON columns as str or dict depending on version; normalise.
        if isinstance(raw_result, dict):
            return json.dumps(raw_result)
        return str(raw_result)

    def set(
        self,
        cache_key: str,
        result: dict[str, Any],
        ttl: timedelta | None = None,
    ) -> None:
        """Store result under cache_key, replacing any existing entry.

        Args:
            cache_key: Opaque string key; callers derive this via stable_id().
            result:    The dict to store; JSON-serialised before writing.
            ttl:       Optional time-to-live. When None the entry never expires.
        """
        expires_at = datetime.now(UTC) + ttl if ttl is not None else None
        self._conn.execute(
            """
            INSERT INTO analysis_cache (cache_key, result, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (cache_key) DO UPDATE SET
                result     = excluded.result,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
            """,
            [cache_key, json.dumps(result), datetime.now(UTC), expires_at],
        )


def _to_utc(value: datetime) -> datetime:
    """Normalise a datetime that may or may not carry timezone info to UTC-aware."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
