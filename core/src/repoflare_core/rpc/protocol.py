"""Content-Length-framed JSON-RPC 2.0 message I/O — the same wire framing LSP uses (see
docs/ARCHITECTURE.md ADR-001). Kept separate from server.py so the framing logic is
independently testable without spinning up the whole request dispatcher.
"""

from __future__ import annotations

import json
from typing import IO, Any

_HEADER_ENCODING = "ascii"
_CONTENT_LENGTH_PREFIX = "Content-Length: "


class MalformedMessageError(ValueError):
    """Raised when the input stream doesn't contain a well-formed framed message."""


def read_message(stream: IO[bytes]) -> dict[str, Any] | None:
    """Read one framed JSON-RPC message. Returns None at a clean EOF between messages (no
    header bytes read yet) — anything else that goes wrong raises MalformedMessageError."""
    content_length: int | None = None
    while True:
        line = stream.readline()
        if line == b"":
            if content_length is None:
                return None  # clean EOF between messages
            raise MalformedMessageError("EOF while reading headers")
        line = line.rstrip(b"\r\n")
        if line == b"":
            break  # blank line ends the header block
        try:
            header = line.decode(_HEADER_ENCODING)
        except UnicodeDecodeError as exc:
            raise MalformedMessageError(f"non-ASCII header: {line!r}") from exc
        if header.startswith(_CONTENT_LENGTH_PREFIX):
            try:
                content_length = int(header[len(_CONTENT_LENGTH_PREFIX) :])
            except ValueError as exc:
                raise MalformedMessageError(f"invalid Content-Length: {header!r}") from exc

    if content_length is None:
        raise MalformedMessageError("missing Content-Length header")

    body = stream.read(content_length)
    if len(body) != content_length:
        raise MalformedMessageError("stream ended before Content-Length bytes were read")

    try:
        parsed: dict[str, Any] = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MalformedMessageError(f"invalid JSON body: {exc}") from exc
    return parsed


def write_message(stream: IO[bytes], message: dict[str, Any]) -> None:
    body = json.dumps(message).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode(_HEADER_ENCODING)
    stream.write(header)
    stream.write(body)
    stream.flush()
