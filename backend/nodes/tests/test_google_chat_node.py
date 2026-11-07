"""Google Chat discovery, scope, request, and OAuth credential contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.google_chat_node import (
    CHAT_SCOPES, CONFIG_MODELS, OPERATIONS, GoogleChatNode, GoogleChatNodeConfig,
    _field_name,
)


REQUIRED_QUERIES = {
    "spaces_find_direct_message": ("query_name", "users/123456789"),
    "spaces_members_patch": ("query_update_mask", "role"),
    "spaces_messages_patch": ("query_update_mask", "text"),
    "spaces_messages_update": ("query_update_mask", "text"),
    "spaces_patch": ("query_update_mask", "displayName"),
    "spaces_search": ("query_query", 'spaceType = "SPACE" AND displayName:"Project"'),
    "spaces_space_events_list": (
        "query_filter", 'eventTypes:"google.workspace.chat.message.v1.created"'),
}


def _action(op: dict) -> dict:
    values = {"operation": op["name"]}
    for prefix in ("path", "query"):
        for param in op[f"{prefix}_params"]:
            if param["required"]:
                values[_field_name(prefix, param["name"])] = (
                    "spaces/test-space" if prefix == "path" else "sample"
                )
    if op["body_json"]:
        values["body_json"] = json.dumps({key: "sample" for key in op["body_required_fields"]})
    if op["name"] in REQUIRED_QUERIES:
        field, value = REQUIRED_QUERIES[op["name"]]
        values[field] = value
    return values


def _node(action: dict) -> GoogleChatNode:
    config = GoogleChatNodeConfig.model_validate({
        "config": action,
        "credentials": {
            "credential_type": "google_oauth",
            "access_token": "test-token", "refresh_token": "test-refresh",
            "expires_at": "2099-01-01T00:00:00+00:00", "email": "user@example.com",
            "scope": " ".join(CHAT_SCOPES.declared_scopes()),
        },
    })
    return GoogleChatNode(
        node_id="chat-test", node_type="automation-google-chat", node_data={},
        config=config, sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("op", OPERATIONS.values(), ids=lambda op: op["name"])
async def test_every_discovery_action_uses_method_path_and_bearer_token(op):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": []})

    real_client = httpx.AsyncClient
    with patch("nodes.google_chat_node.httpx.AsyncClient",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        result = await GoogleChatNode._request("test-token", op["name"],
                                               _node(_action(op)).config.config.model_dump(
                                                   exclude={"operation"}, exclude_none=True))
    request = requests[0]
    assert result["status"] == "success"
    assert result["data"] == {"items": []}
    assert request.url.host == "chat.googleapis.com"
    assert request.method == op["method"]
    assert request.url.path == re.sub(r"\{\+?[^{}]+\}", "spaces/test-space", "/" + op["path"])
    assert request.headers["authorization"] == "Bearer test-token"
    if op["body_json"]:
        assert json.loads(request.content) == json.loads(_action(op)["body_json"])
    if op["name"] in REQUIRED_QUERIES:
        field, value = REQUIRED_QUERIES[op["name"]]
        name = "updateMask" if field == "query_update_mask" else field[6:]
        assert request.url.params[name] == value


@pytest.mark.parametrize("operation,query", REQUIRED_QUERIES.items())
@pytest.mark.parametrize("empty", [None, ""])
def test_required_query_is_not_optional_in_config_or_generated_schema(operation, query, empty):
    field, _ = query
    action = _action(OPERATIONS[operation])
    if empty is None:
        action.pop(field)
    else:
        action[field] = empty
    with pytest.raises(ValidationError):
        _node(action)
    schema = CONFIG_MODELS[operation].model_json_schema()
    assert field in schema["required"]
    root = Path(__file__).resolve().parents[3]
    generated = json.loads((root / "frontend/app/schemas/nodes/google-chat.json").read_text())
    assert field in generated["$defs"][CONFIG_MODELS[operation].__name__]["required"]


@pytest.mark.asyncio
async def test_required_update_mask_is_rejected_before_http():
    with patch("nodes.google_chat_node.httpx.AsyncClient") as client:
        with pytest.raises(ValueError, match="updateMask is required"):
            await GoogleChatNode._request("test-token", "spaces_messages_patch", {
                "path_name": "spaces/SPACE_NAME/messages/MESSAGE_NAME",
                "body_json": '{"text":"Updated with user credential!"}',
            })
    client.assert_not_called()


def test_catalog_schema_and_requested_scopes_match_official_methods():
    root = Path(__file__).resolve().parents[2]
    from nodes.scopes.google_chat import CATALOG as catalog
    schema = json.loads((root.parent / "frontend/app/schemas/nodes/google-chat.json").read_text())
    assert catalog["source"] == "https://chat.googleapis.com/$discovery/rest?version=v1"
    assert len(catalog["operations"]) == len(OPERATIONS) == len(CONFIG_MODELS) == 28
    schema_operations = {
        entry["properties"]["operation"]["const"]
        for entry in schema["$defs"].values()
        if isinstance(entry, dict) and "operation" in entry.get("properties", {})
    }
    assert schema_operations == set(OPERATIONS)
    assert set(CHAT_SCOPES.declared_scopes()) == set(catalog["scopes"])
    assert {name for name in CHAT_SCOPES} == set(OPERATIONS)


@pytest.mark.asyncio
async def test_message_write_preserves_resource_slash_and_json_body():
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"name": "spaces/abc/messages/msg1", "text": "hello"})

    real_client = httpx.AsyncClient
    with patch("nodes.google_chat_node.httpx.AsyncClient",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        result = await GoogleChatNode._request("test-token", "spaces_messages_create", {
            "path_parent": "spaces/abc", "body_json": '{"text":"hello"}',
        })
    assert requests[0].url.path == "/v1/spaces/abc/messages"
    assert json.loads(requests[0].content) == {"text": "hello"}
    assert result["data"]["name"] == "spaces/abc/messages/msg1"


@pytest.mark.asyncio
async def test_execute_uses_connected_credential_and_selected_action():
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"spaces": [{"name": "spaces/abc"}]})

    real_client = httpx.AsyncClient
    node = _node({"operation": "list_spaces"})
    with patch.object(node, "_ensure_token", return_value="fresh-token") as refresh:
        with patch("nodes.google_chat_node.httpx.AsyncClient",
                   side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
            result = await node.execute({})
    refresh.assert_awaited_once()
    assert requests[0].headers["authorization"] == "Bearer fresh-token"
    assert result["data"]["spaces"][0]["name"] == "spaces/abc"


@pytest.mark.asyncio
async def test_invalid_resource_body_and_error_do_not_leak_tokens():
    with pytest.raises(ValueError, match="Invalid Google Chat resource name"):
        await GoogleChatNode._request("secret", "spaces_get", {"path_name": "spaces/../bad"})
    with pytest.raises(ValueError, match="valid JSON"):
        await GoogleChatNode._request("secret", "spaces_messages_create", {
            "path_parent": "spaces/abc", "body_json": "{",
        })

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "Permission denied"}})

    real_client = httpx.AsyncClient
    with patch("nodes.google_chat_node.httpx.AsyncClient",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        with pytest.raises(ValueError, match="Google Chat API error 403: Permission denied") as error:
            await GoogleChatNode._request("secret", "list_spaces", {})
    assert "secret" not in str(error.value)


def test_google_oauth_exchange_uses_staging_generic_google_credential():
    from wss.handlers.oauth.google_oauth_handler import GoogleOAuthHandler

    assert GoogleOAuthHandler._get_credential_type_from_scopes(
        object(), CHAT_SCOPES.declared_scopes()) == "google_oauth"
