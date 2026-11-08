"""Exercise native Cardly requests against deterministic HTTP responses."""
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError

from nodes import cardly_node as native
from nodes.core.registry import NodeFactory

KEY = "test_cardly-fixture-key"
CONTACT = {"firstName": "Thor", "address": "1 Main Street", "locality": "Brooklyn", "region": "NY", "country": "US", "postcode": "12345"}
RECIPIENT = {"firstName": "Thor", "address": "1 Main Street", "city": "Brooklyn", "region": "NY", "country": "US", "postcode": "12345"}
LIST = "6d7c260b-f39f-e822-6aa5-612014047d20"
ID = "23fb4b1c-f127-eeea-9f68-6f0a7945da43"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="cardly-test", node_type="automation-cardly", node_data={
        "config": config, "credentials": {"credential_type": "cardly_api_key", "api_key": KEY}})


def transport(monkeypatch, reply, *, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(status, json=reply)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs) as session:
            yield session
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def response(data, **extra):
    return {"state": {"status": "OK", "messages": [], "version": 1181}, "data": data, **extra}


def page(rows=None):
    return response({"results": rows or [], "meta": {"offset": 0, "limit": 25, "lastRecord": 25, "totalRecords": 50}})


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,query", [
    ({"operation": "list_artwork", "ownOnly": True, "offset": 25}, "/art", {"ownOnly": "true", "limit": "25", "offset": "25"}),
    ({"operation": "list_contact_lists"}, "/contact-lists", {"limit": "25", "offset": "0"}),
    ({"operation": "list_contacts", "list_id": LIST}, f"/contact-lists/{LIST}/contacts", {"limit": "25", "offset": "0"}),
    ({"operation": "search_contacts", "list_id": LIST, "query": "thor+card@example.com"}, f"/contact-lists/{LIST}/contacts/find", {"query": "thor+card@example.com"}),
    ({"operation": "get_order", "id": ID}, f"/orders/{ID}", {}),
])
async def test_read_paths_auth_and_queries(monkeypatch, config, path, query):
    requests = transport(monkeypatch, page() if config["operation"].startswith("list_") else response({"id": ID}))
    result = await node(config).execute({})
    assert result["status"] == "success"
    request = requests[0]
    assert len(requests) == 1 and request.method == "GET"
    assert request.url.host == "api.card.ly" and request.url.path == "/v2" + path
    assert request.headers["API-Key"] == KEY
    assert dict(request.url.params) == query
    if config["operation"].startswith("list_"):
        assert result["has_more"] is True and result["next_offset"] == 25


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,fields", [
    ("create_contact", f"/contact-lists/{LIST}/contacts", {**CONTACT, "externalId": "thor1234"}),
    ("update_contact", f"/contact-lists/{LIST}/contacts/{ID}", {**CONTACT, "lastName": "Odinson"}),
    ("sync_contact", f"/contact-lists/{LIST}/contacts/sync", {**CONTACT, "email": "thor@avengers.com"}),
])
async def test_contact_writes_are_json_with_no_routing_fields(monkeypatch, operation, path, fields):
    requests = transport(monkeypatch, response({"id": ID}))
    config = {"operation": operation, "list_id": LIST, **fields}
    if operation == "update_contact": config["id"] = ID
    result = await node(config).execute({})
    request = requests[0]
    assert result["success"] is True and request.method == "POST"
    assert request.url.path == "/v2" + path
    assert json.loads(request.content) == fields
    assert request.headers["Content-Type"] == "application/json"
    assert not request.url.query


@pytest.mark.asyncio
async def test_order_place_preserves_nested_payload_and_test_mode(monkeypatch):
    requests = transport(monkeypatch, response({"order": {"id": ID}}, testMode=True))
    line = {"artwork": "happy-birthday", "template": "happy-birthday-promo", "recipient": RECIPIENT, "variables": {"firstName": "Thor"}, "quantity": 1}
    result = await node({"operation": "place_order", "lines": [line]}).execute({})
    assert result["test_mode"] is True and result["data"]["order"]["id"] == ID
    assert requests[0].url.path == "/v2/orders/place" and requests[0].method == "POST"
    assert json.loads(requests[0].content) == {"lines": [line]}


@pytest.mark.asyncio
async def test_preview_and_delete_are_single_contract_operations(monkeypatch):
    requests = transport(monkeypatch, response({"preview": {"urls": {"card": "https://api.card.ly/preview.pdf"}}}))
    result = await node({"operation": "preview_order", "artwork": "happy-birthday", "recipient": RECIPIENT}).execute({})
    assert requests[0].url.path == "/v2/orders/preview" and requests[0].method == "POST"
    assert result["data"]["preview"]["urls"]["card"].endswith("preview.pdf")
    requests = transport(monkeypatch, response({"id": LIST, "status": "deleted"}))
    result = await node({"operation": "delete_contact_list", "id": LIST}).execute({})
    assert len(requests) == 1 and requests[0].method == "DELETE"
    assert requests[0].url.path == "/v2/contact-lists/" + LIST
    assert result["data"]["status"] == "deleted"


@pytest.mark.asyncio
async def test_error_envelope_is_not_success_and_key_is_redacted(monkeypatch):
    transport(monkeypatch, {"state": {"status": "ERROR", "messages": ["Invalid API key " + KEY]}} , status=401)
    result = await node({"operation": "get_balance"}).execute({})
    assert result["status"] == "error" and result["http_status"] == 401
    assert result["error"] == "Invalid API key [redacted]" and KEY not in str(result)


@pytest.mark.asyncio
async def test_write_timeout_is_unknown_and_never_retried(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout("timeout"))
    result = await node({"operation": "place_order", "lines": [{"artwork": "happy-birthday", "recipient": RECIPIENT}]}).execute({})
    assert result["status"] == "unknown" and result["write_outcome"] == "unknown"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_connection_evidence_returns_organisation_lists(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, page([{"id": LIST, "name": "Online Sales"}]))
    evidence = await collect_evidence(node_type="automation-cardly", user_id="cardly-test-user", credential_data={"credential_type": "cardly_api_key", "api_key": KEY})
    assert evidence.reachable is True
    assert "Online Sales" in str(evidence)


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "list_id": "../other", "id": ID},
    {"operation": "sync_contact", "list_id": LIST, **CONTACT},
    {"operation": "place_order", "lines": []},
    {"operation": "preview_order", "artwork": "happy-birthday", "recipient": {}},
    {"operation": "list_orders", "offset": -1},
])
def test_invalid_configuration_is_rejected(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)
