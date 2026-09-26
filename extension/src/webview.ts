/**
 * buildWebviewHtml — renders the full self-contained HTML page for the RepoFlare panel.
 *
 * Everything is inlined (no external assets) so it works with localResourceRoots=[].
 * The page uses VS Code's CSS variables for colours so it respects the active theme.
 * A small amount of inline JS handles the Analyze button and the impact-ref form.
 */

import { StatusResult, ImpactSummary, GraphOverview, GraphNode } from "./rpc";

// ── State union for the renderer ──────────────────────────────────────────────

type PanelState =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "overview"; status: StatusResult; root: string }
  | { state: "impact"; status: StatusResult; root: string; from: string; to: string; impact: ImpactSummary }
  | { state: "graph"; graph: GraphOverview; total_node_count: number };

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
${nav(state.state)}
${body(state)}
${script(state)}
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
  .first-run {
    border: 1px solid var(--vscode-panel-border);
    border-radius: 6px;
    padding: 20px 24px;
    margin-top: var(--gap);
    background: var(--vscode-editor-inactiveSelectionBackground);
  }
  .first-run p { margin: 0 0 12px; }
  /* Nav bar */
  .nav {
    display: flex;
    gap: 2px;
    margin-bottom: var(--gap);
    border-bottom: 1px solid var(--vscode-panel-border);
    padding-bottom: 8px;
  }
  .nav button {
    background: none;
    color: var(--vscode-foreground);
    border: none;
    border-radius: 4px;
    padding: 4px 12px;
    cursor: pointer;
    font-size: 0.88em;
    opacity: 0.7;
  }
  .nav button:hover { background: var(--vscode-toolbar-hoverBackground); opacity: 1; }
  .nav button.active { opacity: 1; font-weight: 600; background: var(--vscode-toolbar-activeBackground); }
  /* Graph SVG */
  .graph-wrap {
    border: 1px solid var(--vscode-panel-border);
    border-radius: 6px;
    overflow: hidden;
    background: var(--vscode-editor-inactiveSelectionBackground);
    margin-bottom: var(--gap);
  }
  .graph-wrap svg { display: block; width: 100%; }
  .graph-note { font-size: 0.82em; color: var(--vscode-descriptionForeground); margin-bottom: 8px; }
  .node-detail {
    border: 1px solid var(--vscode-panel-border);
    border-radius: 4px;
    padding: 8px 12px;
    font-size: 0.88em;
    min-height: 36px;
    background: var(--vscode-editor-inactiveSelectionBackground);
  }
  .node-detail .detail-label { font-weight: 600; margin-bottom: 2px; }
  .node-detail .detail-path { font-family: monospace; color: var(--vscode-textLink-foreground); }
  /* Legend */
  .legend { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 8px; }
  .legend-item { display: flex; align-items: center; gap: 5px; font-size: 0.82em; }
  .legend-swatch { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
</style>`;
}

// ── Header strip ──────────────────────────────────────────────────────────────

function header(): string {
  return `<div style="display:flex;align-items:center;margin-bottom:8px">
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

// ── Nav bar ───────────────────────────────────────────────────────────────────

function nav(active: string): string {
  const btn = (id: string, label: string, msg: string) => {
    const cls = active === id ? " active" : "";
    return `<button class="${cls}" data-msg="${escHtml(msg)}">${label}</button>`;
  };
  return `<nav class="nav" id="nav-bar">
  ${btn("overview", "Overview", "back")}
  ${btn("overview", "Analyze", "analyze")}
  ${btn("impact", "Impact", "nav-impact")}
  ${btn("graph", "Graph", "nav-graph")}
</nav>`;
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
    case "graph":
      return graphBody(state.graph);
  }
}

// ── Overview view ─────────────────────────────────────────────────────────────

function overviewBody(status: StatusResult, root: string): string {
  if (!status.snapshot_id) {
    return `
<div class="muted" style="margin-bottom:var(--gap)">${escHtml(root)}</div>
<div class="first-run">
  <p>This repository hasn't been analyzed yet. Run <strong>Analyze</strong> to build the dependency graph — it scans every Python/TypeScript/JavaScript file and extracts symbols, calls, and imports.</p>
  <button class="action" id="btn-analyze">Analyze repository</button>
</div>`;
  }

  const snapLine = `<span class="snap-id">${escHtml(status.snapshot_id)}</span>`;

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
  <button class="action" id="btn-analyze">Re-analyze repository</button>
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

// ── Graph view ────────────────────────────────────────────────────────────────

// Node colors by kind — chosen for distinctness against both light and dark VS Code themes.
const NODE_COLOR: Record<string, string> = {
  FILE:     "#4a7bc4",   // blue
  SYMBOL:   "#5a9e6f",   // green
  TEST:     "#c47a3a",   // amber
  MODULE:   "#7c5cd8",   // purple
  API_ENDPOINT:    "#c45a7c",   // rose
  CONFIG_ITEM:     "#4a9e9e",   // teal
  EXTERNAL_SERVICE:"#9e7c4a",   // tan
};
const NODE_COLOR_DEFAULT = "#888";

const SVG_W = 720;
const SVG_H = 480;
const NODE_R = 9;   // circle radius for non-FILE nodes
const FILE_HALF = 11; // half-size for FILE rectangles

/** Pure deterministic circular layout: evenly spaced around a circle. */
function layoutNodes(nodes: GraphNode[]): Array<{ x: number; y: number }> {
  const n = nodes.length;
  if (n === 0) return [];
  if (n === 1) return [{ x: SVG_W / 2, y: SVG_H / 2 }];

  // Use concentric rings when there are many nodes: inner ring up to 16, outer ring the rest.
  // All arithmetic is deterministic (index-based), no random.
  const cx = SVG_W / 2;
  const cy = SVG_H / 2;
  const positions: Array<{ x: number; y: number }> = [];

  if (n <= 24) {
    // Single ring
    const r = Math.min(SVG_W, SVG_H) / 2 - 40;
    for (let i = 0; i < n; i++) {
      const angle = (2 * Math.PI * i) / n - Math.PI / 2;
      positions.push({ x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });
    }
  } else {
    // Two rings: inner holds ~1/3, outer holds the rest
    const innerCount = Math.max(8, Math.floor(n / 3));
    const outerCount = n - innerCount;
    const rInner = Math.min(SVG_W, SVG_H) / 2 - 100;
    const rOuter = Math.min(SVG_W, SVG_H) / 2 - 40;
    for (let i = 0; i < innerCount; i++) {
      const angle = (2 * Math.PI * i) / innerCount - Math.PI / 2;
      positions.push({ x: cx + rInner * Math.cos(angle), y: cy + rInner * Math.sin(angle) });
    }
    for (let i = 0; i < outerCount; i++) {
      const angle = (2 * Math.PI * i) / outerCount - Math.PI / 2;
      positions.push({ x: cx + rOuter * Math.cos(angle), y: cy + rOuter * Math.sin(angle) });
    }
  }
  return positions;
}

function graphBody(graph: GraphOverview): string {
  const { nodes, edges, truncated, total_node_count } = graph;

  const truncNote = truncated
    ? `<div class="graph-note">Showing the ${escHtml(String(nodes.length))} most-connected nodes out of ${escHtml(String(total_node_count))} — not the full graph.</div>`
    : "";

  const legend = `<div class="legend">
  ${Object.entries(NODE_COLOR).map(([kind, color]) =>
    `<div class="legend-item"><div class="legend-swatch" style="background:${escHtml(color)}"></div><span>${escHtml(kind)}</span></div>`
  ).join("")}
</div>`;

  if (nodes.length === 0) {
    return `<div class="empty-state">No nodes in the current snapshot. Run <strong>Analyze</strong> first.</div>`;
  }

  const positions = layoutNodes(nodes);

  // Build a node_id → index map for fast edge lookup
  const idxById: Record<string, number> = {};
  nodes.forEach((n, i) => { idxById[n.node_id] = i; });

  // SVG edges (lines drawn before nodes so nodes sit on top)
  const edgeLines = edges.map((e) => {
    const si = idxById[e.src_node_id];
    const di = idxById[e.dst_node_id];
    if (si === undefined || di === undefined) return "";
    const s = positions[si];
    const d = positions[di];
    return `<line x1="${s.x.toFixed(1)}" y1="${s.y.toFixed(1)}" x2="${d.x.toFixed(1)}" y2="${d.y.toFixed(1)}" stroke="var(--vscode-panel-border)" stroke-width="1" opacity="0.6"/>`;
  }).join("");

  // SVG nodes
  const nodeShapes = nodes.map((n, i) => {
    const { x, y } = positions[i];
    const color = NODE_COLOR[n.kind] ?? NODE_COLOR_DEFAULT;
    const label = escHtml(n.name.length > 14 ? n.name.slice(0, 13) + "…" : n.name);
    const title = escHtml(`${n.name} (${n.kind})${n.file_path ? "\n" + n.file_path : ""}`);

    // FILE nodes: rounded rectangle; all others: circle
    let shape: string;
    if (n.kind === "FILE") {
      const rx = (x - FILE_HALF).toFixed(1);
      const ry = (y - FILE_HALF * 0.75).toFixed(1);
      shape = `<rect x="${rx}" y="${ry}" width="${(FILE_HALF * 2).toFixed(1)}" height="${(FILE_HALF * 1.5).toFixed(1)}" rx="3" fill="${escHtml(color)}" class="graph-node" data-idx="${i}"/>`;
    } else {
      shape = `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${NODE_R}" fill="${escHtml(color)}" class="graph-node" data-idx="${i}"/>`;
    }

    // Small text label below the node
    const labelY = (y + NODE_R + 11).toFixed(1);
    const textEl = `<text x="${x.toFixed(1)}" y="${labelY}" text-anchor="middle" font-size="9" fill="var(--vscode-descriptionForeground)" pointer-events="none">${label}</text>`;

    return `<g><title>${title}</title>${shape}${textEl}</g>`;
  }).join("");

  const svg = `<svg viewBox="0 0 ${SVG_W} ${SVG_H}" xmlns="http://www.w3.org/2000/svg" id="graph-svg">
  <style>
    .graph-node { cursor: pointer; transition: opacity 0.1s; }
    .graph-node:hover { opacity: 0.75; }
  </style>
  ${edgeLines}
  ${nodeShapes}
</svg>`;

  // Embed node data for the click handler as a JSON blob.  The JSON goes verbatim inside a
  // <script> tag — escape ALL "<" to "\u003c" so no injected HTML tag (opening or closing,
  // including "</script>") can break out of the script context.  \u003c is valid JSON.
  const nodeDataJson = JSON.stringify(
    nodes.map((n) => ({
      name: n.name,
      kind: n.kind,
      file_path: n.file_path ?? "",
    }))
  ).replace(/</g, "\\u003c");

  return `
${truncNote}
${legend}
<h2>Dependency graph</h2>
<div class="graph-wrap">${svg}</div>
<div class="node-detail" id="node-detail">
  <span class="muted">Click a node to see details.</span>
</div>
<script>
(function() {
  var nodes = ${nodeDataJson};
  var detail = document.getElementById('node-detail');
  document.getElementById('graph-svg').addEventListener('click', function(e) {
    var el = e.target.closest('.graph-node');
    if (!el) return;
    var idx = parseInt(el.getAttribute('data-idx'), 10);
    var n = nodes[idx];
    if (!n) return;
    var fp = n.file_path ? '<div class="detail-path">' + n.file_path.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</div>' : '';
    detail.innerHTML = '<div class="detail-label">' + n.name.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</div><div class="muted">' + n.kind + '</div>' + fp;
  });
}());
</script>
`;
}

// ── Inline script ──────────────────────────────────────────────────────────────

function script(state: PanelState): string {
  // The graph state inlines its own click handler above; skip the global script for it
  // (the nav buttons still need to be wired though — handled via the nav section below).
  return `<script>
  (function () {
    const vscode = acquireVsCodeApi();

    function on(id, handler) {
      const el = document.getElementById(id);
      if (el) el.addEventListener('click', handler);
    }

    // Nav bar — each button carries its message type as data-msg
    document.querySelectorAll('#nav-bar button[data-msg]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var msg = btn.getAttribute('data-msg');
        if (msg === 'nav-impact') {
          vscode.postMessage({ type: 'nav-impact' });
        } else if (msg === 'nav-graph') {
          vscode.postMessage({ type: 'nav-graph' });
        } else {
          vscode.postMessage({ type: msg });
        }
      });
    });

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

export function escHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
