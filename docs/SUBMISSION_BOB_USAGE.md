Paste this into the "IBM Bob Usage Statement" field (trim to fit the form's exact word limit
if it enforces one strictly — this draft is ~500 words). Task briefs, IBM Bob's raw output
summaries, and session screenshots are in `bob_sessions/` in this repo — this statement
describes exactly what's backed by that evidence.

---

We used IBM Bob 2.0 as a scoped implementation agent for two independently-defined,
well-bounded tasks within RepoFlare's existing architecture — not as the primary
architecture/design driver (that groundwork — the graph model, the data model, the module
boundaries — was already established before either task was handed to Bob), but as the agent
that actually wrote the code for two real, shipped features.

**Task 1 — the VS Code extension shell.** We gave Bob a task brief describing the required
architecture: a `RepoFlareRpcClient` speaking JSON-RPC 2.0 over stdio to the Python core, a
singleton webview panel, and three commands (show overview, analyze, show impact). Bob wrote
the full TypeScript implementation — `rpc.ts`, `extension.ts`, `panel.ts`, `webview.ts` —
end to end. On review, we found and fixed one real bug in Bob's output: the "back to
overview" button posted a message type the extension host silently ignored, so clicking it
just re-rendered the same impact view instead of returning to the overview — fixed with a
proper `back` message type. We also added a test suite (`extension/test/`, 9 tests, none
existed in Bob's submission), including two integration tests that spawn the real Python RPC
subprocess to prove the TypeScript client and Python server genuinely agree on the wire
protocol.

**Task 2 — the `cache/` module.** We gave Bob a second, more detailed brief: build a
`CacheProvider` backed by an existing `analysis_cache` DuckDB table, using a specific
content-hash-keyed cache-key format we'd already defined in our data model, and wire it into
the `explain` command so a repeated question against an unchanged part of the codebase skips
the AI network call entirely. Bob delivered `cache/provider.py`, the `service.py` wiring, and
10 new tests (get/set roundtrip, TTL expiry, and an end-to-end proof that a cache hit
genuinely bypasses the AI provider call). We reviewed the control flow by hand — correct: the
cache check happens while the database connection is open, the AI call happens after it's
released (so a slow network call never holds a database connection), and the result is
written back afterward. The full test suite (171 tests) and strict-mode type checking passed
unmodified after merging this.

**How we directed Bob.** Both tasks were handed to Bob as self-contained written briefs that
named the exact files to touch, the exact conventions already in force in the codebase (one-
way module dependencies, no comments explaining *what* code does, frozen dataclasses for
domain entities), and the exact quality gate to pass before calling the task done
(formatter, linter, strict type checker, full test suite). This let Bob work inside an
existing, opinionated codebase rather than starting from a blank slate, and let us verify its
output against the same standard the rest of the codebase already met.

**What this demonstrates.** Bob's contribution is concrete and independently checkable: two
real modules, their tests, and the fixes/reviews we made on top of them are all in this
repo's git history and diffable. This is "clear application of IBM Bob 2.0" in the sense the
judging criteria ask for — Bob wrote real, working, tested code that ships in the final
product, not a demo-only stub.
