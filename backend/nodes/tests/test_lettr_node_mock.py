"""Offline regressions against Lettr's own published examples; no live sends."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import lettr_node as native
from nodes.core.registry import NodeFactory

TOKEN = "lettr-fixture-api-key"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/lettr/contract.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="lettr-test", node_type="automation-lettr", node_data={
        "config": config, "credentials": {"credential_type": "lettr_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_send_exact_wire_body_aliases_editor_and_idempotency(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["send_email"]["response"])
    result = await node({"operation": "send_email", "from": "sender@example.com", "to": '["recipient@example.com"]',
        "subject": "Hello", "text": "Welcome", "idempotency_key": "order-123", "options": {"transactional": False}}).run({})
    assert result["status"] == "success"
    request = requests[0]
    assert request.method == "POST" and str(request.url) == native.BASE + "/emails"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["Idempotency-Key"] == "order-123"
    assert json.loads(request.content) == {"from": "sender@example.com", "to": ["recipient@example.com"],
        "subject": "Hello", "text": "Welcome", "options": {"transactional": False}}


@pytest.mark.asyncio
async def test_account_evidence_domains_and_team(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["list_domains"]["response"])
    result = await node({"operation": "list_domains"}).run({})
    assert result["items"][0]["domain"] == "example.com"
    assert len(requests) == 1
    transport(monkeypatch, FIXTURES["check_connection"]["response"])
    result = await node({"operation": "check_connection"}).run({})
    assert result["name"] == "Lettr team 123"


@pytest.mark.asyncio
async def test_csv_filters_and_pagination_are_one_page(monkeypatch):
    body = {"data": [], "next_cursor": "next-owned-page", "has_more": True}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_email_events", "events": ["delivery", "bounce"],
        "recipients": ["recipient@example.com", "other@example.com"], "cursor": "previous", "per_page": 10}).run({})
    assert result["data"] == body and len(requests) == 1
    assert dict(requests[0].url.params) == {"events": "delivery,bounce", "recipients": "recipient@example.com,other@example.com", "cursor": "previous", "per_page": "10"}


@pytest.mark.asyncio
async def test_update_contact_null_properties_and_patch(monkeypatch):
    requests = transport(monkeypatch, {"message": "Contact updated.", "data": {}})
    result = await node({"operation": "update_contact", "contact_id": "12345678-1234-4234-8234-123456789012",
        "properties": {"first_name": None}, "status": "unsubscribed"}).run({})
    assert result["status"] == "success"
    assert requests[0].method == "PATCH"
    assert json.loads(requests[0].content) == {"properties": {"first_name": None}, "status": "unsubscribed"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 422, 429, 500])
async def test_failure_has_no_retry_or_secret(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await node({"operation": "send_email", "from": "sender@example.com", "to": ["recipient@example.com"],
        "subject": "Test", "text": "Test"}).run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"success": False}, {"error_code": "invalid_key"}, {"data": {"team_id": True}}])
async def test_malformed_identity_never_claims_success(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation": "check_connection"}).run({}))["status"] == "error"


@pytest.mark.asyncio
async def test_path_escape_refused_before_request(monkeypatch):
    requests = transport(monkeypatch, {})
    assert (await node({"operation": "get_template", "slug": "../emails"}).run({}))["status"] == "error"
    assert requests == []


@pytest.mark.parametrize("config", [
    {"operation": "send_email", "from": "sender@example.com", "to": ["recipient@example.com"]},
    {"operation": "create_template", "name": "Welcome"},
    {"operation": "update_template", "slug": "welcome", "html": "hi", "json": "{}"},
    {"operation": "create_contact", "email": "invalid"},
    {"operation": "get_contact", "contact_id": "invalid"},
    {"operation": "list_emails", "per_page": 101},
])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credential_default_and_cleaning():
    assert native.LettrAPIKeyCredential(api_key="  secret-lettr-key  ").api_key == "secret-lettr-key"
    assert native.LettrAPIKeyCredential(api_key=TOKEN).credential_type == "lettr_api_key"
    with pytest.raises(ValidationError):
        native.LettrAPIKeyCredential(api_key="Bearer " + TOKEN)
    assert set(FIXTURES) == set(native.ROUTES) and len(native.ROUTES) == 25


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(FIXTURES))
async def test_every_operation_method_and_fixed_route(monkeypatch, operation):
    configs = json.loads((Path(__file__).parent / "fixtures/lettr/configs.json").read_text())
    fixture = FIXTURES[operation]
    response = fixture["response"] or {"message": "Completed.", "data": {}}
    requests = transport(monkeypatch, response)
    result = await node(configs[operation]).run({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture["method"]
    assert request.url.host == "app.lettr.com"
    assert request.url.path.startswith("/api/")
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert "operation" not in json.loads(request.content or "{}")


@pytest.mark.asyncio
async def test_connect_evidence_shows_the_accounts_domain_names(monkeypatch):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence
    calls = []

    async def run(**kwargs):
        calls.append(kwargs["operation"])
        return {"status": "success", "items": FIXTURES["list_domains"]["response"]["data"]["domains"]}

    monkeypatch.setattr(run_op, "run_node_operation", run)
    result = await collect_evidence(node_type="automation-lettr", user_id="lettr-test-user",
        credential_data={"credential_type": "lettr_api_key", "api_key": TOKEN})
    assert result.reachable is True
    assert [sample.label for sample in result.samples] == ["example.com", "pending.example.com"]
    assert calls == ["list_domains"]
