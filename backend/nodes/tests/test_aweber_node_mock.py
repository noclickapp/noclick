"""AWeber catalog, request shape, and OAuth contract tests.

These tests exercise local code only. They are not live FlowCanvas verification.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes.aweber_operations import OPERATIONS
from nodes.aweber_node import AWeberNode, AWeberNodeConfig
from nodes.core.registry import NODE_REGISTRY
from nodes.oauth import aweber_oauth


class FakeClient:
    def __init__(self, response: httpx.Response):
        self.response = response
        self.request = AsyncMock(return_value=response)
        self.get = AsyncMock(return_value=response)
        self.post = AsyncMock(return_value=response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


def _response(status=200, payload=None, headers=None):
    request = httpx.Request("GET", "https://api.aweber.com/1.0/accounts")
    return httpx.Response(status, json=payload if payload is not None else {}, headers=headers, request=request)


def _node(config):
    parsed = AWeberNodeConfig.model_validate({
        "config": config,
        "credentials": {"credential_type": "aweber_oauth", "access_token": "token"},
    })
    return AWeberNode("node-1", "automation-aweber", {}, config=parsed)


def test_catalog_has_unique_actions_and_valid_schema():
    assert NODE_REGISTRY["automation-aweber"] is AWeberNode
    assert len(OPERATIONS) == 53
    assert len({item["id"] for item in OPERATIONS}) == len(OPERATIONS)
    assert {item["method"] for item in OPERATIONS} == {"GET", "POST", "PATCH", "PUT", "DELETE"}
    schema = AWeberNode.get_config_schema()
    variants = schema["properties"]["config"]["oneOf"]
    assert len(variants) == len(OPERATIONS) + 1
    assert schema["$defs"]["AWeberOAuthCredential"]["x-oauth-provider"] == "aweber"


def test_required_fields_follow_operation_and_secret_is_not_an_input():
    with pytest.raises(ValidationError):
        _node({"operation": "add_subscriber", "accountId": "1", "listId": "2"})
    _node({"operation": "add_subscriber", "accountId": "1", "listId": "2", "body_email": "hello@example.org"})
    with pytest.raises(ValidationError):
        _node({"operation": "get_list", "accountId": "1"})


@pytest.mark.asyncio
async def test_read_operation_uses_typed_path_and_preserves_fixed_op(monkeypatch):
    client = FakeClient(_response(payload={"entries": [{"id": 1}]}))
    monkeypatch.setattr("nodes.aweber_node.httpx.AsyncClient", lambda **_: client)
    node = _node({
        "operation": "find_lists", "accountId": "123", "name": "Prospects",
        "extra_query": {"ws.op": "delete"},
    })
    result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["entries"][0]["id"] == 1
    args, kwargs = client.request.await_args
    assert args[:2] == ("GET", "https://api.aweber.com/1.0/accounts/123/lists")
    assert kwargs["params"]["ws.op"] == "find"
    assert kwargs["params"]["name"] == "Prospects"
    assert kwargs["headers"]["Authorization"] == "Bearer token"


@pytest.mark.asyncio
async def test_write_operation_sends_json_and_returns_location(monkeypatch):
    client = FakeClient(_response(201, {"id": "22"}, {"Location": "/accounts/1/lists/2/subscribers/22"}))
    monkeypatch.setattr("nodes.aweber_node.httpx.AsyncClient", lambda **_: client)
    node = _node({
        "operation": "add_subscriber", "accountId": "1", "listId": "2",
        "body_email": "hello@example.org", "body_name": "Ada",
    })
    result = await node.execute({})
    assert result["status_code"] == 201
    assert result["data"]["location"].endswith("/22")
    assert client.request.await_args.kwargs["json"] == {"email": "hello@example.org", "name": "Ada"}


@pytest.mark.asyncio
async def test_form_operation_pins_ws_op_and_formats_booleans(monkeypatch):
    client = FakeClient(_response(200, {"id": 42}))
    monkeypatch.setattr("nodes.aweber_node.httpx.AsyncClient", lambda **_: client)
    node = _node({
        "operation": "move_subscriber", "accountId": "1", "listId": "2",
        "subscriberId": "42", "body_list_link": "https://api.aweber.com/1.0/accounts/1/lists/3",
        "body_enforce_custom_field_mapping": True,
        "extra_body": {"ws.op": "remove"},
    })
    result = await node.execute({})
    assert result["status"] == "success"
    data = client.request.await_args.kwargs["data"]
    assert data["ws.op"] == "move"
    assert data["enforce_custom_field_mapping"] == "true"


@pytest.mark.asyncio
async def test_api_error_is_visible_to_canvas(monkeypatch):
    client = FakeClient(_response(401, {"error": "invalid_token"}))
    monkeypatch.setattr("nodes.aweber_node.httpx.AsyncClient", lambda **_: client)
    result = await _node({"operation": "get_accounts"}).execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 401
    assert result["error"] == "invalid_token"


@pytest.mark.asyncio
async def test_expiring_token_is_refreshed_before_request(monkeypatch):
    client = FakeClient(_response(200, {"entries": []}))
    monkeypatch.setattr("nodes.aweber_node.httpx.AsyncClient", lambda **_: client)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: None)

    async def refresh(**kwargs):
        kwargs["credential"].update({
            "access_token": "fresh-access", "refresh_token": "rotated-refresh",
            "expires_at": "2030-01-01T00:00:00+00:00",
        })
        return "fresh-access"

    monkeypatch.setattr("nodes.core.oauth_refresh.ensure_fresh_oauth_token", refresh)
    parsed = AWeberNodeConfig.model_validate({
        "config": {"operation": "get_accounts"},
        "credentials": {
            "credential_type": "aweber_oauth", "access_token": "expired-access",
            "refresh_token": "old-refresh", "expires_at": "2020-01-01T00:00:00+00:00",
        },
    })
    node = AWeberNode("node-1", "automation-aweber", {}, config=parsed)
    result = await node.execute({})
    assert result["status"] == "success"
    assert client.request.await_args.kwargs["headers"]["Authorization"] == "Bearer fresh-access"
    assert parsed.credentials.refresh_token == "rotated-refresh"


@pytest.mark.asyncio
async def test_oauth_exchange_uses_basic_auth_and_returns_account(monkeypatch):
    monkeypatch.setenv("AWEBER_CLIENT_ID", "client")
    monkeypatch.setenv("AWEBER_CLIENT_SECRET", "secret")
    token_client = FakeClient(_response(200, {
        "access_token": "access", "refresh_token": "refresh", "expires_in": 3600,
        "scope": "account.read list.read",
    }))
    account_client = FakeClient(_response(200, {"entries": [{"id": 17, "company": "NoClick"}]}))
    clients = iter([token_client, account_client])
    monkeypatch.setattr("nodes.core.oauth_provider.httpx.AsyncClient", lambda **_: next(clients))
    tokens, account = await aweber_oauth.OAUTH_PROVIDER.exchange("code", "https://noclick.com/callback")
    assert tokens.access_token == "access" and tokens.refresh_token == "refresh"
    assert account == "NoClick"
    kwargs = token_client.post.await_args.kwargs
    assert kwargs["data"]["grant_type"] == "authorization_code"
    assert isinstance(kwargs["auth"], httpx.BasicAuth)
    assert account_client.get.await_args.kwargs["headers"]["Authorization"] == "Bearer access"


def test_documented_constraints_reject_invalid_ids_pagination_and_enums():
    for config in (
        {"operation": "get_subscribers", "accountId": "a/b", "listId": 456},
        {"operation": "get_subscribers", "accountId": 123, "listId": 456, "ws_size": 101},
        {"operation": "get_subscribers", "accountId": 123, "listId": 456, "sort_order": "random"},
    ):
        with pytest.raises(ValidationError):
            _node(config)


@pytest.mark.asyncio
async def test_broadcast_links_analytics_uses_documented_beta_server(monkeypatch):
    client = FakeClient(_response(payload={"items": []}))
    monkeypatch.setattr("nodes.aweber_node.httpx.AsyncClient", lambda **_: client)
    await _node({"operation": "broadcast_links_analytics", "account_id": "b619e767-9de6-43b7-a914-9a8d77a08ee5",
                 "broadcast_id": "b619e767-9de6-43b7-a914-9a8d77a08ee5", "filter": "clicks"}).execute({})
    assert client.request.await_args.args[:2] == (
        "GET", "https://api.aweber.com/2.0-beta/analytics/reports/broadcasts-links")


@pytest.mark.asyncio
async def test_subscriber_poll_baseline_dedup_and_repoint(monkeypatch):
    # Each field value is an unchanged property example from AWeber's Subscriber
    # schema; collection wrapping follows the documented Subscribers schema.
    import json
    from pathlib import Path
    examples = json.loads((Path(__file__).parent / "fixtures/aweber/subscriber-property-examples.json").read_text())
    row = {key: value["example"] for key, value in examples["properties"].items() if "example" in value}
    client = FakeClient(_response(payload={"entries": []}))
    monkeypatch.setattr("nodes.aweber_node.httpx.AsyncClient", lambda **_: client)
    node = _node({"operation": "on_new_subscriber", "accountId": 123, "listId": 456})
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    node._update_node_state = update
    baseline = await node.execute({})
    assert baseline["new_subscriber_count"] == 0
    client.request.return_value = _response(payload={"entries": [row]})
    fresh = await node.execute({})
    assert fresh["subscribers"] == [row]
    assert node.should_propagate_output(fresh, {"operation": "on_new_subscriber"})
    event = node.resolve_agent_event(fresh)
    assert row["name"] in event["text"] and str(row["id"]) in event["text"]
    assert "None" not in event["text"]
    assert "list 456" in event["text"] and "account 123" in event["text"]
    assert client.request.await_args.kwargs["params"]["sort_order"] == "desc"
    repeated = await node.execute({})
    assert repeated["new_subscriber_count"] == 0
    assert not node.should_propagate_output(repeated, {"operation": "on_new_subscriber"})
    assert node.resolve_agent_event(repeated) is None
    node.config.config.listId = 789
    assert (await node.execute({}))["new_subscriber_count"] == 0


@pytest.mark.asyncio
async def test_subscriber_poll_refuses_malformed_collection(monkeypatch):
    client = FakeClient(_response(payload={"message": "not a collection"}))
    monkeypatch.setattr("nodes.aweber_node.httpx.AsyncClient", lambda **_: client)
    with pytest.raises(ValueError, match="no subscriber collection"):
        await _node({"operation": "on_new_subscriber", "accountId": 123, "listId": 456}).execute({})


@pytest.mark.asyncio
async def test_documented_click_property_examples_survive_parser(monkeypatch):
    import json
    from pathlib import Path
    examples = json.loads((Path(__file__).parent / "fixtures/aweber/click-property-examples.json").read_text())
    for definition in examples["definitions"].values():
        row = {key: field["example"] for key, field in definition["properties"]["entries"]["items"]["properties"].items()
               if "example" in field}
        payload = {"entries": [row]}
        client = FakeClient(_response(payload=payload))
        monkeypatch.setattr("nodes.aweber_node.httpx.AsyncClient", lambda **_: client)
        output = await _node({"operation": "get_broadcast_clicks", "accountId": 123,
                              "listId": 456, "broadcastId": 789}).execute({})
        assert output["data"] == payload


def test_formatted_inputs_reject_invalid_values():
    for config in (
        {"operation": "add_subscriber", "accountId": 123, "listId": 456, "body_email": "1"},
        {"operation": "get_landing_page", "accountId": 123, "listId": 456, "landingPageId": "1"},
        {"operation": "move_subscriber", "accountId": 123, "listId": 456, "subscriberId": 789,
         "body_list_link": "1"},
    ):
        with pytest.raises(ValidationError):
            _node(config)
