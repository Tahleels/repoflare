# RepoFlare — what this is, in plain words

**The problem:** when you change some code, you don't actually know everything it touches.
You either guess, or you grep around and hope. AI coding assistants have the same problem —
they re-read a pile of files from scratch every time you ask them something, which is slow
and often still misses things.

**What RepoFlare does:** it reads a codebase once and builds a map of it — which file calls
which function, which file imports which, which tests cover which code. Think of it like a
dependency graph, but for your whole repo, kept up to date as things change.

Once that map exists, you can ask two useful questions:

1. **"If I change this, what else does it affect?"** — answered instantly, by walking the
   map. No AI needed for this part — it's just graph traversal, so it's fast, free, and
   works offline.
2. **"Explain this change in plain English, and show me exactly where in the code you got
   that from."** — this part uses AI, but only on the small, relevant slice of the map the
   first question already found — never the whole repository. The answer comes back with
   citations like `[auth.py#L12-L30]` pointing at the exact lines, so you can verify it
   instead of just trusting it.

**How you use it:** a CLI (`repoflare impact`, `repoflare explain`, …) and a VS Code
extension — both are just two thin front doors onto the same underlying engine, so they
never disagree with each other.

## Why this design, specifically

- **Deterministic first, AI second.** Anything that can be answered by just reading the code
  structure (imports, calls, tests) is answered that way — reliably, instantly, no API cost.
  AI is reserved for the one thing it's actually good at: explaining *meaning*.
- **Never dump the whole repo into a prompt.** Most tools ask an LLM to "read the codebase"
  every time, which is slow, expensive, and prone to missing things buried in a huge context.
  RepoFlare instead retrieves a small, targeted, graph-selected slice and hands that to the
  AI — smaller input, better answer, cheaper call.
- **Citations, not vibes.** Every AI answer points back to a real file and line range, so a
  developer can check it in two seconds instead of having to trust it blindly.
- **One shared brain, two interfaces.** The CLI and the VS Code extension don't duplicate
  logic — they both call into the same Python core, so a bug fixed once is fixed everywhere.

## The one-line pitch

*"RepoFlare builds a live map of your codebase's relationships, so it can tell you — fast,
for free, and with proof — exactly what a change touches, before you find out the hard way."*
