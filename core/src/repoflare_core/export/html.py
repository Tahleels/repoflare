"""render_html / render_governance_html: pure functions producing self-contained static
HTML reports.

This exists specifically to satisfy the hackathon submission's required "Demo Application
URL" field (see AGENTS.md) without turning RepoFlare into a web app: it's a one-command
snapshot of output the CLI already computes (via service.py), meant to be hosted as a plain
static file (e.g. GitHub Pages). RepoFlare's actual product stays CLI + VS Code extension.

Deliberately mirrors extension/src/webview.ts's approach (a pure state-in, HTML-string-out
function; escape every dynamic value; no external assets) — this and the VS Code webview
are RepoFlare's two presentation surfaces over the exact same service.py data, and should
look and behave consistently rather than diverging.
"""

from __future__ import annotations

from html import escape as _esc

from repoflare_core.domain.entities import (
    GovernanceFinding,
    GovernanceReport,
    GovernanceStatus,
    ImpactCategory,
)
from repoflare_core.service import ImpactSummary, StatusResult

_CATEGORY_BADGE_CLASS: dict[ImpactCategory, str] = {
    ImpactCategory.DIRECT: "badge-direct",
    ImpactCategory.INDIRECT: "badge-indirect",
    ImpactCategory.RELATED: "badge-related",
    ImpactCategory.POSSIBLE: "badge-possible",
}

_CATEGORY_ORDER = [
    ImpactCategory.DIRECT,
    ImpactCategory.INDIRECT,
    ImpactCategory.RELATED,
    ImpactCategory.POSSIBLE,
]


def render_html(
    repository_root: str,
    status: StatusResult,
    impact: ImpactSummary | None = None,
    impact_refs: tuple[str, str] | None = None,
) -> str:
    """`impact`/`impact_refs` are both None for an overview-only report; both set together
    for an overview + impact report. (Not enforced by the type system — this is a rendering
    function, not a validating boundary; the CLI caller always passes them as a pair.)"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
<title>RepoFlare report</title>
{_styles()}
</head>
<body>
{_header()}
<div class="muted">{_esc(repository_root)}</div>
{_snapshot_section(status)}
{_impact_section(impact, impact_refs) if impact is not None and impact_refs is not None else ""}
</body>
</html>"""


def _styles() -> str:
    return """<style>
  :root { --gap: 16px; }
  body { font-family: -apple-system, "Segoe UI", sans-serif; font-size: 14px; color: #1e1e1e;
         background: #ffffff; margin: 0; padding: 24px; line-height: 1.5; max-width: 900px; }
  h1 { font-size: 1.3em; font-weight: 600; margin: 0 0 4px; }
  h2 { font-size: 1.05em; font-weight: 600; margin: var(--gap) 0 8px;
       border-bottom: 1px solid #ddd; padding-bottom: 4px; }
  .muted { color: #6a6a6a; font-size: 0.9em; }
  .badge { display: inline-block; padding: 1px 7px; border-radius: 9px; font-size: 0.8em;
           font-weight: 600; color: #fff; }
  .badge-direct { background: #c53030; }
  .badge-indirect { background: #b7791f; }
  .badge-related { background: #2b6cb0; }
  .badge-possible { background: #276749; }
  .stat-row { display: flex; gap: var(--gap); margin-bottom: var(--gap); }
  .stat-card { background: #f5f5f5; border: 1px solid #ddd; border-radius: 6px;
               padding: 10px 16px; min-width: 100px; }
  .stat-card .value { font-size: 1.6em; font-weight: 700; }
  .stat-card .label { font-size: 0.8em; color: #6a6a6a; }
  table { border-collapse: collapse; width: 100%; margin-top: 8px; }
  th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid #eee; font-size: 0.9em; }
  th { color: #6a6a6a; font-weight: 600; }
  .filepath { font-family: monospace; color: #2b6cb0; }
  .snap-id { font-family: monospace; font-size: 0.85em; }
  .changed-list { padding-left: 18px; margin: 4px 0 12px; }
  .changed-list li { font-family: monospace; font-size: 0.88em; }
  .empty-state { color: #6a6a6a; padding: 12px 0; font-style: italic; }
  .generated { color: #999; font-size: 0.8em; margin-top: 32px; }
</style>"""


def _header() -> str:
    return """<div style="margin-bottom:var(--gap)">
  <h1>RepoFlare</h1>
  <div class="muted">Repository intelligence report</div>
</div>"""


def _snapshot_section(status: StatusResult) -> str:
    snap_line = (
        f'<span class="snap-id">{_esc(status.snapshot_id)}</span>'
        if status.snapshot_id
        else '<span class="muted">not yet analyzed</span>'
    )
    return f"""
<h2>Snapshot</h2>
<div style="margin-bottom:var(--gap)">{snap_line}</div>
<div class="stat-row">
  <div class="stat-card"><div class="value">{status.node_count}</div>
    <div class="label">Nodes</div></div>
  <div class="stat-card"><div class="value">{status.edge_count}</div>
    <div class="label">Edges</div></div>
</div>"""


def _impact_section(impact: ImpactSummary, refs: tuple[str, str]) -> str:
    from_ref, to_ref = refs
    changed_section = (
        '<div class="empty-state">No changed files between these refs.</div>'
        if not impact.changed_files
        else '<ul class="changed-list">'
        + "".join(f"<li>{_esc(f)}</li>" for f in impact.changed_files)
        + "</ul>"
    )
    impact_section = (
        '<div class="empty-state">No affected nodes found.</div>'
        if not impact.results
        else _impact_table(impact)
    )
    return f"""
<h2>Changed files <span class="muted">{_esc(from_ref)} → {_esc(to_ref)}</span></h2>
{changed_section}

<h2>Affected nodes</h2>
{impact_section}
<div class="generated">Generated by <code>repoflare export-html</code>.</div>"""


def _impact_table(impact: ImpactSummary) -> str:
    results_by_category = {r.category: r for r in impact.results}
    rows: list[str] = []
    for category in _CATEGORY_ORDER:
        result = results_by_category.get(category)
        if result is None:
            continue
        badge_class = _CATEGORY_BADGE_CLASS[category]
        for node_id in result.affected_node_ids:
            summary = impact.node_summaries.get(node_id)
            label = summary.label if summary else node_id
            file_path = summary.file_path if summary and summary.file_path else ""
            rows.append(
                f'<tr><td><span class="badge {badge_class}">{_esc(category.value)}</span></td>'
                f'<td>{_esc(label)}</td><td class="filepath">{_esc(file_path)}</td></tr>'
            )
    return (
        "<table><thead><tr><th>Category</th><th>Symbol</th><th>File</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Governance report renderer
# ---------------------------------------------------------------------------

_STATUS_BADGE: dict[GovernanceStatus, str] = {
    GovernanceStatus.PASS: "badge-possible",  # green
    GovernanceStatus.WARN: "badge-indirect",  # amber
    GovernanceStatus.FAIL: "badge-direct",  # red
    GovernanceStatus.UNKNOWN: "badge-related",  # blue
}

_STATUS_ICON = {
    GovernanceStatus.PASS: "✓",
    GovernanceStatus.WARN: "⚠",
    GovernanceStatus.FAIL: "✗",
    GovernanceStatus.UNKNOWN: "?",
}

_CHECK_SECTION = {
    "DEPENDABOT": "Security",
    "STALE_PR": "Delivery",
    "CONFLICT": "Delivery",
    "DEPLOY_WITHOUT_TEST": "Delivery",
    "PII": "Data Security",
    "REPO_SPRAWL": "Repository Health",
    "PLAN_BEFORE_SHIP": "AI Governance",
    "INFLATED_DIFF": "AI Governance",
    "HITL": "AI Governance",
}

_SECTION_ORDER = ["Security", "Delivery", "Repository Health", "Data Security", "AI Governance"]


def render_governance_html(report: GovernanceReport) -> str:
    """Render a self-contained static HTML governance audit report."""
    from datetime import UTC as _UTC

    generated = report.generated_at.astimezone(_UTC).strftime("%Y-%m-%d %H:%M UTC")

    # Group findings by section
    sections: dict[str, list[GovernanceFinding]] = {s: [] for s in _SECTION_ORDER}
    for finding in report.findings:
        section = _CHECK_SECTION.get(finding.check.value, "Other")
        sections.setdefault(section, []).append(finding)

    # Summary counts
    fail_count = sum(1 for f in report.findings if f.status == GovernanceStatus.FAIL)
    warn_count = sum(1 for f in report.findings if f.status == GovernanceStatus.WARN)
    pass_count = sum(1 for f in report.findings if f.status == GovernanceStatus.PASS)

    sections_html = "\n".join(
        _governance_section(name, sections[name]) for name in _SECTION_ORDER if sections.get(name)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
<title>RepoFlare Governance Audit — {_esc(report.org)}</title>
{_styles()}
{_governance_styles()}
</head>
<body>
{_governance_header(report.org, generated, len(report.repositories))}
<div class="stat-row">
  <div class="stat-card"><div class="value fail-color">{fail_count}</div>
    <div class="label">Failures</div></div>
  <div class="stat-card"><div class="value warn-color">{warn_count}</div>
    <div class="label">Warnings</div></div>
  <div class="stat-card"><div class="value pass-color">{pass_count}</div>
    <div class="label">Passing</div></div>
  <div class="stat-card"><div class="value">{len(report.repositories)}</div>
    <div class="label">Repositories</div></div>
</div>
{sections_html}
<div class="generated">Generated by <code>repoflare audit --html</code> on {_esc(generated)}.</div>
</body>
</html>"""


def _governance_styles() -> str:
    return """<style>
  .fail-color { color: #c53030; }
  .warn-color { color: #b7791f; }
  .pass-color { color: #276749; }
  .finding { border: 1px solid #e0e0e0; border-radius: 6px; padding: 10px 14px;
             margin-bottom: 8px; background: #fafafa; }
  .finding-title { font-weight: 600; font-size: 0.95em; margin-bottom: 4px; }
  .finding-desc { font-size: 0.88em; color: #444; margin-bottom: 6px; }
  .evidence-list { margin: 4px 0 0 0; padding: 0; list-style: none; }
  .evidence-list li { font-size: 0.82em; color: #6a6a6a; font-family: monospace;
                      padding: 1px 0; }
  .provenance { font-size: 0.78em; color: #999; margin-top: 4px; }
</style>"""


def _governance_header(org: str, generated: str, repo_count: int) -> str:
    return f"""<div style="margin-bottom:var(--gap)">
  <h1>RepoFlare Governance Audit</h1>
  <div class="muted">Organisation: <strong>{_esc(org)}</strong>
    &nbsp;·&nbsp; {repo_count} repositories
    &nbsp;·&nbsp; {_esc(generated)}</div>
</div>"""


def _governance_section(name: str, findings: list[GovernanceFinding]) -> str:
    if not findings:
        return ""
    items = "\n".join(_finding_card(f) for f in findings)
    return f"<h2>{_esc(name)}</h2>\n{items}\n"


def _finding_card(finding) -> str:  # type: ignore[no-untyped-def]
    badge_class = _STATUS_BADGE.get(finding.status, "badge-related")
    icon = _STATUS_ICON.get(finding.status, "?")
    evidence_items = "".join(
        f"<li><strong>{_esc(str(e.get('key', '')))}</strong>:"
        f" {_esc(str(e.get('value', ''))[:120])}</li>"
        for e in (finding.evidence or [])[:6]
    )
    evidence_html = f'<ul class="evidence-list">{evidence_items}</ul>' if evidence_items else ""
    return f"""<div class="finding">
  <div class="finding-title">
    <span class="badge {badge_class}">{_esc(icon)} {_esc(finding.status.value)}</span>
    &nbsp;{_esc(finding.title)}
  </div>
  <div class="finding-desc">{_esc(finding.description)}</div>
  {evidence_html}
  <div class="provenance">provenance: {_esc(finding.provenance)}</div>
</div>"""
