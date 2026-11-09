"""Exercise Simplicate's native node through the real factory and HTTP boundary."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import simplicate_node as native
from nodes.core.registry import NodeFactory

CREDENTIAL = {"credential_type": "simplicate_api_key", "subdomain": "your-company",
              "api_key": "example-key-123", "api_secret": "example-secret-456"}
FIXTURES = Path(__file__).parent / "fixtures" / "simplicate"


def node(config):
    return NodeFactory.create_node(node_id="simplicate-test", node_type="automation-simplicate",
                                  node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_account_evidence_page_and_next_page(monkeypatch):
    page = json.loads((FIXTURES / "relation_types.json").read_text())
    requests = transport(monkeypatch, httpx.Response(200, json=page))
    result = await node({"operation": "list_relation_types", "page": 2, "items_per_page": 10, "search": "Klant"}).execute({})
    assert result["data"] == page["data"] and result["next_page"] == 3
    request = requests[0]
    assert str(request.url).startswith("https://your-company.simplicate.app/api/v3/relation.relationtype.list?")
    assert dict(request.url.params) == {"page": "2", "itemsPerPage": "10", "search": "Klant"}
    assert request.headers["Authorization"] == "Bearer example-key-123:example-secret-456"
    assert request.method == "GET" and request.content == b""
    assert native.SimplicateNode.connection_evidence.operation == "list_relation_types"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,route", [
    ("get_project", "project"), ("get_project_service", "projectService"),
    ("get_invoice_draft_request", "invoiceDraftRequest"), ("get_cost_type", "costType"),
    ("get_hour_type", "hourType"), ("get_default_service", "defaultService"),
    ("get_vat_code", "vatCode"), ("get_revenue_group", "revenueGroup"),
])
async def test_exact_read_route_and_opaque_id_encoding(monkeypatch, operation, route):
    requests = transport(monkeypatch, httpx.Response(200, json={"id": "entity:one/two", "name": "Owned"}))
    result = await node({"operation": operation, "id": "entity:one/two"}).execute({})
    assert result["data"]["id"] == "entity:one/two"
    assert requests[0].url.raw_path == ("/api/v3/" + route + ".get/entity%3Aone%2Ftwo").encode()
    assert requests[0].method == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,body,status", [
    ({"operation": "create_relation_type", "name": "Klant", "color": "#ff5500"}, "relation.relationtype.create", {"name": "Klant", "color": "#ff5500"}, 201),
    ({"operation": "update_relation_type", "relationTypeId": "relationtype:1234567890abcdef", "color": "#fff"}, "relation.relationtype.update", {"relationTypeId": "relationtype:1234567890abcdef", "color": "#fff"}, 200),
    ({"operation": "delete_relation_type", "relationTypeId": "relationtype:1234567890abcdef"}, "relation.relationtype.delete", {"relationTypeId": "relationtype:1234567890abcdef"}, 204),
    ({"operation": "set_default_relation_type"}, "relation.relationtype.setDefault", {"relationTypeId": None}, 204),
    ({"operation": "create_sale_service_group", "saleId": "sales:one", "name": "Consultancy services", "type": "all_included"}, "saleService.group.create", {"saleId": "sales:one", "name": "Consultancy services", "type": "all_included"}, 201),
    ({"operation": "update_sale_service_group", "serviceGroupId": "salesservicegroup:one", "name": "Consultancy services", "type": "single_optional"}, "saleService.group.update", {"serviceGroupId": "salesservicegroup:one", "name": "Consultancy services", "type": "single_optional"}, 201),
    ({"operation": "delete_sale_service_group", "serviceGroupId": "salesservicegroup:one"}, "saleService.group.delete", {"serviceGroupId": "salesservicegroup:one", "shouldDeleteServices": False}, 201),
])
async def test_mutations_are_single_documented_rpc(monkeypatch, config, path, body, status):
    response = httpx.Response(status) if status == 204 else httpx.Response(status, json={"id": "owned-resource"})
    requests = transport(monkeypatch, response)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["http_status"] == status
    assert len(requests) == 1 and requests[0].method == "POST"
    assert requests[0].url.path == "/api/v3/" + path
    assert json.loads(requests[0].content) == body
    assert requests[0].headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,field,value", [("list_invoice_methods", "invoiceMethods", "fixed_price"), ("list_subscription_cycles", "cycleOptions", "monthly")])
async def test_nonpaginated_option_queries(monkeypatch, operation, field, value):
    requests = transport(monkeypatch, httpx.Response(200, json={field: [value]}))
    result = await node({"operation": operation}).execute({})
    assert result["data"] == {field: [value]} and not requests[0].url.query


@pytest.mark.asyncio
async def test_problem_details_and_redirects_fail_without_leaking_credentials(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(403, json={"detail": "Denied example-secret-456"}, headers={"Content-Type": "application/problem+json"}))
    result = await node({"operation": "list_relation_types"}).execute({})
    assert result == {"status": "error", "http_status": 403, "error": "Denied [redacted]"}
    redirected_requests = transport(monkeypatch, httpx.Response(302, headers={"Location": "https://attacker.example/"}))
    result = await node({"operation": "list_relation_types"}).execute({})
    assert result["status"] == "error" and len(redirected_requests) == 1


@pytest.mark.asyncio
async def test_invalid_collection_is_not_success(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"data": []}))
    with pytest.raises(ValueError, match="pagination"):
        await node({"operation": "list_relation_types"}).execute({})


def test_manual_defaults_host_bounds_and_input_bounds():
    assert native.SimplicateAPIKeyCredential.model_validate({k: v for k, v in CREDENTIAL.items() if k != "credential_type"}).credential_type == "simplicate_api_key"
    for host in ("https://company.simplicate.app", "evil.example", "a/b", "company.simplicate.app@evil", "127.0.0.1"):
        with pytest.raises(ValidationError):
            native.SimplicateAPIKeyCredential.model_validate({**CREDENTIAL, "subdomain": host})
    for config in ({"operation": "list_relation_types", "items_per_page": 31},
                   {"operation": "create_relation_type", "name": "Klant", "color": "red"},
                   {"operation": "create_sale_service_group", "saleId": "one", "name": "X", "type": "unknown"}):
        with pytest.raises(ValueError):
            node(config)
