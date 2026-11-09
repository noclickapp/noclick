"""Exercise the real TeamUp node at the HTTP boundary."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import teamup_node as native
from nodes.core.registry import NodeFactory

TOKEN = "teamup-test-secret"
CREDENTIAL = {"credential_type": "teamup_m2m_token", "api_token": TOKEN, "provider_id": 123}


def node(config):
    return NodeFactory.create_node(node_id="teamup-test", node_type="automation-teamup",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    real = httpx.AsyncClient

    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"Location": "https://example.invalid/"})

    monkeypatch.setattr(native.httpx, "AsyncClient", lambda **kw: real(**kw, transport=httpx.MockTransport(reply)))
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", json.loads((Path(__file__).parent / "fixtures/teamup/operations.json").read_text()))
async def test_operation_route_method_and_payload(monkeypatch, case):
    config, method, path, body = case["config"], case["method"], case["path"], case.get("body")
    listing = config["operation"].startswith("list_")
    response = {"results": [{"id": 1}], "count": 1, "next": None} if listing else {"id": 1}
    requests = transport(monkeypatch, response, case.get("status", 200))
    result = await node(config).run({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == "/api/v2" + path
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert req.headers["TeamUp-Provider-ID"] == "123"
    assert req.headers["TeamUp-Request-Mode"] == "provider"
    if body is not None:
        assert json.loads(req.content) == body
    else:
        assert not req.content
    if listing:
        assert req.url.params["page"] == "1" and req.url.params["page_size"] == "50"
        assert result["items"] == [{"id": 1}] and result["next_page"] is None


@pytest.mark.asyncio
async def test_filters_paging_and_no_provider_url_follow(monkeypatch):
    requests = transport(monkeypatch, {"results": [], "count": 200, "next": "https://evil.invalid/?token=stolen"})
    result = await node({"operation": "list_customers", "query": "Jane Doe", "page": 3, "page_size": 10}).run({})
    assert result["next_page"] == 4 and len(requests) == 1
    assert dict(requests[0].url.params) == {"query": "Jane Doe", "page": "3", "page_size": "10"}


@pytest.mark.asyncio
async def test_dates_and_array_filter_serialization(monkeypatch):
    requests = transport(monkeypatch, {"results": [], "count": 0})
    await node({"operation": "list_events", "starts_at_gte": "2026-11-09T10:00:00Z"}).run({})
    assert requests[0].url.params["starts_at_gte"] == "2026-11-09T10:00:00Z"
    await node({"operation": "list_attendances", "customer": 42}).run({})
    assert requests[1].url.params["customer"] == "42"


@pytest.mark.asyncio
async def test_explicit_invitation_and_membership_dates(monkeypatch):
    requests = transport(monkeypatch, {"id": 1}, 201)
    await node({"operation": "create_customer", "first_name": "Jane", "last_name": "Doe", "email": "jane@example.com", "send_invitation_email": True}).run({})
    assert json.loads(requests[0].content)["send_invitation_email"] is True
    await node({"operation": "create_customer_membership", "customer": 1, "membership": 2, "start_date": "2026-11-09", "payment_plan": 3}).run({})
    assert json.loads(requests[1].content) == {"customer": 1, "membership": 2, "start_date": "2026-11-09", "payment_plan": 3}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_errors_redact_token_and_do_not_follow_redirects(monkeypatch, status):
    requests = transport(monkeypatch, {"detail": "Rejected " + TOKEN}, status)
    result = await node({"operation": "list_customers"}).run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_success_redaction_and_optional_provider(monkeypatch):
    requests = transport(monkeypatch, {"results": [{"id": 1, "name": TOKEN}], "count": 1})
    n = NodeFactory.create_node(node_id="teamup-test", node_type="automation-teamup", node_data={
        "config": {"operation": "list_providers"}, "credentials": {"api_token": TOKEN}})
    result = await n.run({})
    assert result["items"][0]["name"] == "[redacted]" and "TeamUp-Provider-ID" not in requests[0].headers


@pytest.mark.parametrize("config", [
    {"operation": "get_event", "event_id": "../customers"},
    {"operation": "get_customer", "customer_id": 0},
    {"operation": "list_events", "page_size": 101},
    {"operation": "list_customers", "page": True},
    {"operation": "create_customer", "first_name": "Jane", "last_name": "Doe", "email": "invalid"},
    {"operation": "create_customer_membership", "customer": 1},
    {"operation": "mark_no_show", "event_id": 1},
])
def test_invalid_configs(config):
    assert not native.TeamUpNode.validate_config({"config": config, "credentials": CREDENTIAL})["valid"]


@pytest.mark.parametrize("value", ["Bearer secret", "https://example.com/key", "<token>", "hello\nworld"])
def test_manual_token_rejects_placeholders_headers_and_urls(value):
    with pytest.raises((ValidationError, ValueError)):
        native.TeamUpM2MTokenCredential(api_token=value)


@pytest.mark.asyncio
async def test_unexpanded_event_keeps_empty_attendance_collection(monkeypatch):
    body = {"id": 1, "name": "Morning class", "small_session_attendances": [],
            "offering_type": 2, "instructors": "https://goteamup.com/api/v2/instructors"}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "get_event", "event_id": 1}).run({})
    assert result == {"status": "success", "item": body}
    assert not requests[0].url.query
