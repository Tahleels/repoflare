# Testing RepoFlare — CLI + extension, end to end

This is a step-by-step walkthrough to actually exercise RepoFlare, not just read about it.
For install/setup only, see `HOW_TO_RUN.md`. This file assumes you've already done that once
(`cd core && uv sync`, and `cd extension && npm install && npm run build`).

Runs in **PowerShell**. Swap `D:\temp\repoflare-demo` for any path you like — just avoid
`C:` if you'd rather keep test data off the system drive.

## 0. Build a real, tiny demo repo

Two files, one genuine cross-file dependency (`main.py` imports from `utils.py`), two commits
(so there's a real change to analyze).

```powershell
mkdir D:\temp\repoflare-demo
cd D:\temp\repoflare-demo
git init
[System.IO.File]::WriteAllText("$pwd\utils.py", "def calculate_total(items):`n    return sum(items)`n")
[System.IO.File]::WriteAllText("$pwd\main.py", "from utils import calculate_total`n`ndef run():`n    return calculate_total([1, 2, 3])`n")
git add -A
git commit -m "initial"
[System.IO.File]::WriteAllText("$pwd\utils.py", "def calculate_total(items):`n    return sum(items) * 1.0`n")
git add -A
git commit -m "make calculate_total return float"
```

**Use `[System.IO.File]::WriteAllText`, not `Out-File -Encoding utf8`.** `Out-File`'s `utf8`
encoding writes a UTF-8 byte-order mark (BOM) by default in Windows PowerShell 5.1 — RepoFlare
now handles that correctly (fixed, see git log), but `WriteAllText` avoids it cleanly rather
than relying on that fix, so it's the safer command to reach for either way.

## 1. CLI walkthrough

```powershell
cd D:\repoflare\core
uv run repoflare init D:\temp\repoflare-demo
uv run repoflare analyze D:\temp\repoflare-demo
```
Expect: `Analyzed 2 files, extracted 2 symbols (0 tests), resolved 1 CALLS/IMPORTS edges and 0 TESTED_BY edges.`
(**Resolved edges must be 1, not 0** — that's the cross-file import actually being tracked.
If you see 0, something's wrong; see Troubleshooting.)

```powershell
uv run repoflare status D:\temp\repoflare-demo
```
Expect a small table: `Nodes 4`, `Edges 2`.

```powershell
uv run repoflare impact --from HEAD~1 --to HEAD D:\temp\repoflare-demo
```
Expect:
```
Changed files (1): utils.py
DIRECT (1):
  main (main.py)
```
This is pure graph traversal — no AI call, no network, works offline.

If you've set `GEMINI_API_KEY`/`OPENROUTER_API_KEY` (see `.env.example`), load them into this
PowerShell session first:
```powershell
Get-Content D:\repoflare\.env | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim())
    }
}
```
Then:
```powershell
uv run repoflare explain --from HEAD~1 --to HEAD D:\temp\repoflare-demo
```
Expect a short (a few sentences, not a wall of text — it scales to the size of the change),
plain-English explanation containing a `[utils.py#L1-L2]` citation tag.

```powershell
uv run repoflare export-html --from HEAD~1 --to HEAD --output D:\temp\repoflare-demo\report.html D:\temp\repoflare-demo
start D:\temp\repoflare-demo\report.html
```
Expect a self-contained HTML file that opens and renders correctly in your browser.

## 2. Extension walkthrough

```powershell
cd D:\repoflare\extension
npm install
npm run build
npm test
```
Expect `16 passed`. (Two of the tests spawn the real Python core — if those specifically
*skip* rather than pass, it means `uv`/the core venv wasn't found from that shell, not a real
failure.)

**Launch the debug host:**
1. Open `D:\repoflare\extension` in VS Code / Antigravity IDE as its own workspace (not the
   parent `D:\repoflare` folder — `launch.json` is only found relative to this exact folder).
2. Run and Debug panel (`Ctrl+Shift+D`) → confirm the dropdown says **"Run Extension"** →
   click the green ▶. (If `Ctrl+Shift+D`/F5 does nothing, see Troubleshooting.)
3. A new window opens. **Check its title bar says `[Extension Development Host]`** — that's
   the only window with the extension actually loaded. Everything below happens in that
   window specifically.

**Point it at the right Python, in that window:**
Create `D:\temp\repoflare-demo\.vscode\settings.json`:
```json
{
  "repoflare.pythonPath": "D:\\repoflare\\core\\.venv\\Scripts\\python.exe"
}
```

**Open the demo repo as the workspace** (File → Open Folder → `D:\temp\repoflare-demo`),
then Command Palette (`Ctrl+Shift+P`) → run in order:

- **RepoFlare: Show Repository Overview** — should show 2 files, matching the CLI's `status`.
- **RepoFlare: Analyze Repository** — only needed once; you already ran it via the CLI above
  against the same `.repoflare` state, so this is really re-analyzing (harmless).
- **RepoFlare: Show Impact for Ref Range…** — enter `HEAD~1` / `HEAD` when prompted. Should
  show the same DIRECT/`main.py` result as the CLI's `impact` command.
- **RepoFlare: Show Dependency Graph** — should render a small SVG graph (2 nodes, 1 edge):
  a blue rectangle for each file, connected by a line. Click a node — its name/kind/file path
  should appear in the detail box below the graph.

Once the panel is open, you don't need the Command Palette again — a nav bar
(**Overview | Analyze | Impact | Graph**) stays visible at the top of the panel in every
state, so you can click between views directly.

## Troubleshooting

- **`impact`/`explain` finds nothing, or `analyze` reports 0 resolved edges** — two known
  causes, both already fixed in this repo, but worth knowing about if you're testing an older
  checkout: (1) source files with a UTF-8 BOM (see step 0's encoding note), (2) analyzing
  RepoFlare's *own* repo specifically — its `src/`-layout package isn't resolved by the
  current bounded import matcher (a real, documented limitation, not a bug — see AGENTS.md
  item 1). Use the tiny demo repo from step 0 for anything you need real impact results for.
- **F5 does nothing** — confirm `extension/.vscode/launch.json` exists and that
  `D:\repoflare\extension` (not its parent) is the open folder.
- **Command Palette shows no RepoFlare commands** — wrong window; check for the
  `[Extension Development Host]` title-bar prefix.
- **"⚠ repoflare_core process exited with code 1"** — `repoflare.pythonPath` is pointing at a
  `python` that doesn't have `repoflare_core` installed. Set it to
  `D:\repoflare\core\.venv\Scripts\python.exe` as shown above.
- **"⚠ RPC client is closed"** — the underlying process already crashed once (e.g. from the
  error above) and won't auto-retry. Reload the window (`Ctrl+Shift+P` → **Developer: Reload
  Window**) to get a fresh client after fixing the actual cause.
- **"Constraint Error: Violates foreign key constraint... repository_id..."** — this was a
  real bug (CLI vs. extension computing different repository IDs for the same folder due to
  Windows drive-letter casing) that's now fixed. If you still see it on a repo you `init`ed
  before pulling that fix, delete its `.repoflare/` folder and re-`init`/`analyze` it.
- **`explain` says "No AI provider configured"** — the `.env` file's values aren't loaded into
  your current PowerShell session's environment variables; see the loader snippet in step 1.
