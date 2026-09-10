"""Exercise Canva comment routing and HTTP bodies with synthetic transport."""

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes.canva_node import CanvaNode, CanvaNodeConfig


def run_operation(monkeypatch, operation, fields, handler):
    node = CanvaNode(
        node_id="canva-test",
        node_type="canva",
        node_data={},
        config=CanvaNodeConfig(
            config={"operation": operation, "design_id": "test-design", **fields},
            credentials={
                "credential_type": "canva_oauth",
                "access_token": "synthetic-access-token",
                "refresh_token": "synthetic-refresh-token",
                "expires_at": "2099-01-01T00:00:00Z",
            },
        ),
    )
    node._get_access_token = AsyncMock(return_value="synthetic-access-token")
    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = asyncio.run(node.execute({}))
    node._get_access_token.assert_awaited_once_with(node.config.credentials)
    return result


@pytest.mark.parametrize(
    "operation,fields,suffix,key",
    [
        ("create_design_comment_thread", {}, "", "thread"),
        (
            "create_comment_thread_reply",
            {"thread_id": "test-thread"},
            "/test-thread/replies",
            "reply",
        ),
    ],
)
@pytest.mark.parametrize(
    "message",
    ["Review demo", "Hello 🌱\nSecond line", "a" * 2048],
    ids=["plain", "unicode-newline", "max-length"],
)
def test_comment_writes_use_documented_plaintext_body(
    monkeypatch,
    operation,
    fields,
    suffix,
    key,
    message,
):
    seen = []
    payload = {key: {"id": "test-result", "content": {"plaintext": message}}}

    def handler(request):
        seen.append(request)
        assert request.method == "POST"
        assert (
            str(request.url)
            == f"https://api.canva.com/rest/v1/designs/test-design/comments{suffix}"
        )
        assert request.headers["Authorization"] == "Bearer synthetic-access-token"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {"message_plaintext": message}
        return httpx.Response(200, json=payload)

    result = run_operation(
        monkeypatch, operation, {**fields, "message": message}, handler
    )
    assert len(seen) == 1
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["status_code"] == 200
    assert result["data"] == payload


@pytest.mark.parametrize(
    "operation,suffix,extra",
    [
        ("get_design_comment_thread", "/test-thread", {}),
        ("list_comment_thread_replies", "/test-thread/replies", {}),
        (
            "get_comment_thread_reply",
            "/test-thread/replies/test-reply",
            {"reply_id": "test-reply"},
        ),
    ],
)
def test_comment_reads_remain_bodyless(monkeypatch, operation, suffix, extra):
    seen = []
    payload = {"id": "test-result"}

    def handler(request):
        seen.append(request)
        assert request.method == "GET"
        assert request.url.path == f"/rest/v1/designs/test-design/comments{suffix}"
        assert request.content == b""
        return httpx.Response(200, json=payload)

    result = run_operation(
        monkeypatch, operation, {"thread_id": "test-thread", **extra}, handler
    )
    assert len(seen) == 1
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["data"] == payload


@pytest.mark.parametrize(
    "operation,extra",
    [
        ("create_design_comment_thread", {}),
        ("create_comment_thread_reply", {"thread_id": "test-thread"}),
    ],
)
def test_rejected_comment_is_not_reported_as_success(monkeypatch, operation, extra):
    seen = []

    def handler(request):
        seen.append(request)
        assert json.loads(request.content) == {"message_plaintext": "Review demo"}
        return httpx.Response(
            403, json={"code": "permission_denied", "message": "Not allowed"}
        )

    result = run_operation(
        monkeypatch, operation, {"message": "Review demo", **extra}, handler
    )
    assert len(seen) == 1
    assert result["status"] == "error"
    assert result["status_code"] == 403
    assert result["action"] == operation
    assert result["error"] == "Not allowed"
    assert "data" not in result
