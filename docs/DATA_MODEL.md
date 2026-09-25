# RepoFlare — Data Model

Domain entities live in `core/src/repoflare_core/domain/` as typed, immutable dataclasses.
Every entity has: a stable identifier, a snapshot association, a source location where
applicable, and a content/semantic hash where useful for change detection.

## Entities

| Entity | Stable ID | Key fields | Notes |
|---|---|---|---|
| `Repository` | `repository_id` (content hash of root path) | `root_path`, `name`, `created_at` | One per analyzed repo. |
| `Snapshot` | `snapshot_id` (uuid) | `repository_id`, `git_commit_sha`, `created_at`, `is_current` | Immutable point-in-time index. New snapshot per `analyze` run. |
| `File` | `file_id` (hash of snapshot_id + path) | `snapshot_id`, `path`, `language`, `content_hash`, `size`, `last_modified` | `content_hash` drives incremental re-parse skip. |
| `Symbol` | `symbol_id` (hash of snapshot_id + qualified_name) | `snapshot_id`, `kind` (FUNCTION/CLASS/METHOD/VARIABLE/INTERFACE), `name`, `qualified_name`, `file_id`, `start_line`, `end_line`, `signature_hash` | Unified table across function/class/method — see `docs/GRAPH_MODEL.md` for why. |
| `APIEndpoint` | `endpoint_id` | `snapshot_id`, `method`, `route`, `symbol_id` | Detected from framework-specific route decorators/annotations. |
| `Test` | `test_id` | `snapshot_id`, `name`, `file_id`, `framework` | Feeds `VerificationService` test-candidate selection. |
| `ConfigItem` | `config_id` | `snapshot_id`, `key`, `file_id` | Config keys referenced by code (env vars, settings). |
| `ExternalService` | `service_id` | `snapshot_id`, `name`, `kind` | Detected external integrations (DB, HTTP client targets). |
| `ChangeSet` | `change_set_id` | `snapshot_from_id`, `snapshot_to_id`, `changed_files` (JSON) | Produced by `ChangeDetector` from a git diff. |
| `ImpactResult` | `impact_id` | `change_set_id`, `category` (DIRECT/INDIRECT/RELATED/POSSIBLE), `affected_node_ids`, `provenance` | `provenance` records whether a result came from static traversal, test evidence, or AI inference. |
| `AnalysisJob` | `job_id` | `kind`, `status`, `started_at`, `finished_at`, `error` | Tracks long-running analyze/verify runs. |
| `VerificationResult` | `verification_id` | `job_id`, `tests_run`, `tests_passed`, `summary` | Output of `VerificationService`. |
| `AIContextPackage` | `context_id` | `change_set_id`, `snippets`, `graph_paths`, `direct_dependents`, `relevant_tests` | The bounded payload sent to `BobProvider` — never the whole repo (see `CLAUDE_CODE_MASTER_PROMPT.md` §10). |

## Access patterns → structures

| Query | Structure used |
|---|---|
| Symbol lookup by qualified name | Hash index on `nodes.qualified_name` (DuckDB) |
| File lookup by path | Hash index on `nodes.file_path` |
| Direct dependents of a symbol (reverse dependency) | Indexed reverse-adjacency lookup on `edges.dst_node_id` |
| k-hop impact traversal | Bounded `WITH RECURSIVE` CTE over `edges`, depth-limited |
| Changed-file detection | Content-hash comparison between snapshots, not full re-diff |
| Analysis result reuse | `analysis_cache` keyed by `repository_id + snapshot_id + relevant_node_hashes + question_hash` |
| Deduplication (e.g. affected-node sets) | Set semantics via `SELECT DISTINCT` / application-level sets |

See `docs/GRAPH_MODEL.md` for the concrete DuckDB schema implementing this table.
