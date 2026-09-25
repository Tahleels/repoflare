import { test } from "node:test";
import assert from "node:assert/strict";
import { buildWebviewHtml } from "../src/webview";
import type { StatusResult, ImpactSummary } from "../src/rpc";

test("escapes HTML-significant characters in error messages", () => {
  const html = buildWebviewHtml({ state: "error", message: '<script>alert("xss")</script>' });

  assert.ok(!html.includes("<script>alert"));
  assert.ok(html.includes("&lt;script&gt;"));
});

test("escapes a malicious repository root path in the overview", () => {
  const status: StatusResult = { snapshot_id: "abc123", node_count: 3, edge_count: 2 };
  const html = buildWebviewHtml({
    state: "overview",
    status,
    root: '<img src=x onerror=alert(1)>',
  });

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

  const html = buildWebviewHtml({ state: "impact", status, root: "/repo", from: "HEAD~1", to: "HEAD", impact });

  assert.ok(!html.includes("<b>evil</b>"));
  assert.ok(html.includes("&lt;b&gt;evil&lt;/b&gt;"));
  assert.ok(!html.includes("<script>x</script>.py"));
});

test("overview shows 'not yet analyzed' when there is no snapshot", () => {
  const status: StatusResult = { snapshot_id: null, node_count: 0, edge_count: 0 };
  const html = buildWebviewHtml({ state: "overview", status, root: "/repo" });

  assert.ok(html.includes("not yet analyzed"));
});

test("impact view renders an empty state when there are no changed files", () => {
  const status: StatusResult = { snapshot_id: "abc", node_count: 0, edge_count: 0 };
  const impact: ImpactSummary = { changed_files: [], results: [], node_summaries: {} };
  const html = buildWebviewHtml({ state: "impact", status, root: "/repo", from: "HEAD~1", to: "HEAD", impact });

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
