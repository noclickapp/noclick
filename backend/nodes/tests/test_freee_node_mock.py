"""All Freee operations through the factory and real HTTP boundary."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.freee_node import FreeeNode
from nodes.freee_operations import FREEE_OPERATIONS
from nodes.oauth.freee_oauth import OAUTH_PROVIDER
from nodes.scopes.freee import FREEE_SCOPES

CASES = json.loads((Path(__file__).parent / "fixtures/freee/operations.json").read_text())["cases"]
AUTH = {"credential_type": "freee_oauth", "access_token": "synthetic-freee-token"}


def node(config):
    return NodeFactory.create_node(node_id="freee-test", node_type="automation-freee",
        node_data={"config": config, "credentials": AUTH})


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    async def send(client, request, **kwargs):
        calls.append(request)
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload, request=request)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    return calls, replies


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_freee_operation_request_and_envelope(operation, transport):
    case = CASES[operation]
    calls, replies = transport
    replies.append((200, case["response"]))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    assert request.url.host == "api.freee.co.jp" and request.url.path == case["path"]
    assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
    if case["body"]:
        assert json.loads(request.content) == case["body"]
    for param in FREEE_OPERATIONS[operation]["parameters"]:
        if param["in"] == "query" and param["name"] in case["config"]:
            assert request.url.params[param["name"]] == str(case["config"][param["name"]])
    key = FREEE_OPERATIONS[operation]["response_key"]
    assert result[key] == case["response"][key]


@pytest.mark.asyncio
async def test_freee_pagination_filters(transport):
    transport[1].append((200, {"deals": []}))
    result = await node({"operation": "list_deals", "company_id": 1, "type": "income",
        "status": "unsettled", "limit": 10, "offset": 20}).execute({})
    assert dict(transport[0][0].url.params) == {
        "company_id": "1", "type": "income", "status": "unsettled", "limit": "10", "offset": "20"}
    assert result["items"] == []


@pytest.mark.asyncio
async def test_freee_nullable_clear_and_omission(transport):
    case = CASES["update_partner"]
    transport[1].append((200, case["response"]))
    await node({**case["config"], "org_code": None}).execute({})
    body = json.loads(transport[0][0].content)
    assert body["org_code"] is None and "email" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_freee_error_not_success_or_retried(transport, status):
    transport[1].append((status, {"message": AUTH["access_token"]}))
    result = await node({"operation": "list_companies"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert AUTH["access_token"] not in json.dumps(result) and len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"companies": {}}, {"companies": [], "errors": ["refused"]}])
async def test_freee_bad_envelope_cannot_prove_connection(transport, body):
    transport[1].append((200, body))
    with pytest.raises(ValueError):
        await node({"operation": "list_companies"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_partner", "id": "1/../../users", "company_id": 1},
    {"operation": "list_deals", "company_id": 0},
    {"operation": "list_deals", "company_id": 1, "limit": 101},
    {"operation": "create_tag", "company_id": 1, "name": "x" * 31},
    {"operation": "create_deal", "company_id": 1, "issue_date": "2019-12-17", "type": "income", "details": '[{"amount":1}]'},
    {"operation": "list_companies", "url": "https://foreign.example"},
])
def test_freee_bad_config_fails_before_http(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
async def test_freee_refresh_through_choke_point(monkeypatch):
    import nodes.core.oauth_refresh as refresh
    async def update(**kwargs):
        assert kwargs["provider"] == "freee" and kwargs["caller_path"] == "execute"
        kwargs["credential"].update(access_token="new-token", refresh_token="rotated-token")
    monkeypatch.setattr(refresh, "ensure_fresh_oauth_token", AsyncMock(side_effect=update))
    instance = node({"operation": "list_companies"})
    assert await instance._token(instance.config.credentials) == "new-token"
    assert instance.config.credentials.refresh_token == "rotated-token"
    fresh = AsyncMock(return_value=AUTH)
    monkeypatch.setattr(refresh, "freshen_oauth_credential", fresh)
    assert await FreeeNode.freshen_credential(AUTH, credential_id="row") == AUTH
    assert fresh.call_args.kwargs["credential_id"] == "row"


def test_freee_oauth_and_evidence_contract():
    assert OAUTH_PROVIDER.rotates_refresh_tokens and OAUTH_PROVIDER.name_field == "user.email"
    assert OAUTH_PROVIDER.identity_url == "https://api.freee.co.jp/api/1/users/me"
    assert set(FREEE_SCOPES.declared_scopes()) == {"read", "write"}
    assert FreeeNode.connection_evidence.operation == "list_companies"
    assert set(CASES) == set(FREEE_OPERATIONS)


@pytest.mark.asyncio
async def test_freee_provider_rejection_preserves_documented_message(transport):
    transport[1].append((403, {"errors": [{"type": "status", "messages": ["アクセス権限がありません。"]}]}))
    result = await node({"operation": "list_companies"}).execute({})
    assert result["error"] == "アクセス権限がありません。"
