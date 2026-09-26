Paste this into the "Problem & Solution Statement" field (trim to fit the form's exact word
limit if it enforces one strictly — this draft is ~500 words).

---

**The problem.** When a developer changes a piece of code, they rarely know everything that
change touches. They grep, they guess, or they wait for CI to tell them what broke. AI
coding assistants have the same blind spot in a different form: most re-read a pile of files
from scratch on every question, because they have no persistent structural memory of the
repository. That's slow, expensive (every query re-sends large chunks of code to an LLM),
and — worse — unverifiable: the assistant states a conclusion, and the developer has no easy
way to check whether it actually traced the dependency correctly or just pattern-matched.

**The solution — RepoFlare.** RepoFlare builds a structured knowledge graph of a repository
once, then maintains it incrementally: every file, function, class, and test becomes a node;
every import, call, and test-to-symbol link becomes an edge, stored in an embedded DuckDB
database that lives next to the repo. That graph is queried, not rebuilt, on every question.

Given a change (a diff between two git refs), RepoFlare answers two things:

1. *"What does this affect?"* — by walking the graph backwards from the changed code,
   entirely deterministically. No AI call, no network dependency, instant, and reproducible.
   Results are categorized by confidence (DIRECT / INDIRECT / RELATED / POSSIBLE) rather than
   presented as one flat, undifferentiated list.
2. *"Explain this change, and prove it"* — only for this genuinely semantic question does
   RepoFlare call an AI model, and only with a bounded, graph-selected context package (the
   changed code plus its direct dependents) — never the whole repository. Every claim in the
   AI's answer is required to cite an exact `[file#Lstart-Lend]` location pulled from that
   context, so a developer can verify the reasoning in seconds instead of trusting it
   blindly.

The CLI and VS Code extension are two thin interfaces over one shared Python core — neither
duplicates logic, so a fix in one place fixes both.

**Why this matters (business value).** Separating "what changed structurally" (cheap, fast,
deterministic graph traversal) from "what does it mean" (the one place an LLM call is
actually needed) directly cuts AI API cost and latency compared to tools that re-embed or
re-read an entire codebase per query — and it produces a verifiable, citable answer instead
of an opaque one. This is directly useful in code review, onboarding to an unfamiliar
codebase, and pre-merge risk checks — anywhere the real question is "did I miss anything?"
rather than "write me some code."

**Originality.** Most repository-AI tools treat the codebase as an unstructured pile of text
chunks for similarity search. RepoFlare treats repository structure as a first-class,
queryable data structure — the graph is the source of truth for "what's connected to what,"
and AI is deliberately kept out of that determination, reserved only for the reasoning a
graph traversal genuinely can't do on its own. That discipline — deterministic first, AI
second, always cited — is the core differentiator.

**Current state.** A working vertical slice exists end-to-end: repository scanning,
tree-sitter parsing, graph construction and persistence, git-based change detection,
categorized impact analysis, targeted AI-context retrieval with citation grounding, a CLI,
and a VS Code extension, backed by 170+ passing tests.
