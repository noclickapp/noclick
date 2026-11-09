"""Exercise native discovery and HTTP behavior using offline provider-shaped responses."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import systemeio_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/systemeio/requests.json").read_text())
TOKEN = "systemeio-synthetic-api-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="systemeio-test", node_type="automation-systemeio", node_data={
        "config": config, "credentials": {"credential_type": "systemeio_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, reply):
    requests = []

    def handle(request):
        requests.append(request)
        return reply(request)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_systemeio_operation_contract(monkeypatch, case):
    op = case["config"]["operation"]
    code = 204 if case["method"] == "DELETE" or op == "assign_tag" else 201 if case["method"] == "POST" else 200
    body = {"items": [{"id": 12, "email": "ada@example.com"}], "hasMore": False} if op.startswith("list_") else {"id": 12}
    requests = transport(monkeypatch, lambda request: httpx.Response(code, **({"json": body} if code != 204 else {})))
    result = await node(case["config"]).execute({})
    assert result["http_status"] == code and len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert request.url.host == "api.systeme.io" and request.headers["X-API-Key"] == TOKEN
    assert "authorization" not in request.headers
    assert (json.loads(request.content) if request.content else None) == case["body"]
    if case["body"] is not None:
        assert request.headers["content-type"] == ("application/merge-patch+json" if op == "update_contact" else "application/json")
    if op.startswith("list_") and op != "list_campaign_steps":
        assert dict(request.url.params) == {"limit": "100", "order": "desc", **({"course": "78", "contact": "12"} if op == "list_enrollments" else {})}
        assert result["items"] == body["items"] and result["has_more"] is False and result["next_starting_after"] is None
    if code == 204:
        assert result == {"success": True, "http_status": 204}


@pytest.mark.asyncio
async def test_systemeio_filters_and_cursor_are_explicit(monkeypatch):
    requests = transport(monkeypatch, lambda request: httpx.Response(200, json={"items": [{"id": 23}], "hasMore": True}))
    result = await node({"operation": "list_contacts", "email": "ada+test@example.com", "tags": "1,2", "bounced": False,
                         "needs_confirmation": True, "registered_before": "2023-11-22T00:00:00+00:00", "starting_after": 12, "order": "asc", "limit": 10}).execute({})
    assert dict(requests[0].url.params) == {"limit": "10", "order": "asc", "startingAfter": "12", "email": "ada+test@example.com", "tags": "1,2",
                                           "bounced": "false", "needsConfirmation": "true", "registeredBefore": "2023-11-22T00:00:00Z"}
    assert result["next_starting_after"] == 23 and result["has_more"] is True and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"items": [], "hasMore": True}, {"items": [{"id": 12}], "hasMore": True}, {"items": [], "hasMore": "false"}])
async def test_systemeio_invalid_page_refused(monkeypatch, body):
    transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "list_contacts", "starting_after": 12}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 404, 429, 500])
async def test_systemeio_provider_rejection_not_success_or_retried(monkeypatch, code):
    requests = transport(monkeypatch, lambda request: httpx.Response(code, json={"message": "Request refused"}, headers={"Location": "https://example.com"}))
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "create_tag", "name": "Customer"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_systemeio_reflected_secret_redacted(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"id": 12, "name": TOKEN, "nested": [{TOKEN: TOKEN}]}))
    result = await node({"operation": "get_tag", "tag_id": 12}).execute({})
    assert TOKEN not in str(result) and result["data"]["name"] == "[redacted]"


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": "../tags"},
    {"operation": "get_tag", "tag_id": 0},
    {"operation": "update_contact", "contact_id": 12},
    {"operation": "create_tag", "name": "x" * 65},
    {"operation": "enroll_contact", "course_id": 78, "contact_id": 12, "access_type": "partial_access"},
    {"operation": "list_contacts", "limit": 101},
    {"operation": "list_contacts", "starting_after": 0},
    {"operation": "list_contacts", "tags": "1,../2"},
])
def test_systemeio_rejects_invalid_config(config):
    with pytest.raises(ValueError):
        native.SystemeioNode.parse_config({"config": config})


def test_systemeio_manual_credential_default_and_evidence():
    credential = native.SystemeioAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "systemeio_api_key"
    assert native.SystemeioNode.connection_evidence.operation == "list_contacts"
    assert len(CASES) == len(native.ROUTES) == 20
    for key in ["https://example.com/key", "<token>", "bad\nkey"]:
        with pytest.raises(ValueError):
            native.SystemeioAPIKeyCredential(api_key=key)
