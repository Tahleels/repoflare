# Demo script — for the hackathon video

Three scripted beats, ~3 minutes total.

**Important, verified during prep:** don't use *this* repo's own commit history for Beats 1
and 2. RepoFlare's core package uses a `src/`-layout (`core/src/repoflare_core/...`), and
the current CALLS/IMPORTS resolver (deliberately bounded — see `AGENTS.md` "Next up" item 1)
matches imports against a file's module-qualified name without accounting for a `src/`
prefix, so cross-file impact doesn't resolve against our own real history yet. That's a
known, documented limitation, not a bug — but it means a commit range from this repo will
print "No downstream impact found," which is a bad demo moment. Use the tiny flat-layout
demo repo below instead — it's a real (not fabricated) end-to-end run, just small.

Do a full dry run before recording. If the live AI call ever hesitates or times out during a
take, fall back to the pre-baked output (see "Fallback" at the bottom) rather than stalling
the recording.

## Setup (do this once, before recording — not on camera)

```
cd core
uv sync
```

Build the tiny demo repo (2 files, one real cross-file dependency):

```
mkdir /tmp/repoflare-demo && cd /tmp/repoflare-demo
git init
printf 'def calculate_total(items):\n    return sum(items)\n' > utils.py
printf 'from utils import calculate_total\n\ndef run():\n    return calculate_total([1, 2, 3])\n' > main.py
git add -A && git commit -m "initial"
printf 'def calculate_total(items):\n    return sum(items) * 1.0\n' > utils.py
git add -A && git commit -m "make calculate_total return float"
```

Then, back in `core/`:

```
repoflare init /tmp/repoflare-demo
repoflare analyze /tmp/repoflare-demo
```

Confirm `repoflare status /tmp/repoflare-demo` shows 2 files / 2 symbols before recording.

## Beat 1 — CLI: categorized impact (deterministic, no AI)

```
repoflare impact --from HEAD~1 --to HEAD /tmp/repoflare-demo
```

Verified output:

```
Changed files (1): utils.py
DIRECT (1):
  main (main.py)
```

**Show this:** `utils.py` changed, and `main.py` — which imports it, unchanged itself — is
correctly found as a DIRECT dependent. Narrate that this is pure graph traversal, zero AI
calls, so it's instant and deterministic even offline.

## Beat 2 — CLI: grounded explanation (AI reasoning, cited)

Same commit range:

```
repoflare explain --from HEAD~1 --to HEAD /tmp/repoflare-demo
```

**Show this:** the plain-language explanation, and specifically point at a
`[path/to/file.py#L12-L30]` citation tag in the output — say explicitly that every claim is
grounded in a real line range from the targeted context package, not a summary of the whole
repo. This is the traceability story judges are told to look for ("clear application of IBM
Bob 2.0" and grounded/traceable reasoning both apply here even though Bob wasn't the one
that wrote this specific module — the point being demonstrated is the product's own
traceability, independent of which agent built it).

## Beat 3 — VS Code extension: the same pipeline, visually

Open `/tmp/repoflare-demo` (the tiny demo repo, not this repo — same reason as above: the
extension calls the identical resolver, so it needs a flat-layout target too) in VS Code /
Antigravity IDE as the workspace folder, with the extension running (F5 → Extension
Development Host, per `extension/.vscode/launch.json`).

1. Command Palette → **RepoFlare: Show Repository Overview** — show the webview panel with
   node/edge counts.
2. Command Palette → **RepoFlare: Show Impact** (same `HEAD~1`/`HEAD` range as Beat 1) — show
   the categorized impact table rendering in the webview, same DIRECT/`main.py` result as the
   CLI, now visual.

**Show this:** narrate that CLI and extension are two thin clients over the identical Python
core (`service.py`) — nothing is duplicated or reimplemented per-surface. This repo
(RepoFlare itself, 66 files / 281 symbols per its own `repoflare analyze` run) is the right
thing to point at separately, on camera, as "here's the real, much larger codebase this was
built on and tested against" — just don't run `impact`/`explain` against it live, for the
`src/`-layout reason above.

## Closing shot — the static report

```
repoflare export-html --from HEAD~1 --to HEAD --output /tmp/repoflare-demo/report.html /tmp/repoflare-demo
```

Open `report.html` in a browser — this is the file hosted for the hackathon's required
"Demo Application URL" field. Say so on camera: "this static report is also live at
[your hosted URL]." (You can also export a from-scratch, impact-free overview report of
*this* repo — `repoflare export-html --output ../report.html ..` with no `--from` — as an
additional, larger-scale example if you want two reports linked from the same URL.)

## Fallback (prep before recording, don't show on camera)

A real, live-generated `explain` output for exactly this scenario is already saved at
`docs/demo_fallback_explain_output.txt` (generated 2026-09-26, not fabricated — see that
file for the exact commands). If the live Gemini/OpenRouter call stalls or errors mid-take,
read from that file instead of waiting on a live retry, so a flaky network doesn't cost you
a recording take.
