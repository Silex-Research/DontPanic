"""JSON-RPC batch behavior for the default MCP protocol version."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import mcp_server  # noqa: E402


def _serve(*messages: object) -> list[object]:
    stdin = io.StringIO("".join(json.dumps(message) + "\n" for message in messages))
    stdout = io.StringIO()
    assert mcp_server.serve_stdio(stdin=stdin, stdout=stdout) == 0
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def _initialize() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "batch-test", "version": "1"},
        },
    }


def test_batch_line_returns_one_array_and_omits_notification_response():
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]

    output = _serve(_initialize(), batch)

    assert len(output) == 2
    batch_response = output[1]
    assert isinstance(batch_response, list)
    assert [response["id"] for response in batch_response] == [1, 2]
    assert all("result" in response for response in batch_response)

    direct_batch_response = mcp_server.handle_message(batch)
    assert isinstance(direct_batch_response, list)
    assert [response["id"] for response in direct_batch_response] == [1, 2]


def test_batch_of_only_notifications_produces_no_output_line():
    batch = [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    output = _serve(batch)

    assert output == []
    mcp_server.handle_message(batch)


def test_empty_batch_returns_single_invalid_request_error_object():
    output = _serve([])

    assert len(output) == 1
    response = output[0]
    assert isinstance(response, dict)
    assert response["id"] is None
    assert response["error"]["code"] == -32600

    direct_response = mcp_server.handle_message([])
    assert isinstance(direct_response, dict)
    assert direct_response["id"] is None
    assert direct_response["error"]["code"] == -32600


def test_invalid_batch_item_returns_array_with_invalid_request_error():
    output = _serve([1])

    assert len(output) == 1
    response = output[0]
    assert isinstance(response, list)
    assert len(response) == 1
    assert response[0]["id"] is None
    assert response[0]["error"]["code"] == -32600

    direct_response = mcp_server.handle_message([1])
    assert isinstance(direct_response, list)
    assert len(direct_response) == 1
    assert direct_response[0]["id"] is None
    assert direct_response[0]["error"]["code"] == -32600


def test_initialize_in_batch_is_invalid_but_other_items_are_answered():
    batch = [
        {"jsonrpc": "2.0", "id": 3, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
    ]

    output = _serve(_initialize(), batch)

    assert len(output) == 2
    batch_response = output[1]
    assert isinstance(batch_response, list)
    assert batch_response[0]["id"] == 3
    assert batch_response[0]["error"]["code"] == -32600
    assert batch_response[1]["id"] == 4
    assert "result" in batch_response[1]

    direct_batch_response = mcp_server.handle_message(batch)
    assert isinstance(direct_batch_response, list)
    assert direct_batch_response[0]["error"]["code"] == -32600
    assert "result" in direct_batch_response[1]


def test_single_request_still_returns_one_object():
    message = {"jsonrpc": "2.0", "id": 9, "method": "tools/list"}

    direct = mcp_server.handle_message(message)
    assert isinstance(direct, dict)
    assert direct == mcp_server.handle_request(message)

    output = _serve(message)
    assert len(output) == 1
    assert isinstance(output[0], dict)
    assert output[0]["id"] == 9
    assert "result" in output[0]
