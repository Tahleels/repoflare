import { test } from "node:test";
import assert from "node:assert/strict";
import { buildWebviewHtml, escHtml } from "../src/webview";
import type { StatusResult, ImpactSummary, GraphOverview } from "../src/rpc";

// ── Helpers ──────────────────────────────────────────────────────────────────

function readyHtml(
  status: StatusResult,
  root: string,
  activeTab: "overview" | "impact" | "graph" = "overview",
  graph: GraphOverview | null = null,
  impactResult?: { from: string; to: string; impact: ImpactSummary }
): string {
  return buildWebviewHtml({ state: "ready", status, root, graph, activeTab, impactResult });
}

// ── Escape / XSS tests ───────────────────────────────────────────────────────

test("escapes HTML-significant characters in error messages", () => {
  const html = buildWebviewHtml({ state: "error", message: '<script>alert("xss")</script>' });

  assert.ok(!html.includes("<script>alert"));
  assert.ok(html.includes("&lt;script&gt;"));
});

test("escapes a malicious repository root path in the overview", () => {
  const status: StatusResult = { snapshot_id: "abc123", node_count: 3, edge_count: 2 };
  const html = readyHtml(status, '<img src=x onerror=alert(1)>');

  assert.ok(!html.includes("<img src=x onerror"));
  assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"));
});

test("escapes node labels and file paths in the impact table", () => {
  const status: StatusResult = { snapshot_id: "abc123", node_count: 1, edge_count: 0 };
  const impact: ImpactSummary = {
    changed_files: ["a.py"],
    results: [
      {
        impact_id: "i1",
        change_set_id: "cs1",
        category: "DIRECT",
        affected_node_ids: ["n1"],
        provenance: "graph_traversal",
      },
    ],
    node_summaries: {
      n1: { node_id: "n1", label: '<b>evil</b>', file_path: "<script>x</script>.py" },
    },
  };

  const html = readyHtml(status, "/repo", "impact", null, { from: "HEAD~1", to: "HEAD", impact });

  assert.ok(!html.includes("<b>evil</b>"));
  assert.ok(html.includes("&lt;b&gt;evil&lt;/b&gt;"));
  assert.ok(!html.includes("<script>x</script>.py"));
});

test("overview shows first-run prompt when there is no snapshot", () => {
  const status: StatusResult = { snapshot_id: null, node_count: 0, edge_count: 0 };
  const html = readyHtml(status, "/repo");

  assert.ok(html.includes("hasn't been analyzed yet"));
  // Must NOT show "not yet analyzed" bare text (old behaviour replaced by first-run block)
  assert.ok(!html.includes("not yet analyzed"));
});

test("impact view renders an empty state when there are no changed files", () => {
  const status: StatusResult = { snapshot_id: "abc", node_count: 0, edge_count: 0 };
  const impact: ImpactSummary = { changed_files: [], results: [], node_summaries: {} };
  const html = readyHtml(status, "/repo", "impact", null, { from: "HEAD~1", to: "HEAD", impact });

  assert.ok(html.includes("No changed files between these refs."));
});

test("loading state renders without throwing and contains no interpolated data", () => {
  const html = buildWebviewHtml({ state: "loading" });

  assert.ok(html.includes("Loading"));
});

test("every rendered page sets a restrictive Content-Security-Policy", () => {
  const html = buildWebviewHtml({ state: "loading" });

  assert.ok(html.includes("default-src 'none'"));
});

test("rendered page shows the three nav tabs and the analyze button in overview", () => {
  const status: StatusResult = { snapshot_id: "s1", node_count: 2, edge_count: 1 };
  const html = readyHtml(status, "/repo");

  // Three nav tabs
  assert.ok(html.includes("Overview"));
  assert.ok(html.includes("Impact"));
  assert.ok(html.includes("Graph"));
  // Analyze button lives in the overview section, not in the nav
  assert.ok(html.includes("Re-analyze repository"));
});

// ── Graph tab tests ──────────────────────────────────────────────────────────

function makeGraph(overrides?: Partial<GraphOverview>): GraphOverview {
  return {
    nodes: [
      { node_id: "n1", kind: "FILE", name: "a.py", file_path: "a.py" },
      { node_id: "n2", kind: "SYMBOL", name: "helper", file_path: "a.py" },
    ],
    edges: [
      { src_node_id: "n1", dst_node_id: "n2", edge_type: "CONTAINS" },
    ],
    truncated: false,
    total_node_count: 2,
    ...overrides,
  };
}

function graphHtml(graph: GraphOverview): string {
  const status: StatusResult = { snapshot_id: "s1", node_count: graph.total_node_count, edge_count: graph.edges.length };
  return readyHtml(status, "/repo", "graph", graph);
}

test("graph state renders the correct node count", () => {
  const html = graphHtml(makeGraph());

  // Two nodes → two shapes in SVG (one rect for FILE, one circle for SYMBOL)
  assert.ok(html.includes('<rect '));   // FILE node
  assert.ok(html.includes('<circle ')); // SYMBOL node
});

test("graph state renders edges as SVG lines", () => {
  const html = graphHtml(makeGraph());

  assert.ok(html.includes('<line '));
});

test("graph state shows truncated note when truncated=true", () => {
  const html = graphHtml(makeGraph({ truncated: true, total_node_count: 500 }));

  assert.ok(html.includes("most-connected nodes out of"));
  assert.ok(html.includes("500"));
});

test("graph state does NOT show truncated note when truncated=false", () => {
  const html = graphHtml(makeGraph({ truncated: false, total_node_count: 2 }));

  assert.ok(!html.includes("most-connected nodes out of"));
});

test("graph state escapes XSS in node name and file_path", () => {
  const maliciousGraph: GraphOverview = {
    nodes: [
      { node_id: "x1", kind: "SYMBOL", name: '<script>evil()</script>', file_path: '"><img onerror=x>' },
    ],
    edges: [],
    truncated: false,
    total_node_count: 1,
  };
  const html = graphHtml(maliciousGraph);

  assert.ok(!html.includes("<script>evil()"));
  assert.ok(!html.includes('"><img onerror=x>'));
  assert.ok(html.includes("&lt;script&gt;"));
});

test("escHtml is exported and handles all five HTML-significant chars", () => {
  assert.equal(escHtml('a & b < c > d " e'), "a &amp; b &lt; c &gt; d &quot; e");
});
