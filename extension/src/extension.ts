/**
 * Extension entry point.  Manages the lifecycle of one RepoFlareRpcClient per workspace
 * folder and wires VS Code commands to the panel.
 */

import * as vscode from "vscode";
import { RepoFlareRpcClient, RpcError, ERROR_NOT_INITIALIZED, ERROR_NOT_ANALYZED } from "./rpc";
import { RepoFlarePanel } from "./panel";

// One client per workspace folder (keyed by folder URI string).
const clients = new Map<string, RepoFlareRpcClient>();
let outputChannel: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext): void {
  outputChannel = vscode.window.createOutputChannel("RepoFlare");
  context.subscriptions.push(outputChannel);

  context.subscriptions.push(
    vscode.commands.registerCommand("repoflare.showOverview", () =>
      withClient(context, (client, root) => RepoFlarePanel.show(context, client, root))
    ),
    vscode.commands.registerCommand("repoflare.analyze", () =>
      withClient(context, (client, root) => runAnalyze(client, root))
    ),
    vscode.commands.registerCommand("repoflare.showImpact", () =>
      withClient(context, (client, root) => promptAndShowImpact(context, client, root))
    ),
    vscode.commands.registerCommand("repoflare.showGraph", () =>
      withClient(context, (client, root) => RepoFlarePanel.showGraph(context, client, root))
    )
  );
}

export function deactivate(): void {
  for (const client of clients.values()) {
    client.dispose();
  }
  clients.clear();
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function pythonPath(): string {
  return (
    vscode.workspace.getConfiguration("repoflare").get<string>("pythonPath") ?? "python"
  );
}

function workspaceRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

function getOrCreateClient(root: string): RepoFlareRpcClient {
  const existing = clients.get(root);
  if (existing) {
    return existing;
  }
  const client = new RepoFlareRpcClient(pythonPath(), root, (err) => {
    outputChannel.appendLine(`[error] ${err.message}`);
  });
  clients.set(root, client);
  return client;
}

/**
 * Resolve the workspace root and RPC client, then call `fn`.  Shows a user-facing error
 * message for the common failure modes rather than letting unhandled rejections surface.
 */
async function withClient(
  context: vscode.ExtensionContext,
  fn: (client: RepoFlareRpcClient, root: string) => Promise<void>
): Promise<void> {
  const root = workspaceRoot();
  if (!root) {
    vscode.window.showErrorMessage("RepoFlare: no workspace folder open.");
    return;
  }
  const client = getOrCreateClient(root);
  try {
    await fn(client, root);
  } catch (err) {
    if (err instanceof RpcError) {
      if (err.code === ERROR_NOT_INITIALIZED) {
        const action = await vscode.window.showErrorMessage(
          "RepoFlare: repository not initialized.",
          "Run repoflare init"
        );
        if (action) {
          await runInit(client, root);
        }
        return;
      }
      if (err.code === ERROR_NOT_ANALYZED) {
        const action = await vscode.window.showErrorMessage(
          "RepoFlare: repository not analyzed yet.",
          "Run repoflare analyze"
        );
        if (action) {
          await runAnalyze(client, root);
        }
        return;
      }
      vscode.window.showErrorMessage(`RepoFlare error (${err.code}): ${err.message}`);
    } else if (err instanceof Error) {
      // Likely the subprocess failed to start (Python not found, module not installed).
      vscode.window.showErrorMessage(
        `RepoFlare: could not reach core process — ${err.message}. ` +
        `Check the "repoflare.pythonPath" setting.`
      );
      outputChannel.appendLine(`[fatal] ${err.message}`);
    }
  }
}

async function runInit(client: RepoFlareRpcClient, root: string): Promise<void> {
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "RepoFlare: initializing…" },
    async () => {
      await client.init(root);
      vscode.window.showInformationMessage("RepoFlare initialized.");
    }
  );
}

async function runAnalyze(client: RepoFlareRpcClient, root: string): Promise<void> {
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "RepoFlare: analyzing repository…",
      cancellable: false,
    },
    async () => {
      const result = await client.analyze(root);
      vscode.window.showInformationMessage(
        `RepoFlare: analyzed ${result.file_count} files, ` +
        `${result.symbol_count} symbols, ${result.test_count} tests.`
      );
    }
  );
}

async function promptAndShowImpact(
  context: vscode.ExtensionContext,
  client: RepoFlareRpcClient,
  root: string
): Promise<void> {
  const fromRef = await vscode.window.showInputBox({
    prompt: "From git ref (commit SHA, branch, tag)",
    placeHolder: "HEAD~1",
  });
  if (!fromRef) {
    return;
  }
  const toRef = await vscode.window.showInputBox({
    prompt: "To git ref (leave empty for HEAD)",
    placeHolder: "HEAD",
  });
  // Open the panel on the Impact tab with the refs pre-filled in the form.
  await RepoFlarePanel.show(context, client, root);
}
