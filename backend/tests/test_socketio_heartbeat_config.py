"""Regression tests for the Socket.IO heartbeat configuration."""

from __future__ import annotations

import ast
from pathlib import Path


SERVER_PATH = Path(__file__).parents[1] / "server.py"


def _socketio_server_keywords() -> dict[str, ast.expr]:
    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "socketio"
            and func.attr == "AsyncServer"
        ):
            return {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
    raise AssertionError("socketio.AsyncServer configuration not found")


def test_socketio_heartbeat_uses_engineio_seconds() -> None:
    keywords = _socketio_server_keywords()

    assert ast.literal_eval(keywords["ping_interval"]) == 25
    assert ast.literal_eval(keywords["ping_timeout"]) == 20
