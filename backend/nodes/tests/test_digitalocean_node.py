"""Request-contract checks for the DigitalOcean node and OAuth flow."""

from __future__ import annotations

import json
import re

import httpx
import pytest

from nodes.digitalocean_node import (
    CONFIG_MODELS,
    OPERATIONS,
    DigitalOceanNode,
    DigitalOceanNodeConfig,
    DigitalOceanOAuthCredential,
    DigitalOceanPersonalAccessTokenCredential,
    _field_name,
    OAUTH_SCOPES,
    DIGITALOCEAN_SCOPES,
)
from nodes.oauth.digitalocean_oauth import OAUTH_PROVIDER, refresh_access_token


def _values(op):
    values = {}
    for prefix, params in (("path", op["path_params"]), ("query", op["query_params"]),
                           ("header", op["header_params"])):
        for param in params:
            if param["required"]:
                values[_field_name(prefix, param["name"])] = "123"
    if op["body_required"]:
        values["body_json"] = json.dumps({key: "test" for key in op["body_required_fields"]})
    return values


def test_oauth_requests_valid_full_api_alias():
    # DigitalOcean documents api:write as covering all API operations.
    assert OAUTH_SCOPES == ["api:write"]
    assert DIGITALOCEAN_SCOPES.declared_scopes() == OAUTH_SCOPES


@pytest.mark.parametrize("name", list(OPERATIONS))
@pytest.mark.asyncio
async def test_every_action_uses_documented_method_path_and_bearer_token(name, monkeypatch):
    op = OPERATIONS[name]
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    real_client = httpx.AsyncClient
    monkeypatch.setattr("nodes.digitalocean_node.httpx.AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(reply)))
    credential = DigitalOceanPersonalAccessTokenCredential(token="secret-test-token")
    result = await DigitalOceanNode._request(credential, name, _values(op))
    assert result["status"] == "success"
    assert result["data"] == {"ok": True}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == op["method"]
    assert request.url.host == "api.digitalocean.com"
    assert request.url.path == re.sub(r"\{[^}]+\}", "123", op["path"])
    assert request.headers["Authorization"] == "Bearer secret-test-token"
    assert CONFIG_MODELS[name](**_values(op)).operation == name


def test_credentials_and_scope_catalog():
    assert len(OPERATIONS) >= 500
    assert "get_account" in OPERATIONS
    assert OPERATIONS["get_account"]["scopes"] == ["account:read"]
    assert DigitalOceanNodeConfig.model_json_schema()["$defs"]["DigitalOceanOAuthCredential"]
    assert DigitalOceanOAuthCredential(access_token="x").credential_type == "digitalocean_oauth"
    assert DigitalOceanPersonalAccessTokenCredential(token="x").credential_type == "digitalocean_pat"


@pytest.mark.asyncio
async def test_oauth_code_exchange_and_refresh(monkeypatch):
    monkeypatch.setenv("DIGITALOCEAN_CLIENT_ID", "client-id")
    monkeypatch.setenv("DIGITALOCEAN_CLIENT_SECRET", "client-secret")
    requests = []

    def reply(request):
        requests.append(request)
        if request.url.path == "/v2/account":
            assert request.headers["Authorization"] == "Bearer first"
            return httpx.Response(200, json={"account": {"email": "sammy@example.com"}})
        assert request.url == "https://cloud.digitalocean.com/v1/oauth/token"
        if b"authorization_code" in request.content:
            assert b"client_secret=client-secret" in request.content
            return httpx.Response(200, json={
                "access_token": "first", "refresh_token": "refresh-1",
                "expires_in": 3600, "scope": "account:read",
                "info": {"name": "Admin", "team_name": "NoClick"},
            })
        assert b"refresh_token=refresh-1" in request.content
        return httpx.Response(200, json={
            "access_token": "second", "refresh_token": "refresh-2", "expires_in": 3600,
        })

    real_client = httpx.AsyncClient
    monkeypatch.setattr("nodes.core.oauth_provider.httpx.AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(reply)))
    first, name = await OAUTH_PROVIDER.exchange("code", "https://noclick.com/api/auth/oauth/digitalocean/callback", code_verifier="v" * 43)
    assert first.access_token == "first"
    second = await refresh_access_token(first.refresh_token)
    assert second.access_token == "second" and second.refresh_token == "refresh-2"
    assert name == "sammy@example.com"
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_path_input_cannot_change_api_host(monkeypatch):
    paths = []

    def reply(request):
        paths.append(str(request.url))
        return httpx.Response(200, json={})

    real_client = httpx.AsyncClient
    monkeypatch.setattr("nodes.digitalocean_node.httpx.AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(reply)))
    await DigitalOceanNode._request(
        DigitalOceanPersonalAccessTokenCredential(token="test"),
        "actions_get", {"path_action_id": "https://evil.example/../../"},
    )
    assert paths[0].startswith("https://api.digitalocean.com/v2/actions/")
    assert "evil.example" not in httpx.URL(paths[0]).host


@pytest.mark.asyncio
async def test_array_query_uses_repeated_parameters(monkeypatch):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={})

    real_client = httpx.AsyncClient
    monkeypatch.setattr("nodes.digitalocean_node.httpx.AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(reply)))
    op = OPERATIONS["apps_list_events"]
    values = _values(op)
    values["query_event_types"] = '["build", "deploy"]'
    await DigitalOceanNode._request(
        DigitalOceanPersonalAccessTokenCredential(token="test"),
        "apps_list_events", values,
    )
    assert requests[0].url.params.get_list("event_types") == ["build", "deploy"]


@pytest.mark.asyncio
async def test_alert_poll_uses_documented_payload_and_suppresses_seen_items(monkeypatch):
    from pathlib import Path

    payload = json.loads((Path(__file__).parent / "fixtures/digitalocean/alert_instances.json").read_text())
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    real_client = httpx.AsyncClient
    monkeypatch.setattr("nodes.digitalocean_node.httpx.AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(reply)))
    node = DigitalOceanNode("test-node", "automation-digitalocean", {})
    node._config = DigitalOceanNodeConfig.model_validate({
        "config": {"operation": "on_new_alert", "resource_urn": "do:droplet:12345"},
        "credentials": {"credential_type": "digitalocean_pat", "token": "test"},
    })
    state = {"seen_ids": []}

    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    node._update_node_state = update
    result = await node.execute({})
    assert result["alert_instances"] == payload["alert_instances"]
    assert result["new_alert_count"] == 1
    event = node.resolve_agent_event(result)
    assert "do:droplet:12345" in event["text"]
    assert "87.5" in event["text"]
    assert payload["alert_instances"][0]["rule_id"] in event["text"]
    assert requests[0].url.path == "/v2/insights/alert-instances"
    assert requests[0].url.params["resource_urn"] == "do:droplet:12345"
    again = await node.execute({})
    assert again["new_alert_count"] == 0
    assert node.resolve_agent_event(again) is None
    assert not node.should_propagate_output(again, {"operation": "on_new_alert"})


@pytest.mark.asyncio
async def test_uptime_create_accepts_provider_documented_request(monkeypatch):
    from pathlib import Path

    body = json.loads((Path(__file__).parent / "fixtures/digitalocean/uptime_create_check.json").read_text())
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(201, json={})

    real_client = httpx.AsyncClient
    monkeypatch.setattr("nodes.digitalocean_node.httpx.AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(reply)))
    await DigitalOceanNode._request(
        DigitalOceanPersonalAccessTokenCredential(token="test"),
        "uptime_create_check", {"body_json": json.dumps(body)},
    )
    assert json.loads(requests[0].content) == body
    assert "method" not in body
