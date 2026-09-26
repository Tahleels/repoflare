import io
import subprocess
import sys
from pathlib import Path

import pytest

from repoflare_core.rpc.protocol import read_message, write_message
from repoflare_core.rpc.server import RpcServer


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_init_analyze_status_over_rpc(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def helper():\n    pass\n\ndef entry():\n    helper()\n")
    server = RpcServer()

    init_response = server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "repoflare/init", "params": {"path": str(tmp_path)}}
    )
    assert init_response is not None
    assert "error" not in init_response

    analyze_response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "repoflare/analyze",
            "params": {"path": str(tmp_path)},
        }
    )
    assert analyze_response is not None
    assert analyze_response["result"]["symbol_count"] == 2

    status_response = server.handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "repoflare/status", "params": {"path": str(tmp_path)}}
    )
    assert status_response is not None
    assert status_response["result"]["node_count"] == 3
    assert status_response["result"]["edge_count"] == 3


def test_init_and_analyze_agree_on_repository_id_despite_path_casing(tmp_path: Path) -> None:
    """Regression: rpc/server.py used to pass an unresolved Path straight through to
    service.py, so a differently-cased but identical Windows path (e.g. a VS Code
    workspace fsPath, which lowercases the drive letter) hashed to a different
    repository_id than the CLI's `.resolve()`-normalized path — causing a foreign-key
    error on `analyze` after an `init` done under a different case of the same path.
    _resolve_path() fixes this by resolving before hashing, matching cli/main.py."""
    if not sys.platform.startswith("win"):
        pytest.skip("drive-letter casing is a Windows-only path quirk")

    (tmp_path / "a.py").write_text("def helper():\n    pass\n")
    server = RpcServer()

    canonical = str(tmp_path)
    assert canonical[1] == ":"
    differently_cased = canonical[0].swapcase() + canonical[1:]

    init_response = server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "repoflare/init", "params": {"path": canonical}}
    )
    assert init_response is not None
    assert "error" not in init_response

    analyze_response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "repoflare/analyze",
            "params": {"path": differently_cased},
        }
    )
    assert analyze_response is not None
    assert "error" not in analyze_response
    assert analyze_response["result"]["symbol_count"] == 1


def test_impact_and_explain_over_rpc(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "a.py").write_text("def helper():\n    pass\n")
    (repo / "b.py").write_text("from a import helper\n\ndef entry():\n    helper()\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "first")
    first_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    server = RpcServer()
    server.handle_request({"id": 1, "method": "repoflare/init", "params": {"path": str(repo)}})
    server.handle_request({"id": 2, "method": "repoflare/analyze", "params": {"path": str(repo)}})

    (repo / "a.py").write_text("def helper():\n    return 1\n")
    _git(repo, "commit", "-a", "-q", "-m", "second")

    impact_response = server.handle_request(
        {"id": 3, "method": "repoflare/impact", "params": {"path": str(repo), "from": first_sha}}
    )
    assert impact_response is not None
    assert impact_response["result"]["changed_files"] == ["a.py"]
    assert any(r["category"] == "DIRECT" for r in impact_response["result"]["results"])

    # explain with no AI provider configured must surface the -32004 error code, not crash
    explain_response = server.handle_request(
        {"id": 4, "method": "repoflare/explain", "params": {"path": str(repo), "from": first_sha}}
    )
    assert explain_response is not None
    assert explain_response["error"]["code"] == -32004


def test_not_initialized_maps_to_correct_error_code(tmp_path: Path) -> None:
    response = RpcServer().handle_request(
        {"id": 1, "method": "repoflare/analyze", "params": {"path": str(tmp_path)}}
    )

    assert response is not None
    assert response["error"]["code"] == -32001


def test_not_analyzed_maps_to_correct_error_code(tmp_path: Path) -> None:
    server = RpcServer()
    server.handle_request({"id": 1, "method": "repoflare/init", "params": {"path": str(tmp_path)}})

    response = server.handle_request(
        {"id": 2, "method": "repoflare/impact", "params": {"path": str(tmp_path), "from": "HEAD~1"}}
    )

    assert response is not None
    assert response["error"]["code"] == -32002


def test_unknown_method_returns_method_not_found() -> None:
    response = RpcServer().handle_request({"id": 1, "method": "repoflare/nonexistent"})

    assert response is not None
    assert response["error"]["code"] == -32601


def test_missing_method_returns_invalid_request() -> None:
    response = RpcServer().handle_request({"id": 1})

    assert response is not None
    assert response["error"]["code"] == -32600


def test_missing_required_param_returns_invalid_request() -> None:
    response = RpcServer().handle_request({"id": 1, "method": "repoflare/init", "params": {}})

    assert response is not None
    assert response["error"]["code"] == -32600


def test_notification_without_id_gets_no_response(tmp_path: Path) -> None:
    response = RpcServer().handle_request(
        {"method": "repoflare/init", "params": {"path": str(tmp_path)}}
    )

    assert response is None


def test_serve_forever_processes_stream_and_stops_at_eof(tmp_path: Path) -> None:
    input_stream = io.BytesIO()
    write_message(
        input_stream,
        {"jsonrpc": "2.0", "id": 1, "method": "repoflare/init", "params": {"path": str(tmp_path)}},
    )
    input_stream.seek(0)
    output_stream = io.BytesIO()

    RpcServer().serve_forever(input_stream, output_stream)

    output_stream.seek(0)
    response = read_message(output_stream)
    assert response is not None
    assert response["id"] == 1
    assert "error" not in response


def test_graph_overview_over_rpc(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def helper():\n    pass\n\ndef entry():\n    helper()\n")
    server = RpcServer()
    server.handle_request({"id": 1, "method": "repoflare/init", "params": {"path": str(tmp_path)}})
    server.handle_request(
        {"id": 2, "method": "repoflare/analyze", "params": {"path": str(tmp_path)}}
    )

    response = server.handle_request(
        {"id": 3, "method": "repoflare/graph", "params": {"path": str(tmp_path)}}
    )

    assert response is not None
    assert "error" not in response
    result = response["result"]
    assert isinstance(result["nodes"], list)
    assert isinstance(result["edges"], list)
    assert isinstance(result["truncated"], bool)
    assert result["truncated"] is False
    assert len(result["nodes"]) >= 1
