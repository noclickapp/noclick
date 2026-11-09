"""Kommo route catalog, tenant safety, JSON shapes, and OAuth contracts."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx
import pytest

from nodes import kommo_node as module
from nodes.kommo_node import (
    KOMMO_CONFIGS,
    KOMMO_OPERATIONS,
    KommoLongLivedTokenCredential,
    KommoNode,
    KommoNodeConfig,
    KommoOAuthCredential,
)
from nodes.oauth import kommo_oauth


def _node(operation, credential=None, **values):
    return KommoNode(
        "test",
        "automation-kommo",
        {},
        config=KommoNodeConfig(
            config=KOMMO_CONFIGS[operation](**values),
            credentials=credential
            or KommoLongLivedTokenCredential(subdomain="example", token="test-token"),
        ),
    )


def _values(spec):
    values = {
        name: "leads" if name == "entity_type" else "abc"
        for name in spec["path_parameters"]
    }
    if spec["has_body"]:
        values["body"] = json.dumps([{"name": "Example"}])
    return values


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", KOMMO_OPERATIONS)
async def test_every_catalog_operation_routes_to_verified_tenant(
    operation, monkeypatch
):
    spec = KOMMO_OPERATIONS[operation]
    seen = []
    original = httpx.AsyncClient
    monkeypatch.setattr(
        module,
        "guarded_async_client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: (
                    seen.append(request),
                    httpx.Response(200, json={"_embedded": {}}),
                )[-1]
            ),
            **kwargs,
        ),
    )
    values = _values(spec)
    result = await _node(operation, **values).execute({})
    assert result["status"] == "success"
    assert result["data"] == {"_embedded": {}}
    request = seen.pop()
    assert request.method == spec["method"]
    assert request.url.host == "example.kommo.com"
    expected = spec["path"]
    for name in spec["path_parameters"]:
        expected = expected.replace("{" + name + "}", quote(values[name], safe=""))
    assert request.url.raw_path.decode() == "/api/v4" + expected
    assert request.headers["Authorization"] == "Bearer test-token"
    if spec["has_body"]:
        assert json.loads(request.content) == [{"name": "Example"}]


@pytest.mark.asyncio
async def test_query_encoding_and_invalid_tenant_blocked(monkeypatch):
    seen = []
    original = httpx.AsyncClient
    monkeypatch.setattr(
        module,
        "guarded_async_client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: (seen.append(request), httpx.Response(200, json={}))[-1]
            ),
            **kwargs,
        ),
    )
    result = await _node(
        "list_tasks", query='{"filter[is_completed]": 1, "limit": 25}'
    ).execute({})
    assert result["status"] == "success"
    assert seen[0].url.params["filter[is_completed]"] == "1"
    assert seen[0].url.params["limit"] == "25"
    with pytest.raises(ValueError, match="valid JSON"):
        await _node("list_tasks", query="{").execute({})
    with pytest.raises(ValueError, match="JSON object"):
        await _node("list_tasks", query="[]").execute({})
    with pytest.raises(ValueError):
        await _node(
            "get_account",
            credential=KommoLongLivedTokenCredential(
                subdomain="https://example.kommo.com@127.0.0.1", token="secret"
            ),
        ).execute({})
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_oauth_token_used_and_errors_preserved(monkeypatch):
    seen = []
    original = httpx.AsyncClient
    monkeypatch.setattr(
        module,
        "guarded_async_client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: (
                    seen.append(request),
                    httpx.Response(429, json={"title": "rate limit"}),
                )[-1]
            ),
            **kwargs,
        ),
    )
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    credential = KommoOAuthCredential(
        referer="example.kommo.com",
        access_token="access",
        refresh_token="refresh",
        expires_at=expiry,
    )
    result = await _node("list_leads", credential=credential).execute({})
    assert seen[0].headers["Authorization"] == "Bearer access"
    assert result["status_code"] == 429
    assert result["error"] == {"title": "rate limit"}


def test_catalog_schema_and_reference_links():
    assert len(KOMMO_OPERATIONS) == len(KOMMO_CONFIGS) == 72
    schema = KommoNode.get_config_schema()
    assert "KommoOAuthCredential" in schema["$defs"]
    assert "KommoLongLivedTokenCredential" in schema["$defs"]
    for spec in KOMMO_OPERATIONS.values():
        assert spec["reference"].startswith("https://developers.kommo.com/reference/")
        assert spec["path"].startswith("/")
        assert set(spec["path_parameters"]) == set(
            __import__("re").findall(r"{([^}]+)}", spec["path"])
        )


@pytest.mark.asyncio
async def test_oauth_exchange_refresh_and_account_verification(monkeypatch):
    monkeypatch.setenv("KOMMO_CLIENT_ID", "client")
    monkeypatch.setenv("KOMMO_CLIENT_SECRET", "secret")
    monkeypatch.setenv(
        "KOMMO_REDIRECT_URI", "https://noclick.example/api/auth/kommo/callback"
    )
    seen = []
    original = httpx.AsyncClient

    def respond(request):
        seen.append(request)
        if request.url.path.endswith("/account"):
            return httpx.Response(200, json={"id": 123, "name": "Test Company"})
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 86400,
            },
        )

    monkeypatch.setattr(
        "utils.ssrf.guarded_async_client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    spec = kommo_oauth.OAUTH_PROVIDER
    exchanged, name = await spec.exchange(
        "auth-code",
        "https://noclick.example/api/auth/kommo/callback",
        context={"referer": "example.kommo.com"},
    )
    assert name == "Test Company"
    assert exchanged.referer == "example.kommo.com"
    assert exchanged.refresh_token == "new-refresh"
    assert json.loads(seen[0].content)["grant_type"] == "authorization_code"
    assert json.loads(seen[0].content)["code"] == "auth-code"
    refreshed = await spec.bind_refresh({"referer": "example.kommo.com"})("old-refresh")
    assert refreshed.refresh_token == "new-refresh"
    assert refreshed.referer == "example.kommo.com"
    assert json.loads(seen[2].content)["grant_type"] == "refresh_token"
    assert (
        json.loads(seen[2].content)["redirect_uri"]
        == "https://noclick.example/api/auth/kommo/callback"
    )
    assert all(request.url.host == "example.kommo.com" for request in seen)


@pytest.mark.asyncio
async def test_refresh_requires_rotated_token(monkeypatch):
    monkeypatch.setenv("KOMMO_CLIENT_ID", "client")
    monkeypatch.setenv("KOMMO_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KOMMO_REDIRECT_URI", "https://noclick.example/callback")
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "utils.ssrf.guarded_async_client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"access_token": "new-access", "expires_in": 86400}
                )
            ),
            **kwargs,
        ),
    )
    with pytest.raises(ValueError, match="refresh_token"):
        await kommo_oauth.OAUTH_PROVIDER.bind_refresh({"referer": "example.kommo.com"})(
            "old-refresh"
        )


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "a.kommo.com.evil.example",
        "a.kommo.com:443",
        "a.kommo.com@127.0.0.1",
        "127.0.0.1",
        "https://a.kommo.com",
    ],
)
def test_oauth_context_rejects_untrusted_hosts(host):
    with pytest.raises(ValueError):
        kommo_oauth.OAUTH_PROVIDER.validate_context({"referer": host})


@pytest.mark.asyncio
async def test_freshen_passes_context_through_refresh_choke_point(monkeypatch):
    credential = {
        "credential_type": "kommo_oauth",
        "referer": "a.kommo.com",
        "access_token": "old",
        "refresh_token": "old-refresh",
        "expires_at": "2000-01-01T00:00:00Z",
    }

    async def refresh(self, token, *, context=None):
        assert token == "old-refresh"
        assert context == {"referer": credential["referer"]}
        return {
            "access_token": "new",
            "refresh_token": "rotated",
            "referer": "a.kommo.com",
        }

    async def freshen(data, **kwargs):
        assert kwargs["additional_token_fields"] == ("referer",)
        return await kwargs["refresh"](data["refresh_token"])

    monkeypatch.setattr(kommo_oauth.KommoOAuthProviderSpec, "refresh", refresh)
    monkeypatch.setattr("nodes.core.oauth_refresh.freshen_oauth_credential", freshen)
    result = await KommoNode.freshen_credential(credential)
    assert result["referer"] == "a.kommo.com"
    assert result["access_token"] == "new"


EVENTS = json.loads((Path(__file__).parent / "fixtures/kommo/events.json").read_text())


def _form_pairs(value, prefix=""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _form_pairs(child, f"{prefix}[{key}]" if prefix else key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _form_pairs(child, f"{prefix}[{index}]")
    else:
        yield prefix, str(value)


@pytest.mark.parametrize("event_type", EVENTS)
@pytest.mark.parametrize("wire_format", ["json", "form"])
def test_documented_webhooks_reach_agents(event_type, wire_format):
    # Official examples: https://developers.kommo.com/docs/webhooks-general
    body = EVENTS[event_type]["body"]
    payload = (
        {"raw": urlencode(list(_form_pairs(body)))} if wire_format == "form" else body
    )
    config = module.KommoOnEventConfig(event_type=event_type).model_dump()
    assert KommoNode.verify_webhook_signature(b"unsigned", {}, config)
    assert KommoNode.filter_trigger_payload(payload, config)
    output = KommoNode.resolve_trigger_payload(payload, config)
    assert output["data"]["records"]
    event = KommoNode.resolve_agent_event(output)
    assert "Kommo:" in event["text"]
    assert event["conversation_key"]
    assert not KommoNode.filter_trigger_payload({}, config)
    for other in EVENTS:
        if other != event_type:
            assert not KommoNode.filter_trigger_payload(payload, {"event_type": other})


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", EVENTS)
async def test_webhook_registration_and_cleanup_use_destination(
    monkeypatch, event_type
):
    requests = []
    original = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        # Registration only needs successful acknowledgement: the response ID
        # is not used by Kommo's documented delete-by-destination endpoint.
        return httpx.Response(204 if request.method == "DELETE" else 200)

    monkeypatch.setattr(
        module,
        "guarded_async_client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    credential = KommoLongLivedTokenCredential(
        subdomain="example", token="token"
    ).model_dump()
    url = "https://example.test"
    result = await KommoNode._register_external_webhook(
        webhook_url=url,
        credential=credential,
        config={"event_type": event_type},
        node_id="test",
    )
    assert result == {"external_webhook_id": url}
    await KommoNode._unregister_external_webhook(
        credential=credential, config=result, node_id="test"
    )
    assert [r.method for r in requests] == ["POST", "DELETE"]
    assert all(
        str(r.url) == "https://example.kommo.com/api/v4/webhooks" for r in requests
    )
    assert json.loads(requests[0].content) == {
        "destination": url,
        "settings": [event_type],
    }
    assert json.loads(requests[1].content) == {"destination": url}


@pytest.mark.asyncio
async def test_trigger_manual_execution_has_no_event():
    node = KommoNode(
        "test",
        "automation-kommo",
        {},
        config=KommoNodeConfig(
            config=module.KommoOnEventConfig(),
            credentials=KommoLongLivedTokenCredential(
                subdomain="example", token="token"
            ),
        ),
    )
    assert (await node.execute({"unrelated": "data"}))["status"] == "no_event"


@pytest.mark.asyncio
async def test_registration_failure_and_invalid_host_are_not_accepted(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        module,
        "guarded_async_client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(403)), **kwargs
        ),
    )
    credential = KommoLongLivedTokenCredential(
        subdomain="example", token="token"
    ).model_dump()
    with pytest.raises(httpx.HTTPStatusError):
        await KommoNode._register_external_webhook(
            webhook_url="https://example.test",
            credential=credential,
            config={},
            node_id="test",
        )
    credential["subdomain"] = "evil.example"
    with pytest.raises(ValueError):
        await KommoNode._register_external_webhook(
            webhook_url="https://example.test",
            credential=credential,
            config={},
            node_id="test",
        )


def test_updated_lead_without_stage_transition_still_reaches_agent():
    body = json.loads(json.dumps(EVENTS["update_lead"]["body"]))
    body["leads"]["update"][0].pop("old_status_id")
    output = KommoNode.resolve_trigger_payload(body, {"event_type": "update_lead"})
    event = KommoNode.resolve_agent_event(output)
    assert "Previous stage" not in event["text"]
    assert "get_lead" in event["text"]


@pytest.mark.parametrize("event_type", ["add_task", "add_message"])
def test_agent_event_bounds_content_and_preserves_action_ids(event_type):
    body = json.loads(json.dumps(EVENTS[event_type]["body"]))
    record = body["task"]["add"][0] if event_type == "add_task" else body["add"][0]
    record["text"] = "x" * 10000
    output = KommoNode.resolve_trigger_payload(body, {"event_type": event_type})
    event = KommoNode.resolve_agent_event(output)
    assert record["id"] in event["text"]
    assert len(event["text"]) < 2500
    assert "x" * 1501 not in event["text"]
