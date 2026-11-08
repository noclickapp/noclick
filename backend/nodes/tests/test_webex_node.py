"""Webex catalog, schema, and HTTP request contracts (without a live grant)."""

import json

import httpx
import pytest
from unittest.mock import AsyncMock
from pydantic import ValidationError

from nodes.core.binary_output import BinaryOutput
from nodes.webex_node import CONFIG_MODELS, OPERATIONS, WebexNode, WebexNodeConfig


def _config(operation: str, **fields):
    return WebexNodeConfig.model_validate({
        "config": {"operation": operation, **fields},
        "credentials": {
            "credential_type": "webex_oauth", "access_token": "test-token",
            "refresh_token": "refresh-token",
        },
    })


def _transport(monkeypatch, callback):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.webex_node.httpx.AsyncClient",
        lambda *args, **kwargs: original(transport=httpx.MockTransport(callback)),
    )


def test_catalog_and_schema_cover_core_webex_workflows():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 48
    assert {o["method"] for o in OPERATIONS.values()} == {"GET", "POST", "PUT", "DELETE"}
    assert all(o["path"].startswith("/") and ".." not in o["path"] for o in OPERATIONS.values())
    assert {"Messages", "Rooms", "Meetings", "Invitees", "Recordings"} <= {
        o["category"] for o in OPERATIONS.values()
    }
    assert WebexNode.connection_evidence.operation == "list_rooms"
    with pytest.raises(ValidationError):
        _config("messages_get_message_details")


@pytest.mark.asyncio
async def test_list_spaces_sends_bearer_and_preserves_pagination(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(200, json={"items": [{"id": "room-1", "title": "Product"}]}, headers={
            "Link": '<https://webexapis.com/v1/rooms?max=100&cursor=next>; rel="next"',
        })

    _transport(monkeypatch, callback)
    result = await WebexNode._request("test-token", "list_rooms", {"query_json": '{"max":100}'})
    assert result["data"]["items"][0]["title"] == "Product"
    assert result["next_page"].endswith("cursor=next")
    assert str(seen[0].url) == "https://webexapis.com/v1/rooms?max=100"
    assert seen[0].headers["Authorization"] == "Bearer test-token"


@pytest.mark.asyncio
async def test_create_meeting_validates_body_and_sends_json(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(201, json={"id": "meeting-1"})

    _transport(monkeypatch, callback)
    body = {"title": "Planning", "start": "2026-10-01T10:00:00Z", "end": "2026-10-01T11:00:00Z"}
    result = await WebexNode._request("test-token", "meetings_createmeeting", {"body_json": json.dumps(body)})
    assert result["data"]["id"] == "meeting-1"
    assert seen[0].url.path == "/v1/meetings"
    assert json.loads(seen[0].content) == body
    with pytest.raises(ValueError, match="end, start"):
        await WebexNode._request("test-token", "meetings_createmeeting", {"body_json": '{"title":"Planning"}'})
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_path_parameter_is_encoded_and_provider_error_is_reported(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(404, json={"message": "Message was not found"})

    _transport(monkeypatch, callback)
    with pytest.raises(ValueError, match="Webex API error 404: Message was not found"):
        await WebexNode._request("test-token", "messages_get_message_details", {"path_messageid": "a/b"})
    assert seen[0].url.raw_path.endswith(b"/messages/a%2Fb")
    with pytest.raises(ValueError, match="messageId is required"):
        await WebexNode._request("test-token", "messages_get_message_details", {"path_messageid": ".."})
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_non_json_response_uses_binary_output(monkeypatch):
    _transport(monkeypatch, lambda request: httpx.Response(
        200, content=b"\x89PNG\r\n", headers={"content-type": "image/png"},
    ))
    result = await WebexNode._request("test-token", "list_rooms", {})
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == b"\x89PNG\r\n"
    assert result["data"].content_type == "image/png"


@pytest.mark.asyncio
async def test_freshen_credential_rotates_expired_webex_token(monkeypatch):
    refresh = AsyncMock(return_value={
        "access_token": "new-access", "refresh_token": "new-refresh",
        "expires_at": "2030-01-01T00:00:00+00:00",
    })
    monkeypatch.setattr("nodes.oauth.webex_oauth.refresh_access_token", refresh)
    credential = {
        "credential_type": "webex_oauth", "access_token": "old-access",
        "refresh_token": "old-refresh", "expires_at": "2000-01-01T00:00:00+00:00",
    }
    result = await WebexNode.freshen_credential(credential)
    refresh.assert_awaited_once_with("old-refresh")
    assert result is credential
    assert result["access_token"] == "new-access"
    assert result["refresh_token"] == "new-refresh"
