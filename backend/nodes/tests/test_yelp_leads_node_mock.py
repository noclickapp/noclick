"""Exercise the real node against Yelp's publisher examples, without accounts."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import yelp_leads_node as native
from nodes.core.registry import NodeFactory
from nodes.oauth.yelp_leads_oauth import OAUTH_PROVIDER

FIXTURES = Path(__file__).parent / "fixtures" / "yelp-leads"
BUSINESS = "VXi7gzRqPKp63X0u6fUtbg"
LEAD = "jPlz8TM628rzyCRPqrtcvm"
AUTH = {"credential_type": "yelp_leads_oauth", "business_id": BUSINESS,
        "access_token": "synthetic-yelp-access-token", "refresh_token": "synthetic-yelp-refresh-token",
        "expires_at": "2099-01-01T00:00:00+00:00"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, auth=None):
    return NodeFactory.create_node(node_id="yelp-fixture", node_type="automation-yelp-leads",
        node_data={"config": config, "credentials": AUTH if auth is None else auth})


def transport(monkeypatch, status, payload):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_older_lead_events", "lead_id": LEAD, "older_than_cursor": "cursor5"}, "GET", f"/v3/leads/{LEAD}/events", None, "events.json"),
    ({"operation": "get_newer_lead_events", "lead_id": LEAD, "newer_than_cursor": "cursor1"}, "GET", f"/v3/leads/{LEAD}/events", None, "events.json"),
    ({"operation": "mark_lead_replied_by_phone", "lead_id": LEAD}, "POST", f"/v3/leads/{LEAD}/mark_as_replied", {"reply_type": "PHONE"}, None),
    ({"operation": "mark_lead_replied_by_email", "lead_id": LEAD}, "POST", f"/v3/leads/{LEAD}/mark_as_replied", {"reply_type": "EMAIL"}, None),
    ({"operation": "get_lead", "lead_id": LEAD}, "GET", f"/v3/leads/{LEAD}", None, "lead.json"),
    ({"operation": "get_lead_events", "lead_id": LEAD, "limit": 2, "older_than_cursor": "cursor5"},
     "GET", f"/v3/leads/{LEAD}/events", None, "events.json"),
    ({"operation": "write_lead_event", "lead_id": LEAD, "request_content": "The text message you want to send"},
     "POST", f"/v3/leads/{LEAD}/events", {"request_content": "The text message you want to send", "request_type": "TEXT"}, None),
    ({"operation": "mark_lead_as_replied", "lead_id": LEAD, "reply_type": "PHONE"},
     "POST", f"/v3/leads/{LEAD}/mark_as_replied", {"reply_type": "PHONE"}, None),
    ({"operation": "mark_lead_event_as_read", "lead_id": LEAD, "event_id": "NJJQvyxvpk87NUpsm2y5Yw", "time_read": "2022-07-21T20:54:42+00:00"},
     "POST", f"/v3/leads/{LEAD}/events/mark_as_read", {"event_id": "NJJQvyxvpk87NUpsm2y5Yw", "time_read": "2022-07-21T20:54:42+00:00"}, None),
    ({"operation": "list_lead_ids", "created_after": "2024-06-30T23:59:59Z", "after_lead_id": LEAD},
     "GET", f"/v3/businesses/{BUSINESS}/lead_ids", None, "lead_ids.json"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body,fixture", CASES)
async def test_all_six_published_operations(monkeypatch, config, method, path, body, fixture):
    response = json.loads((FIXTURES / fixture).read_text()) if fixture else {}
    requests = transport(monkeypatch, 200 if method == "GET" else 201, response)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == response
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.host == "api.yelp.com" and request.url.path == path
    assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
    assert (json.loads(request.content) if request.content else None) == body
    assert AUTH["access_token"] not in json.dumps(result)
    if config["operation"] == "get_lead_events":
        assert dict(request.url.params) == {"limit": "2", "older_than_cursor": "cursor5"}
    if config["operation"] == "list_lead_ids":
        assert dict(request.url.params) == {"limit": "20", "after_lead_id": LEAD, "created_after": "2024-06-30T23:59:59Z"}
        assert result["next_after_lead_id"] == response["lead_ids"][-1]


@pytest.mark.asyncio
async def test_empty_connection_evidence(monkeypatch):
    transport(monkeypatch, 200, {"lead_ids": [], "has_more": False})
    result = await node({"operation": "list_lead_ids"}).execute({})
    assert result["items"] == [] and result["next_after_lead_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_failed_or_redirected_calls_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, status, {"error": {"description": "Rejected " + AUTH["access_token"]}})
    result = await node({"operation": "write_lead_event", "lead_id": LEAD, "request_content": "Reply"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert AUTH["access_token"] not in result["error"] and len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_lead", "lead_id": "../other"},
    {"operation": "get_lead_events", "lead_id": LEAD, "limit": 21},
    {"operation": "write_lead_event", "lead_id": LEAD, "request_content": "  "},
    {"operation": "mark_lead_as_replied", "lead_id": LEAD, "reply_type": "SMS"},
    {"operation": "mark_lead_event_as_read", "lead_id": LEAD, "event_id": "event", "time_read": "2024-01-01"},
    {"operation": "list_lead_ids", "unknown": "field"},
])
def test_invalid_inputs(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_credential_type_default_and_scopes():
    assert native.YelpLeadsOAuthCredential.model_validate({k: v for k, v in AUTH.items() if k != "credential_type"}).credential_type == "yelp_leads_oauth"
    assert native.YELP_LEADS_SCOPES.declared_scopes() == ["leads"]
    assert OAUTH_PROVIDER.rotates_refresh_tokens is True


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,accepted", [({"lead_ids": []}, True), ({"lead_ids": [LEAD]}, True), ({"error": "rejected"}, False), ({}, False)])
async def test_oauth_identity_requires_business_access(monkeypatch, payload, accepted):
    def client(*args, **kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    monkeypatch.setattr(type(OAUTH_PROVIDER), "_client", client)
    if accepted:
        assert await OAUTH_PROVIDER.account_name(AUTH["access_token"], context={"business_id": BUSINESS}) == BUSINESS
    else:
        with pytest.raises(ValueError):
            await OAUTH_PROVIDER.account_name(AUTH["access_token"], context={"business_id": BUSINESS})
