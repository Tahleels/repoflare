/**
 * RepoFlarePanel — the single VS Code WebviewPanel that renders the RepoFlare UI.
 *
 * Design:
 *  - One panel instance per workspace (singleton).
 *  - All four tabs (Overview, Analyze, Impact, Graph) are rendered into the page at once.
 *    Tab switching happens in pure client-side JS — no round-trip to the host, no blink.
 *  - Only two messages still travel host→webview→host:
 *      "analyze"  — user clicked Analyze
 *      "impact"   — user submitted the impact form
 *  - The panel caches the last-fetched status and graph so switching tabs never re-fetches.
 */

import * as vscode from "vscode";
import { RepoFlareRpcClient, ImpactSummary, RpcError, StatusResult, GraphOverview } from "./rpc";
import { buildWebviewHtml, PanelState } from "./webview";

// Messages the webview sends to the extension host.
type WebviewMessage =
  | { type: "analyze" }
  | { type: "impact"; from: string; to: string }
  | { type: "ready" };

export class RepoFlarePanel {
  private static _current: RepoFlarePanel | undefined;

  private readonly _panel: vscode.WebviewPanel;
  private readonly _disposables: vscode.Disposable[] = [];

  // Cached data so tab switches don't re-fetch
  private _status: StatusResult | null = null;
  private _graph: GraphOverview | null = null;

  private constructor(
    panel: vscode.WebviewPanel,
    private readonly _context: vscode.ExtensionContext,
    private readonly _client: RepoFlareRpcClient,
    private readonly _root: string
  ) {
    this._panel = panel;
    this._panel.onDidDispose(() => this._dispose(), null, this._disposables);
    this._panel.webview.onDidReceiveMessage(
      (msg: WebviewMessage) => this._handleMessage(msg),
      null,
      this._disposables
    );
  }

  /**
   * Create or reveal the panel, opening on the Overview tab.
   */
  static async show(
    context: vscode.ExtensionContext,
    client: RepoFlareRpcClient,
    root: string
  ): Promise<void> {
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : vscode.ViewColumn.One;

    if (RepoFlarePanel._current) {
      RepoFlarePanel._current._panel.reveal(column);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      "repoflare",
      "RepoFlare",
      column ?? vscode.ViewColumn.One,
      {
        enableScripts: true,
        localResourceRoots: [],
        retainContextWhenHidden: true,
      }
    );

    RepoFlarePanel._current = new RepoFlarePanel(panel, context, client, root);
    await RepoFlarePanel._current._load("overview");
  }

  /** Open the panel directly on the graph tab. */
  static async showGraph(
    context: vscode.ExtensionContext,
    client: RepoFlareRpcClient,
    root: string
  ): Promise<void> {
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : vscode.ViewColumn.One;

    if (RepoFlarePanel._current) {
      RepoFlarePanel._current._panel.reveal(column);
      // Panel is already open — no re-fetch needed; the graph tab is already rendered.
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      "repoflare",
      "RepoFlare",
      column ?? vscode.ViewColumn.One,
      { enableScripts: true, localResourceRoots: [], retainContextWhenHidden: true }
    );
    RepoFlarePanel._current = new RepoFlarePanel(panel, context, client, root);
    await RepoFlarePanel._current._load("graph");
  }

  // ── Private ─────────────────────────────────────────────────────────────────

  /**
   * Fetches status + graph in parallel (graph may fail gracefully) and renders the full page.
   * Subsequent tab switches happen client-side without calling this again.
   */
  private async _load(
    activeTab: "overview" | "impact" | "graph",
    impactResult?: { from: string; to: string; impact: ImpactSummary }
  ): Promise<void> {
    this._panel.webview.html = buildWebviewHtml({ state: "loading" });
    try {
      // Fetch status unconditionally; use cached graph if available.
      const [status, graph] = await Promise.all([
        this._client.status(this._root),
        this._graph
          ? Promise.resolve(this._graph)
          : this._client.graphOverview(this._root).catch(() => null),
      ]);
      this._status = status;
      if (graph) { this._graph = graph; }

      this._panel.webview.html = buildWebviewHtml({
        state: "ready",
        status,
        root: this._root,
        graph: this._graph,
        activeTab,
        impactResult,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this._panel.webview.html = buildWebviewHtml({ state: "error", message });
    }
  }

  private async _handleMessage(msg: WebviewMessage): Promise<void> {
    switch (msg.type) {
      case "ready":
        // Webview signals it has fully loaded — nothing to do.
        break;

      case "analyze":
        this._panel.webview.html = buildWebviewHtml({ state: "loading" });
        try {
          const result = await this._client.analyze(this._root);
          vscode.window.showInformationMessage(
            `RepoFlare: analyzed ${result.file_count} files, ` +
            `${result.symbol_count} symbols, ${result.test_count} tests.`
          );
          // Bust the graph cache so the freshly-analyzed graph is fetched.
          this._graph = null;
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          this._panel.webview.html = buildWebviewHtml({ state: "error", message });
          break;
        }
        await this._load("overview");
        break;

      case "impact":
        this._panel.webview.html = buildWebviewHtml({ state: "loading" });
        try {
          const status = this._status ?? await this._client.status(this._root);
          const impact = await this._client.impact(this._root, msg.from, msg.to);
          this._status = status;
          this._panel.webview.html = buildWebviewHtml({
            state: "ready",
            status,
            root: this._root,
            graph: this._graph,
            activeTab: "impact",
            impactResult: { from: msg.from, to: msg.to, impact },
          });
        } catch (err) {
          if (err instanceof RpcError) {
            this._panel.webview.html = buildWebviewHtml({
              state: "error",
              message: `${err.message} (code ${err.code})`,
            });
          } else {
            const message = err instanceof Error ? err.message : String(err);
            this._panel.webview.html = buildWebviewHtml({ state: "error", message });
          }
        }
        break;
    }
  }

  private _dispose(): void {
    RepoFlarePanel._current = undefined;
    this._panel.dispose();
    for (const d of this._disposables) {
      d.dispose();
    }
    this._disposables.length = 0;
  }
}
