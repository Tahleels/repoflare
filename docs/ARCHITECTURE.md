# RepoFlare — Architecture

## 1. System shape

```
                    ┌───────────────────────────┐      ┌───────────────────────────┐
                    │   VS Code Extension        │      │   CLI (repoflare)          │
                    │   (TypeScript, thin client) │      │   (Python, Typer)          │
                    └──────────────┬──────────────┘      └──────────────┬──────────────┘
                                   │ JSON-RPC over stdio                │ in-process
                                   │ (spawns core as subprocess)        │ calls
                                   └──────────────────┬──────────────────┘
                                                       ▼
                                       ┌───────────────────────────────┐
                                       │   RepoFlare Core (Python)      │
                                       │   repoflare_core package       │
                                       └───────────────┬─────────────────┘
                                                        │
        ┌───────────────┬───────────────┬──────────────┼───────────────┬───────────────┐
        ▼               ▼               ▼              ▼               ▼               ▼
   Scanning         Parsing          Graph          Change          Impact          AI (Bob
  (RepositoryScanner) (ParserAdapter) (GraphStore,   (ChangeDetector) (ImpactAnalyzer, adapter)
                       tree-sitter)   DuckDB)         git diff)       ContextRetriever) (BobProvider)
```

Both interfaces (CLI, extension) are clients of the same `repoflare_core` package — no
business logic is duplicated between them. The CLI imports the core directly; the extension
talks to a spawned core process over JSON-RPC, matching the LSP integration pattern (see
`docs/DECISIONS.md` ADR-001).

## 2. Module boundaries (`core/src/repoflare_core/`)

| Module | Responsibility | Depends on |
|---|---|---|
| `domain/` | Pure entities and value objects (Repository, Snapshot, File, Symbol, Edge, ChangeSet, ImpactResult, AIContextPackage). No I/O. | nothing |
| `scanning/` | Walks the repository filesystem, respects `.gitignore`, yields candidate files. | `domain` |
| `parsing/` | `ParserAdapter` — tree-sitter wrapper; extracts symbols/imports/calls from source text into domain entities. | `domain` |
| `graph/` | `GraphStore` — DuckDB-backed persistence and traversal (`GraphTraversalService`): forward/reverse adjacency, k-hop, path tracing. | `domain` |
| `change/` | `ChangeDetector` — git-diff-based changed-file/changed-symbol detection between snapshots. | `domain`, `graph` |
| `impact/` | `ImpactAnalyzer` — reverse-dependency traversal, categorizes results as DIRECT / INDIRECT / RELATED / POSSIBLE. | `graph`, `change` |
| `retrieval/` | `ContextRetriever` — assembles a targeted `AIContextPackage` from impact results (never the whole repo). | `impact`, `graph` |
| `ai/` | `BobProvider` interface + `GeminiProvider` / `OpenRouterProvider` implementations. Semantic reasoning only. | `domain` |
| `verification/` | `VerificationService` — test-candidate selection and verification reasoning. | `impact`, `ai` |
| `cache/` | `CacheProvider` — in-process LRU + persisted `analysis_cache` table (content-hash keyed). | `graph` |
| `cli/` | Typer commands: `init`, `analyze`, `impact`, `explain`, `verify`, `status`. | everything above |
| `rpc/` | JSON-RPC stdio server exposing the same operations to the VS Code extension. | everything above |
| `config/` | Configuration loading (`.repoflare/config.toml`, env vars). | nothing |

Dependency direction is strictly one-way: `cli`/`rpc` (interface layer) depend on the
application services (`impact`, `retrieval`, `verification`), which depend on the
infrastructure modules (`graph`, `ai`, `cache`), which depend on `domain`. `domain` depends
on nothing. This is the dependency-inversion boundary SOLID requires, applied concretely.

## 3. Canonical workflow

```
Initial scan → structured repository index → persistent graph (DuckDB)

Later change → git diff detection → changed symbols → local re-parse (affected units only)
             → graph diff (edge insert/remove) → reverse-dependency traversal
             → affected subgraph → targeted retrieval → AI (Bob adapter) reasoning
             → implementation → post-change graph update → targeted verification
```

The key optimization: **do structural work once, persist it, and reuse it.** AI reasons over
the relevant slice of the graph, never the whole repository. See
`CLAUDE_CODE_MASTER_PROMPT.md` §8–10 for the source requirement this implements.

## 4. Persistence

One DuckDB file per repository: `.repoflare/graph.duckdb`. Holds node/edge tables, snapshot
metadata, change sets, and the analysis cache — see `docs/GRAPH_MODEL.md` for schema. No
external services required to run RepoFlare locally (ADR-003).

## 5. MVP vs. production evolution

### MVP (this repo, current target)

- Single Python core process + DuckDB file, no server processes
- CLI + VS Code extension against the same core
- In-process LRU cache + DuckDB-persisted analysis cache (no Redis)
- `BobProvider` backed by free-tier Gemini/OpenRouter
- Docker packaging for reproducible local runs (optional, not required to develop)

### Production evolution (documented, not built)

| Concept | MVP | Production trigger |
|---|---|---|
| Persistence | DuckDB file | Postgres, once multi-user/concurrent-writer access is needed |
| Cache | In-process + DuckDB table | Redis, once multiple stateless API instances need a shared cache |
| Core process | Local subprocess (stdio RPC) | HTTP/gRPC service behind a load balancer, once hosted multi-tenant |
| AI provider | Gemini/OpenRouter free tier | Paid provider with SLA, once reliability requirements exceed free-tier limits |
| Deployment | Local install, optional Docker | Container orchestration (K8s), once running as a hosted service |
| Search | DuckDB full-text/LIKE queries | Dedicated search index, once corpus size/query patterns demand it |

Each row is a swap behind an existing interface boundary (`GraphStore`, `CacheProvider`,
`BobProvider`), not a rewrite — see the module table in §2.

## 6. Failure handling boundaries

Every external boundary has an explicit failure story (detailed per-module in code, tracked
here at the architecture level):

- **Malformed/unparseable source files:** parser errors are caught per-file; the scan
  continues and the file is recorded as `PARSE_FAILED` rather than aborting the whole run.
- **DuckDB unavailable/locked:** surfaced as a clear CLI/RPC error, never silently swallowed.
- **AI provider unavailable or rate-limited:** `BobProvider` fallback chain (Gemini →
  OpenRouter); if both fail, deterministic (non-AI) results are still returned with a note
  that semantic reasoning was unavailable.
- **Concurrent analysis jobs on the same snapshot:** guarded by a snapshot-level advisory
  lock in DuckDB (single-writer discipline appropriate to an embedded engine).
