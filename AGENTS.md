# RepoFlare — agent context

Read this before doing anything else in this repo. It's written for whichever AI coding
agent picks up work here next (including IBM Bob IDE) so you don't have to re-derive the
architecture from scratch.

## Hackathon submission requirements (verified from the official Sept 25–27 2026 IBM Bob
2.0 hackathon submission form — do not treat as optional)

- The public repo must include: the code/files **IBM Bob actually assisted with**, plus
  **each team member's IBM Bob task session summary screenshots** — not just Claude-written
  code sitting next to unrelated screenshots. Put screenshots + exported task history in
  `bob_sessions/` (this is the officially-required folder name per the hackathon's own
  `.gitignore` template).
- `.bobignore` and the credential patterns in `.gitignore` are already in place at the repo
  root (copied from `github.com/watsonxhackathon/ibm-hackathon-template`) — don't remove
  them, and never put a real API key anywhere Bob or this file's `.env.example` doesn't
  already account for.
- Submission also needs: a 500-word Problem & Solution statement, a 500-word IBM Bob Usage
  Statement (be specific about what Bob did), a ≤3-minute video (≥90s must show the solution
  running), a slide PDF, and a **live Demo Application URL** — see item 9 below for how we're
  satisfying that last one without turning RepoFlare into a web app.
- Judging criteria (unweighted, no published point values): Application of Technology,
  Presentation, Business Value, Originality — all four explicitly reference "clear
  application of IBM Bob 2.0," so the Bob Usage Statement and video need to make Bob's
  actual contribution legible, not just claimed.

## What this is

RepoFlare is a repository-intelligence tool (CLI + VS Code extension over a shared Python
core): it builds and incrementally maintains a structured knowledge graph of a codebase
(files, symbols, relationships), then answers "what does this change affect?" and "did this
change miss anything?" using deterministic graph traversal first, AI reasoning only for the
semantic parts that traversal can't answer. Full product vision:
`CLAUDE_CODE_MASTER_PROMPT.md` at the repo root. Engineering principles reference:
`SYSTEM_DESIGN_REFERENCE.md`.

**Read these four docs before changing architecture, schema, or module boundaries:**
- `docs/ARCHITECTURE.md` — system shape, module boundaries, dependency direction
- `docs/DATA_MODEL.md` — domain entities
- `docs/GRAPH_MODEL.md` — the actual DuckDB schema and traversal queries
- `docs/DECISIONS.md` — why DuckDB (not Kùzu — it's abandoned, verified 2026-09), why
  embedded/local-first, why a unified nodes/edges table instead of one table per entity kind

## Current state (verified working, as of this session)

```
core/
  pyproject.toml          uv-managed, Python >=3.11, hatchling build backend
  src/repoflare_core/
    domain/                Frozen dataclasses: Node, Edge, Repository, Snapshot, etc.
                            (entities.py), deterministic id hashing (ids.py)
    graph/                 GraphStore (DuckDB persistence: schema.py + store.py) and
                            GraphTraversalService (traversal.py: direct_dependents,
                            bounded reverse_impact via recursive CTE)
    scanning/               RepositoryScanner — walks a repo, respects .gitignore,
                            filters to known languages (python, typescript, javascript)
    parsing/                ParserAdapter — tree-sitter extraction of functions/classes/
                            methods + CONTAINS edges, for Python and TypeScript/JS.
                            CallImportResolver (resolver.py) — second pass, resolves
                            CALLS (same-file, module-level function calls only) and
                            IMPORTS (File->File, by module-qualified-name match) edges.
                            Bounded scope deliberately — see resolver.py's module docstring.
    change/                 GitAdapter (safe `git` subprocess wrapper, no shell=True) +
                            ChangeDetector — git diff between two refs -> ChangeSet.
    impact/                 ImpactAnalyzer — takes a ChangeSet, resolves changed files to
                            changed node ids, runs GraphTraversalService.reverse_impact per
                            changed node, maps depth -> ImpactCategory (1=DIRECT, 2=INDIRECT,
                            3=RELATED, 4+=POSSIBLE). Excludes the changed nodes themselves
                            from results.
    cli/                    Typer commands: init, analyze, status, impact (all working end
                            to end; analyze resolves+inserts CALLS/IMPORTS edges and records
                            git_commit_sha on the snapshot when run inside a git repo; impact
                            diffs two refs via ChangeDetector and prints categorized results
                            with human-readable node labels, not raw ids)
    ai/                     BobProvider (Protocol, provider.py) + GeminiProvider (primary,
                            free tier — endpoint/schema verified 2026-09-26 against
                            ai.google.dev) + OpenRouterProvider (fallback — no hardcoded
                            default model, since free models "rotate out without warning"
                            per OpenRouter's own docs; pass one via config) +
                            FallbackBobProvider (tries providers in order) +
                            default_bob_provider() factory (reads GEMINI_API_KEY /
                            OPENROUTER_API_KEY+OPENROUTER_MODEL from env — see .env.example).
                            All HTTP tested via httpx.MockTransport — no real network calls
                            in the test suite.
    config/                 Shared .repoflare/graph.duckdb path resolution
  tests/                    92 tests, all passing (1 skipped on Windows — symlink test):
                            test_ids, test_scanner, test_parser_adapter,
                            test_call_import_resolver, test_graph_store, test_traversal,
                            test_change_detector, test_impact_analyzer, test_ai_providers,
                            test_ai_factory, test_cli
```

Verified: `cd core && uv sync && uv run pytest -q` → 92 passed, 1 skipped. `uv run ruff check src tests`
→ clean. `uv run mypy src` (strict mode) → clean. `impact` was smoke-tested in a throwaway
git repo end-to-end (init -> analyze at commit 1 -> edit + commit 2 -> impact --from commit1)
and correctly reported both a same-file CALLS-based DIRECT hit and a cross-file
IMPORTS-based DIRECT hit (cross-file *CALLS* resolution is explicitly out of scope for this
pass — see item 1 below). `ai/` has not been smoke-tested against a real Gemini/OpenRouter
key yet (no key available in this session) — only via mocked HTTP; do that before relying on
it for a live demo.

Not started yet: `retrieval/`, `verification/`, `cache/`, `rpc/`, the `extension/` (VS Code)
TypeScript side, and `export-html` (item 5 below).

## Conventions in force — match these, don't introduce new patterns

- **Module dependency direction is one-way**: `cli`/`rpc` → application services (`impact`,
  `retrieval`, `verification`) → infrastructure (`graph`, `ai`, `cache`) → `domain`.
  `domain` has zero dependencies on anything else in the package. See
  `docs/ARCHITECTURE.md` §2 for the full table — a new module goes in the row that matches
  what it depends on, not where it's convenient to put it.
- **Domain entities are frozen dataclasses with `slots=True`**, not pydantic — pydantic is
  reserved for boundary validation (CLI args, RPC payloads, config parsing), not internal
  hot-path graph objects. See `docs/DECISIONS.md` if you're unsure which to use for a new
  type.
- **Node/edge ids are deterministic content hashes** (`domain/ids.py::stable_id`), never
  random UUIDs, for anything that should be stable across re-analysis. Random ids are fine
  for `AnalysisJob`, `VerificationResult` — anything that's inherently a fresh event.
- **No comments explaining what code does** — names should do that. Comments only for
  non-obvious WHY (a workaround, a constraint, a deliberate trade-off). Look at the existing
  modules for the calibration.
- **Don't build half a feature.** If something needs a follow-on piece to be useful
  end-to-end (e.g. don't add a CLI `impact` command before `ImpactAnalyzer` exists), leave
  it out and note it below instead of stubbing it.
- Format/lint/type-check before considering anything done:
  `uv run ruff format src tests && uv run ruff check src tests && uv run mypy src`
- Every new module gets tests in `core/tests/` mirroring its path. Run with `uv run pytest -q`.

## Next up — pick one, each is independently scoped

CALLS/IMPORTS resolution, ChangeDetector, `impact/`, and `ai/` are now done — see "Current
state" above. Renumbered list below starts from what's actually left.

1. **Wire `ai/` up to something real.** The provider layer exists and is tested against
   mocked HTTP, but nothing in the CLI calls it yet, and it's never been smoke-tested against
   a live key. Two independent pieces of value here: (a) get a real `GEMINI_API_KEY` and run
   `default_bob_provider().complete("...")` once by hand to confirm the verified-2026-09-26
   request/response shapes still hold; (b) start `retrieval/` — a `ContextRetriever` that
   builds an `AIContextPackage` (already defined in `domain/entities.py`) from an
   `ImpactResult`, which is the missing piece between "impact analysis" and "ask Bob to
   explain it."

2. **Extend CALLS/IMPORTS resolution beyond its current bounded scope**, for more graph
   density (this directly improves `impact` results — see the smoke-test note above about
   the cross-file-call gap): cross-file call resolution (the callee is imported from
   elsewhere — needs the IMPORTS edges plus a per-file "what names does this file's imports
   bring into scope" table), `self.method()` / `obj.method()` attribute calls, and aliased
   (`import x as y`) / wildcard (`from x import *`) imports. Each of these is independently
   scoped; don't try to do all of them in one pass. See `parsing/resolver.py`'s module
   docstring for exactly what's already covered.

3. **`cache/` — CacheProvider.** In-process LRU (stdlib `functools.lru_cache` won't do — it
   doesn't support the content-hash-keyed invalidation from `docs/DATA_MODEL.md`; write a
   small explicit wrapper) plus a `analysis_cache` table read/write path in `GraphStore`. Key
   format: `repository_id + snapshot_id + relevant_node_hashes + question_hash` (see
   `docs/DATA_MODEL.md` access-patterns table). Worth doing once `ai/` is actually being
   called, since that's the expensive operation worth caching.

4. **`rpc/` — JSON-RPC stdio server** — `impact` now exists, so this is unblocked. This is
   what the VS Code extension will talk to (see `docs/ARCHITECTURE.md` ADR-001 for the
   protocol choice).

5. **`extension/` — VS Code extension shell.** TypeScript client that spawns the core
   subprocess and renders the first panel (repository overview). Depends on `rpc/` existing
   first.

6. **`repoflare export-html`** — a CLI command that takes an already-analyzed repository
   and renders its graph/impact view as a single static HTML file (no server, no backend at
   demo time). This exists specifically to satisfy the hackathon submission's required
   "Demo Application URL" field: host the exported file for free on GitHub Pages. It does
   NOT make RepoFlare a web app — the product stays CLI + extension; this is a one-command
   shareable snapshot of output the CLI already computes. Depends on at least `impact/`
   existing to be worth doing (a bare symbol list isn't a compelling demo page). Good Bob
   candidate: rendering structured data as a page is squarely doc/tooling work.

Whichever you pick, update this file's "Current state" and "Next up" sections when you're
done, so the next agent (or the next Bob session) picks up from an accurate baseline instead
of a stale one.
