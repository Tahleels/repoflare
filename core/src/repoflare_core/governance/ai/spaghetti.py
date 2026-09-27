"""Inflated-diff / spaghetti AI governance check.

Bob examines:
  - PR description
  - Diff statistics (file count, +/-)
  - Changed file list (filenames + status)
  - Sample patch text

And determines whether the diff appears inflated — i.e. the changeset contains significant
portions unrelated to the stated feature/fix.

Possible verdicts:
  CLEAN          — diff looks proportionate to stated purpose
  INFLATED_DIFF  — files changed appear disproportionate to stated purpose
  UNKNOWN        — Bob cannot determine from available context

Severity:
  INFLATED_DIFF is WARN (not FAIL) — it is a code-review signal, not a blocker.
  It is most actionable when the PR author can be asked to split the PR.

Provenance: 'bob_reasoning'
"""

from __future__ import annotations

import json
import re
from typing import Any

from repoflare_core.domain.entities import (
    GovernanceCheck,
    GovernanceFinding,
    GovernanceStatus,
)
from repoflare_core.domain.ids import stable_id
from repoflare_core.governance.evidence import EvidenceBuilder
from repoflare_core.retrieval.governance_context import GovernanceContextPackage

_LARGE_PR_FILE_THRESHOLD = 15
"""PRs changing fewer than this many files are not sent to Bob — they're unlikely to be
inflated and sending every small PR wastes API budget."""


def _build_prompt(ctx: GovernanceContextPackage) -> str:
    lines = [
        "You are a governance auditor reviewing a pull request for diff inflation.",
        "",
        "## PR Information",
        f"Title: {ctx.pr_title}",
        f"Author: {ctx.author}",
        f"Changed files: {ctx.changed_file_count}  (+{ctx.additions} / -{ctx.deletions})",
        "",
        "## PR Description",
        ctx.pr_description or "(no description provided)",
        "",
        "## Changed Files",
    ]
    for f in ctx.changed_files[:30]:
        lines.append(f"  {f['filename']}  [{f['status']}]  +{f['additions']}/-{f['deletions']}")
    lines.append("")

    if ctx.commit_messages:
        lines.append("## Commit Messages")
        for msg in ctx.commit_messages[:5]:
            lines.append(f"- {msg}")
        lines.append("")

    lines += [
        "## Your Task",
        "Determine whether the diff is inflated — i.e. the changeset contains significant",
        "portions unrelated to the stated PR purpose.",
        "",
        "Return ONLY valid JSON in this exact shape:",
        "{",
        '  "finding": "INFLATED_DIFF",',
        '  "verdict": "CLEAN" | "INFLATED_DIFF" | "UNKNOWN",',
        '  "unrelated_files": ["list of filenames you judge unrelated, if any"],',
        '  "reasoning": "...one paragraph..."',
        "}",
        "",
        "Rules:",
        "- Base your judgment on whether the changed files match the PR title/description.",
        "- Lockfile changes (package-lock.json, uv.lock, poetry.lock) count as expected",
        "  and should not be listed as unrelated unless they are the only change.",
        "- Keep reasoning to ≤ 3 sentences.",
        "- Do NOT use any verdict other than the three listed above.",
    ]
    return "\n".join(lines)


def _parse_response(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        return {}
    try:
        parsed: dict[str, Any] = json.loads(cleaned[start:end])
        return parsed
    except json.JSONDecodeError:
        return {}


def run(
    owner: str,
    repo: str,
    ctx: GovernanceContextPackage,
    provider: Any,  # BobProvider
) -> GovernanceFinding | None:
    """Run the inflated-diff check using Bob.

    Returns ``None`` when the PR is below the file-count threshold (too small to be worth
    checking).
    """
    if ctx.changed_file_count < _LARGE_PR_FILE_THRESHOLD:
        return None

    prompt = _build_prompt(ctx)
    try:
        raw = provider.complete(prompt)
        parsed = _parse_response(raw)
    except Exception as exc:  # noqa: BLE001
        parsed = {}
        raw = f"Provider error: {exc}"

    verdict = parsed.get("verdict", "UNKNOWN")
    reasoning = parsed.get("reasoning", raw[:400] if raw else "No response.")
    unrelated = parsed.get("unrelated_files", [])

    status_map = {
        "CLEAN": GovernanceStatus.PASS,
        "INFLATED_DIFF": GovernanceStatus.WARN,
        "UNKNOWN": GovernanceStatus.UNKNOWN,
    }
    status = status_map.get(verdict.upper(), GovernanceStatus.UNKNOWN)

    eb = EvidenceBuilder()
    eb.add("pr_number", ctx.pr_number)
    eb.add("changed_file_count", ctx.changed_file_count)
    eb.add("additions", ctx.additions)
    eb.add("deletions", ctx.deletions)
    eb.add("verdict", verdict)
    eb.add("reasoning", reasoning)
    for uf in unrelated[:15]:
        eb.add("unrelated_file", uf)

    return GovernanceFinding(
        finding_id=stable_id(owner, repo, "INFLATED_DIFF", str(ctx.pr_number)),
        repository=f"{owner}/{repo}",
        check=GovernanceCheck.INFLATED_DIFF,
        status=status,
        severity="medium",
        title=f"Inflated diff [{verdict}] — PR #{ctx.pr_number} ({ctx.changed_file_count} files)",
        description=(f"PR #{ctx.pr_number} ({ctx.pr_title[:80]}): {reasoning}"),
        evidence=eb.build(),
        provenance="bob_reasoning",
    )
