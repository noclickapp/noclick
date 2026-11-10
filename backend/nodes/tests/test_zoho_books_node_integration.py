"""Zoho Books OAuth and request contracts for every pinned OpenAPI action."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

from nodes.zoho_books_node import (
    CONFIG_MODELS, OPERATIONS, ZohoBooksNode, ZohoBooksNodeConfig,
    _field_name,
)
from nodes.oauth.zoho_books_oauth import (
    OAUTH_PROVIDER, validate_api_domain, ACCOUNTS,
)


def _node(action: dict, *, api_domain: str = "https://www.zohoapis.eu") -> ZohoBooksNode:
    action = dict(action)
    if action.get("operation") in OPERATIONS and OPERATIONS[action["operation"]]["requires_org_id"]:
        action.setdefault("organization_id", "default-org")
    config = ZohoBooksNodeConfig.model_validate({
        "config": action,
        "credentials": {
            "access_token": "test-access-token", "refresh_token": "test-refresh-token",
            "expires_at": "2099-01-01T00:00:00+00:00", "api_domain": api_domain,
            "accounts_server": "https://accounts.zoho.eu",
            "organization_id": "default-org", "organization_name": "Example Books",
        },
    })
    return ZohoBooksNode(
        node_id="zoho-books-test", node_type="automation-zoho-books", node_data={},
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
    with patch("utils.ssrf.guarded_async_client",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        result = await _node(_action(op)).execute({})
    assert result["status"] == "success"
    request = requests[0]
    assert request.method == op["method"]
    assert request.url.host == "www.zohoapis.eu"
    expected_path = re.sub(r"\{organization_id\}", "default-org", op["path"])
    expected_path = re.sub(r"\{[^{}]+\}", "sample-id", expected_path)
    assert request.url.path == "/books/v3" + expected_path
    assert request.headers["authorization"] == "Zoho-oauthtoken test-access-token"
    if op["requires_org_id"]:
        assert request.url.params["organization_id"] == "default-org"
    if op["body_mime"] == "application/json":
        assert json.loads(request.content) == json.loads(_action(op)["body_json"])
    if op["body_mime"] == "multipart/form-data":
        assert b"sample file" in request.content


def test_catalog_and_scope_coverage_are_pinned():
    from nodes.zoho_books_operations import CATALOG as catalog
    assert catalog["source"] == "https://www.zoho.com/books/api/v3/openapi-all.zip"
    assert len(catalog["operations"]) == len(OPERATIONS) == len(CONFIG_MODELS) == 878
    assert "AaaServer.profile.READ" in ZohoBooksNode.scope_registry.declared_scopes()
    for name in OPERATIONS:
        ZohoBooksNode.scope_registry.require(name)


@pytest.mark.parametrize("op", [op for op in OPERATIONS.values() if op["body_required"]],
                         ids=lambda op: op["name"])
def test_documented_required_bodies_are_required_in_the_node(op):
    action = _action(op)
    del action["body_json"]
    with pytest.raises(ValueError):
        _node(action)


@pytest.mark.asyncio
async def test_create_invoice_requires_documented_fields():
    op = OPERATIONS["create_invoice"]
    assert op["body_required_fields"] == ["customer_id", "line_items"]
    with pytest.raises(ValueError, match="line_items"):
        await _node({"operation": "create_invoice", "body_json": '{"customer_id":"customer"}'}).execute({})


def test_region_hosts_are_approved_exactly():
    assert validate_api_domain("https://www.zohoapis.eu") == "https://www.zohoapis.eu"
    assert "https://accounts.zoho.in" in ACCOUNTS
    for unsafe in ("http://www.zohoapis.eu", "https://www.zohoapis.eu.evil.test",
                   "https://www.zohoapis.eu/path", "https://user@www.zohoapis.eu"):
        with pytest.raises(ValueError):
            validate_api_domain(unsafe)


def test_declared_oauth_uses_regional_context_and_comma_scopes():
    assert OAUTH_PROVIDER.scope_separator == ","
    assert OAUTH_PROVIDER.identity_url == "{accounts_server}/oauth/user/info"
    assert OAUTH_PROVIDER.name_field == "Display_Name"
    assert OAUTH_PROVIDER.authorize_params == {"access_type": "offline", "prompt": "consent"}
    assert OAUTH_PROVIDER.credential_type == "zoho_books_oauth"
    with pytest.raises(ValueError):
        OAUTH_PROVIDER.context_fields["accounts"].validate("https://accounts.zoho.com.evil.test")


@pytest.mark.asyncio
async def test_invalid_path_query_and_provider_error():
    with pytest.raises(ValueError, match="valid identifier"):
        await _node({"operation": "get_contact", "path_contact_id": "../private"}).execute({})
    with pytest.raises(ValueError, match="JSON object"):
        await _node({"operation": "list_contacts", "query_json": "[]"}).execute({})
    real_client = httpx.AsyncClient
    with patch("utils.ssrf.guarded_async_client",
               side_effect=lambda **kw: real_client(
                   transport=httpx.MockTransport(lambda _request: httpx.Response(
                       200, json={"code": 57, "message": "Invalid organization"})), **kw)):
        with pytest.raises(ValueError, match="Invalid organization"):
            await _node({"operation": "list_contacts"}).execute({})


@pytest.mark.asyncio
async def test_binary_response_returns_shared_binary_marker():
    real_client = httpx.AsyncClient
    with patch("utils.ssrf.guarded_async_client",
               side_effect=lambda **kw: real_client(
                   transport=httpx.MockTransport(lambda _request: httpx.Response(
                       200, content=b"PDF", headers={"content-type": "application/pdf"})), **kw)):
        result = await _node({"operation": "list_contacts"}).execute({})
    from nodes.core.binary_output import BinaryOutput
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == b"PDF"
    assert result["data"].content_type == "application/pdf"

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fixture,resource,id_key", [
    ("on_invoice_updated", "invoices", "invoices", "invoice_id"),
    ("on_contact_updated", "contacts", "contacts", "contact_id"),
    ("on_payment_updated", "customer-payments", "customer_payments", "payment_id"),
])
async def test_poll_baselines_then_emits_changes_and_an_agent_turn(operation, fixture, resource, id_key):
    from copy import deepcopy
    documented = json.loads((Path(__file__).parent / "fixtures" / "zoho-books" / (fixture + ".json")).read_text())
    payload = {"code": 0, resource: [documented["record"]], "page_context": {"has_more_page": False}}
    rows = payload[resource]
    assert rows
    node = _node({"operation": operation, "organization_id": "10234695"})
    state = {}

    async def update(mutator, **kwargs):
        nonlocal state
        replacement, result = mutator(deepcopy(state))
        if replacement is not None:
            state = replacement
        return result

    async def request(credential, name, values):
        assert json.loads(values["query_json"])["page"] == 1
        return {"data": deepcopy(payload)}

    node._update_node_state = update
    node._request = request
    baseline = await node.execute({})
    assert baseline["records"] == []
    assert not node.should_propagate_output(baseline, {"operation": operation})
    assert node.resolve_agent_event(baseline) is None
    # Updating an existing id must fire, even if the API list omits a modification timestamp.
    rows[0]["last_modified_time"] = "2026-11-10T10:00:00+0000"
    result = await node.execute({})
    assert result["records"][0][id_key] == rows[0][id_key]
    assert node.should_propagate_output(result, {"operation": operation})
    assert str(rows[0][id_key]) in node.resolve_agent_event(result)["text"]
    assert (await node.execute({}))["records"] == []
    assert len(state["versions"]) == len(rows)
    node._poll_baseline_only = True
    rows[0]["last_modified_time"] = "2026-11-10T11:00:00+0000"
    assert (await node.execute({}))["records"] == []
    node._poll_baseline_only = False
    assert len((await node.execute({}))["records"]) == 1
    node.config.config.organization_id = "repointed-org"
    assert (await node.execute({}))["records"] == []


def test_accounting_action_requires_explicit_organization():
    with pytest.raises(ValueError, match="organization_id"):
        ZohoBooksNodeConfig.model_validate({"config": {"operation": "list_contacts"}})
