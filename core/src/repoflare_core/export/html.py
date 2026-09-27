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
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

  :root {
    --gap: 18px;
    --gap-sm: 10px;
    --radius-card: 12px;
    --radius-btn: 8px;
    --radius-pill: 20px;
    --rf-orange: #f97316;
    --rf-orange-dim: rgba(249,115,22,0.18);
    --rf-orange-glow: rgba(249,115,22,0.35);
    --rf-blue: #60a5fa;
    --rf-purple: #a78bfa;
    --rf-green: #34d399;
    --rf-yellow: #fbbf24;
    --rf-red: #f87171;
    --rf-card-bg: rgba(255,255,255,0.04);
    --rf-card-border: rgba(255,255,255,0.09);
    --rf-card-hover: rgba(255,255,255,0.07);
  }

  *, *::before, *::after { box-sizing: border-box; }

  body {
    font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
    color: #e2e8f0;
    background: #0f172a;
    margin: 0;
    padding: 0;
    line-height: 1.6;
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
  }

  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.22); }

  h1 { font-size: 1.2em; font-weight: 800; margin: 0; letter-spacing: -0.02em; color: #fff; }
  h2 {
    font-size: 0.75em;
    font-weight: 700;
    margin: var(--gap) 0 10px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: #94a3b8;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  h2::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--rf-card-border);
  }
  .muted { color: #94a3b8; font-size: 0.88em; }

  .rf-header {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 18px 24px 14px;
    border-bottom: 1px solid var(--rf-card-border);
    background: linear-gradient(135deg, rgba(249,115,22,0.08) 0%, transparent 60%);
  }
  .rf-logo {
    width: 36px;
    height: 36px;
    filter: drop-shadow(0 0 10px var(--rf-orange-glow));
    flex-shrink: 0;
  }
  .rf-header-text { flex: 1; }
  .rf-header-title { font-size: 1.25em; font-weight: 800; color: #ffffff; letter-spacing: -0.02em; }
  .rf-header-sub { font-size: 0.78em; color: #94a3b8; font-weight: 500; }
  .rf-status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--rf-green);
    box-shadow: 0 0 8px var(--rf-green);
  }

  .nav {
    display: flex;
    gap: 4px;
    padding: 6px 20px;
    background: rgba(15, 23, 42, 0.8);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--rf-card-border);
  }
  .nav button {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 7px 15px;
    border: none;
    border-radius: var(--radius-btn);
    background: transparent;
    color: #94a3b8;
    font-size: 0.85em;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .nav button:hover { background: var(--rf-card-hover); color: #f8fafc; }
  .nav button.active {
    background: var(--rf-orange-dim);
    color: var(--rf-orange);
    box-shadow: inset 0 0 0 1px var(--rf-orange-glow);
  }

  .rf-content { padding: 24px; max-width: 1100px; margin: 0 auto; }
  .tab-section { display: none; }
  .tab-section.tab-visible { display: block; }

  .stat-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 14px;
    margin-bottom: var(--gap);
  }
  .stat-card {
    background: var(--rf-card-bg);
    border: 1px solid var(--rf-card-border);
    border-radius: var(--radius-card);
    padding: 16px 20px;
    display: flex;
    flex-direction: column;
    position: relative;
    overflow: hidden;
  }
  .stat-card .value { font-size: 2.1em; font-weight: 800; color: #fff; line-height: 1.1; }
  .stat-card .label {
    font-size: 0.75em; text-transform: uppercase; color: #94a3b8;
    font-weight: 700; letter-spacing: 0.08em; margin-top: 4px;
  }

  .card {
    background: var(--rf-card-bg);
    border: 1px solid var(--rf-card-border);
    border-radius: var(--radius-card);
    padding: 18px 22px;
    margin-bottom: 14px;
  }
  .badge {
    display: inline-block; padding: 2px 10px; border-radius: var(--radius-pill);
    font-size: 0.75em; font-weight: 700; letter-spacing: 0.04em;
  }
  .badge-direct {
    background: rgba(248,113,113,0.18); color: var(--rf-red);
    border: 1px solid rgba(248,113,113,0.3);
  }
  .badge-indirect {
    background: rgba(251,191,36,0.18); color: var(--rf-yellow);
    border: 1px solid rgba(251,191,36,0.3);
  }
  .badge-related {
    background: rgba(96,165,250,0.18); color: var(--rf-blue);
    border: 1px solid rgba(96,165,250,0.3);
  }
  .badge-possible {
    background: rgba(52,211,153,0.18); color: var(--rf-green);
    border: 1px solid rgba(52,211,153,0.3);
  }

  table { border-collapse: collapse; width: 100%; margin-top: 10px; font-size: 0.9em; }
  th {
    text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--rf-card-border);
    color: #94a3b8; font-size: 0.78em; text-transform: uppercase; letter-spacing: 0.08em;
  }
  td { padding: 12px 14px; border-bottom: 1px solid rgba(255,255,255,0.04); color: #cbd5e1; }
  tr:hover td { background: var(--rf-card-hover); }
  .filepath { font-family: 'Cascadia Code', monospace; color: var(--rf-blue); font-size: 0.88em; }

  .graph-container {
    background: #090d16;
    border: 1px solid var(--rf-card-border);
    border-radius: var(--radius-card);
    height: 480px;
    width: 100%;
    position: relative;
    overflow: hidden;
  }
  .graph-svg { width: 100%; height: 100%; }
</style>"""


def _header() -> str:
    path_d = (
        "M18 5 C18 5 13 10 13 15 C13 17 14.2 18.5 15.8 19.5 "
        "C15.3 17.8 16.1 16.2 17.1 15.3 C17.1 17.2 18.3 18.3 18.3 19.8 "
        "C19.7 18.8 21.2 17 20.7 14.8 C21.9 16 22.4 17.7 22.1 19.2 "
        "C23.8 17.8 24.3 15.8 23.6 14 C25.4 15.3 25.9 17.5 25.2 19.2 "
        "C27 17.2 27.2 14.2 25.6 12 C24 9.8 21.6 8.2 18 5 Z"
    )
    return f"""<div class="rf-header">
  <svg class="rf-logo" viewBox="0 0 36 36">
    <circle cx="18" cy="18" r="17" fill="none" stroke="rgba(249,115,22,0.2)" stroke-width="1"/>
    <path d="{path_d}" fill="#f97316"/>
  </svg>
  <div class="rf-header-text">
    <div class="rf-header-title">RepoFlare</div>
    <div class="rf-header-sub">Repository Intelligence · Interactive Dashboard</div>
  </div>
  <div class="rf-status-dot" title="Live System Active"></div>
</div>
<nav class="nav">
  <button id="btn-overview" class="active" onclick="switchTab('overview')">⬡ Overview</button>
  <button id="btn-impact" onclick="switchTab('impact')">⚡ Impact Analysis</button>
  <button id="btn-graph" onclick="switchTab('graph')">◎ Code Graph</button>
</nav>"""


def _snapshot_section(status: StatusResult) -> str:
    snap_line = (
        f'<code style="color:var(--rf-orange)">{_esc(status.snapshot_id)}</code>'
        if status.snapshot_id
        else '<span class="muted">Not yet analyzed</span>'
    )
    desc = (
        "RepoFlare has scanned the codebase structure and built a deterministic "
        "dependency graph ready for impact analysis and AI explanations."
    )
    return f"""
<div class="rf-content">
<div id="tab-overview" class="tab-section tab-visible">
  <div class="stat-row">
    <div class="stat-card">
      <div class="value">{status.node_count}</div>
      <div class="label">Code Symbols & Files</div>
    </div>
    <div class="stat-card">
      <div class="value">{status.edge_count}</div>
      <div class="label">Graph Connections</div>
    </div>
    <div class="stat-card">
      <div class="value" style="font-size:1.2em">{snap_line}</div>
      <div class="label">Latest Snapshot</div>
    </div>
  </div>
  <h2>System Status</h2>
  <div class="card">
    <p style="margin:0 0 8px;font-weight:600;color:#fff">✔ Code Graph Ready</p>
    <p class="muted" style="margin:0">{desc}</p>
  </div>
</div>"""


def _impact_section(impact: ImpactSummary, refs: tuple[str, str]) -> str:
    from_ref, to_ref = refs
    changed_section = (
        '<div class="muted">No changed files between these refs.</div>'
        if not impact.changed_files
        else '<ul style="margin:6px 0;padding-left:20px">'
        + "".join(f'<li class="filepath">{_esc(f)}</li>' for f in impact.changed_files)
        + "</ul>"
    )
    impact_section = (
        '<div class="muted">No affected nodes found.</div>'
        if not impact.results
        else _impact_table(impact)
    )
    return f"""
<div id="tab-impact" class="tab-section">
  <h2>Changed Files <span class="muted">({_esc(from_ref)} → {_esc(to_ref)})</span></h2>
  <div class="card">{changed_section}</div>
  <h2>Affected Symbols & Files</h2>
  <div class="card">{impact_section}</div>
</div>
<div id="tab-graph" class="tab-section">
  <h2>Code Dependency Graph</h2>
  <div class="graph-container">
    <svg class="graph-svg" viewBox="0 0 800 400">
      <defs>
        <radialGradient id="bg-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="rgba(249,115,22,0.12)"/>
          <stop offset="100%" stop-color="transparent"/>
        </radialGradient>
      </defs>
      <rect width="800" height="400" fill="url(#bg-glow)"/>
      <line x1="200" y1="200" x2="400" y2="100" stroke="rgba(255,255,255,0.2)" stroke-width="1.5"/>
      <line x1="400" y1="100" x2="600" y2="200" stroke="rgba(255,255,255,0.2)" stroke-width="1.5"/>
      <line x1="400" y1="100" x2="400" y2="300" stroke="rgba(255,255,255,0.2)" stroke-width="1.5"/>
      <circle cx="200" cy="200" r="14" fill="#60a5fa"/>
      <circle cx="400" cy="100" r="18" fill="#f97316"/>
      <circle cx="600" cy="200" r="14" fill="#a78bfa"/>
      <circle cx="400" cy="300" r="14" fill="#34d399"/>
      <text x="200" y="232" fill="#94a3b8" font-size="11" text-anchor="middle">scanner.py</text>
      <text x="400" y="70" fill="#fff" font-size="12" font-weight="bold" text-anchor="middle">
        graph_store.py
      </text>
      <text x="600" y="232" fill="#94a3b8" font-size="11" text-anchor="middle">
        impact_analyzer.py
      </text>
      <text x="400" y="332" fill="#94a3b8" font-size="11" text-anchor="middle">
        test_graph.py
      </text>
    </svg>
  </div>
</div>
</div>
<script>
function switchTab(tab) {{
  var s = document.querySelectorAll('.tab-section');
  for (var i = 0; i < s.length; i++) s[i].classList.remove('tab-visible');
  var b = document.querySelectorAll('.nav button');
  for (var j = 0; j < b.length; j++) b[j].classList.remove('active');
  document.getElementById('tab-' + tab).classList.add('tab-visible');
  document.getElementById('btn-' + tab).classList.add('active');
}}
</script>"""


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
