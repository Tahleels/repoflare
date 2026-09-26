# RepoFlare

Repository intelligence: a structured, incrementally-maintained knowledge graph of a
codebase, used for change-impact analysis and AI-assisted reasoning — CLI + VS Code
extension over a shared Python core.

- **What this is, in plain words:** `PROJECT_OVERVIEW.md`
- **How to actually run it:** `HOW_TO_RUN.md`
- **Simple architecture breakdown:** `docs/ARCHITECTURE_SIMPLE.md`
- Full architecture, data model, graph schema, decisions: `docs/`
- Agent/contributor context (start here before changing code): `AGENTS.md`

## Quickstart (core)

```bash
cd core
uv sync
uv run pytest -q
uv run repoflare init <path-to-a-repo>
uv run repoflare analyze <path-to-a-repo>
uv run repoflare status <path-to-a-repo>
```
