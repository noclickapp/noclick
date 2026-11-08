"""Roam native requests and documented envelopes exercised at the HTTP boundary."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import roam_node as roam
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-roam-personal-token"
CASES = json.loads((Path(__file__).parent / "fixtures/roam/requests.json").read_text())["cases"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="roam-fixture", node_type="automation-roam", node_data={
        "config": config, "credentials": credentials or {"credential_type": "roam_token", "api_token": TOKEN},
    })


def transport(monkeypatch, status=200, body=None, *, headers=None, raw=None):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers=headers, **({"content": raw} if raw is not None else {"json": body} if body is not None else {}))

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(roam, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_roam_published_requests_and_response_shapes(monkeypatch, case):
    requests = transport(monkeypatch, case["status"], case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == (case["response"] or {})
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case["method"] and req.url.path == case["path"]
    assert req.url.host == "api.ro.am" and req.url.scheme == "https"
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert req.headers["Roam-Version"] == "2026-08-25"
    if req.method == "POST":
        payload = json.loads(req.content)
        for key, value in case["config"].items():
            if key != "operation":
                assert payload[key] == value
        if case["operation"] == "post_message":
            assert payload["sync"] is True
    else:
        for key, value in case["config"].items():
            if key != "operation":
                assert req.url.params[key] == (str(value).lower() if isinstance(value, bool) else str(value))
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_roam_cursor_and_query_encoding(monkeypatch):
    cursor = "opaque+/= cursor"
    requests = transport(monkeypatch, body={"groups": [], "nextCursor": cursor})
    result = await node({"operation": "list_groups", "query": "R&D + café", "cursor": cursor}).execute({})
    assert result["items"] == [] and result["has_more"] is True and result["next_cursor"] == cursor
    assert requests[0].url.params["query"] == "R&D + café"
    assert requests[0].url.params["cursor"] == cursor
    assert len(requests) == 1  # Never follows a cursor or an untrusted URL.


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"ok": False, "error": "token_revoked"}),
    (403, {"ok": False, "error": "missing_scope"}), (429, {"ok": False, "error": "ratelimited"}),
    (200, {"ok": False, "error": "invalid_parameter"}), (302, None), (500, None)])
async def test_roam_errors_are_failures_and_never_retried(monkeypatch, status, body):
    requests = transport(monkeypatch, status, body, headers={"Retry-After": "10"})
    result = await node({"operation": "get_token_info"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert len(requests) == 1
    if body:
        assert result["error"] == body["error"]
    if status == 429:
        assert result["retry_after"] == "10"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"chats": {}}, {"chats": [], "nextCursor": 42}, []])
async def test_roam_malformed_lists_are_not_success(monkeypatch, body):
    transport(monkeypatch, body=body)
    with pytest.raises(ValueError):
        await node({"operation": "list_chats"}).execute({})


@pytest.mark.asyncio
async def test_roam_invalid_json_and_missing_identity(monkeypatch):
    transport(monkeypatch, raw=b"<html>Sign in</html>")
    with pytest.raises(ValueError, match="unexpected response"):
        await node({"operation": "get_token_info"}).execute({})
    transport(monkeypatch, body={"ok": True})
    with pytest.raises(ValueError, match="principal or workspace"):
        await node({"operation": "get_token_info"}).execute({})


@pytest.mark.asyncio
async def test_roam_response_and_error_redaction(monkeypatch):
    for status, body in [(200, {"groups": [{"name": TOKEN}]}), (401, {"error": TOKEN})]:
        transport(monkeypatch, status, body)
        result = await node({"operation": "list_groups"}).execute({})
        assert TOKEN not in json.dumps(result)
        assert "[redacted]" in json.dumps(result)


@pytest.mark.parametrize("config", [
    {"operation": "post_message", "text": "hello"},
    {"operation": "post_message", "text": "hello", "chatId": "757dfe66-37b4-4772-baa5-8c86ec68c176", "groupId": "88bebce7-6cbb-4666-96f9-5c02d73e6661"},
    {"operation": "post_message", "text": "hello", "userIds": []},
    {"operation": "post_message", "text": "hello", "userIds": ["709b8a57-70bc-427a-b6f0-b16ba5297f8c"], "threadKey": "incident", "threadTimestamp": 123},
    {"operation": "list_chats", "limit": 51},
    {"operation": "get_meeting", "id": "not-a-uuid"},
    {"operation": "create_group", "name": "Team", "members": []},
    {"operation": "join_group", "id": "88bebce7-6cbb-4666-96f9-5c02d73e6661", "extra": "discard me"},
])
def test_roam_invalid_config_rejected(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize("token", ["https://ro.am", "<token>", "Bearer secret", "token\nheader", "", "é"])
def test_roam_rejects_invalid_secrets(token):
    with pytest.raises(ValidationError):
        roam.RoamTokenCredential(api_token=token)


def test_roam_rejects_foreign_credentials():
    with pytest.raises(ValueError, match="Roam"):
        node({"operation": "get_token_info"}, {"credential_type": "other_token", "api_token": TOKEN})


@pytest.mark.asyncio
async def test_roam_connection_identity_needs_no_config_or_scope(monkeypatch):
    case = CASES[0]
    requests = transport(monkeypatch, body=case["response"])
    result = await node({"operation": roam.RoamNode.connection_evidence.identity_operation}).execute({})
    assert result["data"]["roam"]["name"] == "Acme Corp"
    assert requests[0].url.path == "/v1/token.info" and not requests[0].url.query
