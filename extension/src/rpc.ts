/**
 * Content-Length-framed JSON-RPC 2.0 client over a child_process stdio pipe.
 *
 * Wire format is identical to LSP (Language Server Protocol):
 *   Content-Length: <byte-length>\r\n
 *   \r\n
 *   <UTF-8 JSON body>
 *
 * The server end is `python -m repoflare_core.rpc` (see core/src/repoflare_core/rpc/).
 * We spawn it once per workspace and keep it alive, sending requests and routing responses
 * back to their callers by request id.
 */

import * as cp from "child_process";

// ── Types matching the Python service layer's JSON-serialised results ──────────

export interface StatusResult {
  snapshot_id: string | null;
  node_count: number;
  edge_count: number;
}

export interface AnalyzeResult {
  snapshot_id: string;
  file_count: number;
  symbol_count: number;
  test_count: number;
  resolved_edge_count: number;
  test_edge_count: number;
}

export interface InitResult {
  db_path: string;
}

export interface NodeSummary {
  node_id: string;
  label: string;
  file_path: string | null;
}

export interface ImpactResult {
  impact_id: string;
  change_set_id: string;
  category: "DIRECT" | "INDIRECT" | "RELATED" | "POSSIBLE";
  affected_node_ids: string[];
  provenance: string;
}

export interface ImpactSummary {
  changed_files: string[];
  results: ImpactResult[];
  node_summaries: Record<string, NodeSummary>;
}

export interface ExplainResult {
  explanation: string | null;
}

export interface GraphNode {
  node_id: string;
  kind: string;
  name: string;
  file_path: string | null;
}

export interface GraphEdge {
  src_node_id: string;
  dst_node_id: string;
  edge_type: string;
}

export interface GraphOverview {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
  total_node_count: number;
}

// ── Error from the server ──────────────────────────────────────────────────────

export class RpcError extends Error {
  constructor(
    public readonly code: number,
    message: string
  ) {
    super(message);
    this.name = "RpcError";
  }
}

// Known error codes from rpc/server.py
export const ERROR_NOT_INITIALIZED = -32001;
export const ERROR_NOT_ANALYZED = -32002;
export const ERROR_GIT_FAILED = -32003;
export const ERROR_AI_NOT_CONFIGURED = -32004;
export const ERROR_AI_CALL_FAILED = -32005;

// ── Client ─────────────────────────────────────────────────────────────────────

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
};

export class RepoFlareRpcClient {
  private readonly _proc: cp.ChildProcessWithoutNullStreams;
  private readonly _pending = new Map<number, PendingRequest>();
  private _nextId = 1;
  private _readBuffer = Buffer.alloc(0);
  private _closed = false;

  /**
   * @param pythonPath  Path to the Python interpreter (from extension settings).
   * @param workspaceRoot  Passed to the subprocess as cwd so relative paths resolve.
   */
  constructor(
    pythonPath: string,
    workspaceRoot: string,
    private readonly _onError: (err: Error) => void
  ) {
    this._proc = cp.spawn(
      pythonPath,
      ["-m", "repoflare_core.rpc"],
      {
        cwd: workspaceRoot,
        stdio: ["pipe", "pipe", "pipe"],
        // Suppress Windows console window popup.
        windowsHide: true,
      }
    );

    this._proc.stdout.on("data", (chunk: Buffer) => this._onData(chunk));
    this._proc.stderr.on("data", (chunk: Buffer) => {
      // The Python core writes nothing to stderr during normal operation; anything here
      // is diagnostic/crash output — surface it via the error callback so it shows in the
      // output channel, not silently dropped.
      _onError(new Error(`repoflare_core stderr: ${chunk.toString("utf8").trim()}`));
    });
    this._proc.on("error", (err) => {
      this._closed = true;
      this._rejectAll(err);
      _onError(err);
    });
    this._proc.on("close", (code) => {
      this._closed = true;
      const err = new Error(`repoflare_core process exited with code ${code}`);
      this._rejectAll(err);
    });
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  init(path: string): Promise<InitResult> {
    return this._call("repoflare/init", { path }) as Promise<InitResult>;
  }

  analyze(path: string): Promise<AnalyzeResult> {
    return this._call("repoflare/analyze", { path }) as Promise<AnalyzeResult>;
  }

  status(path: string): Promise<StatusResult> {
    return this._call("repoflare/status", { path }) as Promise<StatusResult>;
  }

  impact(path: string, from: string, to = "HEAD"): Promise<ImpactSummary> {
    return this._call("repoflare/impact", { path, from, to }) as Promise<ImpactSummary>;
  }

  explain(path: string, from: string, to = "HEAD"): Promise<ExplainResult> {
    return this._call("repoflare/explain", { path, from, to }) as Promise<ExplainResult>;
  }

  graphOverview(path: string): Promise<GraphOverview> {
    return this._call("repoflare/graph", { path }) as Promise<GraphOverview>;
  }

  dispose(): void {
    this._closed = true;
    // Close stdin — the server loop exits on EOF, so this is the clean shutdown path
    // documented in rpc/server.py's serve_forever docstring.
    this._proc.stdin.end();
  }

  // ── Internals ───────────────────────────────────────────────────────────────

  private _call(method: string, params: Record<string, unknown>): Promise<unknown> {
    if (this._closed) {
      return Promise.reject(new Error("RPC client is closed"));
    }
    const id = this._nextId++;
    const message = JSON.stringify({ jsonrpc: "2.0", id, method, params });
    const body = Buffer.from(message, "utf8");
    const header = `Content-Length: ${body.byteLength}\r\n\r\n`;

    return new Promise((resolve, reject) => {
      this._pending.set(id, { resolve, reject });
      this._proc.stdin.write(header, "ascii");
      this._proc.stdin.write(body);
    });
  }

  private _onData(chunk: Buffer): void {
    this._readBuffer = Buffer.concat([this._readBuffer, chunk]);
    this._drainBuffer();
  }

  private _drainBuffer(): void {
    // Parse as many complete messages as are currently in the buffer.
    while (true) {
      // Find the end of the header block (\r\n\r\n).
      const headerEnd = this._readBuffer.indexOf("\r\n\r\n");
      if (headerEnd === -1) {
        return; // header not yet complete
      }
      const headerBlock = this._readBuffer.slice(0, headerEnd).toString("ascii");
      const contentLengthLine = headerBlock
        .split("\r\n")
        .find((l) => l.startsWith("Content-Length: "));
      if (!contentLengthLine) {
        // Malformed — discard up to the separator and continue.
        this._readBuffer = this._readBuffer.slice(headerEnd + 4);
        continue;
      }
      const contentLength = parseInt(contentLengthLine.slice("Content-Length: ".length), 10);
      const bodyStart = headerEnd + 4;
      if (this._readBuffer.length < bodyStart + contentLength) {
        return; // body not yet complete
      }
      const body = this._readBuffer.slice(bodyStart, bodyStart + contentLength);
      this._readBuffer = this._readBuffer.slice(bodyStart + contentLength);

      try {
        const msg = JSON.parse(body.toString("utf8")) as {
          id?: number;
          result?: unknown;
          error?: { code: number; message: string };
        };
        this._dispatch(msg);
      } catch {
        // Malformed JSON from the server — nothing to dispatch, just keep going.
      }
    }
  }

  private _dispatch(msg: {
    id?: number;
    result?: unknown;
    error?: { code: number; message: string };
  }): void {
    if (msg.id === undefined || msg.id === null) {
      return; // server notification — we don't send any so this shouldn't happen
    }
    const pending = this._pending.get(msg.id);
    if (!pending) {
      return;
    }
    this._pending.delete(msg.id);
    if (msg.error) {
      pending.reject(new RpcError(msg.error.code, msg.error.message));
    } else {
      pending.resolve(msg.result);
    }
  }

  private _rejectAll(err: Error): void {
    for (const { reject } of this._pending.values()) {
      reject(err);
    }
    this._pending.clear();
  }
}
