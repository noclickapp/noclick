"""Sellsy requests through the factory and real httpx serialization, offline."""
import json
from pathlib import Path
from unittest.mock import Mock
from contextlib import asynccontextmanager

import httpx
import pytest

from nodes import sellsy_node as sellsy
from nodes.core.registry import NodeFactory
from nodes.oauth.sellsy_oauth import OAUTH_PROVIDER

CASES = json.loads((Path(__file__).parent / "fixtures/sellsy/requests.json").read_text())
AUTH = {"credential_type": "sellsy_oauth", "access_token": "test-access", "refresh_token": "test-refresh",
        "expires_at": "2099-01-01T00:00:00+00:00"}
CLIENT = httpx.AsyncClient


def node(operation, config=None, auth=None):
    return NodeFactory.create_node(node_id="sellsy-test", node_type="automation-sellsy",
        node_data={"config": {"operation": operation, **(config or {})}, "credentials": auth or AUTH},
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user")


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    def handle(request):
        requests.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        async with CLIENT(transport=httpx.MockTransport(handle), **kwargs) as session:
            yield session
    monkeypatch.setattr(sellsy, "guarded_async_client", client)
    return requests, replies


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_documented_requests_and_preserved_results(transport, case):
    requests, replies = transport
    listing = case["operation"].startswith("list_")
    result = {"pagination": {"limit":25,"total":152,"count":25,"offset":"opaque-next"},
              "data": [{"id":6657,"name":"Example company"}]} if listing else {"id":6657,"email":"john@example-company.com"}
    replies.append((201 if case["method"] == "POST" else 200, result))
    response = await node(case["operation"], case["config"]).execute({})
    assert response["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url).split("?")[0] == sellsy.BASE + case["path"]
    assert request.headers["Authorization"] == "Bearer test-access"
    if listing:
        assert request.url.params["offset"] == "WzIwMTQtMDEtMDEsNTk4XQ=="
        assert response["pagination"] == result["pagination"]
        assert response["data"] == result["data"]
    else:
        assert response["data"] == result
        if case["body"] is not None:
            assert json.loads(request.content) == case["body"]
    assert len(replies) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("name,operation", [("Get Company","get_company"), ("Get contact","get_contact"),
    ("Get Individual","get_individual"), ("Get Opportunity","get_opportunity")])
async def test_provider_authored_postman_responses_preserved(transport, name, operation):
    samples = json.loads((Path(__file__).parent / "fixtures/sellsy/documented_responses.json").read_text())
    body = samples[name]["body"]
    transport[1].append((200,body))
    result = await node(operation,{"id":body["id"]}).execute({})
    assert result["status"] == "success"
    assert result["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401,{"error":"test-access"}), (429,{"message":"rate limited"}), (302,{"message":"redirect"})])
async def test_provider_failure_cannot_pass_or_leak_tokens(transport, status, body):
    transport[1].append((status, body))
    response = await node("get_me").execute({})
    assert response["status"] == "error"
    assert response["status_code"] == status
    assert "test-access" not in json.dumps(response)


@pytest.mark.asyncio
async def test_documented_error_envelope_preserves_rejection(transport):
    transport[1].append((403, {"error": {"code":403,"message":"Insufficient privileges","context":"permission"}}))
    response = await node("get_me").execute({})
    assert response["error"] == "Insufficient privileges"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"error":"no"}, {"data":[]}, {"pagination":{},"data":{}}])
async def test_bad_page_refused(transport, body):
    transport[1].append((200,body))
    assert (await node("list_contacts").execute({}))["status"] == "error"


@pytest.mark.parametrize("config", [{"operation":"get_contact","id":"../staffs/me"},
    {"operation":"create_company","name":"Example company"},
    {"operation":"create_contact","email":"john.doe@example-company.com"},
    {"operation":"update_contact","id":6657},
    {"operation":"create_opportunity","name":"New website","pipeline":9763,"step":299},
    {"operation":"get_me","url":"https://example.com"},
    {"operation":"create_contact","last_name":"Doe","email":"bad email"},
    {"operation":"create_opportunity","name":"New website","pipeline":9763,"step":299,"related":[{"id":1,"type":"contact"}]}])
def test_invalid_input_never_sends_a_request(config):
    with pytest.raises(ValueError):
        sellsy.SellsyNode.parse_config({"config":config,"credentials":AUTH})


@pytest.mark.asyncio
async def test_refresh_uses_shared_hook_and_adopts_rotating_token(transport, monkeypatch):
    import nodes.core.oauth_refresh as shared
    seen = []
    async def freshen(**kwargs):
        seen.append(kwargs)
        kwargs["credential"].update(access_token="renewed-access", refresh_token="renewed-refresh")
    monkeypatch.setattr(shared,"ensure_fresh_oauth_token",freshen)
    transport[1].append((200,{"id":6657,"email":"john@example-company.com"}))
    n=node("get_me")
    await n.execute({})
    assert seen[0]["provider"] == "sellsy"
    assert seen[0]["refresh"] == OAUTH_PROVIDER.refresh
    assert transport[0][0].headers["Authorization"] == "Bearer renewed-access"
    assert n.config.credentials.refresh_token == "renewed-refresh"


def test_oauth_pkce_identity_json_and_exact_scopes():
    assert OAUTH_PROVIDER.pkce and OAUTH_PROVIDER.rotates_refresh_tokens
    assert OAUTH_PROVIDER.identity_url == sellsy.BASE + "/staffs/me"
    assert OAUTH_PROVIDER.name_field == "email"
    assert OAUTH_PROVIDER.token_format == "json"
    assert sellsy.SellsyOAuthCredential.model_fields["credential_type"].default == "sellsy_oauth"
    assert set(sellsy.OPERATIONS) == sellsy.SELLSY_SCOPES.keys_declared
    assert frozenset(sellsy.SELLSY_SCOPES.declared_scopes()) == frozenset({"companies.read","companies.write","contacts.read","contacts.write",
        "individuals.read","individuals.write","opportunities.read","opportunities.write","staffs.read"})


@pytest.mark.parametrize("tag", ["google_oauth", "", None, 42])
def test_foreign_credential_family_refused_before_reconciliation(tag):
    data = {"config":{"operation":"get_me"},"credentials":{**AUTH,"credential_type":tag}}
    with pytest.raises(ValueError, match="Sellsy account"):
        sellsy.SellsyNode.parse_config(data)
    assert sellsy.SellsyNode.validate_config(data)["valid"] is False


@pytest.mark.asyncio
async def test_no_content_write_acknowledgment(transport):
    transport[1].append((204,None))
    result=await node("update_company",{"id":6657,"name":"Example company"}).execute({})
    assert result == {"status":"success","status_code":204,"data":None}
