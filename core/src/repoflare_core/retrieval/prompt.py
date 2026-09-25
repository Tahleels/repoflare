"""format_explain_prompt: turns an AIContextPackage into a prompt string for a BobProvider.

Kept separate from ContextRetriever (which builds the structured package) so the prompt
template can change without touching graph-query logic, and vice versa — the two are
genuinely different concerns (retrieval vs. presentation to an LLM).
"""

from __future__ import annotations

from repoflare_core.domain.entities import AIContextPackage


def format_explain_prompt(context: AIContextPackage) -> str:
    lines = [
        "You are analyzing the impact of a code change in a repository.",
        "",
        f"Directly affected symbols: {', '.join(context.direct_dependents) or 'none'}",
        "",
        "Relevant source:",
    ]
    for file_path, snippet in context.snippets.items():
        lines.append(f"--- {file_path} ---")
        lines.append(snippet)
        lines.append("")
    lines.append(
        "Explain, in plain language, what this change affects and what a developer "
        "should double-check before merging it."
    )
    return "\n".join(lines)
