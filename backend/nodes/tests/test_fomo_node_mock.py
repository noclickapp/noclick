"""Offline Fomo wire regressions against the provider's v1 curl examples."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import fomo_node as fomo
from nodes.core.registry import NodeFactory

TOKEN = "fomo-fixture-token-42"
FIXTURES = Path(__file__).parent / "fixtures" / "fomo"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="fomo-test", node_type="automation-fomo", node_data={
        "config": config, "credentials": {"credential_type": "fomo_api_token", "api_token": TOKEN},
    })


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(fomo, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body,query", [
    ({"operation": "list_events", "page": 2, "per_page": 20}, "GET", "/applications/me/events", None,
        {"page": "2", "per_page": "20", "show_meta": "false", "order_by": "created_at", "order_direction": "desc"}),
    ({"operation": "get_event", "event_id": 1}, "GET", "/applications/me/events/1", None, {}),
    ({"operation": "delete_event", "event_id": 1}, "DELETE", "/applications/me/events/1", None, {}),
    ({"operation": "create_event", "event_type_id": 123, "first_name": "John"}, "POST", "/applications/me/events",
        {"event": {"event_type_id": 123, "first_name": "John"}}, {}),
    ({"operation": "update_event", "event_id": 1, "event_type_id": 123, "custom_event_fields_attributes": [{"id": 1, "key": "Model", "value": "Clio"}]},
        "PATCH", "/applications/me/events/1", {"event": {"event_type_id": 123, "custom_event_fields_attributes": [{"id": 1, "key": "Model", "value": "Clio"}]}}, {}),
    ({"operation": "search_event_by_email", "email_address": "john+sales@fomo.com"}, "GET", "/applications/me/events/find", None,
        {"field": "email_address", "q": "john+sales@fomo.com"}),
    ({"operation": "search_event_by_external_id", "external_id": "adf23r"}, "GET", "/applications/me/events/find", None,
        {"field": "external_id", "q": "adf23r"}),
    ({"operation": "create_template", "name": "New Lead", "message": "Someone joined", "markdown_enabled": False}, "POST", "/applications/me/event_types",
        {"event_type": {"name": "New Lead", "message": "Someone joined", "markdown_enabled": False}}, {}),
    ({"operation": "get_statistics", "date_from": "2020-03-20", "date_to": "2020-04-20"}, "GET", "/applications/me/dashboard", None,
        {"date_range[from]": "2020-03-20", "date_range[to]": "2020-04-20"}),
    ({"operation": "update_application", "application_id": 1, "hide_mobile": False, "display_interval": 0}, "PATCH", "/users/me/applications/1",
        {"application": {"hide_mobile": False, "display_interval": 0}}, {}),
])
async def test_documented_routes_auth_envelopes_and_falsy_values(monkeypatch, config, method, path, body, query):
    response = [] if config["operation"] == "list_events" else {"id": 1}
    calls = transport(monkeypatch, response)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.host == "api.fomo.com"
    assert request.url.path == "/api/v1" + path
    assert request.headers["Authorization"] == "Token " + TOKEN
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create_event", "update_event", "get_event", "search_event_by_email", "search_event_by_external_id", "delete_event", "get_statistics"])
async def test_provider_authored_responses(monkeypatch, operation):
    fixture = json.loads((FIXTURES / "responses.json").read_text())["search_event" if operation.startswith("search_event_") else operation]
    configs = {
        "create_event": {"event_type_id": 123}, "update_event": {"event_id": 1, "event_type_id": 123},
        "get_event": {"event_id": 1}, "search_event_by_email": {"email_address": "john@fomo.com"},
        "search_event_by_external_id": {"external_id": "adf23r"},
        "delete_event": {"event_id": 1}, "get_statistics": {},
    }
    transport(monkeypatch, fixture["body"])
    result = await node({"operation": operation, **configs[operation]}).execute({})
    assert result["status"] == "success" and result["data"] == fixture["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"error": "Invalid token"}), (403, {"error": {"message": "Forbidden"}}),
    (429, {"error": "Rate limit"}), (500, {"error": "Unavailable"}), (200, {"success": False, "error": "Query must not be empty"})])
async def test_rejection_envelopes_do_not_claim_success(monkeypatch, status, body):
    transport(monkeypatch, body, status)
    result = await node({"operation": "list_events"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status and result["error"] == body


@pytest.mark.asyncio
async def test_application_secrets_and_echoed_token_never_escape(monkeypatch):
    transport(monkeypatch, {"id": 1, "client_secret": "provider-secret", "name": TOKEN})
    result = await node({"operation": "update_application", "application_id": 1, "name": "Fomo app"}).execute({})
    assert TOKEN not in str(result) and "provider-secret" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"events": [], "meta": {"page": 1}}])
async def test_account_list_empty_and_metadata_forms(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation": "list_events", "show_meta": True}).execute({}))["data"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [({}, 200), ("not an event list", 200), ({}, 302)])
async def test_malformed_or_redirected_list_never_proves_account(monkeypatch, body, status):
    transport(monkeypatch, body, status)
    with pytest.raises(ValueError):
        await node({"operation": "list_events"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_event", "event_id": "../find"}, {"operation": "delete_event", "event_id": -1},
    {"operation": "create_event"}, {"operation": "update_application", "application_id": 1},
    {"operation": "get_statistics", "date_from": "2020-04-20", "date_to": "2020-03-20"},
    {"operation": "search_event_by_email"},
])
def test_invalid_operation_inputs_fail_before_http(config):
    with pytest.raises(ValueError):
        node(config)
