"""HITL (Human-in-the-loop) outsourcing detection check.

Bob looks for evidence that the final architectural decision in a PR was independently
reasoned about by a human reviewer — rather than delegated end-to-end to AI tooling.

IMPORTANT — epistemic humility:
  Bob must NOT claim "No human reviewed this."
  The check asks: "Is there evidence of *substantive* human decision-making?"

  The distinction:
    "LGTM" after an AI-generated explanation  →  review *present*, substance *unknown*
    Detailed inline comments challenging design  →  substantive review *present*

Possible verdicts:
  SUBSTANTIVE_REVIEW_PRESENT   — reviewer(s) engaged substantively
  REVIEW_PRESENT_SUBSTANCE_UNKNOWN  — review actions exist but substance is unclear
  INSUFFICIENT_REVIEW_EVIDENCE — no review actions detected

Status mapping:
  SUBSTANTIVE_REVIEW_PRESENT        → PASS
  REVIEW_PRESENT_SUBSTANCE_UNKNOWN  → WARN
  INSUFFICIENT_REVIEW_EVIDENCE      → FAIL

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

_LGTM_PATTERN = re.compile(r"\blgtm\b", re.IGNORECASE)
_SHORT_APPROVAL_PATTERN = re.compile(
    r"^(lgtm|looks good|approved|ship it|✓|👍|:\+1:)\s*$", re.IGNORECASE
)


def _is_shallow_approval(body: str) -> bool:
    return bool(_SHORT_APPROVAL_PATTERN.match(body.strip()))


def _build_prompt(ctx: GovernanceContextPackage) -> str:
    lines = [
        "You are a governance auditor reviewing a pull request for evidence of substantive",
        "human review — specifically whether the final decision to merge was made by a human",
        "who independently reasoned about the change, rather than rubber-stamping AI output.",
        "",
        "## PR Information",
        f"Title: {ctx.pr_title}",
        f"Author: {ctx.author}",
        f"Changed files: {ctx.changed_file_count}  (+{ctx.additions} / -{ctx.deletions})",
        "",
        "## PR Description",
        ctx.pr_description or "(no description provided)",
        "",
    ]

    if ctx.review_comments:
        lines.append("## Review Actions")
        for rv in ctx.review_comments[:8]:
            lines.append(f"  [{rv['author']} — {rv['state']}] {rv['body'][:200]}")
        lines.append("")

    if ctx.issue_comments:
        lines.append("## Discussion Comments")
        for cm in ctx.issue_comments[:8]:
            lines.append(f"  [{cm['author']}] {cm['body'][:200]}")
        lines.append("")

    lines += [
        "## Your Task",
        "Determine whether there is evidence that a human reviewer independently and",
        "substantively reasoned about this change — not just approved it.",
        "",
        "Return ONLY valid JSON in this exact shape:",
        "{",
        '  "finding": "HITL",',
        '  "verdict": "SUBSTANTIVE_REVIEW_PRESENT" |',
        '             "REVIEW_PRESENT_SUBSTANCE_UNKNOWN" |',
        '             "INSUFFICIENT_REVIEW_EVIDENCE",',
        '  "human_review_detected": true | false,',
        '  "substantive_evidence": ["...brief bullet points of substantive signals..."],',
        '  "ai_rationale_detected": true | false,',
        '  "reasoning": "...one paragraph..."',
        "}",
        "",
        "Rules:",
        "- Do NOT say 'No human reviewed this' — say there is insufficient evidence.",
        "- A single 'LGTM' comment counts as review_detected=true, substance=unknown.",
        "- Inline code comments challenging design count as substantive evidence.",
        "- Keep reasoning to ≤ 3 sentences.",
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
) -> GovernanceFinding:
    """Run the HITL outsourcing check using Bob."""
    prompt = _build_prompt(ctx)
    try:
        raw = provider.complete(prompt)
        parsed = _parse_response(raw)
    except Exception as exc:  # noqa: BLE001
        parsed = {}
        raw = f"Provider error: {exc}"

    verdict = parsed.get("verdict", "REVIEW_PRESENT_SUBSTANCE_UNKNOWN")
    reasoning = parsed.get("reasoning", raw[:400] if raw else "No response.")
    human_review_detected = parsed.get("human_review_detected")
    ai_rationale_detected = parsed.get("ai_rationale_detected")
    substantive_bullets: list[str] = parsed.get("substantive_evidence", [])

    status_map = {
        "SUBSTANTIVE_REVIEW_PRESENT": GovernanceStatus.PASS,
        "REVIEW_PRESENT_SUBSTANCE_UNKNOWN": GovernanceStatus.WARN,
        "INSUFFICIENT_REVIEW_EVIDENCE": GovernanceStatus.FAIL,
    }
    status = status_map.get(verdict.upper(), GovernanceStatus.UNKNOWN)
    severity_map = {
        GovernanceStatus.PASS: "info",
        GovernanceStatus.WARN: "medium",
        GovernanceStatus.FAIL: "high",
        GovernanceStatus.UNKNOWN: "medium",
    }

    eb = EvidenceBuilder()
    eb.add("pr_number", ctx.pr_number)
    eb.add("verdict", verdict)
    eb.add("human_review_detected", human_review_detected)
    eb.add("ai_rationale_detected", ai_rationale_detected)
    eb.add("reasoning", reasoning)
    for bullet in substantive_bullets[:10]:
        eb.add("substantive_evidence", bullet)

    # Heuristic pre-computation: count shallow vs substantive review comments
    shallow = sum(1 for rv in ctx.review_comments if _is_shallow_approval(rv.get("body", "")))
    total_reviews = len(ctx.review_comments)
    eb.add("review_comment_count", total_reviews)
    eb.add("shallow_approval_count", shallow)

    return GovernanceFinding(
        finding_id=stable_id(owner, repo, "HITL", str(ctx.pr_number)),
        repository=f"{owner}/{repo}",
        check=GovernanceCheck.HITL,
        status=status,
        severity=severity_map.get(status, "medium"),
        title=f"HITL [{verdict}] — PR #{ctx.pr_number}",
        description=(f"PR #{ctx.pr_number} ({ctx.pr_title[:80]}): {reasoning}"),
        evidence=eb.build(),
        provenance="bob_reasoning",
    )
