"""Entry point for `python -m repoflare_core.rpc` — what the VS Code extension spawns as a
subprocess (see docs/ARCHITECTURE.md ADR-001)."""

from __future__ import annotations

import sys

from repoflare_core.rpc.server import RpcServer


def main() -> None:
    RpcServer().serve_forever(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main()
