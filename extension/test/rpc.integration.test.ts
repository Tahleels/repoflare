/**
 * Cross-language integration test: spawns the REAL `python -m repoflare_core.rpc` server
 * (via `uv run`) and drives it through the actual RepoFlareRpcClient — not a mock on either
 * side. This is what proves the TypeScript client and Python server genuinely agree on the
 * wire protocol, which unit-testing each side in isolation cannot prove.
 *
 * Skips itself (rather than failing) if `uv` isn't on PATH, since CI/dev environments vary
 * — see the skip message for what's missing when that happens.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { execFileSync, spawnSync } from "child_process";
import { RepoFlareRpcClient, RpcError, ERROR_NOT_ANALYZED } from "../src/rpc";

const CORE_DIR = path.resolve(__dirname, "../../core");

function uvAvailable(): boolean {
  try {
    execFileSync("uv", ["--version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

function makeTempRepo(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "repoflare-ext-test-"));
  fs.writeFileSync(path.join(dir, "a.py"), "def helper():\n    pass\n\ndef entry():\n    helper()\n");
  const git = (...args: string[]) => spawnSync("git", args, { cwd: dir, stdio: "ignore" });
  git("init", "-q");
  git("config", "user.email", "t@example.com");
  git("config", "user.name", "T");
  git("add", ".");
  git("commit", "-q", "-m", "first");
  return dir;
}

// RepoFlareRpcClient always spawns `<pythonPath> -m repoflare_core.rpc`, so pythonPath must
// be a real Python executable, not `uv` itself (which needs `run --project <dir> python`
// before `-m`). Resolve the venv interpreter uv manages for core/ once, then pass that
// straight to the client, exercising its actual spawn path.
function resolvePythonExecutable(): string | null {
  const result = spawnSync("uv", ["run", "--project", CORE_DIR, "python", "-c", "import sys; print(sys.executable)"], {
    encoding: "utf8",
  });
  if (result.status !== 0) {
    return null;
  }
  return result.stdout.trim();
}

test("RepoFlareRpcClient talks to the real Python server end to end", async (t) => {
  if (!uvAvailable()) {
    t.skip("uv is not on PATH — cannot resolve the repoflare_core Python environment");
    return;
  }
  const pythonExe = resolvePythonExecutable();
  if (!pythonExe) {
    t.skip("could not resolve the repoflare_core Python interpreter via `uv run`");
    return;
  }

  const repo = makeTempRepo();
  const client = new RepoFlareRpcClient(pythonExe, repo, (err) => {
    throw err;
  });

  try {
    const initResult = await client.init(repo);
    assert.ok(initResult.db_path.length > 0);

    const analyzeResult = await client.analyze(repo);
    assert.equal(analyzeResult.symbol_count, 2);

    const statusResult = await client.status(repo);
    assert.equal(statusResult.snapshot_id, analyzeResult.snapshot_id);
    assert.equal(statusResult.node_count, 3);

    // impact against a nonexistent-yet-plausible ref should surface a real RpcError with
    // the git-failure code, proving error codes round-trip correctly, not just happy paths.
    await assert.rejects(
      () => client.impact(repo, "not-a-real-ref-xyz"),
      (err: unknown) => err instanceof RpcError && err.code === -32003
    );
  } finally {
    client.dispose();
  }
});

test("RepoFlareRpcClient surfaces NOT_ANALYZED before analyze has run", async (t) => {
  if (!uvAvailable()) {
    t.skip("uv is not on PATH");
    return;
  }
  const pythonExe = resolvePythonExecutable();
  if (!pythonExe) {
    t.skip("could not resolve the repoflare_core Python interpreter via `uv run`");
    return;
  }

  const repo = makeTempRepo();
  const client = new RepoFlareRpcClient(pythonExe, repo, (err) => {
    throw err;
  });

  try {
    await client.init(repo);
    await assert.rejects(
      () => client.impact(repo, "HEAD~1"),
      (err: unknown) => err instanceof RpcError && err.code === ERROR_NOT_ANALYZED
    );
  } finally {
    client.dispose();
  }
});
