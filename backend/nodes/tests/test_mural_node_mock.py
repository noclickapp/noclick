"""Mural API contract tests over real httpx request construction.

Every exposed operation has a dispatch case. The transport checks method,
encoded path, query/body names, and the public API's ``value`` envelope.
"""

import json
from unittest.mock import Mock

import httpx
import pytest

from nodes.mural_node import MURAL_API_BASE, MuralNode, MuralNodeConfig, OPERATIONS
from nodes.scopes.mural import MURAL_SCOPES


VALUES = {
    "workspace_id": "work space",
    "room_id": 123456789,
    "mural_id": "workspace.123",
    "template_id": "template-1",
    "widget_id": "widget-1",
    "name": "Planning",
    "title": "Planning board",
    "type": "open",
    "q": "Planning",
    "text": "Discuss risks",
    "x": 120.0,
    "y": 140.0,
    "notes_json": '[{"text":"One","x":10,"y":20}]',
    "message": "Looks good",
}
CREDENTIAL = {
    "credential_type": "mural_oauth",
    "access_token": "test-access",
    "refresh_token": "test-refresh",
    "expires_at": "2099-01-01T00:00:00+00:00",
}
REAL_CLIENT = httpx.AsyncClient


def _node(operation: str, **overrides):
    spec = OPERATIONS[operation]
    fields = {key: VALUES[key] for key, field in spec.fields.items()
              if field.required and key in VALUES}
    if spec.method == "PATCH":
        fields["text" if "text" in spec.fields else "title" if "title" in spec.fields else "name"] = (
            "Updated note" if "text" in spec.fields else "Updated title"
        )
    fields.update(overrides)
    config = MuralNodeConfig.model_validate({
        "config": {"operation": operation, **fields}, "credentials": CREDENTIAL,
    })
    return MuralNode(node_id="mural-test", node_type="automation-mural", node_data={},
                     config=config, sio=Mock(), sid="sid", workflow_id="workflow", user_id="user")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", tuple(OPERATIONS))
async def test_every_operation_dispatches_to_documented_endpoint(monkeypatch, operation):
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"value": [{"id": "item-1"}], "next": "page-2"})

    monkeypatch.setattr("nodes.mural_node.httpx.AsyncClient",
                        lambda **kwargs: REAL_CLIENT(transport=httpx.MockTransport(handle)))
    node = _node(operation)
    result = await node.execute({})
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["timing_ms"]["api_request"] >= 0
    assert len(seen) == 1

    spec = OPERATIONS[operation]
    request = seen[0]
    assert request.method == spec.method
    expected = spec.path
    for key, value in VALUES.items():
        expected = expected.replace("{" + key + "}", str(value))
    assert request.url.path == "/api/public/v1" + expected
    assert b"%20" in request.url.raw_path if " " in expected else b"%20" not in request.url.raw_path
    assert str(request.url).startswith(MURAL_API_BASE)
    assert request.headers["authorization"] == "Bearer test-access"
    if operation == "create_sticky_note":
        assert json.loads(request.content) == [{"text": "Discuss risks", "x": 120, "y": 140, "shape": "rectangle"}]
    elif operation == "create_sticky_notes":
        assert json.loads(request.content) == [{"text": "One", "x": 10, "y": 20, "shape": "rectangle"}]
    elif operation == "create_template":
        assert json.loads(request.content) == {"muralId": "workspace.123", "title": "Planning board"}
    elif operation == "create_mural":
        assert json.loads(request.content)["roomId"] == 123456789
    if request.method != "DELETE":
        assert result["data"][spec.result] == [{"id": "item-1"}]
        assert result["data"]["next_page_token"] == "page-2"


@pytest.mark.asyncio
async def test_dynamic_workspace_options_are_account_specific_and_paginated(monkeypatch):
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/public/v1/workspaces"
        assert request.headers["authorization"] == "Bearer test-access"
        return httpx.Response(200, json={"value": [{"id": "ws-1", "name": "Design"}], "next": "cursor"})

    monkeypatch.setattr("nodes.mural_node.httpx.AsyncClient",
                        lambda **kwargs: REAL_CLIENT(transport=httpx.MockTransport(handle)))
    result = await MuralNode.load_field_options("workspace_id", CREDENTIAL)
    assert result == {"options": [{"value": "ws-1", "label": "Design"}], "next_page_token": "cursor"}


@pytest.mark.asyncio
async def test_credential_loader_refreshes_short_lived_access_token(monkeypatch):
    from nodes.core.oauth_provider import OAuthTokens

    async def refresh(token):
        assert token == "reusable-refresh"
        return OAuthTokens(access_token="fresh-access", expires_at="2099-01-01T00:00:00+00:00")

    monkeypatch.setattr("nodes.oauth.mural_oauth.refresh_access_token", refresh)
    credential = await MuralNode.freshen_credential(
        {"access_token": "stale-access", "refresh_token": "reusable-refresh",
         "expires_at": "2020-01-01T00:00:00+00:00"})
    assert credential["access_token"] == "fresh-access"
    assert credential["refresh_token"] == "reusable-refresh"


@pytest.mark.asyncio
async def test_dynamic_options_require_connected_account():
    with pytest.raises(ValueError, match="Connect a Mural account"):
        await MuralNode.load_field_options("workspace_id", {})


def test_scope_registry_covers_every_operation():
    assert MURAL_SCOPES.keys_declared == set(OPERATIONS)


def test_bulk_sticky_note_rejects_invalid_payload_without_request():
    from nodes.mural_node import _body
    node = _node("create_sticky_notes", notes_json="{}")
    with pytest.raises(ValueError, match="1 to 1,000"):
        _body("create_sticky_notes", OPERATIONS["create_sticky_notes"], node.config.config)

    node = _node("create_sticky_notes", notes_json='[{"text":"Missing position"}]')
    with pytest.raises(ValueError, match="text, x and y"):
        _body("create_sticky_notes", OPERATIONS["create_sticky_notes"], node.config.config)

    node = _node("create_sticky_notes", notes_json='[{"text":"Wrong shape","x":1,"y":2,"shape":"star"}]')
    with pytest.raises(ValueError, match="rectangle or circle"):
        _body("create_sticky_notes", OPERATIONS["create_sticky_notes"], node.config.config)
