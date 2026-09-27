/**
 * buildWebviewHtml — renders the full self-contained HTML page for the RepoFlare panel.
 *
 * Everything is inlined (no external assets) so it works with localResourceRoots=[].
 * The page uses VS Code's CSS variables for colours so it respects the active theme.
 *
 * All three tabs (Overview, Impact, Graph) are rendered into the page at once as
 * hidden <section> elements. Tab switching is handled by pure client-side JS — no round-trip
 * to the extension host, which eliminates the full-page blink on navigation.
 *
 * Only two actions still post to the host:
 *   - "analyze"  — runs the analyzer
 *   - "impact"   — queries impact for the given refs
 */

import { StatusResult, ImpactSummary, GraphOverview, GraphNode } from "./rpc";

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
      activeTab: "overview" | "impact" | "graph" | "analyze";
      /** Impact results to pre-populate, if any. */
      impactResult?: { from: string; to: string; impact: ImpactSummary };
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
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

  :root {
    --gap: 18px;
    --gap-sm: 10px;
    --radius-card: 12px;
    --radius-btn: 8px;
    --radius-pill: 20px;
    /* Brand palette */
    --rf-orange: #f97316;
    --rf-orange-dim: rgba(249,115,22,0.18);
    --rf-orange-glow: rgba(249,115,22,0.35);
    --rf-blue: #60a5fa;
    --rf-blue-dim: rgba(96,165,250,0.15);
    --rf-purple: #a78bfa;
    --rf-green: #34d399;
    --rf-yellow: #fbbf24;
    --rf-red: #f87171;
    /* Glass card */
    --rf-card-bg: rgba(255,255,255,0.04);
    --rf-card-border: rgba(255,255,255,0.09);
    --rf-card-hover: rgba(255,255,255,0.07);
    /* Edge color in SVG graph */
    --rf-edge: rgba(255,255,255,0.2);
  }

  *, *::before, *::after { box-sizing: border-box; }

  body {
    font-family: Inter, var(--vscode-font-family), -apple-system, sans-serif;
    font-size: 13px;
    color: var(--vscode-foreground);
    background: var(--vscode-editor-background);
    margin: 0;
    padding: 0;
    line-height: 1.6;
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
  }

  /* ── Scrollbar ──────────────────────────────────────────────────────────── */
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.22); }

  /* ── Typography ─────────────────────────────────────────────────────────── */
  h1 { font-size: 1.1em; font-weight: 800; margin: 0; letter-spacing: -0.02em; }
  h2 {
    font-size: 0.72em;
    font-weight: 700;
    margin: var(--gap) 0 10px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--vscode-descriptionForeground);
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
  .muted { color: var(--vscode-descriptionForeground); font-size: 0.88em; }
  code { font-family: var(--vscode-editor-font-family, 'Cascadia Code', monospace); font-size: 0.9em; }

  /* ── Header ─────────────────────────────────────────────────────────────── */
  .rf-header {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 16px 20px 12px;
    border-bottom: 1px solid var(--rf-card-border);
    background: linear-gradient(135deg, rgba(249,115,22,0.06) 0%, transparent 60%);
  }
  .rf-header-logo { flex-shrink: 0; }
  .rf-header-text { flex: 1; min-width: 0; }
  .rf-header-title {
    font-size: 1.05em;
    font-weight: 800;
    letter-spacing: -0.02em;
    background: linear-gradient(135deg, var(--rf-orange) 0%, var(--rf-yellow) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
  .rf-header-sub {
    font-size: 0.75em;
    color: var(--vscode-descriptionForeground);
    font-weight: 500;
    letter-spacing: 0.04em;
    margin-top: 1px;
  }
  .rf-status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--rf-green);
    box-shadow: 0 0 6px var(--rf-green);
    flex-shrink: 0;
    margin-left: auto;
  }

  /* ── Nav tabs ───────────────────────────────────────────────────────────── */
  .nav {
    display: flex;
    gap: 2px;
    padding: 10px 20px 0;
    border-bottom: 1px solid var(--rf-card-border);
    background: rgba(0,0,0,0.12);
  }
  .nav button {
    background: none;
    color: var(--vscode-descriptionForeground);
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: var(--radius-btn) var(--radius-btn) 0 0;
    padding: 8px 18px 10px;
    cursor: pointer;
    font-size: 0.82em;
    font-weight: 600;
    letter-spacing: 0.03em;
    transition: color 0.15s, border-color 0.15s, background 0.15s;
    display: flex;
    align-items: center;
    gap: 6px;
    white-space: nowrap;
    font-family: inherit;
  }
  .nav button:hover {
    color: var(--vscode-foreground);
    background: rgba(255,255,255,0.04);
  }
  .nav button.active {
    color: var(--rf-orange);
    border-bottom-color: var(--rf-orange);
    background: rgba(249,115,22,0.06);
  }
  .nav-icon { font-size: 1em; }

  /* ── Main content area ──────────────────────────────────────────────────── */
  .rf-content {
    padding: 20px 20px;
    max-width: 900px;
  }

  /* ── Tab sections ───────────────────────────────────────────────────────── */
  .tab-section { display: none; }
  .tab-section.tab-visible { display: block; }

  /* ── Glass card ──────────────────────────────────────────────────────────── */
  .card {
    background: var(--rf-card-bg);
    border: 1px solid var(--rf-card-border);
    border-radius: var(--radius-card);
    padding: 16px 20px;
    margin-bottom: var(--gap);
    transition: border-color 0.2s;
  }
  .card:hover { border-color: rgba(255,255,255,0.14); }
  .card.card-accent { border-color: var(--rf-orange-dim); background: linear-gradient(135deg, rgba(249,115,22,0.06) 0%, var(--rf-card-bg) 60%); }
  .card.card-info { border-color: var(--rf-blue-dim); }
  .card p { margin: 0 0 12px; font-size: 0.9em; line-height: 1.7; color: var(--vscode-descriptionForeground); }
  .card p:last-child { margin-bottom: 0; }

  /* ── Stat row ───────────────────────────────────────────────────────────── */
  .stat-row { display: flex; gap: var(--gap-sm); margin-bottom: var(--gap); flex-wrap: wrap; }
  .stat-card {
    background: var(--rf-card-bg);
    border: 1px solid var(--rf-card-border);
    border-radius: var(--radius-card);
    padding: 16px 20px;
    min-width: 100px;
    flex: 1;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s, transform 0.15s;
  }
  .stat-card:hover { border-color: rgba(249,115,22,0.3); transform: translateY(-1px); }
  .stat-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--rf-orange), var(--rf-purple));
  }
  .stat-card .value { font-size: 2em; font-weight: 800; letter-spacing: -0.03em; color: var(--vscode-foreground); }
  .stat-card .label { font-size: 0.72em; color: var(--vscode-descriptionForeground); text-transform: uppercase; letter-spacing: 0.1em; margin-top: 4px; font-weight: 600; }

  /* ── Buttons ─────────────────────────────────────────────────────────────── */
  button.action {
    background: linear-gradient(135deg, var(--rf-orange) 0%, #fb923c 100%);
    color: #fff;
    border: none;
    border-radius: var(--radius-btn);
    padding: 9px 20px;
    cursor: pointer;
    font-size: 0.84em;
    font-weight: 700;
    margin-right: 8px;
    letter-spacing: 0.03em;
    transition: opacity 0.15s, transform 0.12s, box-shadow 0.15s;
    font-family: inherit;
    box-shadow: 0 2px 12px rgba(249,115,22,0.3);
  }
  button.action:hover {
    opacity: 0.92;
    transform: translateY(-1px);
    box-shadow: 0 4px 18px rgba(249,115,22,0.45);
  }
  button.action:active { transform: translateY(0); opacity: 1; }
  button.secondary {
    background: var(--rf-card-bg);
    border: 1px solid var(--rf-card-border);
    color: var(--vscode-foreground);
    border-radius: var(--radius-btn);
    padding: 9px 20px;
    cursor: pointer;
    font-size: 0.84em;
    font-weight: 600;
    letter-spacing: 0.02em;
    transition: background 0.15s, border-color 0.15s;
    font-family: inherit;
  }
  button.secondary:hover { background: var(--rf-card-hover); border-color: rgba(255,255,255,0.18); }

  /* ── Inputs ──────────────────────────────────────────────────────────────── */
  .ref-input {
    background: rgba(0,0,0,0.25);
    color: var(--vscode-foreground);
    border: 1px solid var(--rf-card-border);
    border-radius: var(--radius-btn);
    padding: 8px 12px;
    font-size: 0.84em;
    font-family: var(--vscode-editor-font-family, monospace);
    width: 140px;
    transition: border-color 0.15s;
    outline: none;
  }
  .ref-input:focus { border-color: var(--rf-orange); box-shadow: 0 0 0 2px var(--rf-orange-dim); }
  .ref-input::placeholder { color: var(--vscode-descriptionForeground); opacity: 0.6; }
  .input-label {
    font-size: 0.75em;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--vscode-descriptionForeground);
    display: block;
    margin-bottom: 5px;
  }
  .input-group { display: flex; flex-direction: column; }

  /* ── Impact form ─────────────────────────────────────────────────────────── */
  .impact-form {
    display: flex;
    align-items: flex-end;
    flex-wrap: wrap;
    gap: 14px;
    margin-bottom: var(--gap);
  }

  /* ── Badge pills ─────────────────────────────────────────────────────────── */
  .badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 10px;
    border-radius: var(--radius-pill);
    font-size: 0.72em;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    white-space: nowrap;
  }
  .badge-direct   { background: rgba(248,113,113,0.18); color: #f87171; border: 1px solid rgba(248,113,113,0.3); }
  .badge-indirect { background: rgba(251,191,36,0.15);  color: #fbbf24; border: 1px solid rgba(251,191,36,0.3);  }
  .badge-related  { background: rgba(96,165,250,0.15);  color: #60a5fa; border: 1px solid rgba(96,165,250,0.3);  }
  .badge-possible { background: rgba(52,211,153,0.15);  color: #34d399; border: 1px solid rgba(52,211,153,0.3);  }

  /* ── Table ───────────────────────────────────────────────────────────────── */
  table { border-collapse: collapse; width: 100%; margin-top: 4px; }
  th, td { text-align: left; padding: 9px 14px; border-bottom: 1px solid var(--rf-card-border); font-size: 0.87em; }
  th { color: var(--vscode-descriptionForeground); font-weight: 700; text-transform: uppercase; font-size: 0.72em; letter-spacing: 0.1em; background: rgba(0,0,0,0.12); }
  tr:hover td { background: rgba(255,255,255,0.025); }
  tr:last-child td { border-bottom: none; }
  .filepath { font-family: var(--vscode-editor-font-family, monospace); color: var(--rf-blue); font-size: 0.88em; }

  /* ── Snap ID ─────────────────────────────────────────────────────────────── */
  .snap-id {
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 0.82em;
    background: rgba(0,0,0,0.3);
    border: 1px solid var(--rf-card-border);
    padding: 3px 10px;
    border-radius: 6px;
    letter-spacing: 0.03em;
    color: var(--rf-blue);
  }

  /* ── Loading / error ────────────────────────────────────────────────────── */
  .spinner {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 48px 20px;
    color: var(--vscode-descriptionForeground);
    font-size: 0.92em;
  }
  .spinner-ring {
    width: 20px; height: 20px;
    border: 2px solid var(--rf-card-border);
    border-top-color: var(--rf-orange);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .error-box {
    background: rgba(248,113,113,0.08);
    border: 1px solid rgba(248,113,113,0.25);
    padding: 16px 20px;
    border-radius: var(--radius-card);
    margin-top: var(--gap);
    font-size: 0.9em;
    color: var(--rf-red);
    display: flex;
    align-items: flex-start;
    gap: 10px;
  }

  /* ── Changed files list ──────────────────────────────────────────────────── */
  .changed-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .changed-list li {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 0;
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 0.87em;
    border-bottom: 1px solid var(--rf-card-border);
    color: var(--rf-yellow);
  }
  .changed-list li:last-child { border-bottom: none; }
  .changed-list li::before { content: '◆'; color: var(--rf-orange); font-size: 0.7em; flex-shrink: 0; }

  /* ── Empty state ─────────────────────────────────────────────────────────── */
  .empty-state {
    color: var(--vscode-descriptionForeground);
    padding: 24px 0;
    font-style: italic;
    font-size: 0.9em;
    text-align: center;
  }

  /* ── First-run ───────────────────────────────────────────────────────────── */
  .first-run {
    border: 1px solid var(--rf-orange-dim);
    border-radius: var(--radius-card);
    padding: 32px 28px;
    margin-top: var(--gap);
    background: linear-gradient(135deg, rgba(249,115,22,0.06) 0%, var(--rf-card-bg) 70%);
    text-align: center;
    position: relative;
    overflow: hidden;
  }
  .first-run::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--rf-orange), var(--rf-purple), var(--rf-blue));
  }
  .first-run-icon { font-size: 2.4em; margin-bottom: 14px; }
  .first-run h3 { font-size: 1em; font-weight: 700; margin: 0 0 10px; }
  .first-run p { margin: 0 0 20px; font-size: 0.9em; color: var(--vscode-descriptionForeground); line-height: 1.7; max-width: 400px; margin-left: auto; margin-right: auto; }

  /* ── Impact results ──────────────────────────────────────────────────────── */
  .impact-results {
    border: 1px solid var(--rf-card-border);
    border-radius: var(--radius-card);
    overflow: hidden;
    margin-bottom: var(--gap-sm);
  }
  .impact-results-header {
    background: rgba(0,0,0,0.18);
    padding: 10px 16px;
    font-size: 0.75em;
    font-weight: 700;
    color: var(--vscode-descriptionForeground);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    border-bottom: 1px solid var(--rf-card-border);
    display: flex;
    align-items: center;
    gap: 8px;
  }

  /* ── Graph tab ───────────────────────────────────────────────────────────── */
  .graph-wrap {
    border: 1px solid var(--rf-card-border);
    border-radius: var(--radius-card);
    overflow: hidden;
    background: rgba(0,0,0,0.2);
    margin-bottom: var(--gap-sm);
  }
  .graph-wrap svg { display: block; width: 100%; }
  .graph-note {
    font-size: 0.78em;
    color: var(--vscode-descriptionForeground);
    margin-bottom: 10px;
    padding: 6px 12px;
    background: rgba(0,0,0,0.15);
    border-radius: 6px;
    display: inline-block;
  }
  .node-detail {
    border: 1px solid var(--rf-card-border);
    border-radius: var(--radius-card);
    padding: 12px 16px;
    font-size: 0.87em;
    min-height: 44px;
    background: var(--rf-card-bg);
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .node-detail .detail-label { font-weight: 700; font-size: 0.96em; }
  .node-detail .detail-path { font-family: var(--vscode-editor-font-family, monospace); color: var(--rf-blue); font-size: 0.88em; margin-top: 2px; }

  /* ── Legend ──────────────────────────────────────────────────────────────── */
  .legend { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 12px; }
  .legend-item { display: flex; align-items: center; gap: 6px; font-size: 0.78em; font-weight: 600; color: var(--vscode-descriptionForeground); }
  .legend-swatch { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }

  /* ── Info strip ──────────────────────────────────────────────────────────── */
  .info-strip {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.78em;
    color: var(--vscode-descriptionForeground);
    padding: 8px 14px;
    background: rgba(0,0,0,0.15);
    border-radius: 8px;
    margin-bottom: var(--gap);
    border: 1px solid var(--rf-card-border);
  }
  .info-strip strong { color: var(--vscode-foreground); font-weight: 700; }

  /* ── Root path ───────────────────────────────────────────────────────────── */
  .root-path {
    font-size: 0.78em;
    color: var(--vscode-descriptionForeground);
    font-family: var(--vscode-editor-font-family, monospace);
    margin-bottom: var(--gap);
    padding: 7px 12px;
    background: rgba(0,0,0,0.15);
    border-radius: 6px;
    border: 1px solid var(--rf-card-border);
    display: flex;
    align-items: center;
    gap: 8px;
  }
</style>`;
}

// ── Header strip ──────────────────────────────────────────────────────────────

function header(): string {
  return `<div class="rf-header">
  <svg class="rf-header-logo" width="36" height="36" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg">
    <!-- Outer glow ring -->
    <circle cx="18" cy="18" r="17" stroke="rgba(249,115,22,0.2)" stroke-width="1"/>
    <!-- Graph edges -->
    <line x1="10" y1="26" x2="26" y2="26" stroke="rgba(255,255,255,0.3)" stroke-width="1.5"/>
    <line x1="18" y1="19" x2="10" y2="26" stroke="rgba(255,255,255,0.18)" stroke-width="1"/>
    <line x1="18" y1="19" x2="26" y2="26" stroke="rgba(255,255,255,0.18)" stroke-width="1"/>
    <!-- Left node -->
    <circle cx="10" cy="26" r="4" fill="#60a5fa"/>
    <!-- Right node -->
    <circle cx="26" cy="26" r="4" fill="#a78bfa"/>
    <!-- Flame -->
    <path d="M18 5 C18 5 13 10 13 15 C13 17 14.2 18.5 15.8 19.5 C15.3 17.8 16.1 16.2 17.1 15.3 C17.1 17.2 18.3 18.3 18.3 19.8 C19.7 18.8 21.2 17 20.7 14.8 C21.9 16 22.4 17.7 22.1 19.2 C23.8 17.8 24.3 15.8 23.6 14 C25.4 15.3 25.9 17.5 25.2 19.2 C27 17.2 27.2 14.2 25.6 12 C24 9.8 21.6 8.2 18 5 Z" fill="#f97316" opacity="0.9"/>
    <path d="M18 9 C18 9 15.5 12 15.5 14.5 C15.5 15.7 16.1 16.7 17 17.2 C16.8 16 17.3 15.2 18 14.5 C18 15.7 18.8 16.4 19 17.2 C19.8 16.3 20.1 15.2 19.6 14 C20.3 14.8 20.6 15.9 20.3 17 C21.3 16.1 21.5 14.5 20.7 13.2 C19.9 12 19.1 10.8 18 9 Z" fill="#fbbf24" opacity="0.85"/>
  </svg>
  <div class="rf-header-text">
    <div class="rf-header-title">RepoFlare</div>
    <div class="rf-header-sub">Repository Intelligence · Graph · AI</div>
  </div>
  <div class="rf-status-dot" title="Extension active"></div>
</div>`;
}

// ── Nav bar ───────────────────────────────────────────────────────────────────

const NAV_ITEMS: Array<{ tab: string; icon: string; label: string }> = [
  { tab: "overview", icon: "⬡", label: "Overview" },
  { tab: "impact",   icon: "⚡", label: "Impact" },
  { tab: "graph",    icon: "◎", label: "Graph" },
];

function nav(active: string): string {
  const buttons = NAV_ITEMS.map(({ tab, icon, label }) => {
    const cls = active === tab || (active === "analyze" && tab === "overview") ? " active" : "";
    return `<button class="${cls}" data-tab="${escHtml(tab)}"><span class="nav-icon">${icon}</span>${label}</button>`;
  }).join("\n  ");

  return `<nav class="nav" id="nav-bar">
  ${buttons}
</nav>`;
}

// ── Body dispatch ─────────────────────────────────────────────────────────────

function body(state: PanelState): string {
  switch (state.state) {
    case "loading":
      return `<div class="spinner"><div class="spinner-ring"></div> Thinking…</div>`;
    case "error":
      return `<div class="rf-content"><div class="error-box">⚠ ${escHtml(state.message)}</div></div>`;
    case "ready":
      return readyBody(state);
  }
}

/**
 * Renders all three tab sections at once. Only the active one is visible initially;
 * the rest are hidden via CSS and revealed by client-side JS without any host round-trip.
 */
function readyBody(state: Extract<PanelState, { state: "ready" }>): string {
  const active = state.activeTab === "analyze" ? "overview" : state.activeTab;
  const vis = (tab: string) => active === tab ? " tab-visible" : "";

  return `<div class="rf-content">
<div id="tab-overview" class="tab-section${vis("overview")}">
  ${overviewSection(state.status, state.root)}
</div>
<div id="tab-impact" class="tab-section${vis("impact")}">
  ${impactSection(state.impactResult)}
</div>
<div id="tab-graph" class="tab-section${vis("graph")}">
  ${graphSection(state.graph)}
</div>
</div>`;
}

// ── Overview tab ──────────────────────────────────────────────────────────────

function overviewSection(status: StatusResult, root: string): string {
  if (!status.snapshot_id) {
    return `
<div class="root-path">📁 ${escHtml(root)}</div>
<div class="first-run">
  <div class="first-run-icon">🔥</div>
  <h3>Ready to analyze</h3>
  <p>Scan every Python, TypeScript, and JavaScript file to build the dependency graph — extracting symbols, calls, imports, and test links.</p>
  <button class="action" id="btn-analyze">⚡ Analyze Repository</button>
</div>`;
  }

  const snapLine = `<span class="snap-id">${escHtml(status.snapshot_id)}</span>`;

  return `
<div class="root-path">📁 ${escHtml(root)}</div>

<div class="stat-row">
  ${statCard(String(status.node_count), "Nodes", "◎")}
  ${statCard(String(status.edge_count), "Edges", "⟶")}
</div>

<h2>Snapshot</h2>
<div class="card card-info" style="display:flex;align-items:center;gap:12px;padding:12px 16px">
  <span style="color:var(--rf-green);font-size:1.1em">✔</span>
  <div>
    <div style="font-size:0.75em;color:var(--vscode-descriptionForeground);font-weight:700;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:4px">Latest Snapshot</div>
    ${snapLine}
  </div>
</div>

<h2>Actions</h2>
<div class="card card-accent">
  <p>Re-scans every Python, TypeScript, and JavaScript file and rebuilds the dependency graph. The current snapshot will be replaced.</p>
  <button class="action" id="btn-analyze">⚡ Re-analyze Repository</button>
</div>`;
}

// ── Impact tab ─────────────────────────────────────────────────────────────────

function impactSection(
  result?: { from: string; to: string; impact: ImpactSummary }
): string {
  const resultsHtml = result ? impactResultsHtml(result.from, result.to, result.impact) : "";

  return `
<h2>⚡ Impact Analysis</h2>
<div class="card">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px">
    <span style="font-size:0.78em;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:var(--vscode-descriptionForeground)">Compare two git refs to see what changed and what it affects</span>
  </div>
  <div class="impact-form">
    <div class="input-group">
      <label class="input-label" for="from-ref">From ref</label>
      <input class="ref-input" id="from-ref" placeholder="HEAD~1" value="${result ? escHtml(result.from) : ""}" />
    </div>
    <div style="color:var(--vscode-descriptionForeground);padding-bottom:2px;font-size:1.1em">→</div>
    <div class="input-group">
      <label class="input-label" for="to-ref">To ref</label>
      <input class="ref-input" id="to-ref" placeholder="HEAD" value="${result ? escHtml(result.to) : ""}" />
    </div>
    <button class="action" id="btn-impact" style="margin-bottom:0">Run analysis</button>
  </div>
</div>
<div id="impact-results-container">${resultsHtml}</div>`;
}

function impactResultsHtml(from: string, to: string, impact: ImpactSummary): string {
  const changedSection =
    impact.changed_files.length === 0
      ? `<div class="empty-state">No changed files between these refs.</div>`
      : `<ul class="changed-list">${impact.changed_files.map((f) => `<li>${escHtml(f)}</li>`).join("")}</ul>`;

  const impactContent =
    impact.results.length === 0
      ? `<div class="empty-state">No affected nodes found — great, this change is well-isolated!</div>`
      : impactTable(impact);

  return `
<div class="impact-results">
  <div class="impact-results-header">
    <span style="color:var(--rf-yellow)">◆</span> Changed files — <strong style="color:var(--vscode-foreground)">${escHtml(from)}</strong> → <strong style="color:var(--vscode-foreground)">${escHtml(to)}</strong>
    <span class="badge badge-indirect" style="margin-left:auto">${impact.changed_files.length} file${impact.changed_files.length !== 1 ? "s" : ""}</span>
  </div>
  <div style="padding:8px 0 4px">${changedSection}</div>
</div>
<div class="impact-results" style="margin-top:10px">
  <div class="impact-results-header">
    <span style="color:var(--rf-red)">◆</span> Affected nodes
    <span class="badge badge-direct" style="margin-left:auto">${impact.results.reduce((n, r) => n + r.affected_node_ids.length, 0)} total</span>
  </div>
  ${impactContent}
</div>`;
}

function statCard(value: string, label: string, icon: string): string {
  return `<div class="stat-card">
  <div style="font-size:1.2em;margin-bottom:6px;opacity:0.5">${icon}</div>
  <div class="value">${escHtml(value)}</div>
  <div class="label">${escHtml(label)}</div>
</div>`;
}

// ── Impact table ───────────────────────────────────────────────────────────────

const CATEGORY_BADGE: Record<string, string> = {
  DIRECT: "badge-direct",
  INDIRECT: "badge-indirect",
  RELATED: "badge-related",
  POSSIBLE: "badge-possible",
};

const CATEGORY_ICON: Record<string, string> = {
  DIRECT: "🔴",
  INDIRECT: "🟡",
  RELATED: "🔵",
  POSSIBLE: "🟢",
};

function impactTable(impact: ImpactSummary): string {
  const rows = impact.results.flatMap((r) =>
    r.affected_node_ids.map((nodeId) => {
      const summary = impact.node_summaries[nodeId];
      const label = summary?.label ?? nodeId;
      const filePath = summary?.file_path ?? "";
      const badgeClass = CATEGORY_BADGE[r.category] ?? "badge-possible";
      const icon = CATEGORY_ICON[r.category] ?? "⚪";
      return `<tr>
  <td><span class="badge ${badgeClass}">${icon} ${escHtml(r.category)}</span></td>
  <td style="font-weight:600">${escHtml(label)}</td>
  <td class="filepath">${escHtml(filePath)}</td>
</tr>`;
    })
  );

  if (rows.length === 0) {
    return `<div class="empty-state" style="padding:20px">No affected nodes found.</div>`;
  }

  return `<table>
<thead><tr><th>Category</th><th>Symbol / File</th><th>Location</th></tr></thead>
<tbody>${rows.join("")}</tbody>
</table>`;
}

// ── Graph tab ─────────────────────────────────────────────────────────────────

// Node colors by kind — chosen for distinctness against both light and dark VS Code themes.
const NODE_COLOR: Record<string, string> = {
  FILE:             "#60a5fa",   // blue
  SYMBOL:           "#34d399",   // green
  TEST:             "#f97316",   // orange
  MODULE:           "#a78bfa",   // purple
  API_ENDPOINT:     "#f472b6",   // pink
  CONFIG_ITEM:      "#2dd4bf",   // teal
  EXTERNAL_SERVICE: "#fb923c",   // amber
};
const NODE_COLOR_DEFAULT = "#9ca3af";

const SVG_W = 800;
const SVG_H = 560;
const NODE_R = 18;    // circle radius for non-FILE nodes
const FILE_HALF = 20; // half-size for FILE rectangles

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
      return `<path ${base} d="M-7,-9 L4,-9 L4,-5 L8,-5 L8,9 L-7,9 Z" fill="none" stroke="rgba(255,255,255,0.85)" stroke-width="1.3"/>
              <path fill="rgba(255,255,255,0.5)" d="M4,-9 L8,-5 L4,-5 Z"/>
              <path fill="none" stroke="rgba(255,255,255,0.85)" stroke-width="1.1" d="M-4,-1 L5,-1 M-4,2 L5,2 M-4,5 L2,5"/>`;
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
      // Lightning bolt
      return `<path ${base} d="M2,-9 L-4,0 L1,0 L-2,9 L8,0 L2,0 Z"/>`;
    case "CONFIG_ITEM":
      // Simplified gear
      return `<circle cx="0" cy="0" r="4" fill="none" stroke="rgba(255,255,255,0.92)" stroke-width="1.8"/>
              <circle cx="0" cy="-7.5" r="1.5" fill="rgba(255,255,255,0.85)"/>
              <circle cx="0" cy="7.5" r="1.5" fill="rgba(255,255,255,0.85)"/>
              <circle cx="-7.5" cy="0" r="1.5" fill="rgba(255,255,255,0.85)"/>
              <circle cx="7.5" cy="0" r="1.5" fill="rgba(255,255,255,0.85)"/>`;
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
    return `<div class="card" style="text-align:center;padding:40px 28px">
  <div style="font-size:2em;margin-bottom:12px">◎</div>
  <div style="font-weight:700;margin-bottom:8px">Graph not loaded</div>
  <p class="muted" style="margin:0">Run <strong>Analyze</strong> first, then re-open the Graph tab.</p>
</div>`;
  }

  const { nodes, edges, truncated, total_node_count } = graph;

  const truncNote = truncated
    ? `<div class="graph-note">Showing the ${escHtml(String(nodes.length))} most-connected nodes out of ${escHtml(String(total_node_count))} total.</div>`
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
    return `<line id="edge-${ei}" data-src="${si}" data-dst="${di}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="var(--rf-edge)" stroke-width="1.5" opacity="0.6" marker-end="url(#arrowhead)"/>`;
  }).join("");

  const nodeShapes = nodes.map((n, i) => {
    const { x, y } = positions[i];
    const color = NODE_COLOR[n.kind] ?? NODE_COLOR_DEFAULT;
    const rawLabel = n.name.length > 15 ? n.name.slice(0, 14) + "…" : n.name;
    const label = escHtml(rawLabel);
    const title = escHtml(`${n.name} (${n.kind})${n.file_path ? "\n" + n.file_path : ""}`);

    let shape: string;
    if (n.kind === "FILE") {
      shape = `<rect x="${-FILE_HALF}" y="${(-FILE_HALF * 0.8).toFixed(1)}" width="${FILE_HALF * 2}" height="${(FILE_HALF * 1.6).toFixed(1)}" rx="7" fill="${escHtml(color)}" stroke="rgba(255,255,255,0.15)" stroke-width="1" class="graph-node" data-idx="${i}"/>`;
    } else {
      shape = `<circle cx="0" cy="0" r="${NODE_R}" fill="${escHtml(color)}" stroke="rgba(255,255,255,0.15)" stroke-width="1" class="graph-node" data-idx="${i}"/>`;
    }

    const iconEl = kindIcon(n.kind);

    const labelW = Math.max(rawLabel.length * 6.3 + 12, 32);
    const labelY = NODE_R + 10;
    const pillEl = `<rect x="${(-labelW / 2).toFixed(1)}" y="${labelY}" width="${labelW.toFixed(1)}" height="15" rx="7.5" fill="rgba(0,0,0,0.55)" pointer-events="none"/>`;
    const textEl = `<text x="0" y="${labelY + 10.5}" text-anchor="middle" font-size="10" font-weight="600" fill="rgba(255,255,255,0.9)" pointer-events="none" style="font-family:var(--vscode-font-family)">${label}</text>`;

    return `<g id="node-g-${i}" transform="translate(${x.toFixed(1)},${y.toFixed(1)})" class="node-group" data-idx="${i}"><title>${title}</title>${shape}${iconEl}${pillEl}${textEl}</g>`;
  }).join("");

  const svg = `<svg viewBox="0 0 ${SVG_W} ${SVG_H}" xmlns="http://www.w3.org/2000/svg" id="graph-svg" style="cursor:default;user-select:none">
  <defs>
    <style>
      :root { --rf-edge: rgba(255,255,255,0.18); }
      .graph-node { cursor: grab; transition: filter 0.15s; }
      .graph-node:hover { filter: brightness(1.3) drop-shadow(0 0 8px currentColor); }
      .node-group.dragging .graph-node { cursor: grabbing; filter: brightness(1.4) drop-shadow(0 0 10px currentColor); }
    </style>
    <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0,0 L0,6 L8,3 z" fill="rgba(255,255,255,0.2)"/>
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
<h2>◎ Dependency Graph <span class="muted" style="font-size:0.82em;font-weight:400;text-transform:none;letter-spacing:0">— drag nodes to rearrange</span></h2>
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

  var pos = nodeData.map(function(_, i) {
    var g = document.getElementById('node-g-' + i);
    var t = g ? g.getAttribute('transform') : 'translate(0,0)';
    var m = t.match(/translate\\(([\\d.\\-]+),([\\d.\\-]+)\\)/);
    return m ? { x: parseFloat(m[1]), y: parseFloat(m[2]) } : { x: 0, y: 0 };
  });

  var detail = document.getElementById('node-detail');
  var svg    = document.getElementById('graph-svg');
  if (!svg) return;

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

  var dragged = null;

  function svgPoint(clientX, clientY) {
    var pt = svg.createSVGPoint();
    pt.x = clientX; pt.y = clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  }

  function nodeIdxFromTarget(el) {
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

  svg.addEventListener('click', function(e) {
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
    var color = nodeColors[n.kind] || '#9ca3af';
    detail.innerHTML =
      '<div style="display:flex;align-items:flex-start;gap:10px;width:100%">' +
        '<div style="width:10px;height:10px;border-radius:50%;background:' + color + ';flex-shrink:0;margin-top:4px;box-shadow:0 0 6px ' + color + '"></div>' +
        '<div style="flex:1;min-width:0">' +
          '<div class="detail-label">' + esc(n.name) + ' <span style="font-size:0.78em;font-weight:600;color:var(--vscode-descriptionForeground);text-transform:uppercase;letter-spacing:0.08em">' + esc(kindLabel) + '</span></div>' +
          fp +
        '</div>' +
      '</div>';
  });

  var nodeColors = ${JSON.stringify(NODE_COLOR).replace(/</g, "\\u003c")};
}());
</script>
`;
}

// ── Inline script ──────────────────────────────────────────────────────────────

function script(state: PanelState): string {
  if (state.state !== "ready") {
    return "";
  }

  return `<script>
(function () {
  const vscode = acquireVsCodeApi();

  // ── Tab switching (pure client-side, no host round-trip) ──────────────────
  const tabs = ['overview', 'impact', 'graph'];

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
      btnAnalyze.textContent = '⏳ Analyzing…';
      btnAnalyze.disabled = true;
      vscode.postMessage({ type: 'analyze' });
    });
  }

  // ── Impact form ────────────────────────────────────────────────────────────
  var btnImpact = document.getElementById('btn-impact');
  if (btnImpact) {
    btnImpact.addEventListener('click', function() {
      var from = document.getElementById('from-ref').value.trim();
      var to   = document.getElementById('to-ref').value.trim() || 'HEAD';
      if (!from) {
        document.getElementById('from-ref').focus();
        return;
      }
      btnImpact.textContent = '⏳ Running…';
      btnImpact.disabled = true;
      vscode.postMessage({ type: 'impact', from: from, to: to });
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
