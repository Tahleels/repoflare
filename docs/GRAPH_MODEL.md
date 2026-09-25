# RepoFlare — Graph Model

Backed by DuckDB (see `docs/DECISIONS.md` ADR-002). One file per repository:
`.repoflare/graph.duckdb`.

## Why a unified `nodes` / `edges` pair, not one table per entity type

Node kinds (File, Symbol-as-Function/Class/Method, APIEndpoint, Test, ConfigItem,
ExternalService) share the same shape of query: "find this node by id/qualified name,"
"find what points to it," "find what it points to." Splitting them into separate physical
tables would force every traversal query to either union across tables or duplicate
edge-table pairs per (source-kind, target-kind) combination — the exact schema explosion
that ruled out a strict per-type property-graph engine. A single `nodes` table with a `kind`
discriminator column, plus a single `edges` table with an `edge_type` discriminator, keeps
every traversal query (forward, reverse, k-hop, path tracing) uniform regardless of which
concrete entity types sit at each end.

## Schema

```sql
CREATE TABLE repositories (
    repository_id   TEXT PRIMARY KEY,
    root_path       TEXT NOT NULL,
    name            TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE snapshots (
    snapshot_id     TEXT PRIMARY KEY,
    repository_id   TEXT NOT NULL REFERENCES repositories(repository_id),
    git_commit_sha  TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT current_timestamp,
    is_current      BOOLEAN NOT NULL DEFAULT true
);

-- Unified entity table. `kind` discriminates FILE / MODULE / SYMBOL / API_ENDPOINT /
-- TEST / CONFIG_ITEM / EXTERNAL_SERVICE. Symbol-specific fields (signature_hash, etc.)
-- are carried in `properties` (JSON) to avoid a wide sparse table.
CREATE TABLE nodes (
    node_id         TEXT PRIMARY KEY,
    snapshot_id     TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    kind            TEXT NOT NULL,
    name            TEXT NOT NULL,
    qualified_name  TEXT,
    file_path       TEXT,
    start_line      INTEGER,
    end_line        INTEGER,
    content_hash    TEXT,
    properties      JSON,
    created_at      TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE INDEX idx_nodes_snapshot_kind ON nodes(snapshot_id, kind);
CREATE INDEX idx_nodes_snapshot_path ON nodes(snapshot_id, file_path);
CREATE INDEX idx_nodes_snapshot_qname ON nodes(snapshot_id, qualified_name);

-- Unified relationship table. `edge_type` discriminates IMPORTS / CALLS / USES /
-- INHERITS / IMPLEMENTS / EXPOSES / TESTED_BY / CONFIGURED_BY / CONNECTS_TO /
-- DEPENDS_ON / CONTAINS.
CREATE TABLE edges (
    edge_id         TEXT PRIMARY KEY,
    snapshot_id     TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    src_node_id     TEXT NOT NULL REFERENCES nodes(node_id),
    dst_node_id     TEXT NOT NULL REFERENCES nodes(node_id),
    edge_type       TEXT NOT NULL,
    properties      JSON,
    created_at      TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- Forward adjacency (what does this node depend on)
CREATE INDEX idx_edges_src ON edges(snapshot_id, src_node_id, edge_type);
-- Reverse adjacency (what depends on this node) — the index impact analysis relies on
CREATE INDEX idx_edges_dst ON edges(snapshot_id, dst_node_id, edge_type);

CREATE TABLE change_sets (
    change_set_id     TEXT PRIMARY KEY,
    snapshot_from_id  TEXT REFERENCES snapshots(snapshot_id),
    snapshot_to_id    TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    changed_files     JSON NOT NULL,
    created_at        TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE analysis_cache (
    cache_key   TEXT PRIMARY KEY,
    result      JSON NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT current_timestamp,
    expires_at  TIMESTAMP
);

CREATE TABLE analysis_jobs (
    job_id       TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    status       TEXT NOT NULL,
    started_at   TIMESTAMP NOT NULL DEFAULT current_timestamp,
    finished_at  TIMESTAMP,
    error        TEXT
);
```

## Traversal patterns

**Direct dependents (reverse adjacency, 1-hop):**

```sql
SELECT n.*
FROM edges e
JOIN nodes n ON n.node_id = e.src_node_id
WHERE e.snapshot_id = ? AND e.dst_node_id = ? AND e.edge_type = 'CALLS';
```

**Bounded k-hop impact traversal (reverse, depth-limited to avoid runaway scans):**

```sql
WITH RECURSIVE impact(node_id, depth) AS (
    SELECT ?::TEXT AS node_id, 0 AS depth
    UNION ALL
    SELECT e.src_node_id, impact.depth + 1
    FROM edges e
    JOIN impact ON e.dst_node_id = impact.node_id
    WHERE e.snapshot_id = ? AND impact.depth < ?  -- max_depth parameter
)
SELECT DISTINCT node_id, MIN(depth) AS min_depth
FROM impact
WHERE depth > 0
GROUP BY node_id
ORDER BY min_depth;
```

`min_depth` maps directly to the impact category: `depth = 1` → DIRECT, `depth = 2` →
INDIRECT, `depth >= 3` → RELATED/POSSIBLE (exact thresholds owned by `ImpactAnalyzer`, not
the storage layer).

## Incremental update

On re-analyze: nodes/edges are scoped by `snapshot_id`, so a new snapshot's rows never
mutate a prior snapshot's rows (append-only across snapshots — no rebuild of unaffected
history). Within a snapshot re-parse (same commit, local edit), only nodes whose
`content_hash` changed are re-inserted; their outgoing edges are deleted and re-derived,
incoming edges from unaffected nodes are untouched. This is the mechanism behind
`CLAUDE_CODE_MASTER_PROMPT.md` §8's "preserve unaffected knowledge, update only what
changed."
