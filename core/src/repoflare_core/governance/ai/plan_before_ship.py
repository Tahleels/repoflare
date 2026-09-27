"""Plan-before-ship AI governance check.

Bob examines the PR evidence package and determines whether there is sufficient signal that
the implementation was reasoned about / planned before being shipped.

IMPORTANT — this is NOT a binary "AI wrote this" detector.  Claiming that is neither
defensible nor the right governance signal.  Instead, the check asks:

  "Is there evidence that a human planned or reasoned about this change before it landed?"

Possible verdicts:

  EVIDENCE_PRESENT       — PR description / commits / discussions show clear reasoning
  INSUFFICIENT_EVIDENCE  — No substantive planning signal found
  UNKNOWN                — Bob could not make a determination from the available context

The finding status maps as:
  EVIDENCE_PRESENT       → PASS
  INSUFFICIENT_EVIDENCE  → WARN
  UNKNOWN                → UNKNOWN

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

_VERDICT_PATTERN = re.compile(
    r'"verdict"\s*:\s*"(EVIDENCE_PRESENT|INSUFFICIENT_EVIDENCE|UNKNOWN)"', re.IGNORECASE
)


def _build_prompt(ctx: GovernanceContextPackage) -> str:
    lines = [
        "You are a governance auditor reviewing a pull request for evidence of planning.",
        "",
        "## PR Information",
        f"Title: {ctx.pr_title}",
        f"Author: {ctx.author}",
        f"Changed files: {ctx.changed_file_count} (+{ctx.additions}/-{ctx.deletions})",
        "",
        "## PR Description",
        ctx.pr_description or "(no description provided)",
        "",
    ]

    if ctx.commit_messages:
        lines.append("## Commit Messages (most recent first)")
        for msg in ctx.commit_messages[:5]:
            lines.append(f"- {msg}")
        lines.append("")

    if ctx.review_comments:
        lines.append("## Review Discussion")
        for rv in ctx.review_comments[:5]:
            lines.append(f"[{rv['author']} — {rv['state']}] {rv['body']}")
        lines.append("")

    if ctx.issue_comments:
        lines.append("## Comments")
        for cm in ctx.issue_comments[:5]:
            lines.append(f"[{cm['author']}] {cm['body']}")
        lines.append("")

    lines += [
        "## Your Task",
        "Determine whether there is evidence that a human reasoned about / planned this",
        "change before it was shipped.",
        "",
        "Return ONLY valid JSON in this exact shape:",
        "{",
        '  "finding": "PLAN_BEFORE_SHIP",',
        '  "verdict": "EVIDENCE_PRESENT" | "INSUFFICIENT_EVIDENCE" | "UNKNOWN",',
        '  "evidence": ["...brief bullet points..."],',
        '  "reasoning": "...one paragraph..."',
        "}",
        "",
        "Rules:",
        "- Do NOT claim the code was AI-generated.",
        "- Do NOT use any verdict other than the three listed above.",
        "- Keep reasoning to ≤ 3 sentences.",
        "- If you cannot determine from the context, use UNKNOWN.",
    ]
    return "\n".join(lines)


def _parse_response(text: str) -> dict[str, Any]:
    """Extract the JSON object from Bob's response, tolerating markdown fences."""
    # Strip ```json ... ``` fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")
    # Find first { ... }
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
    provider: Any,  # BobProvider — typed Any to avoid circular import
) -> GovernanceFinding:
    """Run the plan-before-ship check using Bob.

    Args:
        owner:    GitHub org/user.
        repo:     Repository name.
        ctx:      Pre-built GovernanceContextPackage for the PR.
        provider: A BobProvider instance (same interface as code-intelligence layer).
    """
    prompt = _build_prompt(ctx)
    try:
        raw = provider.complete(prompt)
        parsed = _parse_response(raw)
    except Exception as exc:  # noqa: BLE001
        parsed = {}
        raw = f"Provider error: {exc}"

    verdict = parsed.get("verdict", "UNKNOWN")
    reasoning = parsed.get("reasoning", raw[:400] if raw else "No response.")
    evidence_bullets: list[str] = parsed.get("evidence", [])

    status_map = {
        "EVIDENCE_PRESENT": GovernanceStatus.PASS,
        "INSUFFICIENT_EVIDENCE": GovernanceStatus.WARN,
        "UNKNOWN": GovernanceStatus.UNKNOWN,
    }
    status = status_map.get(verdict.upper(), GovernanceStatus.UNKNOWN)

    eb = EvidenceBuilder()
    eb.add("pr_number", ctx.pr_number)
    eb.add("verdict", verdict)
    eb.add("reasoning", reasoning)
    for bullet in evidence_bullets[:10]:
        eb.add("evidence_bullet", bullet)

    return GovernanceFinding(
        finding_id=stable_id(owner, repo, "PLAN_BEFORE_SHIP", str(ctx.pr_number)),
        repository=f"{owner}/{repo}",
        check=GovernanceCheck.PLAN_BEFORE_SHIP,
        status=status,
        severity="medium",
        title=f"Plan-before-ship [{verdict}] — PR #{ctx.pr_number}",
        description=(f"PR #{ctx.pr_number} ({ctx.pr_title[:80]}): {reasoning}"),
        evidence=eb.build(),
        provenance="bob_reasoning",
    )
