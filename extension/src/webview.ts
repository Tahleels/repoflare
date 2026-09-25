/**
 * buildWebviewHtml — renders the full self-contained HTML page for the RepoFlare panel.
 *
 * Everything is inlined (no external assets) so it works with localResourceRoots=[].
 * The page uses VS Code's CSS variables for colours so it respects the active theme.
 * A small amount of inline JS handles the Analyze button and the impact-ref form.
 */

import { StatusResult, ImpactSummary } from "./rpc";

// ── State union for the renderer ──────────────────────────────────────────────

type PanelState =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "overview"; status: StatusResult; root: string }
  | { state: "impact"; status: StatusResult; root: string; from: string; to: string; impact: ImpactSummary };

// ── Entry point ────────────────────────────────────────────────────────────────

export function buildWebviewHtml(state: PanelState): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
<title>RepoFlare</title>
${styles()}
</head>
<body>
${header()}
${body(state)}
${script()}
</body>
</html>`;
}

// ── CSS ────────────────────────────────────────────────────────────────────────

function styles(): string {
  return `<style>
  :root {
    --gap: 16px;
  }
  body {
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    color: var(--vscode-foreground);
    background: var(--vscode-editor-background);
    margin: 0;
    padding: var(--gap);
    line-height: 1.5;
  }
  h1 { font-size: 1.2em; font-weight: 600; margin: 0 0 4px; }
  h2 { font-size: 1em; font-weight: 600; margin: var(--gap) 0 8px; border-bottom: 1px solid var(--vscode-panel-border); padding-bottom: 4px; }
  .muted { color: var(--vscode-descriptionForeground); font-size: 0.9em; }
  .badge {
    display: inline-block;
    padding: 1px 7px;
    border-radius: 9px;
    font-size: 0.8em;
    font-weight: 600;
    margin-left: 6px;
    vertical-align: middle;
  }
  .badge-direct   { background: #c53030; color: #fff; }
  .badge-indirect { background: #b7791f; color: #fff; }
  .badge-related  { background: #2b6cb0; color: #fff; }
  .badge-possible { background: #276749; color: #fff; }
  .stat-row { display: flex; gap: var(--gap); margin-bottom: var(--gap); flex-wrap: wrap; }
  .stat-card {
    background: var(--vscode-editor-inactiveSelectionBackground);
    border: 1px solid var(--vscode-panel-border);
    border-radius: 6px;
    padding: 10px 16px;
    min-width: 100px;
    flex: 1;
  }
  .stat-card .value { font-size: 1.6em; font-weight: 700; }
  .stat-card .label { font-size: 0.8em; color: var(--vscode-descriptionForeground); }
  button.action {
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
    cursor: pointer;
    font-size: 0.9em;
    margin-right: 8px;
  }
  button.action:hover { background: var(--vscode-button-hoverBackground); }
  button.secondary {
    background: var(--vscode-button-secondaryBackground);
    color: var(--vscode-button-secondaryForeground);
  }
  button.secondary:hover { background: var(--vscode-button-secondaryHoverBackground); }
  input.ref-input {
    background: var(--vscode-input-background);
    color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border);
    border-radius: 4px;
    padding: 5px 10px;
    font-size: 0.9em;
    margin-right: 8px;
    width: 160px;
  }
  .impact-form { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: var(--gap); }
  table { border-collapse: collapse; width: 100%; margin-top: 8px; }
  th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--vscode-panel-border); font-size: 0.88em; }
  th { color: var(--vscode-descriptionForeground); font-weight: 600; }
  .filepath { font-family: var(--vscode-editor-font-family, monospace); color: var(--vscode-textLink-foreground); }
  .snap-id { font-family: monospace; font-size: 0.85em; }
  .spinner { color: var(--vscode-descriptionForeground); padding: 32px 0; }
  .error-box {
    background: var(--vscode-inputValidation-errorBackground);
    border: 1px solid var(--vscode-inputValidation-errorBorder);
    padding: 10px 14px;
    border-radius: 4px;
    margin-top: var(--gap);
  }
  .changed-list { padding-left: 18px; margin: 4px 0 12px; }
  .changed-list li { font-family: monospace; font-size: 0.88em; margin-bottom: 2px; }
  .empty-state { color: var(--vscode-descriptionForeground); padding: 16px 0; font-style: italic; }
</style>`;
}

// ── Header strip ──────────────────────────────────────────────────────────────

function header(): string {
  return `<div style="display:flex;align-items:center;margin-bottom:var(--gap)">
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" style="margin-right:10px">
    <circle cx="12" cy="12" r="11" stroke="var(--vscode-foreground)" stroke-width="1.5"/>
    <circle cx="12" cy="12" r="4" fill="var(--vscode-foreground)"/>
    <line x1="12" y1="1" x2="12" y2="8" stroke="var(--vscode-foreground)" stroke-width="1.5"/>
    <line x1="12" y1="16" x2="12" y2="23" stroke="var(--vscode-foreground)" stroke-width="1.5"/>
    <line x1="1" y1="12" x2="8" y2="12" stroke="var(--vscode-foreground)" stroke-width="1.5"/>
    <line x1="16" y1="12" x2="23" y2="12" stroke="var(--vscode-foreground)" stroke-width="1.5"/>
  </svg>
  <div><h1>RepoFlare</h1><div class="muted">Repository intelligence</div></div>
</div>`;
}

// ── Body dispatch ─────────────────────────────────────────────────────────────

function body(state: PanelState): string {
  switch (state.state) {
    case "loading":
      return `<div class="spinner">⏳ Loading…</div>`;
    case "error":
      return `<div class="error-box">⚠ ${escHtml(state.message)}</div>`;
    case "overview":
      return overviewBody(state.status, state.root);
    case "impact":
      return impactBody(state.status, state.root, state.from, state.to, state.impact);
  }
}

// ── Overview view ─────────────────────────────────────────────────────────────

function overviewBody(status: StatusResult, root: string): string {
  const snapLine = status.snapshot_id
    ? `<span class="snap-id">${escHtml(status.snapshot_id)}</span>`
    : `<span class="muted">not yet analyzed</span>`;

  return `
<div class="muted" style="margin-bottom:var(--gap)">${escHtml(root)}</div>

<h2>Snapshot</h2>
<div style="margin-bottom:var(--gap)">${snapLine}</div>

<div class="stat-row">
  ${statCard(String(status.node_count), "Nodes")}
  ${statCard(String(status.edge_count), "Edges")}
</div>

<h2>Actions</h2>
<div style="margin-bottom:var(--gap)">
  <button class="action" id="btn-analyze">Analyze repository</button>
</div>

<h2>Impact</h2>
<div class="impact-form">
  <label class="muted" for="from-ref">From ref:</label>
  <input class="ref-input" id="from-ref" placeholder="HEAD~1" />
  <label class="muted" for="to-ref">To ref:</label>
  <input class="ref-input" id="to-ref" placeholder="HEAD" />
  <button class="action secondary" id="btn-impact">Show impact</button>
</div>
`;
}

function statCard(value: string, label: string): string {
  return `<div class="stat-card"><div class="value">${escHtml(value)}</div><div class="label">${escHtml(label)}</div></div>`;
}

// ── Impact view ────────────────────────────────────────────────────────────────

const CATEGORY_BADGE: Record<string, string> = {
  DIRECT: "badge-direct",
  INDIRECT: "badge-indirect",
  RELATED: "badge-related",
  POSSIBLE: "badge-possible",
};

function impactBody(
  status: StatusResult,
  root: string,
  from: string,
  to: string,
  impact: ImpactSummary
): string {
  const snapLine = status.snapshot_id
    ? `<span class="snap-id">${escHtml(status.snapshot_id)}</span>`
    : `<span class="muted">not yet analyzed</span>`;

  const changedSection =
    impact.changed_files.length === 0
      ? `<div class="empty-state">No changed files between these refs.</div>`
      : `<ul class="changed-list">${impact.changed_files.map((f) => `<li>${escHtml(f)}</li>`).join("")}</ul>`;

  const impactSection =
    impact.results.length === 0
      ? `<div class="empty-state">No affected nodes found.</div>`
      : impactTable(impact);

  return `
<div class="muted" style="margin-bottom:var(--gap)">${escHtml(root)}</div>

<h2>Snapshot</h2>
<div style="margin-bottom:var(--gap)">${snapLine}</div>

<h2>Changed files <span class="muted">${escHtml(from)} → ${escHtml(to)}</span></h2>
${changedSection}

<h2>Affected nodes</h2>
${impactSection}

<div style="margin-top:var(--gap)">
  <button class="action secondary" id="btn-back">← Back to overview</button>
</div>
`;
}

function impactTable(impact: ImpactSummary): string {
  const rows = impact.results.flatMap((r) =>
    r.affected_node_ids.map((nodeId) => {
      const summary = impact.node_summaries[nodeId];
      const label = summary?.label ?? nodeId;
      const filePath = summary?.file_path ?? "";
      const badgeClass = CATEGORY_BADGE[r.category] ?? "badge-possible";
      return `<tr>
  <td><span class="badge ${badgeClass}">${escHtml(r.category)}</span></td>
  <td>${escHtml(label)}</td>
  <td class="filepath">${escHtml(filePath)}</td>
</tr>`;
    })
  );

  if (rows.length === 0) {
    return `<div class="empty-state">No affected nodes found.</div>`;
  }

  return `<table>
<thead><tr><th>Category</th><th>Symbol</th><th>File</th></tr></thead>
<tbody>${rows.join("")}</tbody>
</table>`;
}

// ── Inline script ──────────────────────────────────────────────────────────────

function script(): string {
  return `<script>
  (function () {
    const vscode = acquireVsCodeApi();

    function on(id, handler) {
      const el = document.getElementById(id);
      if (el) el.addEventListener('click', handler);
    }

    on('btn-analyze', function () {
      vscode.postMessage({ type: 'analyze' });
    });

    on('btn-impact', function () {
      const from = document.getElementById('from-ref').value.trim();
      const to = document.getElementById('to-ref').value.trim() || 'HEAD';
      if (!from) { return; }
      vscode.postMessage({ type: 'impact', from, to });
    });

    on('btn-back', function () {
      vscode.postMessage({ type: 'back' });
    });

    vscode.postMessage({ type: 'ready' });
  }());
</script>`;
}

// ── Utility ────────────────────────────────────────────────────────────────────

function escHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
