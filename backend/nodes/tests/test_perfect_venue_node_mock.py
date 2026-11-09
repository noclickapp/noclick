"""Offline request, paging, error and OAuth contract checks."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
import nodes.perfect_venue_node as mod
from nodes.oauth.perfect_venue_oauth import OAUTH_PROVIDER

CASES = json.loads((Path(__file__).parent / "fixtures/perfect-venue/requests.json").read_text())
CREDENTIAL = {"credential_type": "perfect_venue_oauth", "access_token": "test-secret-token"}


def node(config):
    parsed = mod.PerfectVenueNode.parse_config({"config": config, "credentials": CREDENTIAL})
    return mod.PerfectVenueNode("test", "automation-perfect-venue", {}, config=parsed)


def mock_http(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session
    monkeypatch.setattr(mod, "guarded_async_client", client)
    monkeypatch.setattr(mod, "ensure_fresh_oauth_token", AsyncMock(return_value=CREDENTIAL["access_token"]))


@pytest.mark.parametrize("case", CASES, ids=lambda x: x["operation"])
@pytest.mark.asyncio
async def test_perfect_venue_documented_requests(monkeypatch, case):
    requests = []
    # Distinct page metadata must survive, including the terminal cursor.
    payload = {"data": [{"id": "resource", "name": "Venue"}], "meta": {"next_cursor": None, "total_pages": 3}}
    def handler(request):
        requests.append(request)
        assert request.method == case["method"]
        assert request.url.path == "/api/v1" + case["path"]
        assert request.headers["Authorization"] == "Bearer test-secret-token"
        assert request.headers["PV-Version"] == "2026-11-01"
        params = {k: request.url.params.get_list(k) if len(request.url.params.get_list(k)) > 1 else request.url.params[k] for k in request.url.params}
        assert params == case["params"]
        if case["body"] is not None:
            assert json.loads(request.content) == case["body"]
        return httpx.Response(200, json=payload)
    mock_http(monkeypatch, handler)
    assert await node({"operation": case["operation"], **case["config"]}).execute({}) == payload
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_perfect_venue_inline_contact(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body == {"event": {"venue_id": "VENUE_ID", "name": "Corporate Dinner"},
                        "contact": {"email": "grace@example.com", "first_name": "Grace"}}
        return httpx.Response(200, json={"data": {"id": "event"}})
    mock_http(monkeypatch, handler)
    await node({"operation": "create_event", "venue_id": "VENUE_ID", "name": "Corporate Dinner",
                "contact": {"email": "grace@example.com", "first_name": "Grace"}}).execute({})


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
@pytest.mark.asyncio
async def test_perfect_venue_rejection_is_not_retried(monkeypatch, status):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={"type": "https://docs.perfectvenue.com/api/errors/invalid-request",
            "detail": "Rejected test-secret-token", "request_id": "request-id"})
    mock_http(monkeypatch, handler)
    with pytest.raises(ValueError, match=f"HTTP {status}: Rejected ") as exc:
        await node({"operation": "create_contact", "venue_id": "VENUE_ID"}).execute({})
    assert "test-secret-token" not in str(exc.value)
    assert len(seen) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_event", "event_id": "../other"},
    {"operation": "get_event", "event_id": " .. "},
    {"operation": "list_events", "venue_id": "v", "date_from": "2026-06-01T00:00:00Z"},
    {"operation": "create_event", "venue_id": "v", "name": "Event"},
    {"operation": "create_event", "venue_id": "v", "name": "Event", "contact_id": "c", "contact": {"email": "a@example.com"}},
    {"operation": "list_contacts", "limit": 101},
])
def test_perfect_venue_rejects_invalid_config(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_perfect_venue_oauth_and_evidence():
    assert OAUTH_PROVIDER.token_auth == "basic"
    assert OAUTH_PROVIDER.rotates_refresh_tokens
    assert OAUTH_PROVIDER.identity_url == "https://api.perfectvenue.com/api/v1/venues"
    assert mod.PerfectVenueNode.connection_evidence.operation == "list_venues"
    assert mod.PerfectVenueOAuthCredential(access_token="token").credential_type == "perfect_venue_oauth"
    assert set(mod.ROUTES) == set(mod.PERFECT_VENUE_SCOPES)


@pytest.mark.asyncio
async def test_perfect_venue_refresh_uses_shared_choke_point(monkeypatch):
    freshen = AsyncMock(return_value=CREDENTIAL)
    monkeypatch.setattr(mod, "freshen_oauth_credential", freshen)
    assert await mod.PerfectVenueNode.freshen_credential(CREDENTIAL) == CREDENTIAL
    assert freshen.call_args.kwargs["refresh"] is mod.refresh_access_token
    assert freshen.call_args.kwargs["provider"] == "perfect-venue"
