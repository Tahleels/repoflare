"""Repository sprawl / duplicate detection check.

Rather than comparing repository *names*, this check builds lightweight fingerprints from
multiple signals and computes pairwise similarity scores.  Repositories with high similarity
are reported as a potential duplicate cluster.

Fingerprint signals (each normalised to a 0-1 contribution):
  - README similarity     (tf-idf cosine on top-100 words)
  - Dependency overlap    (Jaccard on package names parsed from requirements.txt /
                           package.json / pyproject.toml)
  - Directory structure   (Jaccard on top-level directory names)

The algorithm deliberately avoids binary "these ARE duplicates" claims.  Instead it reports
"Potential repository cluster" with a similarity score, letting humans decide.

Threshold defaults:
  HIGH_SIMILARITY  ≥ 0.80  → FAIL (likely duplicate/fork)
  MED_SIMILARITY   ≥ 0.60  → WARN (possibly related/split project)

Provenance: 'graph_analysis'
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from repoflare_core.domain.entities import (
    GovernanceCheck,
    GovernanceFinding,
    GovernanceStatus,
)
from repoflare_core.domain.ids import stable_id
from repoflare_core.governance.evidence import EvidenceBuilder
from repoflare_core.governance.github import GitHubAdapter

_HIGH_THRESHOLD = 0.80
_MED_THRESHOLD = 0.60

# ---------------------------------------------------------------------------
# Fingerprint helpers
# ---------------------------------------------------------------------------

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "he",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "will",
    "with",
}


def _tfidf_vector(text: str) -> dict[str, float]:
    """Return a simple term-frequency dict from *text* (no IDF — single document)."""
    words = re.findall(r"[a-z]{3,}", text.lower())
    words = [w for w in words if w not in _STOP_WORDS]
    if not words:
        return {}
    counts = Counter(words)
    total = sum(counts.values())
    return {w: c / total for w, c in counts.most_common(100)}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    shared = set(a) & set(b)
    dot = sum(a[k] * b[k] for k in shared)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def _parse_deps(content: str, filename: str) -> set[str]:
    """Extract package names from common manifest files."""
    deps: set[str] = set()
    if filename == "requirements.txt":
        for line in content.splitlines():
            line = re.sub(r"[>=<!].*", "", line.strip())
            if line and not line.startswith("#"):
                deps.add(line.lower())
    elif filename == "package.json":
        for match in re.finditer(r'"([^"]+)"\s*:', content):
            name = match.group(1)
            if not name.startswith("@") and "/" not in name:
                deps.add(name.lower())
    elif filename == "pyproject.toml":
        for match in re.finditer(r'["\']([\w\-]+)["\']', content):
            deps.add(match.group(1).lower())
    return deps


@dataclass
class _RepoFingerprint:
    name: str
    readme_vec: dict[str, float] = field(default_factory=dict)
    deps: set[str] = field(default_factory=set)
    top_dirs: set[str] = field(default_factory=set)


def _build_fingerprint(owner: str, repo_meta: dict, adapter: GitHubAdapter) -> _RepoFingerprint:  # type: ignore[type-arg]
    name = repo_meta.get("name", "")
    fp = _RepoFingerprint(name=name)

    # README
    readme = adapter.get_readme(owner, name)
    fp.readme_vec = _tfidf_vector(readme)

    # Dependencies
    for manifest in ("requirements.txt", "package.json", "pyproject.toml"):
        content = adapter.get_file_contents(owner, name, manifest)
        if content:
            fp.deps |= _parse_deps(content, manifest)

    # Top-level directories (from repo tree)
    tree = adapter.list_tree(owner, name)
    fp.top_dirs = {
        item["path"].split("/")[0]
        for item in tree
        if item.get("path") and "/" in item.get("path", "")
    }

    return fp


def _similarity(a: _RepoFingerprint, b: _RepoFingerprint) -> float:
    """Return a composite similarity score in [0, 1]."""
    readme_sim = _cosine(a.readme_vec, b.readme_vec)
    dep_sim = _jaccard(a.deps, b.deps)
    dir_sim = _jaccard(a.top_dirs, b.top_dirs)
    # Weighted average: README 50%, deps 30%, dirs 20%
    return 0.50 * readme_sim + 0.30 * dep_sim + 0.20 * dir_sim


# ---------------------------------------------------------------------------
# Public check entry point
# ---------------------------------------------------------------------------


def run(
    owner: str,
    repos: list[dict],  # type: ignore[type-arg]
    adapter: GitHubAdapter,
    high_threshold: float = _HIGH_THRESHOLD,
    med_threshold: float = _MED_THRESHOLD,
) -> list[GovernanceFinding]:
    """Run the repo-sprawl check across all *repos* for *owner*.

    Only the first 10 repos are fingerprinted to stay inside rate limits during an org
    audit.  This is a sampling check, not exhaustive analysis.

    Returns a (possibly empty) list of GovernanceFinding.
    """
    sampled = repos[:10]
    fingerprints: list[_RepoFingerprint] = []
    for repo_meta in sampled:
        try:
            fp = _build_fingerprint(owner, repo_meta, adapter)
        except Exception:  # noqa: BLE001
            continue
        fingerprints.append(fp)

    findings: list[GovernanceFinding] = []
    seen_pairs: set[frozenset[str]] = set()

    for i, a in enumerate(fingerprints):
        for b in fingerprints[i + 1 :]:
            pair = frozenset({a.name, b.name})
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            score = _similarity(a, b)
            if score < med_threshold:
                continue

            status = GovernanceStatus.FAIL if score >= high_threshold else GovernanceStatus.WARN
            severity = "high" if score >= high_threshold else "medium"
            label = "Likely duplicate/fork" if score >= high_threshold else "Possibly related"

            eb = EvidenceBuilder()
            eb.add("repo_a", a.name)
            eb.add("repo_b", b.name)
            eb.add("composite_similarity", round(score, 3))
            eb.add("readme_similarity", round(_cosine(a.readme_vec, b.readme_vec), 3))
            eb.add("dependency_overlap", round(_jaccard(a.deps, b.deps), 3))
            eb.add("directory_overlap", round(_jaccard(a.top_dirs, b.top_dirs), 3))

            findings.append(
                GovernanceFinding(
                    finding_id=stable_id(owner, "REPO_SPRAWL", a.name, b.name),
                    repository=f"{owner}/{a.name}+{b.name}",
                    check=GovernanceCheck.REPO_SPRAWL,
                    status=status,
                    severity=severity,
                    title=f"{label}: {a.name} ↔ {b.name} ({round(score * 100)}% similarity)",
                    description=(
                        f"Repositories {a.name} and {b.name} in org {owner} share a "
                        f"{round(score * 100)}% composite similarity score across README "
                        "content, declared dependencies, and directory structure. "
                        "This is a potential indicator of repository sprawl or an "
                        "unintended duplication — human review is required to confirm."
                    ),
                    evidence=eb.build(),
                    provenance="graph_analysis",
                )
            )

    return findings
