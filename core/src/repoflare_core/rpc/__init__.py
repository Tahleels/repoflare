"""JSON-RPC stdio server exposing repoflare_core.service to the VS Code extension — see
server.py's module docstring for the protocol and method list."""

from repoflare_core.rpc.protocol import MalformedMessageError, read_message, write_message
from repoflare_core.rpc.server import RpcServer

__all__ = ["MalformedMessageError", "RpcServer", "read_message", "write_message"]
