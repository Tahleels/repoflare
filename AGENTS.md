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
  running), a slide PDF, and a **live Demo Application URL** — see item 4 in "Next up" below for how we're
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
semantic parts that traversal can't answer. For a plain-language overview see
`PROJECT_OVERVIEW.md`; for a simple architecture breakdown see `docs/ARCHITECTURE_SIMPLE.md`;
for how to actually run it see `HOW_TO_RUN.md` — all at the repo root/docs. (This repo was
originally directed via two private planning docs, `CLAUDE_CODE_MASTER_PROMPT.md` and
`SYSTEM_DESIGN_REFERENCE.md` — gitignored, not part of the public repo, so don't expect them
to exist in a fresh clone.)

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
                            GraphTraversalService (traversal.py): direct_dependents,
                            bounded reverse_impact (recursive CTE), shortest_reverse_path
                            (BFS path reconstruction, used by retrieval/)
    scanning/               RepositoryScanner — walks a repo, respects .gitignore,
                            filters to known languages (python, typescript, javascript)
    parsing/                ParserAdapter — tree-sitter extraction of functions/classes/
                            methods + CONTAINS edges (Python, TypeScript/JS), and pytest-
                            style test detection (module-level `def test_*` inside
                            test_*.py/*_test.py -> NodeKind.TEST, Python-only).
                            CallImportResolver (resolver.py) — second pass: same-file
                            module-level CALLS + File->File IMPORTS by module-qualified-
                            name match. Deliberately bounded — see its module docstring.
                            TestLinkResolver (test_resolver.py) — second pass: TESTED_BY
                            edges linking `test_foo` to any symbol named `foo` anywhere in
                            the snapshot (naming heuristic, not coverage analysis).
    change/                 GitAdapter (safe `git` subprocess wrapper, no shell=True) +
                            ChangeDetector — git diff between two refs -> ChangeSet.
    impact/                 ImpactAnalyzer — ChangeSet -> categorized ImpactResults via
                            GraphTraversalService.reverse_impact (depth 1=DIRECT,
                            2=INDIRECT, 3=RELATED, 4+=POSSIBLE). Excludes changed nodes
                            themselves from results.
    ai/                     BobProvider (Protocol, provider.py) + GeminiProvider (primary,
                            free tier — endpoint/schema verified 2026-09-26 against
                            ai.google.dev, live-smoke-tested working) + OpenRouterProvider
                            (fallback — defaults to and *hard-enforces* OpenRouter's
                            official `openrouter/free` router; constructor raises
                            NotAFreeModelError for anything that isn't `openrouter/free` or
                            doesn't end in `:free`, so a paid model can never slip through)
                            + FallbackBobProvider (tries providers in order) +
                            default_bob_provider() factory (reads GEMINI_API_KEY and/or
                            OPENROUTER_API_KEY[+optional OPENROUTER_MODEL] from env — see
                            .env.example). HTTP tested via httpx.MockTransport.
    retrieval/              ContextRetriever (context_retriever.py) — builds a bounded
                            AIContextPackage from a ChangeSet + ImpactResults: source
                            snippets (read from disk, capped at 10 nodes), reconstructed
                            graph paths, direct dependents, and relevant_tests (via
                            TESTED_BY edges — empty only when no matching test exists/was
                            detected, not a gap). format_explain_prompt (prompt.py) turns
                            that package into an LLM-ready prompt string.
    service.py              Orchestration layer (new this session): run_init/run_analyze/
                            run_status/run_impact/run_explain — the ONLY place scanning ->
                            parsing -> graph -> change -> impact -> retrieval -> ai get
                            wired together. cli/ and rpc/ both call this and hold no
                            orchestration logic themselves — see docs/ARCHITECTURE.md §2.
    cli/                    Typer commands: init, analyze, status, impact, explain — thin
                            wrappers over service.py: format/print its results, map its
                            exceptions (NotInitializedError, NotAnalyzedError,
                            GitCommandError, BobProviderConfigError, BobProviderError) to
                            exit codes. stdout/stderr forced to UTF-8 at startup (AI text
                            has em-dashes/curly quotes that corrupted default Windows
                            console output before this fix).
    rpc/                    JSON-RPC 2.0 stdio server (new this session) — Content-Length
                            framing, identical wire format to LSP (protocol.py: read_message
                            /write_message). server.py's RpcServer dispatches
                            repoflare/{init,analyze,status,impact,explain} to service.py and
                            JSON-encodes the (dataclass/Enum/Path) results. Exceptions map to
                            JSON-RPC error codes: -32001 not initialized, -32002 not
                            analyzed, -32003 git error, -32004 no AI provider configured,
                            -32005 AI call failed, plus standard -32600/-32601/-32700.
                            `python -m repoflare_core.rpc` is the entry point the VS Code
                            extension will spawn as a subprocess (__main__.py).
    export/                 render_html (html.py) — pure function producing a self-
                            contained static HTML report (repo overview + optional impact
                            view). Mirrors extension/src/webview.ts's escape-everything
                            discipline. Wired into the CLI as `export-html`.
    cache/                  CacheProvider (provider.py) — content-hash-keyed result cache
                            backed by the analysis_cache DuckDB table. get(key) returns
                            cached JSON string or None (pruning expired entries on access);
                            set(key, result, ttl) upserts. Takes the raw DuckDB connection
                            from GraphStore.raw_connection() — no second connection opened.
                            Wired into service.py::run_explain: cache key is
                            stable_id(change_set_id, context_id); hit → return immediately
                            without calling the AI provider; miss → call provider, write
                            result back, return. 10 tests in test_cache_provider.py cover
                            get/set roundtrip, overwrite, TTL, expiry pruning, and the
                            cache-hit short-circuit in run_explain end-to-end.
    config/                 Shared .repoflare/graph.duckdb path resolution
  tests/                    168 tests, all passing (1 skipped on Windows — symlink test):
                            test_ids, test_scanner, test_parser_adapter,
                            test_call_import_resolver, test_test_resolver, test_graph_store,
                            test_traversal, test_change_detector, test_impact_analyzer,
                            test_ai_providers, test_ai_factory, test_context_retriever,
                            test_service, test_rpc_protocol, test_rpc_server, test_export_html,
                            test_cli, test_cache_provider
```

Verified: `cd core && uv sync && uv run pytest -q` → 168 passed, 1 skipped. `uv run ruff check src tests`
→ clean. `uv run mypy src` (strict mode) → clean. `impact` and `explain` were both
smoke-tested end-to-end in throwaway git repos, INCLUDING `explain` against a real, live
`GEMINI_API_KEY` — genuinely calls Gemini and prints a real explanation; encoding fix
verified to eliminate the corruption that was present before it. Test discovery was
smoke-tested against this repo's own `core/` tree: correctly found 90 real test functions
and 0 false positives; 0 TESTED_BY links there specifically because this project's own test
names are descriptive (`test_scan_finds_known_language_files`) rather than the bare
`test_<exact_function_name>` pattern the heuristic matches — the dedicated CLI test
(`test_analyze_discovers_tests_and_links_them`) proves the link actually forms when naming
does match. `rpc/` was additionally smoke-tested by spawning the real
`python -m repoflare_core.rpc` subprocess and talking to it over actual OS pipes (not just
in-process `handle_request` calls) — correct framing, correct responses, clean exit on
stdin close.

The CLI refactor onto service.py was verified to change zero observable CLI behavior: the
full pre-existing CLI test suite (all output-string assertions) passed unmodified except for
two monkeypatch targets that had to move to their new location
(`repoflare_core.service.default_bob_provider`, not `repoflare_core.cli.main.*`).

`export/html.py::render_html` is a pure function (state in, HTML string out) producing a
self-contained static report — mirrors `extension/src/webview.ts`'s approach deliberately,
including the same escape-every-dynamic-value discipline (7 dedicated tests cover this,
including two explicit XSS-payload checks). Wired into the CLI as
`repoflare export-html [--from <ref>] [--to <ref>] [--output <path>]` — overview-only if
`--from` is omitted, overview + impact table if given. Defaults to
`<repo>/.repoflare/report.html`. Smoke-tested: produced a real, valid, self-contained HTML
file in a throwaway repo, inspected by hand — renders correctly, no external assets, ready
to host as-is on GitHub Pages for the hackathon's required Demo Application URL.

Not started yet: `verification/`.

```
extension/
  package.json          npm-managed, TypeScript + esbuild, activates on VS Code startup
  tsconfig.json         strict mode, commonjs/ES2020, rootDir=src
  .vscodeignore         excludes dist/, node_modules/, *.vsix
  src/
    rpc.ts              RepoFlareRpcClient — Content-Length-framed JSON-RPC 2.0 client over
                          child_process stdio. Spawns `python -m repoflare_core.rpc`,
                          routes responses to promises by request id. Typed wrappers for
                          all five RPC methods (init/analyze/status/impact/explain).
                          RpcError with named error code constants for all -320xx codes.
    extension.ts        activate() / deactivate(). One client per workspace folder.
                          Commands: repoflare.showOverview, repoflare.analyze,
                          repoflare.showImpact. withClient() handles NOT_INITIALIZED /
                          NOT_ANALYZED with offer-to-fix prompts.
    panel.ts            RepoFlarePanel — singleton WebviewPanel. show() creates or reveals.
                          _initialLoad() fetches status, then shows overview or immediately
                          runs impact if refs supplied. Handles webview messages (analyze,
                          impact, back, ready) by calling back into the RPC client.
                          _showOverview() factors out the fetch-status-and-render-overview
                          sequence shared by "analyze" and "back".
    webview.ts          buildWebviewHtml(state) — pure function, returns complete self-
                          contained HTML string for loading / error / overview / impact
                          states. Uses VS Code CSS variables for theming. Impact table
                          shows category badges (DIRECT/INDIRECT/RELATED/POSSIBLE),
                          symbol label, and file path. No external assets. Every dynamic
                          value goes through escHtml() — verified by explicit XSS tests.
  test/
    webview.test.ts     7 tests: HTML-escaping (incl. a malicious repo-root path and
                          impact-table values), empty states, CSP presence.
    rpc.integration.test.ts  2 tests: spawns the REAL python -m repoflare_core.rpc via
                          the actual RepoFlareRpcClient — init/analyze/status roundtrip,
                          and JSON-RPC error codes (-32002, -32003) round-tripping
                          correctly from a live server, not a mock. Self-skips (not fails)
                          if `uv`/the core venv can't be resolved.
  tsconfig.test.json     extends tsconfig.json, adds test/ to include, for `npm run typecheck`
  dist/                 esbuild output (gitignored): extension.js + extension.js.map
```

Verified: `cd extension && npm install && npm run build` → clean, 23 KB bundle.
`npm run typecheck` (src + test) → zero type errors (strict mode). `npm test` → 9/9 passing,
including both real subprocess integration tests.

## Conventions in force — match these, don't introduce new patterns

- **Module dependency direction is one-way**: `cli`/`rpc` → `service.py` (orchestration) →
  application services (`impact`, `retrieval`, `verification`) → infrastructure (`graph`,
  `ai`, `cache`) → `domain`. `domain` has zero dependencies on anything else in the package.
  **Orchestration logic goes in `service.py`, never inline in a CLI command or an RPC
  handler** — that's what keeps CLI and extension from duplicating business logic. See
  `docs/ARCHITECTURE.md` §2 for the full table.
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

CALLS/IMPORTS resolution, ChangeDetector, `impact/`, `ai/`, `retrieval/` (+ the `explain`
CLI command tying them together), and test discovery (`NodeKind.TEST` +
`TESTED_BY`) are now done — see "Current state" above. Renumbered list below starts from
what's actually left.

1. **Extend CALLS/IMPORTS resolution beyond its current bounded scope**, for more graph
   density (this directly improves `impact`/`explain` results — see the impact smoke-test
   note above about the cross-file-call gap): cross-file call resolution (the callee is
   imported from elsewhere — needs the IMPORTS edges plus a per-file "what names does this
   file's imports bring into scope" table), `self.method()` / `obj.method()` attribute
   calls, and aliased (`import x as y`) / wildcard (`from x import *`) imports. Each of
   these is independently scoped; don't try to do all of them in one pass. See
   `parsing/resolver.py`'s module docstring for exactly what's already covered.

2. ~~**`cache/` — CacheProvider.**~~ Done — see `cache/provider.py` and "Current state"
   above. Cache key is `stable_id(change_set_id, context_id)`; hits skip the AI provider
   call entirely; misses call the provider and write back. TTL optional (no TTL = permanent).

3. ~~**`extension/` — VS Code extension shell.**~~ Done — Bob IDE built this; see "Current
   state" above and `extension/` tree below. Reviewed and lightly fixed afterward (not by
   Bob): the "← Back to overview" button was a real bug — it posted a `ready` message
   (handled as a no-op) and called `location.reload()`, which just re-rendered the current
   impact HTML instead of returning to the overview. Fixed with a proper `back` message
   type. Also removed an unused `EventEmitter` import in `rpc.ts`, and added a test suite
   that didn't exist yet (`extension/test/`, `npm test`): 7 unit tests for
   `webview.ts`'s HTML building — including explicit XSS-escaping checks on every dynamic
   value (labels, file paths, refs, error messages, a maliciously-crafted repo root path) —
   plus 2 real cross-language integration tests that spawn the actual
   `python -m repoflare_core.rpc` subprocess through the real `RepoFlareRpcClient` (not
   mocked on either side), proving the TS client and Python server genuinely agree on the
   wire protocol, including that JSON-RPC error codes round-trip correctly end to end.

4. ~~**`repoflare export-html`**~~ Done — see `export/html.py` and "Current state" above.
   Real report generated and hand-inspected in a throwaway repo: valid, self-contained
   HTML, no external assets, ready to host as-is (e.g. GitHub Pages) for the hackathon's
   required Demo Application URL field. **You still need to actually host it and paste that
   URL into the submission form** — this only produces the file.

Only one item left: item 1 (CALLS/IMPORTS extension) above.

Whichever you pick, update this file's "Current state" and "Next up" sections when you're
done, so the next agent (or the next Bob session) picks up from an accurate baseline instead
of a stale one.
