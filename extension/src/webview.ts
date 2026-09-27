/**
 * buildWebviewHtml — renders the full self-contained HTML page for the RepoFlare panel.
 *
 * Everything is inlined (no external assets) so it works with localResourceRoots=[].
 * The page uses VS Code's CSS variables for colours so it respects the active theme.
 *
 * All four tabs (Overview, Analyze, Impact, Graph) are rendered into the page at once as
 * hidden <section> elements. Tab switching is handled by pure client-side JS — no round-trip
 * to the extension host, which eliminates the full-page blink on navigation.
 *
 * Only two actions still post to the host:
 *   - "analyze"  — runs the analyzer
 *   - "impact"   — queries impact for the given refs
 */

import { StatusResult, ImpactSummary, GraphOverview, GraphNode, GovernanceReport, GovernanceFinding } from "./rpc";

// ── State union for the renderer ──────────────────────────────────────────────

/**
 * "ready"  — the normal operational state; carries everything needed to render all tabs at once.
 * "loading" — transient; shown while an async operation is in flight.
 * "error"   — something went wrong.
 */
export type PanelState =
  | { state: "loading" }
  | { state: "error"; message: string }
  | {
      state: "ready";
      status: StatusResult;
      root: string;
      /** The graph data — null until graphOverview has been fetched. */
      graph: GraphOverview | null;
      /** Active tab to open initially. */
      activeTab: "overview" | "impact" | "graph" | "analyze" | "audit";
      /** Impact results to pre-populate, if any. */
      impactResult?: { from: string; to: string; impact: ImpactSummary };
      /** Governance audit result, if any. */
      auditResult?: GovernanceReport;
    };

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
${state.state === "ready" ? nav(state.activeTab) : nav("overview")}
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
    --radius-card: 10px;
    --radius-btn: 6px;
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
  h1 { font-size: 1.25em; font-weight: 700; margin: 0 0 4px; letter-spacing: -0.01em; }
  h2 {
    font-size: 0.85em;
    font-weight: 700;
    margin: var(--gap) 0 8px;
    border-bottom: 1px solid var(--vscode-panel-border);
    padding-bottom: 4px;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--vscode-descriptionForeground);
  }
  .muted { color: var(--vscode-descriptionForeground); font-size: 0.9em; }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 0.78em;
    font-weight: 700;
    margin-left: 6px;
    vertical-align: middle;
    letter-spacing: 0.04em;
  }
  .badge-direct   { background: #e53e3e; color: #fff; }
  .badge-indirect { background: #dd6b20; color: #fff; }
  .badge-related  { background: #3182ce; color: #fff; }
  .badge-possible { background: #38a169; color: #fff; }
  .stat-row { display: flex; gap: var(--gap); margin-bottom: var(--gap); flex-wrap: wrap; }
  .stat-card {
    background: var(--vscode-editor-inactiveSelectionBackground);
    border: 1px solid var(--vscode-panel-border);
    border-radius: var(--radius-card);
    padding: 14px 20px;
    min-width: 100px;
    flex: 1;
    position: relative;
    overflow: hidden;
  }
  .stat-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, #4a7bc4, #7c5cd8);
    border-radius: var(--radius-card) var(--radius-card) 0 0;
  }
  .stat-card .value { font-size: 1.8em; font-weight: 800; }
  .stat-card .label { font-size: 0.78em; color: var(--vscode-descriptionForeground); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 2px; }
  button.action {
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    border: none;
    border-radius: var(--radius-btn);
    padding: 7px 16px;
    cursor: pointer;
    font-size: 0.88em;
    font-weight: 600;
    margin-right: 8px;
    letter-spacing: 0.02em;
    transition: opacity 0.15s;
  }
  button.action:hover { opacity: 0.85; background: var(--vscode-button-hoverBackground); }
  button.secondary {
    background: var(--vscode-button-secondaryBackground);
    color: var(--vscode-button-secondaryForeground);
  }
  button.secondary:hover { background: var(--vscode-button-secondaryHoverBackground); opacity: 1; }
  input.ref-input {
    background: var(--vscode-input-background);
    color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border);
    border-radius: var(--radius-btn);
    padding: 6px 10px;
    font-size: 0.88em;
    margin-right: 4px;
    width: 150px;
  }
  .impact-form {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: var(--gap);
    background: var(--vscode-editor-inactiveSelectionBackground);
    border: 1px solid var(--vscode-panel-border);
    border-radius: var(--radius-card);
    padding: 14px 16px;
  }
  .impact-form label { font-size: 0.82em; color: var(--vscode-descriptionForeground); font-weight: 600; }
  table { border-collapse: collapse; width: 100%; margin-top: 8px; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--vscode-panel-border); font-size: 0.88em; }
  th { color: var(--vscode-descriptionForeground); font-weight: 700; text-transform: uppercase; font-size: 0.78em; letter-spacing: 0.05em; }
  .filepath { font-family: var(--vscode-editor-font-family, monospace); color: var(--vscode-textLink-foreground); }
  /* commit stepper */
  .commit-stepper {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    margin-bottom: 10px;
  }
  .commit-stepper label { font-size: 0.88em; color: var(--vscode-foreground); font-weight: 500; }
  .stepper-control { display: flex; align-items: center; gap: 6px; }
  .stepper-btn {
    background: var(--vscode-button-secondaryBackground);
    color: var(--vscode-button-secondaryForeground);
    border: none; border-radius: 4px;
    width: 26px; height: 26px;
    font-size: 1.1em; font-weight: 700;
    cursor: pointer; line-height: 1;
    display: flex; align-items: center; justify-content: center;
    transition: opacity 0.12s;
  }
  .stepper-btn:hover { opacity: 0.8; }
  .stepper-val {
    min-width: 32px; text-align: center;
    font-size: 1.15em; font-weight: 700;
    color: var(--vscode-foreground);
  }
  .stepper-preview {
    font-size: 0.82em;
    color: var(--vscode-descriptionForeground);
    background: var(--vscode-editor-inactiveSelectionBackground);
    border-radius: 5px;
    padding: 4px 10px;
  }
  .stepper-preview code {
    font-family: var(--vscode-editor-font-family, monospace);
    color: var(--vscode-textLink-foreground);
    font-size: 1em;
  }
  details.impact-advanced { margin-top: 10px; }
  details.impact-advanced summary {
    font-size: 0.8em;
    color: var(--vscode-descriptionForeground);
    cursor: pointer;
    user-select: none;
    margin-bottom: 6px;
  }
  details.impact-advanced summary:hover { color: var(--vscode-foreground); }
  .spinner { color: var(--vscode-descriptionForeground); padding: 32px 0; }
  .error-box {
    background: var(--vscode-inputValidation-errorBackground);
    border: 1px solid var(--vscode-inputValidation-errorBorder);
    padding: 12px 16px;
    border-radius: var(--radius-card);
    margin-top: var(--gap);
  }
  .changed-list { padding-left: 18px; margin: 4px 0 12px; }
  .changed-list li { font-family: monospace; font-size: 0.88em; margin-bottom: 2px; }
  .empty-state { color: var(--vscode-descriptionForeground); padding: 16px 0; font-style: italic; }
  .first-run {
    border: 1px solid var(--vscode-panel-border);
    border-radius: var(--radius-card);
    padding: 24px 28px;
    margin-top: var(--gap);
    background: var(--vscode-editor-inactiveSelectionBackground);
  }
  .first-run p { margin: 0 0 12px; }
  /* Nav bar */
  .nav {
    display: flex;
    gap: 4px;
    margin-bottom: var(--gap);
    border-bottom: 1px solid var(--vscode-panel-border);
    padding-bottom: 8px;
  }
  .nav button {
    background: none;
    color: var(--vscode-foreground);
    border: none;
    border-radius: var(--radius-btn);
    padding: 5px 14px;
    cursor: pointer;
    font-size: 0.86em;
    font-weight: 500;
    opacity: 0.55;
    transition: opacity 0.1s, background 0.1s;
  }
  .nav button:hover { background: var(--vscode-toolbar-hoverBackground); opacity: 0.9; }
  .nav button.active { opacity: 1; font-weight: 700; background: var(--vscode-toolbar-activeBackground); }
  /* Tab sections — all rendered but only one visible at a time */
  .tab-section { display: none; }
  .tab-section.tab-visible { display: block; }
  /* Graph SVG */
  .graph-wrap {
    border: 1px solid var(--vscode-panel-border);
    border-radius: var(--radius-card);
    overflow: hidden;
    background: var(--vscode-editor-inactiveSelectionBackground);
    margin-bottom: var(--gap);
  }
  .graph-wrap svg { display: block; width: 100%; }
  .graph-note { font-size: 0.82em; color: var(--vscode-descriptionForeground); margin-bottom: 8px; }
  .node-detail {
    border: 1px solid var(--vscode-panel-border);
    border-radius: var(--radius-card);
    padding: 10px 14px;
    font-size: 0.88em;
    min-height: 36px;
    background: var(--vscode-editor-inactiveSelectionBackground);
  }
  .node-detail .detail-label { font-weight: 700; margin-bottom: 2px; font-size: 1em; }
  .node-detail .detail-path { font-family: monospace; color: var(--vscode-textLink-foreground); font-size: 0.9em; }
  /* Legend */
  .legend { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
  .legend-item { display: flex; align-items: center; gap: 6px; font-size: 0.8em; font-weight: 500; }
  .legend-swatch { width: 13px; height: 13px; border-radius: 50%; flex-shrink: 0; box-shadow: 0 0 0 2px rgba(255,255,255,0.15); }
  /* Impact results box */
  .impact-results {
    border: 1px solid var(--vscode-panel-border);
    border-radius: var(--radius-card);
    overflow: hidden;
    margin-top: var(--gap);
  }
  .impact-results-header {
    background: var(--vscode-editor-inactiveSelectionBackground);
    padding: 10px 14px;
    font-size: 0.82em;
    font-weight: 700;
    color: var(--vscode-descriptionForeground);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-bottom: 1px solid var(--vscode-panel-border);
  }
  /* Analyze tab */
  .analyze-card {
    background: var(--vscode-editor-inactiveSelectionBackground);
    border: 1px solid var(--vscode-panel-border);
    border-radius: var(--radius-card);
    padding: 20px 24px;
    margin-top: 4px;
  }
  .analyze-card p { margin: 0 0 14px; font-size: 0.92em; line-height: 1.6; }
  /* Audit tab */
  .audit-form {
    background: var(--vscode-editor-inactiveSelectionBackground);
    border: 1px solid var(--vscode-panel-border);
    border-radius: var(--radius-card);
    padding: 14px 16px;
    margin-bottom: var(--gap);
    display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end;
  }
  .audit-form label { font-size: 0.82em; color: var(--vscode-descriptionForeground); font-weight: 600; display: block; margin-bottom: 3px; }
  .audit-form input[type=text] {
    background: var(--vscode-input-background);
    color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border);
    border-radius: var(--radius-btn);
    padding: 6px 10px; font-size: 0.88em; width: 200px;
  }
  .finding-card {
    border: 1px solid var(--vscode-panel-border);
    border-radius: var(--radius-card);
    padding: 10px 14px;
    margin-bottom: 8px;
    background: var(--vscode-editor-inactiveSelectionBackground);
  }
  .finding-title { font-weight: 600; font-size: 0.92em; margin-bottom: 3px; display: flex; align-items: center; gap: 8px; }
  .finding-desc { font-size: 0.84em; color: var(--vscode-descriptionForeground); margin-bottom: 4px; line-height: 1.5; }
  .finding-provenance { font-size: 0.76em; color: var(--vscode-descriptionForeground); opacity: 0.7; }
  .badge-pass    { background: #38a169; color: #fff; }
  .badge-warn    { background: #dd6b20; color: #fff; }
  .badge-fail    { background: #e53e3e; color: #fff; }
  .badge-unknown { background: #3182ce; color: #fff; }
  .audit-section-header {
    font-size: 0.78em; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--vscode-descriptionForeground);
    border-bottom: 1px solid var(--vscode-panel-border);
    padding-bottom: 4px; margin: var(--gap) 0 8px;
  }
  .audit-summary-row { display: flex; gap: var(--gap); margin-bottom: var(--gap); flex-wrap: wrap; }
  .audit-stat { background: var(--vscode-editor-inactiveSelectionBackground); border: 1px solid var(--vscode-panel-border); border-radius: var(--radius-card); padding: 10px 18px; min-width: 80px; text-align: center; }
  .audit-stat .val { font-size: 1.6em; font-weight: 800; }
  .audit-stat .lbl { font-size: 0.75em; color: var(--vscode-descriptionForeground); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 2px; }
</style>`;
}

// ── Header strip ──────────────────────────────────────────────────────────────

function header(): string {
  // Logo: two connected graph nodes with a flame rising from them
  return `<div style="display:flex;align-items:center;margin-bottom:8px">
  <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg" style="margin-right:10px;flex-shrink:0">
    <!-- Edge connecting the two base nodes -->
    <line x1="8" y1="20" x2="20" y2="20" stroke="var(--vscode-foreground)" stroke-width="1.5" opacity="0.55"/>
    <!-- Left base node -->
    <circle cx="8" cy="20" r="3.5" fill="#4a7bc4"/>
    <!-- Right base node -->
    <circle cx="20" cy="20" r="3.5" fill="#7c5cd8"/>
    <!-- Flame body -->
    <path d="M14 4 C14 4 10 8 10 12 C10 13.5 10.8 15 12 15.8 C11.6 14.4 12.2 13 13 12.2 C13 13.8 14 14.8 14 16 C15.2 15 16.4 13.4 16 11.6 C17 12.6 17.4 14 17.2 15.4 C18.6 14.2 19 12.4 18.4 10.8 C20 12 20.4 14 19.8 15.8 C21.2 14 21.4 11 20 9 C18.6 7 16.6 5.6 14 4 Z" fill="#e07b2a" opacity="0.92"/>
    <!-- Flame inner highlight -->
    <path d="M14 8 C14 8 12 10.5 12 12.5 C12 13.4 12.5 14.2 13.2 14.6 C13 13.6 13.4 12.8 14 12.2 C14 13.2 14.6 13.8 14.8 14.6 C15.4 13.8 15.6 12.8 15.2 11.8 C15.8 12.4 16 13.2 15.8 14 C16.6 13.2 16.8 11.8 16 10.6 C15.2 9.4 14.6 8.6 14 8 Z" fill="#f6ad55" opacity="0.8"/>
    <!-- Connecting edges from flame base to nodes -->
    <line x1="14" y1="16" x2="8" y2="20" stroke="var(--vscode-foreground)" stroke-width="1" opacity="0.35"/>
    <line x1="14" y1="16" x2="20" y2="20" stroke="var(--vscode-foreground)" stroke-width="1" opacity="0.35"/>
  </svg>
  <div><h1>RepoFlare</h1><div class="muted">Repository intelligence</div></div>
</div>`;
}

// ── Nav bar ───────────────────────────────────────────────────────────────────

function nav(active: string): string {
  const btn = (tab: string, label: string) => {
    const cls = active === tab ? " active" : "";
    return `<button class="${cls}" data-tab="${escHtml(tab)}">${label}</button>`;
  };
  return `<nav class="nav" id="nav-bar">
  ${btn("overview", "Overview")}
  ${btn("impact", "Impact")}
  ${btn("graph", "Graph")}
  ${btn("audit", "Governance")}
</nav>`;
}

// ── Body dispatch ─────────────────────────────────────────────────────────────

function body(state: PanelState): string {
  switch (state.state) {
    case "loading":
      return `<div class="spinner">⏳ Loading…</div>`;
    case "error":
      return `<div class="error-box">⚠ ${escHtml(state.message)}</div>`;
    case "ready":
      return readyBody(state);
  }
}

/**
 * Renders all three tab sections at once. Only the active one is visible initially;
 * the rest are hidden via CSS and revealed by client-side JS without any host round-trip.
 */
function readyBody(state: Extract<PanelState, { state: "ready" }>): string {
  // "analyze" activeTab is treated as "overview" — the button is embedded there now.
  const active = state.activeTab === "analyze" ? "overview" : state.activeTab;
  const vis = (tab: string) => active === tab ? " tab-visible" : "";

  return `
<div id="tab-overview" class="tab-section${vis("overview")}">
  ${overviewSection(state.status, state.root)}
</div>
<div id="tab-impact" class="tab-section${vis("impact")}">
  ${impactSection(state.impactResult)}
</div>
<div id="tab-graph" class="tab-section${vis("graph")}">
  ${graphSection(state.graph)}
</div>
<div id="tab-audit" class="tab-section${vis("audit")}">
  ${auditSection(state.auditResult)}
</div>
`;
}

// ── Overview tab ──────────────────────────────────────────────────────────────

function overviewSection(status: StatusResult, root: string): string {
  if (!status.snapshot_id) {
    return `
<div class="muted" style="margin-bottom:var(--gap)">${escHtml(root)}</div>
<div class="first-run">
  <p>This repository hasn't been analyzed yet. Scan every Python, TypeScript, and JavaScript file to build the dependency graph — extracting symbols, calls, and imports.</p>
  <button class="action" id="btn-analyze">Analyze repository</button>
</div>`;
  }

  return `
<div class="muted" style="margin-bottom:var(--gap)">${escHtml(root)}</div>

<div class="stat-row">
  ${statCard(String(status.node_count), "Nodes")}
  ${statCard(String(status.edge_count), "Edges")}
</div>

<h2>Actions</h2>
<div class="analyze-card">
  <p>Re-scans every Python, TypeScript, and JavaScript file and rebuilds the dependency graph.</p>
  <button class="action" id="btn-analyze">Re-analyze repository</button>
</div>
`;
}

// ── Impact tab ─────────────────────────────────────────────────────────────────

function impactSection(
  result?: { from: string; to: string; impact: ImpactSummary }
): string {
  const resultsHtml = result ? impactResultsHtml(result.from, result.to, result.impact) : "";
  // Detect if last result used a non-stepper ref so we can pre-open advanced
  const isAdvanced = result && !/^HEAD~\d+$/.test(result.from);
  const advancedOpen = isAdvanced ? " open" : "";

  return `
<h2>Impact analysis</h2>
<div class="impact-form">
  <div class="commit-stepper">
    <label for="commit-count">Compare last</label>
    <div class="stepper-control">
      <button class="stepper-btn" id="stepper-minus" type="button" aria-label="Fewer commits">−</button>
      <span class="stepper-val" id="stepper-val">1</span>
      <button class="stepper-btn" id="stepper-plus" type="button" aria-label="More commits">+</button>
    </div>
    <label for="commit-count">commit${result ? "" : "s"}</label>
  </div>
  <div class="stepper-preview" id="stepper-preview">
    Will compare <code id="preview-from">HEAD~1</code> → <code>HEAD</code>
  </div>
  <button class="action" id="btn-impact" style="margin-top:8px">Run impact</button>

  <details class="impact-advanced"${advancedOpen}>
    <summary>Advanced: specify git refs manually</summary>
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <label class="muted" for="from-ref">From</label>
      <input class="ref-input" id="from-ref" placeholder="HEAD~1" value="${result && isAdvanced ? escHtml(result.from) : ""}" />
      <label class="muted" for="to-ref">To</label>
      <input class="ref-input" id="to-ref" placeholder="HEAD" value="${result && isAdvanced ? escHtml(result.to) : ""}" />
    </div>
  </details>
</div>
<div id="impact-results-container">${resultsHtml}</div>
`;
}

function impactResultsHtml(from: string, to: string, impact: ImpactSummary): string {
  const changedSection =
    impact.changed_files.length === 0
      ? `<div class="empty-state" style="padding:12px 14px">No changed files between these refs.</div>`
      : `<ul class="changed-list" style="margin:8px 0 4px;padding-left:28px">${impact.changed_files.map((f) => `<li>${escHtml(f)}</li>`).join("")}</ul>`;

  const impactSection =
    impact.results.length === 0
      ? `<div class="empty-state" style="padding:12px 14px">No affected nodes found.</div>`
      : impactTable(impact);

  return `
<div class="impact-results">
  <div class="impact-results-header">Changed files — ${escHtml(from)} → ${escHtml(to)}</div>
  ${changedSection}
</div>
<div class="impact-results" style="margin-top:10px">
  <div class="impact-results-header">Affected nodes</div>
  ${impactSection}
</div>`;
}

function statCard(value: string, label: string): string {
  return `<div class="stat-card"><div class="value">${escHtml(value)}</div><div class="label">${escHtml(label)}</div></div>`;
}

// ── Impact table ───────────────────────────────────────────────────────────────

const CATEGORY_BADGE: Record<string, string> = {
  DIRECT: "badge-direct",
  INDIRECT: "badge-indirect",
  RELATED: "badge-related",
  POSSIBLE: "badge-possible",
};

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
    return `<div class="empty-state" style="padding:12px 14px">No affected nodes found.</div>`;
  }

  return `<table>
<thead><tr><th>Category</th><th>Symbol</th><th>File</th></tr></thead>
<tbody>${rows.join("")}</tbody>
</table>`;
}

// ── Audit tab ─────────────────────────────────────────────────────────────────

const SECTION_ORDER = ["Security", "Delivery", "Repository Health", "Data Security", "AI Governance"];
const CHECK_SECTION: Record<string, string> = {
  DEPENDABOT: "Security",
  STALE_PR: "Delivery",
  CONFLICT: "Delivery",
  DEPLOY_WITHOUT_TEST: "Delivery",
  PII: "Data Security",
  REPO_SPRAWL: "Repository Health",
  PLAN_BEFORE_SHIP: "AI Governance",
  INFLATED_DIFF: "AI Governance",
  HITL: "AI Governance",
};
const STATUS_ICON: Record<string, string> = {
  PASS: "✅", WARN: "⚠", FAIL: "✗", UNKNOWN: "?",
};
const STATUS_BADGE: Record<string, string> = {
  PASS: "badge-pass", WARN: "badge-warn", FAIL: "badge-fail", UNKNOWN: "badge-unknown",
};

function findingCard(f: GovernanceFinding): string {
  const badgeCls = STATUS_BADGE[f.status] ?? "badge-unknown";
  const icon = STATUS_ICON[f.status] ?? "?";
  return `<div class="finding-card">
  <div class="finding-title">
    <span class="badge ${badgeCls}">${escHtml(icon)} ${escHtml(f.status)}</span>
    ${escHtml(f.title)}
  </div>
  <div class="finding-desc">${escHtml(f.description)}</div>
  <div class="finding-provenance">provenance: ${escHtml(f.provenance)}</div>
</div>`;
}

function auditSection(report?: GovernanceReport): string {
  const formHtml = `
<h2>Governance Audit</h2>
<div class="audit-form">
  <div>
    <label for="audit-org">GitHub org or owner/repo</label>
    <input type="text" id="audit-org" placeholder="e.g. tiangolo/fastapi" value="${report ? escHtml(report.org) : ""}" />
  </div>
  <div>
    <label for="audit-token">GitHub token (optional)</label>
    <input type="text" id="audit-token" placeholder="ghp_… or set GITHUB_TOKEN" />
  </div>
  <button class="action" id="btn-audit">Run audit</button>
</div>`;

  if (!report) {
    return `${formHtml}<div class="empty-state">Enter a GitHub org or repo above and click <strong>Run audit</strong>.</div>`;
  }

  const fail = report.findings.filter(f => f.status === "FAIL").length;
  const warn = report.findings.filter(f => f.status === "WARN").length;
  const pass = report.findings.filter(f => f.status === "PASS").length;

  const summaryHtml = `<div class="audit-summary-row">
  <div class="audit-stat"><div class="val" style="color:#e53e3e">${fail}</div><div class="lbl">Failures</div></div>
  <div class="audit-stat"><div class="val" style="color:#dd6b20">${warn}</div><div class="lbl">Warnings</div></div>
  <div class="audit-stat"><div class="val" style="color:#38a169">${pass}</div><div class="lbl">Passing</div></div>
  <div class="audit-stat"><div class="val">${report.repositories.length}</div><div class="lbl">Repos</div></div>
</div>`;

  const grouped: Record<string, GovernanceFinding[]> = {};
  for (const f of report.findings) {
    const sec = CHECK_SECTION[f.check] ?? "Other";
    if (!grouped[sec]) grouped[sec] = [];
    grouped[sec].push(f);
  }

  const sectionsHtml = SECTION_ORDER
    .filter(s => grouped[s] && grouped[s].length > 0)
    .map(s => `<div class="audit-section-header">${escHtml(s)}</div>
${grouped[s].map(findingCard).join("")}`)
    .join("");

  return `${formHtml}${summaryHtml}${sectionsHtml || '<div class="empty-state">No findings.</div>'}`;
}

// ── Graph tab ─────────────────────────────────────────────────────────────────

// Node colors by kind — chosen for distinctness against both light and dark VS Code themes.
const NODE_COLOR: Record<string, string> = {
  FILE:            "#4a7bc4",   // blue
  SYMBOL:          "#5a9e6f",   // green
  TEST:            "#e07b2a",   // amber
  MODULE:          "#7c5cd8",   // purple
  API_ENDPOINT:    "#d1517a",   // rose
  CONFIG_ITEM:     "#3a9e9e",   // teal
  EXTERNAL_SERVICE:"#9e7c4a",   // tan
};
const NODE_COLOR_DEFAULT = "#888";

const SVG_W = 800;
const SVG_H = 560;
const NODE_R = 18;    // circle radius for non-FILE nodes (larger icons)
const FILE_HALF = 20; // half-size for FILE rectangles (larger icons)

/** Pure deterministic circular layout: evenly spaced around a circle. */
function layoutNodes(nodes: GraphNode[]): Array<{ x: number; y: number }> {
  const n = nodes.length;
  if (n === 0) return [];
  if (n === 1) return [{ x: SVG_W / 2, y: SVG_H / 2 }];

  const cx = SVG_W / 2;
  const cy = SVG_H / 2;
  const positions: Array<{ x: number; y: number }> = [];

  if (n <= 24) {
    const r = Math.min(SVG_W, SVG_H) / 2 - 40;
    for (let i = 0; i < n; i++) {
      const angle = (2 * Math.PI * i) / n - Math.PI / 2;
      positions.push({ x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });
    }
  } else {
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

/**
 * Returns a small SVG icon path centered at (0,0) for a given node kind.
 * All paths are scaled to fit within ±10px, white, pointer-events:none.
 */
function kindIcon(kind: string): string {
  const base = `pointer-events="none" fill="rgba(255,255,255,0.92)"`;
  switch (kind) {
    case "FILE":
      // Document with folded corner
      return `<path ${base} d="M-7,-9 L4,-9 L8,-5 L8,9 L-7,9 Z M4,-9 L4,-5 L8,-5" stroke="rgba(255,255,255,0.6)" stroke-width="1" fill="none"/>
              <path ${base} d="M-7,-9 L4,-9 L4,-5 L8,-5 L8,9 L-7,9 Z" opacity="0.0"/>
              <path fill="none" stroke="rgba(255,255,255,0.92)" stroke-width="1.2" d="M-4,-2 L5,-2 M-4,1 L5,1 M-4,4 L2,4"/>
              <path fill="rgba(255,255,255,0.92)" ${base} d="M-7,-9 L4,-9 L8,-5 L8,9 L-7,9 Z M3.5,-9 L3.5,-4.5 L8,-4.5"/>`;
    case "SYMBOL":
      // Curly braces { }
      return `<path ${base} fill="none" stroke="rgba(255,255,255,0.92)" stroke-width="1.8" stroke-linecap="round"
               d="M-1,-8 C-4,-8 -5,-6 -5,-4 L-5,-2 C-5,0 -7,1 -8,1 C-7,1 -5,2 -5,4 L-5,6 C-5,8 -4,8 -1,8
                  M1,-8 C4,-8 5,-6 5,-4 L5,-2 C5,0 7,1 8,1 C7,1 5,2 5,4 L5,6 C5,8 4,8 1,8"/>`;
    case "TEST":
      // Flask / beaker
      return `<path fill="none" stroke="rgba(255,255,255,0.92)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"
               d="M-3,-8 L-3,-1 L-8,7 C-8,9 -6,9 0,9 C6,9 8,9 8,7 L3,-1 L3,-8"/>
              <line x1="-5" y1="-8" x2="5" y2="-8" stroke="rgba(255,255,255,0.92)" stroke-width="1.6" stroke-linecap="round"/>
              <circle cx="1" cy="4" r="1.2" fill="rgba(255,255,255,0.7)"/>
              <circle cx="-2" cy="6" r="0.9" fill="rgba(255,255,255,0.5)"/>`;
    case "MODULE":
      // Cube
      return `<path fill="none" stroke="rgba(255,255,255,0.92)" stroke-width="1.5" stroke-linejoin="round"
               d="M0,-9 L8,-4 L8,4 L0,9 L-8,4 L-8,-4 Z"/>
              <path fill="none" stroke="rgba(255,255,255,0.55)" stroke-width="1" d="M0,-9 L0,0 M8,-4 L0,0 M-8,-4 L0,0"/>`;
    case "API_ENDPOINT":
      // Lightning bolt / endpoint
      return `<path ${base} d="M2,-9 L-4,0 L1,0 L-2,9 L8,0 L2,0 Z"/>`;
    case "CONFIG_ITEM":
      // Gear / settings cog
      return `<path fill="none" stroke="rgba(255,255,255,0.92)" stroke-width="1.5"
               d="M0,-8 L1,-6 L3.5,-7 L5,-5 L3,-3.5 L3,-2 C5,-1 6,0 6,0 C6,0 5,1 3,2 L3,3.5 L5,5 L3.5,7 L1,6 L0,8 L-1,6 L-3.5,7 L-5,5 L-3,3.5 L-3,2 C-5,1 -6,0 -6,0 C-6,0 -5,-1 -3,-2 L-3,-3.5 L-5,-5 L-3.5,-7 L-1,-6 Z"/>
              <circle cx="0" cy="0" r="3" fill="none" stroke="rgba(255,255,255,0.92)" stroke-width="1.5"/>`;
    case "EXTERNAL_SERVICE":
      // Cloud
      return `<path fill="none" stroke="rgba(255,255,255,0.92)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"
               d="M-7,3 C-9,3 -10,1 -9,-1 C-10,-3 -8,-5 -6,-4 C-5,-7 -2,-9 1,-8 C4,-9 7,-7 7,-4 C9,-3 10,-1 9,1 C10,3 8,5 6,4 L-7,4 Z"/>
              <line x1="-3" y1="6" x2="-3" y2="4" stroke="rgba(255,255,255,0.7)" stroke-width="1.4" stroke-linecap="round"/>
              <line x1="0" y1="7" x2="0" y2="4" stroke="rgba(255,255,255,0.7)" stroke-width="1.4" stroke-linecap="round"/>
              <line x1="3" y1="6" x2="3" y2="4" stroke="rgba(255,255,255,0.7)" stroke-width="1.4" stroke-linecap="round"/>`;
    default:
      // Diamond fallback
      return `<path ${base} d="M0,-8 L7,0 L0,8 L-7,0 Z" opacity="0.7"/>`;
  }
}


function graphSection(graph: GraphOverview | null): string {
  if (!graph) {
    return `<div class="empty-state">Graph data not yet loaded. Run <strong>Analyze</strong> first, then re-open the Graph tab.</div>`;
  }

  const { nodes, edges, truncated, total_node_count } = graph;

  const truncNote = truncated
    ? `<div class="graph-note">Showing the ${escHtml(String(nodes.length))} most-connected nodes out of ${escHtml(String(total_node_count))}.</div>`
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

  const idxById: Record<string, number> = {};
  nodes.forEach((n, i) => { idxById[n.node_id] = i; });

  // Edges — each gets an id so JS can update endpoints when a node is dragged.
  // Shapes use (0,0)-relative coords; position comes from the parent <g> transform.
  const edgeDefs = edges.map((e, ei) => {
    const si = idxById[e.src_node_id];
    const di = idxById[e.dst_node_id];
    if (si === undefined || di === undefined) return "";
    const s = positions[si];
    const d = positions[di];
    const dx = d.x - s.x;
    const dy = d.y - s.y;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const srcR = (nodes[si].kind === "FILE" ? FILE_HALF : NODE_R) + 2;
    const dstR = (nodes[di].kind === "FILE" ? FILE_HALF : NODE_R) + 6;
    const x1 = (s.x + (dx / len) * srcR).toFixed(1);
    const y1 = (s.y + (dy / len) * srcR).toFixed(1);
    const x2 = (d.x - (dx / len) * dstR).toFixed(1);
    const y2 = (d.y - (dy / len) * dstR).toFixed(1);
    return `<line id="edge-${ei}" data-src="${si}" data-dst="${di}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="var(--rf-edge)" stroke-width="1.5" opacity="0.7" marker-end="url(#arrowhead)"/>`;
  }).join("");

  // Nodes — each <g> uses transform="translate(x,y)" so dragging only touches the transform.
  // All child shapes are drawn around (0,0).
  const nodeShapes = nodes.map((n, i) => {
    const { x, y } = positions[i];
    const color = NODE_COLOR[n.kind] ?? NODE_COLOR_DEFAULT;
    const rawLabel = n.name.length > 15 ? n.name.slice(0, 14) + "…" : n.name;
    const label = escHtml(rawLabel);
    const title = escHtml(`${n.name} (${n.kind})${n.file_path ? "\n" + n.file_path : ""}`);

    // ── Node body shape ──────────────────────────────────────────────────────
    // data-idx is on BOTH the shape and the group so closest() works from any child
    let shape: string;
    if (n.kind === "FILE") {
      shape = `<rect x="${-FILE_HALF}" y="${(-FILE_HALF * 0.8).toFixed(1)}" width="${FILE_HALF * 2}" height="${(FILE_HALF * 1.6).toFixed(1)}" rx="6" fill="${escHtml(color)}" stroke="rgba(255,255,255,0.22)" stroke-width="1.5" class="graph-node" data-idx="${i}"/>`;
    } else {
      shape = `<circle cx="0" cy="0" r="${NODE_R}" fill="${escHtml(color)}" stroke="rgba(255,255,255,0.22)" stroke-width="1.5" class="graph-node" data-idx="${i}"/>`;
    }

    // ── Kind icon (SVG path, centered at 0,0) ───────────────────────────────
    const iconEl = kindIcon(n.kind);

    // ── Label pill ──────────────────────────────────────────────────────────
    // Approximate label width: ~6.3px per char for font-size 10
    const labelW = Math.max(rawLabel.length * 6.3 + 12, 32);
    const labelY = NODE_R + 10;
    const pillEl = `<rect x="${(-labelW / 2).toFixed(1)}" y="${labelY}" width="${labelW.toFixed(1)}" height="15" rx="7.5" fill="var(--vscode-editor-inactiveSelectionBackground)" opacity="0.88" pointer-events="none"/>`;
    const textEl = `<text x="0" y="${labelY + 10.5}" text-anchor="middle" font-size="10" font-weight="600" fill="var(--vscode-foreground)" pointer-events="none" style="font-family:var(--vscode-font-family)">${label}</text>`;

    return `<g id="node-g-${i}" transform="translate(${x.toFixed(1)},${y.toFixed(1)})" class="node-group" data-idx="${i}"><title>${title}</title>${shape}${iconEl}${pillEl}${textEl}</g>`;
  }).join("");

  const svg = `<svg viewBox="0 0 ${SVG_W} ${SVG_H}" xmlns="http://www.w3.org/2000/svg" id="graph-svg" style="cursor:default;user-select:none">
  <defs>
    <style>
      :root { --rf-edge: var(--vscode-foreground); }
      .graph-node { cursor: grab; transition: filter 0.15s; }
      .graph-node:hover { filter: brightness(1.22) drop-shadow(0 0 4px rgba(255,255,255,0.18)); }
      .node-group.dragging .graph-node { cursor: grabbing; filter: brightness(1.3) drop-shadow(0 0 6px rgba(255,255,255,0.25)); }
    </style>
    <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0,0 L0,6 L8,3 z" fill="var(--vscode-panel-border)" opacity="0.9"/>
    </marker>
  </defs>
  <g id="edges-layer">${edgeDefs}</g>
  <g id="nodes-layer">${nodeShapes}</g>
</svg>`;

  // Node metadata for the detail panel and drag radii.
  const nodeDataJson = JSON.stringify(
    nodes.map((n) => ({
      name: n.name,
      kind: n.kind,
      file_path: n.file_path ?? "",
      r: n.kind === "FILE" ? FILE_HALF : NODE_R,
    }))
  ).replace(/</g, "\\u003c");

  // Edge connectivity data for live endpoint recalculation during drag.
  const edgeDataJson = JSON.stringify(
    edges.map((e, ei) => ({
      id: ei,
      si: idxById[e.src_node_id] ?? -1,
      di: idxById[e.dst_node_id] ?? -1,
    })).filter((e) => e.si !== -1 && e.di !== -1)
  ).replace(/</g, "\\u003c");

  return `
${truncNote}
${legend}
<h2>Dependency graph <span class="muted" style="font-size:0.82em;font-weight:400;text-transform:none;letter-spacing:0">— drag nodes to rearrange</span></h2>
<div class="graph-wrap">${svg}</div>
<div class="node-detail" id="node-detail">
  <span class="muted">Click a node to see details.</span>
</div>
<script>
(function() {
  var nodeData  = ${nodeDataJson};
  var edgeData  = ${edgeDataJson};
  var SVG_W     = ${SVG_W};
  var SVG_H     = ${SVG_H};

  // Current positions — kept in sync with the <g> transforms
  var pos = nodeData.map(function(_, i) {
    var g = document.getElementById('node-g-' + i);
    var t = g ? g.getAttribute('transform') : 'translate(0,0)';
    var m = t.match(/translate\\(([\\d.\\-]+),([\\d.\\-]+)\\)/);
    return m ? { x: parseFloat(m[1]), y: parseFloat(m[2]) } : { x: 0, y: 0 };
  });

  var detail = document.getElementById('node-detail');
  var svg    = document.getElementById('graph-svg');
  if (!svg) return;

  // ── Edge endpoint recalculation ─────────────────────────────────────────────
  function updateEdges() {
    edgeData.forEach(function(e) {
      var line = document.getElementById('edge-' + e.id);
      if (!line) return;
      var s = pos[e.si], d = pos[e.di];
      var dx = d.x - s.x, dy = d.y - s.y;
      var len = Math.sqrt(dx*dx + dy*dy) || 1;
      var srcR = nodeData[e.si].r + 2;
      var dstR = nodeData[e.di].r + 6;
      line.setAttribute('x1', (s.x + (dx/len)*srcR).toFixed(1));
      line.setAttribute('y1', (s.y + (dy/len)*srcR).toFixed(1));
      line.setAttribute('x2', (d.x - (dx/len)*dstR).toFixed(1));
      line.setAttribute('y2', (d.y - (dy/len)*dstR).toFixed(1));
    });
  }

  // ── Drag state ──────────────────────────────────────────────────────────────
  // dragged = { idx, offX, offY, group, moved }
  var dragged = null;

  function svgPoint(clientX, clientY) {
    var pt = svg.createSVGPoint();
    pt.x = clientX; pt.y = clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  }

  // Resolve the node index from any element inside a node group
  function nodeIdxFromTarget(el) {
    // Try the element itself first (shape has data-idx), then walk up to the group
    if (el.hasAttribute && el.hasAttribute('data-idx')) return parseInt(el.getAttribute('data-idx'), 10);
    var g = el.closest ? el.closest('.node-group') : null;
    if (g && g.hasAttribute('data-idx')) return parseInt(g.getAttribute('data-idx'), 10);
    return -1;
  }

  svg.addEventListener('mousedown', function(e) {
    var idx = nodeIdxFromTarget(e.target);
    if (idx < 0) return;
    e.preventDefault();
    var g = document.getElementById('node-g-' + idx);
    if (!g) return;
    var sp = svgPoint(e.clientX, e.clientY);
    dragged = { idx: idx, offX: sp.x - pos[idx].x, offY: sp.y - pos[idx].y, group: g, moved: false };
    g.classList.add('dragging');
    document.getElementById('nodes-layer').appendChild(g);
  });

  window.addEventListener('mousemove', function(e) {
    if (!dragged) return;
    e.preventDefault();
    var sp = svgPoint(e.clientX, e.clientY);
    var nx = sp.x - dragged.offX;
    var ny = sp.y - dragged.offY;
    var margin = nodeData[dragged.idx].r + 4;
    nx = Math.max(margin, Math.min(SVG_W - margin, nx));
    ny = Math.max(margin, Math.min(SVG_H - margin, ny));
    // Mark as moved if more than 3px from original
    var dx = nx - pos[dragged.idx].x, dy = ny - pos[dragged.idx].y;
    if (Math.sqrt(dx*dx+dy*dy) > 3) dragged.moved = true;
    pos[dragged.idx] = { x: nx, y: ny };
    dragged.group.setAttribute('transform', 'translate(' + nx.toFixed(1) + ',' + ny.toFixed(1) + ')');
    updateEdges();
  });

  window.addEventListener('mouseup', function() {
    if (!dragged) return;
    dragged.group.classList.remove('dragging');
    dragged = null;
  });

  // ── Node click → detail panel ───────────────────────────────────────────────
  // Fires after mouseup. Only show detail if the node wasn't dragged.
  svg.addEventListener('click', function(e) {
    // If a drag just ended and it actually moved, skip this click
    if (dragged && dragged.moved) return;
    var idx = nodeIdxFromTarget(e.target);
    if (idx < 0) return;
    var n = nodeData[idx];
    var esc = function(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); };
    var kindLabels = {
      FILE:'File', SYMBOL:'Symbol', TEST:'Test', MODULE:'Module',
      API_ENDPOINT:'API Endpoint', CONFIG_ITEM:'Config Item', EXTERNAL_SERVICE:'External Service'
    };
    var kindLabel = kindLabels[n.kind] || n.kind;
    var fp = n.file_path ? '<div class="detail-path">' + esc(n.file_path) + '</div>' : '';
    detail.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px">' +
        '<div class="detail-label">' + esc(n.name) + '</div>' +
        '<span class="badge" style="background:' + (nodeColors[n.kind]||\'#888\') + ';color:#fff;margin-left:0">' + esc(kindLabel) + '</span>' +
      '</div>' + fp;
  });

  var nodeColors = ${JSON.stringify(NODE_COLOR).replace(/</g, "\\u003c")};
}());
</script>
`;
}

// ── Inline script ──────────────────────────────────────────────────────────────

function script(state: PanelState): string {
  if (state.state !== "ready") {
    // Loading/error states have no interactive elements.
    return "";
  }

  return `<script>
(function () {
  const vscode = acquireVsCodeApi();

  // ── Tab switching (pure client-side, no host round-trip) ──────────────────
  const tabs = ['overview', 'impact', 'graph', 'audit'];

  function showTab(name) {
    tabs.forEach(function(t) {
      var sec = document.getElementById('tab-' + t);
      if (sec) sec.classList.toggle('tab-visible', t === name);
    });
    document.querySelectorAll('#nav-bar button[data-tab]').forEach(function(btn) {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === name);
    });
  }

  document.querySelectorAll('#nav-bar button[data-tab]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      showTab(btn.getAttribute('data-tab'));
    });
  });

  // ── Analyze button (lives in overview tab) ─────────────────────────────────
  var btnAnalyze = document.getElementById('btn-analyze');
  if (btnAnalyze) {
    btnAnalyze.addEventListener('click', function() {
      vscode.postMessage({ type: 'analyze' });
    });
  }

  // ── Impact form stepper ────────────────────────────────────────────────────
  var stepperVal = 1;
  var stepperValEl  = document.getElementById('stepper-val');
  var previewFromEl = document.getElementById('preview-from');
  var minusBtn = document.getElementById('stepper-minus');
  var plusBtn  = document.getElementById('stepper-plus');

  function updateStepper() {
    if (stepperValEl)  stepperValEl.textContent  = String(stepperVal);
    if (previewFromEl) previewFromEl.textContent = 'HEAD~' + stepperVal;
  }
  if (minusBtn) minusBtn.addEventListener('click', function() {
    if (stepperVal > 1) { stepperVal--; updateStepper(); }
  });
  if (plusBtn) plusBtn.addEventListener('click', function() {
    if (stepperVal < 50) { stepperVal++; updateStepper(); }
  });
  updateStepper();

  // ── Impact run ─────────────────────────────────────────────────────────────
  var btnImpact = document.getElementById('btn-impact');
  if (btnImpact) {
    btnImpact.addEventListener('click', function() {
      // If the advanced section is open and has values, use those; else use the stepper.
      var advDetails = document.querySelector('details.impact-advanced');
      var fromInput = document.getElementById('from-ref');
      var toInput   = document.getElementById('to-ref');
      var advancedFrom = fromInput ? fromInput.value.trim() : '';
      var advancedTo   = toInput   ? toInput.value.trim()   : '';
      var useAdvanced  = advDetails && advDetails.open && advancedFrom;

      var from = useAdvanced ? advancedFrom : ('HEAD~' + stepperVal);
      var to   = useAdvanced ? (advancedTo || 'HEAD') : 'HEAD';
      vscode.postMessage({ type: 'impact', from: from, to: to });
    });
  }

  // ── Audit run ──────────────────────────────────────────────────────────────
  var btnAudit = document.getElementById('btn-audit');
  if (btnAudit) {
    btnAudit.addEventListener('click', function() {
      var orgInput   = document.getElementById('audit-org');
      var tokenInput = document.getElementById('audit-token');
      var org   = orgInput   ? orgInput.value.trim()   : '';
      var token = tokenInput ? tokenInput.value.trim() : '';
      if (!org) { orgInput && orgInput.focus(); return; }
      vscode.postMessage({ type: 'audit', org: org, token: token });
    });
  }

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
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
