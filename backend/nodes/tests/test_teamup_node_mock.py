"""Exercise the real TeamUp node at the HTTP boundary."""
import json
from pathlib import Path

import httpx
from httpx import AsyncClient as RealAsyncClient
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
    real = RealAsyncClient

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


# Exact delivery example: https://docs.goteamup.com/guides/webhooks#payload
REGISTRATION = json.loads((Path(__file__).parent / "fixtures/teamup/registration.json").read_text())


@pytest.mark.asyncio
async def test_trigger_registration_uses_application_and_cleanup(monkeypatch):
    requests = transport(monkeypatch, {"object": "webhook_destination", "id": 53583,
        "url": "https://example.com/receiver", "feed_item_types": ["*"], "application": 533}, 201)
    config = {"operation": "on_class_registration", "application_id": 533}
    state = await native.TeamUpNode._register_external_webhook(webhook_url="https://example.com/receiver",
        credential=CREDENTIAL, config=config, node_id="teamup-test")
    assert state == {"external_webhook_id": "53583"}
    assert json.loads(requests[0].content) == {"url": "https://example.com/receiver",
        "feed_item_types": ["event_registration.created"], "application": 533}
    assert requests[0].method == "POST" and requests[0].url.path == "/api/v2/webhook_destinations"
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN
    assert requests[0].headers["TeamUp-Provider-ID"] == "123"
    assert requests[0].headers["TeamUp-Request-Mode"] == "provider"
    requests = transport(monkeypatch, {}, 204)
    await native.TeamUpNode._unregister_external_webhook(credential=CREDENTIAL,
        config={**config, **state}, node_id="teamup-test")
    assert requests[0].method == "DELETE" and requests[0].url.path == "/api/v2/webhook_destinations/53583"
    assert not requests[0].content
    assert native.TeamUpNode.registration_fingerprint_fields(config) == {"application_id": 533}


def test_documented_registration_delivery_and_agent_turn():
    cls = native.TeamUpNode
    assert cls.webhook_signing_secret_not_issued
    assert cls.verify_webhook_signature(json.dumps(REGISTRATION).encode(), {}, {})
    assert cls.filter_trigger_payload(REGISTRATION, {})
    output = cls.resolve_trigger_payload(REGISTRATION, {})
    assert output == REGISTRATION
    event = cls.resolve_agent_event(output)
    assert event["conversation_key"] == "teamup:285151:customer:818974"
    for fact in ("818974", "14947247", "285151", "13553027", "standalone", "2019-04-27T21:52.45",
                 "get_customer customer_id=818974", "get_event event_id=14947247", "unsigned"):
        assert fact in event["text"]
    assert cls.resolve_trigger_payload({"feed_items": REGISTRATION["feed_items"] * 2}, {})["feed_items"] == REGISTRATION["feed_items"] * 2


@pytest.mark.parametrize("payload", [None, {}, {"feed_items": None}, {"feed_items": [None]},
    {"feed_items": [{"object": "feed_item", "type": "customer.created", "id": 1}]},
    {"feed_items": [{"object": "feed_item", "type": "event_registration.created", "id": 1, "resources": {}}]}])
def test_trigger_filters_unrelated_or_malformed_deliveries(payload):
    assert not native.TeamUpNode.filter_trigger_payload(payload, {})
    assert native.TeamUpNode.resolve_agent_event(native.TeamUpNode.resolve_trigger_payload(payload, {})) is None


@pytest.mark.asyncio
async def test_manual_trigger_run_does_not_fire_or_call_teamup(monkeypatch):
    requests = transport(monkeypatch, {})
    result = await node({"operation": "on_class_registration", "application_id": 533}).run({})
    assert result["status"] == "no_event" and not requests


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_webhook_errors_do_not_leak_token(monkeypatch, status):
    transport(monkeypatch, {"detail": TOKEN}, status)
    with pytest.raises(ValueError) as error:
        await native.TeamUpNode._register_external_webhook(webhook_url="https://example.com/receiver",
            credential=CREDENTIAL, config={"application_id": 533}, node_id="teamup-test")
    assert TOKEN not in str(error.value)


@pytest.mark.asyncio
async def test_cleanup_already_deleted_destination(monkeypatch):
    transport(monkeypatch, {}, 404)
    await native.TeamUpNode._unregister_external_webhook(credential=CREDENTIAL,
        config={"external_webhook_id": "53583"}, node_id="teamup-test")
