"""render_html: pure function producing a self-contained static HTML report.

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

from repoflare_core.domain.entities import ImpactCategory
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
