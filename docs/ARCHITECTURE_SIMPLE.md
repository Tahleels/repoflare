# RepoFlare architecture, simply

For the precise, full version see `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, and
`docs/GRAPH_MODEL.md`. This page is the "explain it on a whiteboard in two minutes" version.

## The big picture

```
   CLI              VS Code extension
    │                       │
    └───────────┬───────────┘
                 │  (both just call the same core)
                 ▼
          Python core engine
                 │
   ┌─────────────┼──────────────┐
   ▼             ▼              ▼
 Scan &        Graph          AI layer
 parse the    (DuckDB: who    (Gemini or
 repo         calls/imports   OpenRouter,
              what)           free tier only)
```

## The flow, step by step

1. **Scan** — walk the repo, find every Python/TypeScript/JS file.
2. **Parse** — pull out every function, class, and test from those files.
3. **Build the graph** — record who calls whom, who imports whom, which test covers which
   function. Stored in a small local database file (DuckDB — no server, no cloud, just a
   file next to your repo).
4. **Detect a change** — diff two git refs (e.g. your last commit vs. the one before) to see
   which files actually changed.
5. **Walk the graph backwards** — from the changed code, follow the graph in reverse to find
   everything that depends on it. This step alone answers "what does this affect?" — no AI
   involved, purely mechanical, instant.
6. **Hand a small slice to AI** — take just the changed code + its direct dependents (never
   the whole repo) and ask an AI model to explain the change in plain English, citing exact
   file/line ranges.
7. **Show the result** — as CLI text output, or in the VS Code extension's panel, or as a
   shareable static HTML report.

## Why it's split this way

- Steps 1–5 are **deterministic** — same input always gives the same output, no network
  call, no cost. This is most of what people actually need day-to-day.
- Step 6 is the only place AI touches the system, and only after the deterministic steps
  have already narrowed things down to a small, relevant slice.
- The CLI and the VS Code extension are both just thin wrappers that call into the same
  core — neither one contains real logic of its own, so there's nothing to keep in sync.

## What each folder is, in one line

| Folder | What it's for |
| :--- | :--- |
| `core/` | The actual engine — scanning, parsing, graph, impact analysis, AI calls. Everything else is a thin shell around this. |
| `core/.../cli/` | The terminal commands (`repoflare init/analyze/impact/explain/...`). |
| `core/.../rpc/` | A small protocol so the VS Code extension can talk to the Python core as a background process. |
| `extension/` | The VS Code extension — panels/commands, talks to the core over that protocol. |
| `docs/` | The detailed design docs, for anyone who wants the precise version. |
