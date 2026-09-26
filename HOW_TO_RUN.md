# How to run RepoFlare

Two ways to use it: the **CLI** (fastest to try) and the **VS Code extension** (visual).
Both need the Python core set up first.

## 0. Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) — Python dependency/environment manager
- Node.js 18+ (only needed for the VS Code extension)
- Git

## 1. Set up the core

```bash
cd core
uv sync
```

Optional — enable the AI-powered `explain` command by setting an API key:

```bash
cp ../.env.example ../.env
# then edit ../.env and set GEMINI_API_KEY and/or OPENROUTER_API_KEY
```

Without a key, everything except `explain` still works (`init`, `analyze`, `status`,
`impact`, `export-html` are all deterministic — no AI, no key needed).

## 2. Run the CLI

Point it at any git repository (your own project, or this repo itself):

```bash
uv run repoflare init <path-to-a-repo>
uv run repoflare analyze <path-to-a-repo>
uv run repoflare status <path-to-a-repo>
```

See what a change affects (deterministic, instant):

```bash
uv run repoflare impact --from <git-ref> --to <git-ref> <path-to-a-repo>
```

Get a plain-English, cited explanation of that same change (needs an API key):

```bash
uv run repoflare explain --from <git-ref> --to <git-ref> <path-to-a-repo>
```

Export a shareable static HTML report:

```bash
uv run repoflare export-html --from <git-ref> --to <git-ref> --output report.html <path-to-a-repo>
```

Run the test suite:

```bash
uv run pytest -q
```

## 3. Run the VS Code extension

```bash
cd extension
npm install
npm run build
```

Open the `extension/` folder in VS Code (or a compatible fork, e.g. Antigravity IDE), then
press **F5** — this launches a second window titled `[Extension Development Host]` with the
extension loaded. In *that* window, open the repo you want to analyze as the workspace
folder, then use the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`) and run:

- **RepoFlare: Analyze Repository** — builds the graph.
- **RepoFlare: Show Repository Overview** — opens the panel with node/edge counts.
- **RepoFlare: Show Impact for Ref Range…** — same impact analysis as the CLI, shown visually.

By default the extension runs `python` to launch the core — if that's not the right
interpreter, set `repoflare.pythonPath` in VS Code settings to the one with
`repoflare_core` installed (e.g. the `core/.venv` created by `uv sync`).

To run the extension's own tests:

```bash
cd extension
npm test
```

## Troubleshooting

- **F5 does nothing** — make sure `extension/.vscode/launch.json` exists (it should, it's
  checked into this repo). Without it, VS Code has no debug configuration to run.
- **Command Palette shows no RepoFlare commands** — you're in the wrong window. The
  extension only loads in the window whose title bar is prefixed
  `[Extension Development Host]`; a normal window (even one opened from inside that debug
  session) does not have it loaded.
- **`explain` errors about a missing provider** — no `GEMINI_API_KEY` or
  `OPENROUTER_API_KEY` is set in `.env`. Every other command still works without one.
