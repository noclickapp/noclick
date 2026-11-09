"""Newie HTTP boundary and public OAuth protocol checks; no live credentials.

Request facts: https://api.newie.app/openapi.json (0.1.0).
Metadata examples: https://api.newie.app/docs/guides/resources.md#your-own-metadata
Report dates: https://api.newie.app/docs/guides/reports.md
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import newie_node as native
from nodes.core.registry import NodeFactory
from nodes.oauth.newie_oauth import OAUTH_PROVIDER

TOKEN = "synthetic-newie-token"
CASES = json.loads((Path(__file__).parent / "fixtures/newie/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credentials):
    return NodeFactory.create_node(
        node_id="newie-test",
        node_type="automation-newie",
        node_data={
            "config": config,
            "credentials": {
                "credential_type": "newie_oauth",
                "access_token": TOKEN,
                **credentials,
            },
        },
    )


def transport(monkeypatch, response):
    requests = []

    def respond(request):
        requests.append(request)
        return response

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_newie_documented_request_contract(monkeypatch, case):
    operation = case["config"]["operation"]
    kind = native.EXPECTED_OBJECT[operation]
    payload = {"object": kind, "id": "abc123", "futureField": {"nullable": None}}
    if kind == "list":
        payload.update(
            data=[{"id": "abc123", "metadata": {}}],
            page={"limit": 25, "nextCursor": "opaque-next"},
        )
    requests = transport(
        monkeypatch,
        httpx.Response(200, json=payload, headers={"Newie-Request-ID": "req-123"}),
    )
    result = await node(case["config"]).execute({})
    assert result == {
        "status": "success",
        "operation": operation,
        "http_status": 200,
        "data": payload,
        "request_id": "req-123",
    }
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.newie.app"
    assert request.url.path == case["path"]
    assert {
        key: request.url.params.get_list(key) for key in request.url.params
    } == case["query"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN


@pytest.mark.asyncio
async def test_newie_repeat_filters_and_preserve_pagination(monkeypatch):
    payload = {"object": "list", "data": [], "page": {"limit": 50, "nextCursor": None}}
    requests = transport(monkeypatch, httpx.Response(200, json=payload))
    result = await node(
        {
            "operation": "list_subscriptions",
            "page_limit": 50,
            "page_after": "opaque&next",
            "status_filter": ["active", "pastDue"],
            "offering_id_filter": ["STUDIO_MONTHLY"],
        }
    ).execute({})
    assert result["data"] == payload
    assert requests[0].url.params.get_list("filter[status]") == ["active", "pastDue"]
    assert requests[0].url.params["page[after]"] == "opaque&next"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [400, 401, 403, 404, 409, 429, 503])
async def test_newie_problem_details_remain_failures_and_redact_secrets(
    monkeypatch, code
):
    problem = {"type": "about:blank", "code": "rejected", "detail": "Rejected " + TOKEN}
    transport(
        monkeypatch,
        httpx.Response(
            code,
            json=problem,
            headers={
                "content-type": "application/problem+json",
                "Retry-After": "30",
                "Newie-Request-ID": "req-err",
            },
        ),
    )
    result = await node({"operation": "get_organization"}).execute({})
    assert result["status"] == "error"
    assert result["http_status"] == code
    assert result["error"] == "Rejected [redacted]"
    assert result["problem"]["code"] == "rejected"
    assert result["retry_after"] == "30"
    assert result["request_id"] == "req-err"
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "https://other.example"}),
        httpx.Response(200, text="<html>wrong host</html>"),
        httpx.Response(
            200, content=b"bad", headers={"content-type": "application/json"}
        ),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"object": "list", "data": []}),
        httpx.Response(200, json={"object": "customer"}),
    ],
)
async def test_newie_malformed_success_cannot_prove_connection(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "list_customers"}).execute({})


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_customer", "customer_id": "https://example.com"},
        {"operation": "get_payment", "payment_id": "cus_wrong"},
        {"operation": "get_payout", "payout_id": "../other"},
        {"operation": "list_customers", "page_limit": 101},
        {
            "operation": "update_customer",
            "customer_id": "cus_example",
            "metadata": {"a" * 41: "x"},
        },
        {
            "operation": "get_payments_report",
            "period_start": "2026-10-31T13:00:00Z",
            "period_end": "2026-08-31T14:00:00Z",
        },
        {
            "operation": "get_payments_report",
            "period_start": "2026-99-31T13:00:00Z",
            "period_end": "2026-10-31T13:00:00Z",
        },
    ],
)
def test_newie_invalid_inputs_refused(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_newie_manual_credential_has_default_type_and_no_hidden_required_fields():
    credential = native.NewieOAuthCredential(access_token=TOKEN)
    assert credential.credential_type == "newie_oauth"
    assert not native.NewieOAuthCredential.model_fields["credential_type"].is_required()


def test_newie_oauth_is_public_pkce_and_resource_bound(monkeypatch):
    monkeypatch.setenv("NEWIE_CLIENT_ID", "public-newie-client")
    monkeypatch.delenv("NEWIE_CLIENT_SECRET", raising=False)
    assert OAUTH_PROVIDER.pkce and OAUTH_PROVIDER.rotates_refresh_tokens
    assert OAUTH_PROVIDER.authorize_params == {"resource": "https://api.newie.app"}
    for grant in [
        {
            "grant_type": "authorization_code",
            "code": "fake",
            "code_verifier": "fake-verifier",
        },
        {"grant_type": "refresh_token", "refresh_token": "fake-refresh"},
    ]:
        request = OAUTH_PROVIDER.token_request(grant)
        assert request["data"]["resource"] == "https://api.newie.app"
        assert request["data"]["client_id"] == "public-newie-client"
        assert "client_secret" not in request["data"]
        assert request["auth"] is None
    assert {"openid", "profile", "offline_access"} <= set(
        native.NEWIE_SCOPES.declared_scopes()
    )


@pytest.mark.asyncio
async def test_newie_refresh_uses_rotation_choke_point(monkeypatch):
    async def fresh(**kwargs):
        assert kwargs["provider"] == "newie"
        kwargs["credential"].update(
            access_token="fresh-token", refresh_token="rotated-refresh"
        )
        return "fresh-token"

    monkeypatch.setattr("nodes.core.oauth_refresh.ensure_fresh_oauth_token", fresh)
    requests = transport(
        monkeypatch,
        httpx.Response(200, json={"object": "organization", "id": "org_123"}),
    )
    instance = node(
        {"operation": "get_organization"}, refresh_token="synthetic-refresh"
    )
    await instance.execute({})
    assert requests[0].headers["Authorization"] == "Bearer fresh-token"
    assert instance.config.credentials.refresh_token == "rotated-refresh"


@pytest.mark.asyncio
async def test_newie_freshen_uses_shared_store_seam(monkeypatch):
    probe = AsyncMock(return_value={"access_token": "new-token"})
    monkeypatch.setattr("nodes.core.oauth_refresh.freshen_oauth_credential", probe)
    await native.NewieNode.freshen_credential(
        {"access_token": TOKEN, "refresh_token": "synthetic-refresh"},
        user_id="user",
        credential_id="credential",
    )
    assert probe.await_args.kwargs["provider"] == "newie"
    assert probe.await_args.kwargs["credential_id"] == "credential"
