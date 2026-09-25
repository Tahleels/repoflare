# Architecture Decision Log

Each entry: decision, options considered, why, what changes at larger scale.

---

## ADR-001: Core language & process model

**Decision:** Python core package (`repoflare_core`). The CLI is the core's own interface
(`python -m repoflare_core.cli`, packaged as the `repoflare` console script). The VS Code
extension is a thin TypeScript client that spawns the core as a local subprocess and
communicates over JSON-RPC on stdio — the same integration pattern used by rust-analyzer,
Pylance, and gopls.

**Options considered:**
- TypeScript-only monorepo (core as a shared npm package, no IPC hop).
- Python core exposed as a long-lived local HTTP service instead of stdio JSON-RPC.

**Why:** Python has the most mature ecosystem for the three things this product leans on
hardest — tree-sitter bindings, embedded analytical SQL engines (DuckDB), and AI SDKs.
Keeping the extension a thin client means it never needs native modules, sidestepping
Electron-ABI rebuild issues entirely (only the spawned core process needs native bindings,
and it manages its own Python environment). stdio JSON-RPC (not HTTP) was chosen over the
service variant because it needs no port management, and lifecycle is tied 1:1 to the
editor session VS Code already manages for us.

**Changes at scale:** A production multi-user deployment would promote the core to a real
HTTP/gRPC service behind the same interface boundary — the RPC module is already isolated
from the domain/application layers specifically so this swap doesn't touch business logic.

---

## ADR-002: Graph storage engine

**Decision:** DuckDB, using adjacency/edge tables (`nodes`, `edges`) with recursive CTEs for
traversal, rather than a dedicated graph database.

**Superseded:** Kùzu (embedded property graph DB, Cypher query language) was the initial
choice. Verified against current sources during Phase 0 and found archived on 2025-10-10 —
the team was acqui-hired by Apple and the project is no longer maintained. Betting the
storage layer on an abandoned dependency was rejected outright; see anti-hallucination
verification requirement in the project brief.

**Why DuckDB over SQLite:** Both are embedded, zero-ops, and use the same relational/CTE
modeling pattern. DuckDB's columnar engine gives materially better performance on the
analytical, aggregation-heavy queries impact analysis actually runs (fan-in/fan-out counts,
multi-hop traversals over thousands of edges), and it's actively developed by a well-funded
team (DuckDB Labs) rather than a side project.

**Why relational over a dedicated graph DB at all:** the closest real-world analogs to this
product — Sourcegraph's code-intelligence storage, Meta's Glean — both model code graphs
relationally (fact/edge tables in SQL or SQL-like fact stores), not in a property-graph
engine like Neo4j. That is the actual industry-precedented pattern for *code intelligence*
graphs specifically, as opposed to general knowledge graphs.

**Changes at scale:** The schema is plain SQL (nodes/edges/snapshots/analysis_cache) with no
DuckDB-specific extensions in the domain layer — the `GraphStore` interface is the only
place that touches the engine, so swapping to Postgres for a multi-tenant service is a
storage-adapter change, not a rewrite.

---

## ADR-003: Persistence scope for the MVP

**Decision:** Fully embedded, local-first. One DuckDB file per repository
(`.repoflare/graph.duckdb`) holds nodes, edges, snapshots, change sets, and the analysis
cache. No Postgres, no Redis, no Docker Compose required to run the tool.

**Why:** RepoFlare is currently a single-user local developer tool (CLI + VS Code
extension), not a multi-tenant service. Running two extra server processes to develop or
use it locally is real ops overhead with no demonstrated bottleneck to justify it yet.

**Changes at scale:** Postgres (read replicas, connection pooling) and Redis (distributed
cache, job coordination) are the documented production-evolution path for a hosted
multi-user deployment — see `docs/ARCHITECTURE.md` §Production Evolution.

---

## ADR-004: AI provider for the semantic reasoning ("Bob adapter") layer

**Decision:** A `BobProvider` interface (dependency-inverted, per SOLID) with two
implementations: `GeminiProvider` (primary, free tier) and `OpenRouterProvider` (fallback,
free-tier models). Selected via config with a graceful fallback chain.

**Why:** Zero marginal cost for a prototype, provider-agnostic from day one so the product
isn't locked to one vendor's pricing or availability. The interface boundary is the same
regardless of which concrete provider is live.

**Note on terminology:** "Bob" in this codebase (`BobProvider`, `BobAdapter`) refers to the
semantic-reasoning-layer concept from the original product brief (Section 10 of
`CLAUDE_CODE_MASTER_PROMPT.md`), not IBM's "Bob IDE" product. The two are unrelated;
RepoFlare's own AI layer does not call IBM Bob's API. The naming collision is coincidental
and is noted here to avoid future confusion.

**Changes at scale:** Additional providers (Anthropic, OpenAI, a self-hosted model) are
additional `BobProvider` implementations; nothing above the interface changes.
