import io

import pytest

from repoflare_core.rpc.protocol import MalformedMessageError, read_message, write_message


def test_write_then_read_roundtrip() -> None:
    stream = io.BytesIO()
    write_message(stream, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    stream.seek(0)

    message = read_message(stream)

    assert message == {"jsonrpc": "2.0", "id": 1, "method": "ping"}


def test_read_returns_none_on_clean_eof() -> None:
    stream = io.BytesIO(b"")

    assert read_message(stream) is None


def test_read_multiple_messages_sequentially() -> None:
    stream = io.BytesIO()
    write_message(stream, {"id": 1})
    write_message(stream, {"id": 2})
    stream.seek(0)

    first = read_message(stream)
    second = read_message(stream)
    third = read_message(stream)

    assert first == {"id": 1}
    assert second == {"id": 2}
    assert third is None


def test_missing_content_length_header_raises() -> None:
    stream = io.BytesIO(b"\r\n{}")

    with pytest.raises(MalformedMessageError, match="missing Content-Length"):
        read_message(stream)


def test_invalid_content_length_value_raises() -> None:
    stream = io.BytesIO(b"Content-Length: not-a-number\r\n\r\n{}")

    with pytest.raises(MalformedMessageError, match="invalid Content-Length"):
        read_message(stream)


def test_truncated_body_raises() -> None:
    stream = io.BytesIO(b"Content-Length: 100\r\n\r\n{}")

    with pytest.raises(MalformedMessageError, match="before Content-Length"):
        read_message(stream)


def test_invalid_json_body_raises() -> None:
    body = b"not json"
    stream = io.BytesIO(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)

    with pytest.raises(MalformedMessageError, match="invalid JSON"):
        read_message(stream)


def test_eof_mid_headers_raises() -> None:
    stream = io.BytesIO(b"Content-Length: 2\r\n")  # no blank line, then EOF

    with pytest.raises(MalformedMessageError, match="EOF while reading headers"):
        read_message(stream)


def test_unicode_body_roundtrips() -> None:
    stream = io.BytesIO()
    write_message(stream, {"text": "café — em dash"})
    stream.seek(0)

    assert read_message(stream) == {"text": "café — em dash"}
