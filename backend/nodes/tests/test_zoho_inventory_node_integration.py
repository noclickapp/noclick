"""Zoho Inventory OAuth and request contracts for every pinned OpenAPI action."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

from nodes.zoho_inventory_node import (
    CONFIG_MODELS, OPERATIONS, ZohoInventoryNode, ZohoInventoryNodeConfig,
    _field_name, POLL_RESOURCES,
)
from nodes.oauth.zoho_inventory_oauth import (
    OAUTH_PROVIDER, validate_api_domain,
)


def _node(action: dict, *, api_domain: str = "https://www.zohoapis.eu") -> ZohoInventoryNode:
    config = ZohoInventoryNodeConfig.model_validate({
        "config": action,
        "credentials": {
            "access_token": "test-access-token", "refresh_token": "test-refresh-token",
            "expires_at": "2099-01-01T00:00:00+00:00", "api_domain": api_domain,
            "accounts_server": "https://accounts.zoho.eu", "accounts": "https://accounts.zoho.eu",
            "organization_id": "default-org", "organization_name": "Example Inventory",
        },
    })
    return ZohoInventoryNode(
        node_id="zoho-inventory-test", node_type="automation-zoho-inventory", node_data={},
        config=config, sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


def _action(op: dict) -> dict:
    value = {"operation": op["name"]}
    for raw in op["path_params"]:
        if raw != "organization_id":
            value[_field_name("path", raw)] = "sample-id"
    for raw in op["required_query"]:
        value[_field_name("query", raw)] = "sample-value"
    for raw in op["required_headers"]:
        value[_field_name("header", raw)] = "sample-value"
    if op["body_mime"] == "application/json":
        value["body_json"] = json.dumps({"sample": "value", **{
            key: "sample-value" for key in op["body_required_fields"]}})
    elif op["body_mime"] == "multipart/form-data":
        value["file_base64"] = base64.b64encode(b"sample file").decode()
        value["file_name"] = "sample.txt"
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("op", OPERATIONS.values(), ids=lambda op: op["name"])
async def test_every_openapi_action_dispatches_to_the_documented_route(op):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "message": "success", "items": []})

    real_client = httpx.AsyncClient
    with patch("nodes.zoho_inventory_node.guarded_async_client",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        result = await _node(_action(op)).execute({})
    assert result["status"] == "success"
    request = requests[0]
    assert request.method == op["method"]
    assert request.url.host == "www.zohoapis.eu"
    expected_path = re.sub(r"\{organization_id\}", "default-org", op["path"])
    expected_path = re.sub(r"\{[^{}]+\}", "sample-id", expected_path)
    assert request.url.path == "/inventory/v1" + expected_path
    assert request.headers["authorization"] == "Zoho-oauthtoken test-access-token"
    if op["requires_org_id"]:
        assert request.url.params["organization_id"] == "default-org"
    if op["body_mime"] == "application/json":
        assert json.loads(request.content) == json.loads(_action(op)["body_json"])
    if op["body_mime"] == "multipart/form-data":
        assert b"sample file" in request.content
        assert f'name="{op["file_field"]}"'.encode() in request.content


def test_catalog_and_scope_coverage_are_pinned():
    from nodes.zoho_inventory_operations import CATALOG as catalog
    assert catalog["source"] == "https://www.zoho.com/inventory/api/v1/openapi-all.zip"
    assert len(catalog["operations"]) == len(OPERATIONS) == len(CONFIG_MODELS) == 580
    assert ZohoInventoryNode.scope_registry.declared_scopes() == ["AaaServer.profile.READ", "ZohoInventory.FullAccess.all", "email"]
    assert OPERATIONS["list_organizations"]["requires_org_id"] is False
    assert OPERATIONS["list_sales_orders"]["required_query"] == []
    assert OPERATIONS["create_sales_order"]["required_query"] == []
    assert OPERATIONS["bulk_delete_sales_orders"]["required_query"] == ["salesorder_ids"]
    assert not any(r"(\d+)" in op["path"] for op in OPERATIONS.values())
    for name in OPERATIONS:
        ZohoInventoryNode.scope_registry.require(name)


@pytest.mark.parametrize("op", [op for op in OPERATIONS.values() if op["body_required"] and op["body_mime"] == "application/json"],
                         ids=lambda op: op["name"])
def test_documented_required_bodies_are_required_in_the_node(op):
    action = _action(op)
    del action["body_json"]
    with pytest.raises(ValueError):
        _node(action)


@pytest.mark.asyncio
async def test_create_sales_order_requires_documented_fields():
    op = OPERATIONS["create_sales_order"]
    assert op["body_required_fields"] == ["customer_id", "line_items", "salesorder_number"]
    with pytest.raises(ValueError, match="line_items"):
        await _node({"operation": "create_sales_order", "body_json": '{"customer_id":"customer"}'}).execute({})


def test_region_hosts_are_approved_exactly():
    assert validate_api_domain("https://www.zohoapis.eu") == "https://www.zohoapis.eu"
    for unsafe in ("http://www.zohoapis.eu", "https://www.zohoapis.eu.evil.test",
                   "https://www.zohoapis.eu/path", "https://user@www.zohoapis.eu"):
        with pytest.raises(ValueError):
            validate_api_domain(unsafe)


@pytest.mark.asyncio
async def test_declared_oauth_exchange_and_refresh(monkeypatch):
    monkeypatch.setenv("ZOHO_INVENTORY_CLIENT_ID", "client-id")
    monkeypatch.setenv("ZOHO_INVENTORY_CLIENT_SECRET", "client-secret")
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/oauth/v2/token":
            return httpx.Response(200, json={
                "access_token": "new-access", "refresh_token": "new-refresh",
                "api_domain": "https://www.zohoapis.com", "expires_in": 3600,
            })
        return httpx.Response(200, json={"Display_Name": "Inventory User"})

    real_client = httpx.AsyncClient
    with patch("nodes.core.oauth_provider.OAuthProviderSpec._client",
               side_effect=lambda _template: real_client(transport=httpx.MockTransport(respond))):
        tokens, name = await OAUTH_PROVIDER.exchange(
            "one-time-code", "https://noclick.com/api/auth/oauth/zoho_inventory/callback",
            context={"accounts": "https://accounts.zoho.com", "accounts_server": "https://accounts.zoho.com"})
        refreshed = await OAUTH_PROVIDER.bind_refresh(tokens.model_dump())("original-refresh")
    assert name == "Inventory User"
    assert tokens.api_domain == refreshed.api_domain == "https://www.zohoapis.com"
    assert requests[0].url.host == "accounts.zoho.com"
    assert b"grant_type=authorization_code" in requests[0].content
    assert requests[1].headers["authorization"] == "Bearer new-access"
    assert b"grant_type=refresh_token" in requests[2].content


@pytest.mark.asyncio
async def test_invalid_path_query_and_provider_error():
    with pytest.raises(ValueError, match="valid identifier"):
        await _node({"operation": "get_contact", "path_contact_id": "../private"}).execute({})
    with pytest.raises(ValueError, match="JSON object"):
        await _node({"operation": "list_contacts", "query_json": "[]"}).execute({})
    real_client = httpx.AsyncClient
    with patch("nodes.zoho_inventory_node.guarded_async_client",
               side_effect=lambda **kw: real_client(
                   transport=httpx.MockTransport(lambda _request: httpx.Response(
                       200, json={"code": 57, "message": "Invalid organization"})), **kw)):
        with pytest.raises(ValueError, match="Invalid organization"):
            await _node({"operation": "list_contacts"}).execute({})


@pytest.mark.asyncio
async def test_binary_response_uses_shared_file_output():
    real_client = httpx.AsyncClient
    with patch("nodes.zoho_inventory_node.guarded_async_client",
               side_effect=lambda **kw: real_client(
                   transport=httpx.MockTransport(lambda _request: httpx.Response(
                       200, content=b"PDF", headers={"content-type": "application/pdf"})), **kw)):
        result = await _node({"operation": "list_contacts"}).execute({})
    from nodes.core.binary_output import BinaryOutput
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == b"PDF"
    assert result["data"].content_type == "application/pdf"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", POLL_RESOURCES)
async def test_poll_baselines_deduplicates_updates_and_supplies_agent_event(operation):
    from unittest.mock import AsyncMock
    _, list_key, id_key, name_key, _ = POLL_RESOURCES[operation]
    node = _node({"operation": operation, "organization_id": "10234695"})
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(state)
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    node._update_node_state = update
    record = {id_key: "4815000000044208", name_key: "Example record"}
    node._request = AsyncMock(return_value={"data": {list_key: [record]}})
    baseline = await node.execute({})
    assert baseline["records"] == []
    assert node.trigger_produced_no_event(baseline)
    assert node.resolve_agent_event(baseline) is None
    record["status"] = "updated"
    emitted = await node.execute({})
    assert emitted["records"] == [record]
    assert node.trigger_emitted_event(emitted)
    turn = node.resolve_agent_event(emitted)
    assert "Example record" in turn["text"]
    assert id_key + "=" + record[id_key] in turn["text"]
    assert (await node.execute({}))["records"] == []


@pytest.mark.asyncio
async def test_poll_fetches_all_pages_before_deduplication_and_refuses_truncation():
    from unittest.mock import AsyncMock
    node = _node({"operation": "on_item_created_or_updated", "organization_id": "10234695"})
    first_page = [{"item_id": str(index + 1), "name": "Item"} for index in range(200)]
    node._request = AsyncMock(side_effect=[{"data": {"items": first_page}}, {"data": {"items": [{"item_id": "201", "name": "Last"}]}}])
    node._filter_unseen = AsyncMock(side_effect=lambda items, key: items)
    output = await node.execute({})
    assert len(output["records"]) == 201
    assert [json.loads(call.args[2]["query_json"])["page"] for call in node._request.call_args_list] == [1, 2]
    node._request = AsyncMock(return_value={"data": {"items": first_page}})
    node._filter_unseen.reset_mock()
    with pytest.raises(ValueError, match="4,000"):
        await node.execute({})
    node._filter_unseen.assert_not_awaited()


@pytest.mark.parametrize("field,value", [
    ("accounts", "https://accounts.zoho.com.evil.test"),
    ("accounts_server", "https://127.0.0.1"),
    ("api_domain", "https://www.zohoapis.com/private"),
])
def test_oauth_refuses_non_provider_context(field, value):
    with pytest.raises(ValueError):
        OAUTH_PROVIDER.context_fields[field].validate(value)


def test_oauth_uses_comma_scopes_and_regional_metadata():
    metadata = OAUTH_PROVIDER.public_metadata()
    assert metadata["scopeSeparator"] == ","
    assert metadata["contextFields"]["accounts_server"]["callbackName"] == "accounts-server"
    assert OAUTH_PROVIDER.endpoint(OAUTH_PROVIDER.token_url, {"accounts_server": "https://accounts.zoho.eu"}) == "https://accounts.zoho.eu/oauth/v2/token"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", POLL_RESOURCES)
async def test_documented_poll_response_delivers_record_and_agent_turn(operation):
    list_operation, list_key, id_key, _, _ = POLL_RESOURCES[operation]
    payload = json.loads((Path(__file__).parent / "fixtures" / "zoho-inventory" / (list_operation + ".json")).read_text())
    node = _node({"operation": operation, "organization_id": "10234695"})
    state = {"seen_ids": []}

    async def update(mutator, **kwargs):
        new_state, result = mutator(state)
        if new_state is not None:
            state.update(new_state)
        return result

    node._update_node_state = update
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json=payload)

    real_client = httpx.AsyncClient
    with patch("nodes.zoho_inventory_node.guarded_async_client",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        output = await node.execute({})
    assert output["records"] == payload[list_key]
    assert output["record_count"] == len(payload[list_key])
    event = node.resolve_agent_event(output)
    assert str(payload[list_key][0][id_key]) in event["text"]
    assert seen[0].url.params["organization_id"] == "10234695"
    assert seen[0].url.params["page"] == "1"
