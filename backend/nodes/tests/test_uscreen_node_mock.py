"""Offline Uscreen Publisher API routing, consent, evidence and paging checks."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import uscreen_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-uscreen-key-4fc938"
CREDENTIAL = {"credential_type": "uscreen_api_key", "api_key": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/uscreen/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="uscreen-test", node_type="automation-uscreen",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, *, body=None, status=200, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body if body is not None else {"id": 123}, headers=headers)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_documented_routes_auth_and_json(monkeypatch, case):
    requests = transport(monkeypatch, body=[] if case["config"]["operation"].startswith("list_") else {"id": 123}, status=201 if case["config"]["operation"] == "add_group_member" else 200)
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url).split("?")[0] == "https://uscreen.io/publisher_api/v1" + case["path"]
    assert dict(request.url.params) == case.get("query", {})
    assert (json.loads(request.content) if request.content else {}) == case.get("body", {})
    assert request.headers["Authorization"] == TOKEN
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_customer_consent_omission_and_explicit_false(monkeypatch):
    requests = transport(monkeypatch)
    await node({"operation": "create_customer", "name": "John Doe", "email": "user@example.org"}).execute({})
    assert json.loads(requests[0].content) == {"name": "John Doe", "email": "user@example.org"}
    await node({"operation": "update_customer", "customer_id": "user+test@example.org", "opted_in_for_news_and_updates": False, "tags": []}).execute({})
    assert json.loads(requests[1].content) == {"opted_in_for_news_and_updates": False, "tags": []}
    assert "user%2Btest%40example.org" in str(requests[1].url)


@pytest.mark.asyncio
async def test_header_pagination_and_capped_count(monkeypatch):
    transport(monkeypatch, body=[], headers={"Total-Count": "10000+", "Link": '<https://uscreen.io/publisher_api/v1/invoices?page=2>; rel="next"'})
    result = await node({"operation": "list_invoices"}).execute({})
    assert result["data"] == [] and result["next_page"] == 2 and result["total_count"] == "10000+"


@pytest.mark.asyncio
@pytest.mark.parametrize("link", ['<https://evil.test/customers?page=2>; rel="next"', '<https://uscreen.io/publisher_api/v1/customers?page=1>; rel="next"'])
async def test_foreign_or_stalled_pagination_is_refused(monkeypatch, link):
    requests = transport(monkeypatch, body=[], headers={"Link": link})
    with pytest.raises(ValueError):
        await node({"operation": "list_customers"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_provider_errors_are_not_success_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, body={"error": "Rejected " + TOKEN}, status=status)
    result = await node({"operation": "create_subscription", "customer_id": "123", "product_id": 987}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_subscription_no_content(monkeypatch):
    transport(monkeypatch, status=204)
    assert (await node({"operation": "get_subscription", "customer_id": "123"}).execute({}))["data"] is None


@pytest.mark.parametrize("config", [
    {"operation": "get_customer", "customer_id": "../other"},
    {"operation": "list_customers", "page": True},
    {"operation": "list_video_views", "per_page": 101},
    {"operation": "update_customer", "customer_id": "123"},
    {"operation": "create_subscription", "customer_id": "123", "product_id": 987, "with_manual_billing": True, "perform_action_at": 1720186999},
])
def test_invalid_inputs(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_credential_default_and_connection_read():
    assert native.UscreenAPIKeyCredential(api_key=TOKEN).credential_type == "uscreen_api_key"
    assert native.UscreenNode.connection_evidence.operation == "list_customers"
