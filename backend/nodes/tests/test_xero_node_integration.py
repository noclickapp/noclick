"""Xero OAuth, tenant, scope, and official request-shape contracts."""

import json
from unittest.mock import Mock

import httpx
import pytest
import respx

from nodes.oauth.xero_oauth import OAUTH_PROVIDER, get_connections, refresh_access_token
from nodes.xero_node import (
    API_BASES, CONFIG_MODELS, OPERATIONS, XERO_SCOPES, XeroNode,
    XeroNodeConfig, XeroOAuthCredential,
)


def node(operation: str, **values) -> XeroNode:
    credential = XeroOAuthCredential(
        access_token="access", refresh_token="refresh",
        expires_at="2099-01-01T00:00:00Z", tenant_id="tenant-1",
        tenant_name="Demo Company",
    )
    config_values = ({"tenant_id": "tenant-1"} if operation != "list_connections" else {}) | values
    return XeroNode(
        node_id="xero-test", node_type="automation-xero", node_data={},
        config=XeroNodeConfig(config=CONFIG_MODELS[operation](**config_values), credentials=credential),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
async def test_oauth_exchange_refresh_and_tenant_lookup(monkeypatch):
    monkeypatch.setenv("XERO_CLIENT_ID", "client")
    monkeypatch.setenv("XERO_CLIENT_SECRET", "secret")
    with respx.mock(assert_all_called=True) as router:
        tokens = router.post("https://identity.xero.com/connect/token").mock(side_effect=[
            httpx.Response(200, json={"access_token": "one", "refresh_token": "rotate-1",
                                      "expires_in": 1800, "scope": "offline_access accounting.invoices"}),
            httpx.Response(200, json={"access_token": "two", "refresh_token": "rotate-2",
                                      "expires_in": 1800}),
        ])
        router.get("https://identity.xero.com/connect/userinfo").mock(
            return_value=httpx.Response(200, json={"email": "demo@example.com"}))
        tenants = router.get("https://api.xero.com/connections").mock(
            return_value=httpx.Response(200, json=[{
                "tenantId": "tenant-1", "tenantName": "Demo Company",
                "tenantType": "ORGANISATION"}]))
        first, name = await OAUTH_PROVIDER.exchange("code", "https://noclick.com/api/auth/oauth/xero/callback")
        assert name == "demo@example.com"
        connections = await get_connections(first.access_token)
        second = await refresh_access_token(first.refresh_token)
    assert first.refresh_token == "rotate-1"
    assert second.refresh_token == "rotate-2"
    assert tokens.call_count == 2
    assert tokens.calls[0].request.headers["Authorization"].startswith("Basic ")
    assert "grant_type=authorization_code" in tokens.calls[0].request.content.decode()
    assert "grant_type=refresh_token" in tokens.calls[1].request.content.decode()
    assert tenants.calls[0].request.headers["Authorization"] == "Bearer one"
    assert connections[0]["tenantName"] == "Demo Company"


@pytest.mark.asyncio
async def test_missing_rotated_refresh_token_fails_closed(monkeypatch):
    monkeypatch.setenv("XERO_CLIENT_ID", "client")
    monkeypatch.setenv("XERO_CLIENT_SECRET", "secret")
    with respx.mock:
        respx.post("https://identity.xero.com/connect/token").mock(
            return_value=httpx.Response(200, json={"access_token": "new", "expires_in": 1800}))
        with pytest.raises(ValueError, match="single-use"):
            await refresh_access_token("consumed")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(OPERATIONS))
async def test_every_operation_uses_its_documented_endpoint_and_tenant(operation):
    op = OPERATIONS[operation]
    values = {field: ('{"Name":"Example"}' if field == "record_json" else
                      "REGISTERED" if field == "status" else "resource-1")
              for field in op.required_fields}
    if operation == "list_connections":
        with respx.mock(assert_all_called=True) as router:
            route = router.get("https://api.xero.com/connections").mock(
                return_value=httpx.Response(200, json=[]))
            result = await node(operation).execute({})
        assert route.call_count == 1
        assert result["data"] == {"connections": []}
        return
    path = op.path
    for field in op.required_fields:
        path = path.replace("{" + field + "}", values[field])
    with respx.mock(assert_all_called=True) as router:
        route = router.request(op.method, API_BASES[op.api] + path).mock(
            return_value=httpx.Response(200, json={"ok": True}))
        result = await node(operation, **values).execute({})
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer access"
    assert request.headers["xero-tenant-id"] == "tenant-1"
    if "record_json" in values:
        expected = ({op.body_envelope: [{"Name": "Example"}]}
                    if op.body_envelope else {"Name": "Example"})
        assert json.loads(request.content) == expected
    if operation == "list_assets":
        assert request.url.params["status"] == "REGISTERED"
    assert result == {"status": "success", "operation": operation, "data": {"ok": True}}


@pytest.mark.asyncio
async def test_tenant_picker_and_query_filters():
    with respx.mock(assert_all_called=True) as router:
        connections = router.get("https://api.xero.com/connections").mock(
            return_value=httpx.Response(200, json=[
                {"tenantId": "tenant-1", "tenantName": "Demo Company", "tenantType": "ORGANISATION"},
                {"tenantId": "tenant-2", "tenantName": "Another Company", "tenantType": "ORGANISATION"},
                {"tenantId": "practice", "tenantName": "Practice", "tenantType": "PRACTICE"},
            ]))
        invoices = router.get(API_BASES["accounting"] + "/Invoices").mock(
            return_value=httpx.Response(200, json={"Invoices": []}))
        options = await XeroNode.load_field_options("tenant_id", {"access_token": "access"}, search="Another")
        result = await node("list_invoices", tenant_id="tenant-2",
                            query_json='{"page":2,"where":"Status==\\"DRAFT\\""}').execute({})
    assert connections.call_count == 1
    assert options == {"options": [{"value": "tenant-2", "label": "Another Company"}]}
    assert invoices.calls[0].request.headers["xero-tenant-id"] == "tenant-2"
    assert invoices.calls[0].request.url.params["page"] == "2"
    assert result["data"] == {"Invoices": []}


@pytest.mark.asyncio
async def test_invalid_json_and_api_errors_are_visible():
    with pytest.raises(ValueError, match="Record JSON must be an object"):
        await node("create_invoice", record_json="[]").execute({})
    with pytest.raises(ValueError, match="Query Parameters JSON must be an object"):
        await node("list_invoices", query_json="[]").execute({})
    with respx.mock:
        respx.get(API_BASES["accounting"] + "/Organisation").mock(
            return_value=httpx.Response(401, json={"Message": "Unauthorized"}))
        with pytest.raises(ValueError, match="Xero API error 401: Unauthorized"):
            await node("get_organisation").execute({})


def test_all_operations_scoped_and_in_schema():
    assert len(OPERATIONS) == 56
    schema = XeroNode.get_config_schema()
    for name, model in CONFIG_MODELS.items():
        assert model.__name__ in schema["$defs"]
        assert XERO_SCOPES.require(name) is not None
    scopes = set(schema["$defs"]["XeroOAuthCredential"]["x-oauth-scopes"])
    assert "offline_access" in scopes
    assert "accounting.invoices" in scopes
    assert "accounting.transactions" not in scopes
    assert "accounting.reports.read" not in scopes


def test_items_use_settings_scopes_and_generic_oauth_needs_no_default_tenant():
    # Items belong to settings, not the granular invoice permission.
    for operation in ("list_items", "get_item", "create_item", "update_item", "delete_item"):
        assert XERO_SCOPES.require(operation).scopes == ("accounting.settings",)
    credential = XeroOAuthCredential(
        access_token="access", refresh_token="refresh", expires_at="2099-01-01T00:00:00Z"
    )
    assert credential.tenant_id is None
    assert set(OAUTH_PROVIDER.scopes) == set(
        XeroOAuthCredential.model_json_schema()["x-oauth-scopes"]
    )
    assert {"openid", "email", "offline_access"} <= set(OAUTH_PROVIDER.scopes)
