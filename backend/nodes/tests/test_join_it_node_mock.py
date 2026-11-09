"""Exercise Join It wire contracts through the production operation runner."""
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import join_it_node as ji
from nodes.core.run_op import run_node_operation
from nodes.oauth.join_it_oauth import OAUTH_PROVIDER
from utils import ssrf

AUTH = {"credential_type": "join_it_oauth", "access_token": "synthetic-join-it-token"}
MEMBER = {"_id": "7GhtrPqzNlmXa4tB9", "email": "emily.johnson@example.com", "status": 100}
CASES = [
    ("list_memberships", {"status": "50,75,100", "membership_type_ids": "type1,type2", "external_id": "invoice-1", "page": 2, "count": 100}, "GET", "/memberships", {"status": "50,75,100", "membership_type_ids": "type1,type2", "external_id": "invoice-1", "page": "2", "count": "100"}, None, [MEMBER]),
    ("get_membership", {"membership_id": MEMBER["_id"]}, "GET", "/memberships", {"_id": MEMBER["_id"]}, None, [MEMBER]),
    ("find_memberships_by_email", {"email": MEMBER["email"]}, "GET", "/memberships", {"email": MEMBER["email"], "page": "1", "count": "50"}, None, [MEMBER]),
    ("create_membership", {"email": MEMBER["email"], "membership_type_id": "type1", "first_name": "Emily", "last_name": "Johnson"}, "POST", "/memberships", {"email": MEMBER["email"], "membership_type_id": "type1", "first_name": "Emily", "last_name": "Johnson"}, None, MEMBER),
    ("list_internal_memberships", {"membership_id": MEMBER["_id"]}, "GET", "/memberships_internal", {"_id": MEMBER["_id"]}, None, [{"_id": MEMBER["_id"], "notes": "admin-only"}]),
    ("list_payments", {"payment_date_start": "2025-01-01", "payment_date_end": "2025-12-31"}, "GET", "/payments", {"payment_date_start": "2025-01-01", "payment_date_end": "2025-12-31", "page": "1", "count": "50"}, None, []),
    ("record_payment", {"email": MEMBER["email"], "amount": 100}, "POST", "/payments", {}, {"email": MEMBER["email"], "amount": 100}, {"_id": "payment1"}),
    ("list_membership_types", {}, "GET", "/membership_types", {}, None, [{"_id": "type1", "membership_name": "Gold"}]),
    ("get_organization", {}, "GET", "/details", {}, None, {"_id": "tw9TwuiDRB4dSGczp", "name": "Demo Organization"}),
    ("verify_membership", {"email": MEMBER["email"]}, "GET", "/verify_membership", {"email": MEMBER["email"], "send_internal_email_when_verification_failed": "false"}, None, {"verified": True, "memberships": [MEMBER]}),
]


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        return replies.pop(0)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(ji, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, config=None, auth=AUTH):
    return await run_node_operation(node_type="automation-join-it", operation=operation,
        arguments=config or {}, credential_data=deepcopy(auth), user_id="test-user")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,query,body,response", CASES)
async def test_join_it_wire_contract(wire, operation, config, method, path, query, body, response):
    wire[1].append(httpx.Response(200, json=response))
    result = await run(operation, config)
    assert result["data"] == response
    assert len(wire[0]) == 1
    request = wire[0][0]
    assert request.method == method
    assert str(request.url).startswith(ji.BASE_URL + path)
    assert request.url.path == "/api/v1/organizations/me" + path
    assert dict(request.url.params) == query
    assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
    assert AUTH["access_token"] not in str(request.url)
    assert (json.loads(request.content) if request.content else None) == body
    if method == "POST":
        assert result["write_acknowledged"] and not result["readback_verified"]


@pytest.mark.asyncio
async def test_join_it_verification_not_found_is_a_negative_result(wire):
    reply = {"verified": False, "message": "No membership found matching the specified criteria"}
    wire[1].append(httpx.Response(404, json=reply))
    assert (await run("verify_membership", {"email": MEMBER["email"]}))["data"] == reply
    assert wire[0][0].url.params["send_internal_email_when_verification_failed"] == "false"


@pytest.mark.asyncio
async def test_join_it_email_opt_in_and_filters(wire):
    wire[1].append(httpx.Response(200, json={"verified": True}))
    await run("verify_membership", {"email": MEMBER["email"], "status": "50,75,100", "membership_type_ids": "type1", "send_internal_email_when_verification_failed": True})
    assert dict(wire[0][0].url.params) == {"email": MEMBER["email"], "status": "50,75,100", "membership_type_ids": "type1", "send_internal_email_when_verification_failed": "true"}


@pytest.mark.asyncio
async def test_join_it_pagination_never_fetches_a_second_page(wire):
    wire[1].append(httpx.Response(200, json=[MEMBER]))
    result = await run("list_memberships", {"count": 1, "page": 3})
    assert result["pagination"] == {"page": 3, "count": 1, "next_page": 4}
    assert len(wire[0]) == 1


@pytest.mark.asyncio
async def test_join_it_empty_payment_ack(wire):
    wire[1].append(httpx.Response(200, content=b""))
    assert (await run("record_payment", {"email": MEMBER["email"], "amount": 100}))["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config", [
    ("verify_membership", {}), ("create_membership", {"email": "bad"}),
    ("record_payment", {"email": MEMBER["email"], "amount": 0}),
    ("record_payment", {"email": MEMBER["email"], "amount": True}),
    ("get_membership", {}), ("list_memberships", {"page": 0}),
    ("list_memberships", {"count": 1001}),
    ("list_payments", {"payment_date_start": "2025-12-31", "payment_date_end": "2025-01-01"}),
])
async def test_join_it_invalid_config_does_not_send(wire, operation, config):
    with pytest.raises(ValueError): await run(operation, config)
    assert wire[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    httpx.Response(302, headers={"Location": "https://example.org"}),
    httpx.Response(401, json={"message": "Denied " + AUTH["access_token"]}),
    httpx.Response(429, json={"message": "Rate limited"}),
    httpx.Response(500, text="Server error"),
    httpx.Response(200, json={"error": "Rejected"}),
    httpx.Response(200, json={"errors": ["Rejected"]}),
    httpx.Response(200, json={"success": False}),
    httpx.Response(200, json={}),
    httpx.Response(200, text="<html>Log in</html>"),
])
async def test_join_it_errors_never_leak_token_or_retry(wire, reply):
    wire[1].append(reply)
    with pytest.raises(ValueError) as error: await run("get_organization")
    assert AUTH["access_token"] not in str(error.value)
    assert len(wire[0]) == 1


@pytest.mark.asyncio
async def test_join_it_response_token_is_redacted(wire):
    wire[1].append(httpx.Response(200, json={"name": AUTH["access_token"]}))
    assert AUTH["access_token"] not in str(await run("get_organization"))


def test_join_it_oauth_contract_and_manual_credential():
    assert ji.JoinItOAuthCredential.model_validate({"access_token": AUTH["access_token"]}).credential_type == "join_it_oauth"
    assert OAUTH_PROVIDER.authorize_url == "https://app.joinit.com/oauth2/authorize"
    assert OAUTH_PROVIDER.token_url == "https://app.joinitapi.com/oauth2/token"
    assert OAUTH_PROVIDER.identity_url == ji.BASE_URL + "/details"
    assert OAUTH_PROVIDER.name_field == "name"
    assert OAUTH_PROVIDER.token_auth == "body" and not OAUTH_PROVIDER.pkce
    assert ji.JOIN_IT_SCOPES.declared_scopes() == []
    assert set(ji.JOIN_IT_SCOPES) == {case[0] for case in CASES}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", [("list_memberships", "memberships"), ("list_membership_types", "membership_types"), ("list_payments", "payments"), ("get_organization", "details")])
async def test_join_it_provider_published_responses(wire, operation, path):
    from pathlib import Path
    examples = json.loads((Path(__file__).parent / "fixtures/join-it/documented_responses.json").read_text())
    body = examples["GET /v1/organizations/me/" + path]["body"]
    wire[1].append(httpx.Response(200, json=body))
    assert (await run(operation))["data"] == body


@pytest.mark.asyncio
async def test_join_it_connection_evidence_names_the_organization(wire):
    from nodes.core.connection_evidence import collect_evidence
    wire[1].append(httpx.Response(200, json={"_id": "tw9TwuiDRB4dSGczp", "name": "Demo Organization"}))
    result = await collect_evidence(node_type="automation-join-it", credential_data=AUTH, user_id="test-user")
    assert result.reachable is True
    assert result.account_label == "Demo Organization"
    assert len(wire[0]) == 1
    assert wire[0][0].url.path.endswith("/details")


def test_join_it_exchange_sends_form_credentials(monkeypatch):
    monkeypatch.setenv("JOIN_IT_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("JOIN_IT_CLIENT_SECRET", "synthetic-secret")
    request = OAUTH_PROVIDER.token_request({"grant_type": "authorization_code", "code": "synthetic-code", "redirect_uri": "https://example.org/callback"})
    assert request["url"] == "https://app.joinitapi.com/oauth2/token"
    assert request["data"] == {"grant_type": "authorization_code", "code": "synthetic-code", "redirect_uri": "https://example.org/callback", "client_id": "synthetic-client", "client_secret": "synthetic-secret"}
    assert request["auth"] is None
