"""RpcServer: JSON-RPC 2.0 stdio server exposing the same repoflare_core.service
operations the CLI uses (see service.py's module docstring and docs/ARCHITECTURE.md
ADR-001) — what the VS Code extension talks to.

Methods:
  repoflare/init     {"path": str}
  repoflare/analyze  {"path": str}
  repoflare/status   {"path": str}
  repoflare/impact   {"path": str, "from": str, "to"?: str}
  repoflare/explain  {"path": str, "from": str, "to"?: str}

Error codes (JSON-RPC "error.code"), beyond the standard -32700/-32600/-32601/-32603:
  -32001  not initialized (run repoflare/init first)
  -32002  not analyzed (run repoflare/analyze first)
  -32003  git command failed (bad ref, not a git repo, etc.)
  -32004  no AI provider configured
  -32005  AI provider call failed
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import IO, Any

from repoflare_core.ai.factory import BobProviderConfigError
from repoflare_core.ai.provider import BobProviderError
from repoflare_core.change.git_adapter import GitCommandError
from repoflare_core.rpc.protocol import MalformedMessageError, read_message, write_message
from repoflare_core.service import (
    NotAnalyzedError,
    NotInitializedError,
    run_analyze,
    run_explain,
    run_impact,
    run_init,
    run_status,
)

_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INTERNAL_ERROR = -32603
_NOT_INITIALIZED = -32001
_NOT_ANALYZED = -32002
_GIT_ERROR = -32003
_AI_NOT_CONFIGURED = -32004
_AI_CALL_FAILED = -32005

_ERROR_CODE_BY_EXCEPTION: dict[type[Exception], int] = {
    NotInitializedError: _NOT_INITIALIZED,
    NotAnalyzedError: _NOT_ANALYZED,
    GitCommandError: _GIT_ERROR,
    BobProviderConfigError: _AI_NOT_CONFIGURED,
    BobProviderError: _AI_CALL_FAILED,
}


def _to_jsonable(value: Any) -> Any:
    """Recursively convert dataclasses/Path/Enum values from service.py's result types
    into plain JSON-serializable structures."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


def _handle_init(params: dict[str, Any]) -> Any:
    return _to_jsonable(run_init(Path(params["path"])))


def _handle_analyze(params: dict[str, Any]) -> Any:
    return _to_jsonable(run_analyze(Path(params["path"])))


def _handle_status(params: dict[str, Any]) -> Any:
    return _to_jsonable(run_status(Path(params["path"])))


def _handle_impact(params: dict[str, Any]) -> Any:
    return _to_jsonable(run_impact(Path(params["path"]), params["from"], params.get("to", "HEAD")))


def _handle_explain(params: dict[str, Any]) -> Any:
    explanation = run_explain(Path(params["path"]), params["from"], params.get("to", "HEAD"))
    return {"explanation": explanation}


_HANDLERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "repoflare/init": _handle_init,
    "repoflare/analyze": _handle_analyze,
    "repoflare/status": _handle_status,
    "repoflare/impact": _handle_impact,
    "repoflare/explain": _handle_explain,
}


class RpcServer:
    def __init__(self, handlers: dict[str, Callable[[dict[str, Any]], Any]] | None = None) -> None:
        self._handlers = handlers if handlers is not None else _HANDLERS

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Process one already-parsed JSON-RPC request, returning the response object to
        send back — or None for a notification (no "id"), which gets no response per the
        JSON-RPC 2.0 spec."""
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        if method is None or not isinstance(method, str):
            return self._error(request_id, _INVALID_REQUEST, "missing or invalid 'method'")

        handler = self._handlers.get(method)
        if handler is None:
            return self._error(request_id, _METHOD_NOT_FOUND, f"unknown method: {method}")

        try:
            result = handler(params)
        except KeyError as exc:
            return self._error(request_id, _INVALID_REQUEST, f"missing required param: {exc}")
        except Exception as exc:  # noqa: BLE001 — deliberately broad: any handler failure
            # must become a JSON-RPC error response, never crash the server loop.
            code = _ERROR_CODE_BY_EXCEPTION.get(type(exc), _INTERNAL_ERROR)
            return self._error(request_id, code, str(exc))

        if request_id is None:
            return None  # notification: no response
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def serve_forever(self, input_stream: IO[bytes], output_stream: IO[bytes]) -> None:
        """Blocking read-dispatch-write loop. Exits cleanly on EOF (the client closed its
        end of the pipe) — this is how the VS Code extension signals shutdown, by closing
        the spawned subprocess's stdin."""
        while True:
            try:
                message = read_message(input_stream)
            except MalformedMessageError as exc:
                write_message(
                    output_stream,
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": _PARSE_ERROR, "message": str(exc)},
                    },
                )
                continue
            if message is None:
                return  # clean EOF
            response = self.handle_request(message)
            if response is not None:
                write_message(output_stream, response)
