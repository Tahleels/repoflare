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

## 4. Run the hosted web API (optional)

The same core also serves an HTTP API — this is what gets deployed for the hackathon's "Demo
Application URL". Because a hosted process cannot read your disk, it clones a public GitHub
repository on demand and runs the identical pipeline against it (`init` → `analyze` → `impact`).

```bash
cd core
uv run python -m repoflare_core.api
```

Then open <http://127.0.0.1:8000/> for the demo page, or call the API directly:

```bash
curl 'http://127.0.0.1:8000/api/v1/analyze?repo=pallets/itsdangerous'
curl 'http://127.0.0.1:8000/api/v1/impact?repo=pallets/itsdangerous&from=HEAD~1&to=HEAD'
curl 'http://127.0.0.1:8000/report?repo=pallets/itsdangerous&from=HEAD~1&to=HEAD'
```

`PORT` (default 8000) is read from the environment, along with the optional deployment knobs
`REPOFLARE_MAX_FILES`, `REPOFLARE_CLONE_DEPTH` and `REPOFLARE_MAX_CONCURRENCY`. Only
`/api/v1/explain` needs an AI key (`GEMINI_API_KEY` or `OPENROUTER_API_KEY`); without one it
returns 503 and every other endpoint keeps working, because they are fully deterministic.

**Speed is the real constraint here.** Every request clones, parses and traverses from scratch.
Measured on a laptop: 15 files → ~6s, 91 files → ~56s. Prefer the small repositories listed
first on the demo page.

### Deploying it to Render (free plan)

`render.yaml` at the repo root is a Render Blueprint that runs exactly the command above on
Render's **free** instance type (0.1 CPU / 512 MB RAM):

1. In the [Render Dashboard](https://dashboard.render.com), choose **New → Blueprint** and pick
   the `Tahleels/repoflare` repository. Render reads `render.yaml`, builds with
   `uv sync --frozen --no-dev` (the `uv.lock` inside `core/` is what makes Render install and
   use `uv`), and health-checks `/healthz`.
2. When prompted, paste a `GEMINI_API_KEY` if you want `/api/v1/explain` to work. Both API-key
   variables are declared `sync: false`, so they are entered in Render's UI and never stored in
   this repository.
3. The service gets a `https://<name>.onrender.com` URL — that is the "Demo Application URL".

Free-plan behaviour worth having ready if a judge is clicking the link:

- The instance **spins down after 15 minutes** without traffic, and the next request takes about
  a minute to wake. Render shows its own loading page while that happens.
- The filesystem is **ephemeral**, so nothing is cached between requests; each one re-clones and
  re-analyzes.
- Any push to `main` redeploys automatically (`autoDeploy: true`).

## Troubleshooting

- **F5 does nothing** — make sure `extension/.vscode/launch.json` exists (it should, it's
  checked into this repo). Without it, VS Code has no debug configuration to run.
- **Command Palette shows no RepoFlare commands** — you're in the wrong window. The
  extension only loads in the window whose title bar is prefixed
  `[Extension Development Host]`; a normal window (even one opened from inside that debug
  session) does not have it loaded.
- **`explain` errors about a missing provider** — no `GEMINI_API_KEY` or
  `OPENROUTER_API_KEY` is set in `.env`. Every other command still works without one.
- **The web API returns 503 for `/api/v1/explain`** — same cause, but the key is missing on the
  *service* rather than in `.env`. Set it in the Render dashboard, never in the repository.
- **The web API returns 413** — the repository has more source files than `REPOFLARE_MAX_FILES`
  (default 400). That is deliberate: refusing is better than analysing an arbitrary subset and
  returning impact results that look authoritative but are wrong.
- **The first web request after a quiet period is slow** — the free instance spun down. Hit
  `/healthz` first to wake it before demoing.
