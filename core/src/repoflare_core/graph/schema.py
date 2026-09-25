"""DDL for the graph store. Mirrors docs/GRAPH_MODEL.md exactly — that file is the
human-readable source of truth; this module is what actually runs."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS repositories (
    repository_id   TEXT PRIMARY KEY,
    root_path       TEXT NOT NULL,
    name            TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id     TEXT PRIMARY KEY,
    repository_id   TEXT NOT NULL REFERENCES repositories(repository_id),
    git_commit_sha  TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT current_timestamp,
    is_current      BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS nodes (
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

CREATE INDEX IF NOT EXISTS idx_nodes_snapshot_kind ON nodes(snapshot_id, kind);
CREATE INDEX IF NOT EXISTS idx_nodes_snapshot_path ON nodes(snapshot_id, file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_snapshot_qname ON nodes(snapshot_id, qualified_name);

CREATE TABLE IF NOT EXISTS edges (
    edge_id         TEXT PRIMARY KEY,
    snapshot_id     TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    src_node_id     TEXT NOT NULL REFERENCES nodes(node_id),
    dst_node_id     TEXT NOT NULL REFERENCES nodes(node_id),
    edge_type       TEXT NOT NULL,
    properties      JSON,
    created_at      TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(snapshot_id, src_node_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(snapshot_id, dst_node_id, edge_type);

CREATE TABLE IF NOT EXISTS change_sets (
    change_set_id     TEXT PRIMARY KEY,
    snapshot_from_id  TEXT REFERENCES snapshots(snapshot_id),
    snapshot_to_id    TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    changed_files     JSON NOT NULL,
    created_at        TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS analysis_cache (
    cache_key   TEXT PRIMARY KEY,
    result      JSON NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT current_timestamp,
    expires_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_jobs (
    job_id       TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    status       TEXT NOT NULL,
    started_at   TIMESTAMP NOT NULL DEFAULT current_timestamp,
    finished_at  TIMESTAMP,
    error        TEXT
);
"""
