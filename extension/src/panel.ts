/**
 * RepoFlarePanel — the single VS Code WebviewPanel that renders both the repository
 * overview and the impact view.
 *
 * Design:
 *  - One panel instance per workspace (singleton).
 *  - Created or revealed by `RepoFlarePanel.show(...)`.
 *  - The panel always loads current status on open, then either shows the overview or
 *    immediately runs an impact query if refs were supplied.
 *  - Messages from the webview (e.g. "user clicked Analyze") are dispatched back to the
 *    extension and handled here, so the panel never holds a reference to the RPC client.
 */

import * as vscode from "vscode";
import { RepoFlareRpcClient, ImpactSummary, RpcError } from "./rpc";
import { buildWebviewHtml } from "./webview";

interface ImpactRequest {
  from: string;
  to: string;
}

// Messages the webview sends to the extension host.
type WebviewMessage =
  | { type: "analyze" }
  | { type: "impact"; from: string; to: string }
  | { type: "back" }
  | { type: "ready" };

export class RepoFlarePanel {
  private static _current: RepoFlarePanel | undefined;

  private readonly _panel: vscode.WebviewPanel;
  private readonly _disposables: vscode.Disposable[] = [];

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
   * Create or reveal the panel.  If `impactRequest` is non-null the panel will immediately
   * run an impact query on load; otherwise it shows the overview.
   */
  static async show(
    context: vscode.ExtensionContext,
    client: RepoFlareRpcClient,
    root: string,
    impactRequest: ImpactRequest | null
  ): Promise<void> {
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : vscode.ViewColumn.One;

    if (RepoFlarePanel._current) {
      RepoFlarePanel._current._panel.reveal(column);
      if (impactRequest) {
        await RepoFlarePanel._current._showImpact(impactRequest.from, impactRequest.to);
      }
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      "repoflare",
      "RepoFlare",
      column ?? vscode.ViewColumn.One,
      {
        enableScripts: true,
        // No local resources needed — all assets are inlined.
        localResourceRoots: [],
        retainContextWhenHidden: true,
      }
    );

    RepoFlarePanel._current = new RepoFlarePanel(panel, context, client, root);
    await RepoFlarePanel._current._initialLoad(impactRequest);
  }

  // ── Private ─────────────────────────────────────────────────────────────────

  private async _initialLoad(impactRequest: ImpactRequest | null): Promise<void> {
    this._panel.webview.html = buildWebviewHtml({ state: "loading" });
    try {
      const status = await this._client.status(this._root);
      if (impactRequest) {
        await this._showImpact(impactRequest.from, impactRequest.to);
      } else {
        this._panel.webview.html = buildWebviewHtml({ state: "overview", status, root: this._root });
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this._panel.webview.html = buildWebviewHtml({ state: "error", message });
    }
  }

  private async _showImpact(from: string, to: string): Promise<void> {
    this._panel.webview.html = buildWebviewHtml({ state: "loading" });
    try {
      const [status, impact] = await Promise.all([
        this._client.status(this._root),
        this._client.impact(this._root, from, to),
      ]);
      this._panel.webview.html = buildWebviewHtml({
        state: "impact",
        status,
        root: this._root,
        from,
        to,
        impact,
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
  }

  private async _handleMessage(msg: WebviewMessage): Promise<void> {
    switch (msg.type) {
      case "ready":
        // Webview signals it has fully loaded — nothing to do currently.
        break;

      case "analyze":
        this._panel.webview.html = buildWebviewHtml({ state: "loading" });
        try {
          const result = await this._client.analyze(this._root);
          vscode.window.showInformationMessage(
            `RepoFlare: analyzed ${result.file_count} files, ` +
            `${result.symbol_count} symbols, ${result.test_count} tests.`
          );
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          this._panel.webview.html = buildWebviewHtml({ state: "error", message });
          break;
        }
        await this._showOverview();
        break;

      case "impact":
        await this._showImpact(msg.from, msg.to);
        break;

      case "back":
        await this._showOverview();
        break;
    }
  }

  private async _showOverview(): Promise<void> {
    this._panel.webview.html = buildWebviewHtml({ state: "loading" });
    try {
      const status = await this._client.status(this._root);
      this._panel.webview.html = buildWebviewHtml({ state: "overview", status, root: this._root });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this._panel.webview.html = buildWebviewHtml({ state: "error", message });
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
