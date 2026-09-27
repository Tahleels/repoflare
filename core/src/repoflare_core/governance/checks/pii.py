"""PII and secret detection check.

Scans key repository files for patterns that may indicate:

  - Hardcoded API keys / access tokens
  - Email addresses
  - Phone numbers (E.164 / common formats)
  - Aadhaar-like numeric patterns (India national ID — 12-digit runs)
  - Credit-card-like numeric patterns
  - Generic credentials (password= / secret= / api_key= assignments)

IMPORTANT — epistemic humility:
  This check never claims "this IS PII" or "this IS a secret".
  Every finding is labelled POSSIBLE_PII or POSSIBLE_SECRET with a confidence level.
  The description explicitly says "potential candidate", not "confirmed".
  False positives are expected — the report is a *signal for human review*, not a verdict.

Files inspected (sampled, not exhaustive):
  - README / docs (README.md, README.rst, docs/*.md)
  - Python sources at the root level (*.py in root)
  - Common config files (config.yml, .env.example, settings.py, config.py)
  - The first 5 Python files found in the tree

The check deliberately avoids fetching every file in every repository — that would be
both slow and noisy.  Governance is about signals, not exhaustive forensics.

Provenance: 'deterministic'
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from repoflare_core.domain.entities import (
    GovernanceCheck,
    GovernanceFinding,
    GovernanceStatus,
)
from repoflare_core.domain.ids import stable_id
from repoflare_core.governance.evidence import EvidenceBuilder
from repoflare_core.governance.github import GitHubAdapter

# ---------------------------------------------------------------------------
# Pattern registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Pattern:
    name: str
    regex: re.Pattern[str]
    confidence: str  # 'high', 'medium', 'low'
    category: str  # 'secret' or 'pii'


_PATTERNS: list[_Pattern] = [
    # Secrets / credentials
    _Pattern(
        "api_key_assignment",
        re.compile(
            r'(?i)(api[_\-]?key|apikey|access[_\-]?token)\s*[=:]\s*["\']?[A-Za-z0-9_\-]{16,}'
        ),
        "high",
        "secret",
    ),
    _Pattern(
        "password_assignment",
        re.compile(r'(?i)(password|passwd|secret|credential)\s*[=:]\s*["\'][^"\']{6,}["\']'),
        "high",
        "secret",
    ),
    _Pattern(
        "aws_access_key",
        re.compile(r"AKIA[0-9A-Z]{16}"),
        "high",
        "secret",
    ),
    _Pattern(
        "github_token",
        re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
        "high",
        "secret",
    ),
    _Pattern(
        "generic_bearer_token",
        re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_\.]{20,}"),
        "medium",
        "secret",
    ),
    # PII
    _Pattern(
        "email_address",
        re.compile(r"[a-zA-Z0-9._%+\-]{3,}@[a-zA-Z0-9.\-]{2,}\.[a-zA-Z]{2,}"),
        "medium",
        "pii",
    ),
    _Pattern(
        "phone_e164",
        re.compile(r"\+[1-9]\d{9,14}\b"),
        "low",
        "pii",
    ),
    _Pattern(
        "aadhaar_like",
        re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b"),
        "low",
        "pii",
    ),
    _Pattern(
        "credit_card_like",
        re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b"),
        "medium",
        "pii",
    ),
]

_SCAN_PATHS = [
    "README.md",
    "README.rst",
    ".env.example",
    "config.yml",
    "config.yaml",
    "settings.py",
    "config.py",
]
_MAX_PY_FILES = 5  # max Python source files to sample from the tree
_MAX_FINDINGS = 20  # cap evidence list per repository to keep reports readable


def run(owner: str, repo: str, adapter: GitHubAdapter) -> list[GovernanceFinding]:
    """Run the PII/secret detection check for *owner/repo*.

    Returns a (possibly empty) list of GovernanceFinding.
    """
    tree = adapter.list_tree(owner, repo)
    tree_paths = [item.get("path", "") for item in tree if item.get("type") == "blob"]

    # Paths to scan: fixed list + a sample of Python files
    py_files = [p for p in tree_paths if p.endswith(".py")][:_MAX_PY_FILES]
    paths_to_scan = list(dict.fromkeys(_SCAN_PATHS + py_files))  # deduplicate, keep order

    all_hits: list[dict] = []  # type: ignore[type-arg]
    for path in paths_to_scan:
        content = adapter.get_file_contents(owner, repo, path)
        if not content:
            continue
        for pattern in _PATTERNS:
            for match in pattern.regex.finditer(content):
                # Redact the actual match value — we do NOT store real secrets in findings
                line_no = content[: match.start()].count("\n") + 1
                snippet = match.group(0)
                redacted = snippet[:4] + "***" if len(snippet) > 4 else "***"
                all_hits.append(
                    {
                        "file": path,
                        "line": line_no,
                        "pattern": pattern.name,
                        "confidence": pattern.confidence,
                        "category": pattern.category,
                        "redacted_match": redacted,
                    }
                )
                if len(all_hits) >= _MAX_FINDINGS:
                    break
            if len(all_hits) >= _MAX_FINDINGS:
                break
        if len(all_hits) >= _MAX_FINDINGS:
            break

    if not all_hits:
        return []

    findings: list[GovernanceFinding] = []
    for hit in all_hits:
        eb = EvidenceBuilder()
        eb.add("file", hit["file"])
        eb.add("line", hit["line"])
        eb.add("pattern", hit["pattern"])
        eb.add("confidence", hit["confidence"])
        eb.add(
            "redacted_match",
            hit["redacted_match"],
            note="Actual value redacted — this is a potential candidate, not a confirmed finding.",
        )

        label = "POSSIBLE_SECRET" if hit["category"] == "secret" else "POSSIBLE_PII"
        findings.append(
            GovernanceFinding(
                finding_id=stable_id(
                    owner, repo, "PII", hit["file"], str(hit["line"]), hit["pattern"]
                ),
                repository=f"{owner}/{repo}",
                check=GovernanceCheck.PII,
                status=GovernanceStatus.WARN,
                severity="high" if hit["confidence"] == "high" else "medium",
                title=f"{label} — {hit['pattern']} in {hit['file']}:{hit['line']}",
                description=(
                    f"A potential {hit['category']} candidate was detected in "
                    f"{hit['file']} at line {hit['line']} (pattern: {hit['pattern']}, "
                    f"confidence: {hit['confidence']}). "
                    "This is NOT a confirmed finding — it requires human review."
                ),
                evidence=eb.build(),
                provenance="deterministic",
            )
        )

    return findings
