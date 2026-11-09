"""Request and response regressions for the Vercel AI Gateway management API."""
from contextlib import asynccontextmanager
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import vercel_ai_gateway_node as gateway

TOKEN = "vercel-management-test-token"


def node(config, **credential):
    full = gateway.VercelAiGatewayConfig.model_validate({"config": config, "credentials": {"access_token": TOKEN, **credential}})
    return gateway.VercelAiGatewayNode("test", gateway.VercelAiGatewayNode.integration_type, {}, config=full)


def mock_client(monkeypatch, body=None, status=200):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as session:
            yield session

    monkeypatch.setattr(gateway, "guarded_async_client", client)
    return calls


CASES = [
    ({"operation": "list_byok_credentials", "providerSlug": "openai"}, "GET", "/ai-gateway/byok-credentials/list", 200),
    ({"operation": "get_byok_credential", "credentialId": "cred_123"}, "GET", "/ai-gateway/byok-credentials/cred_123", 200),
    ({"operation": "update_byok_credential", "credentialId": "cred_123", "active": False}, "PATCH", "/ai-gateway/byok-credentials/cred_123", 200),
    ({"operation": "delete_byok_credential", "credentialId": "cred_123"}, "DELETE", "/ai-gateway/byok-credentials/cred_123", 204),
    ({"operation": "list_virtual_model_configs", "cursor": "opaque/+="}, "GET", "/ai-gateway/virtual-model-configs/list", 200),
    ({"operation": "get_virtual_model_config", "vmcSlug": "my-router"}, "GET", "/ai-gateway/virtual-model-configs/my-router", 200),
    ({"operation": "delete_virtual_model_config", "vmcSlug": "my-router"}, "DELETE", "/ai-gateway/virtual-model-configs/my-router", 204),
    ({"operation": "list_routers"}, "GET", "/v1/ai-gateway/routers", 200),
    ({"operation": "list_rules", "cursor": "page-two", "includeDisabled": "true"}, "GET", "/ai-gateway/rules", 200),
    ({"operation": "delete_rule", "ruleId": "rule_123"}, "DELETE", "/ai-gateway/rules", 204),
    ({"operation": "list_budgets", "scopeType": "api-key", "limit": 50}, "GET", "/ai-gateway/budgets/list", 200),
    ({"operation": "upsert_budget", "scopeType": "project", "projectId": "prj_123", "limitAmount": 25, "includeByokInQuota": False, "alertThresholds": [50, 100]}, "PUT", "/ai-gateway/budgets", 200),
    ({"operation": "archive_budget", "scopeType": "user", "userId": "usr_123", "justification": "Retire user budget"}, "DELETE", "/ai-gateway/budgets", 200),
    ({"operation": "list_budget_defaults"}, "GET", "/ai-gateway/budgets/defaults/list", 200),
    ({"operation": "upsert_budget_default", "scopeType": "api-key", "limitAmount": 10}, "PUT", "/ai-gateway/budgets/defaults", 200),
    ({"operation": "archive_budget_default", "scopeType": "project"}, "DELETE", "/ai-gateway/budgets/defaults", 204),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,status", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_vercel_ai_gateway_single_request(monkeypatch, config, method, path, status):
    response = {"nextCursor": "next/+==", "budgets": [], "virtualModelConfigs": [], "routers": [], "rules": [], "defaults": [], "credentials": [{"name": "Production", "credential": "never-output"}]}
    calls = mock_client(monkeypatch, response, status)
    result = await node(config, team_id="team_123").execute({})
    assert len(calls) == 1
    req = calls[0]
    assert req.method == method
    assert req.url.host == "api.vercel.com"
    assert req.url.path == path
    assert req.headers["authorization"] == "Bearer " + TOKEN
    assert req.url.params["teamId"] == "team_123"
    values = node(config).config.config.model_dump(exclude_none=True, exclude={"operation", "credentialId", "vmcSlug", "teamId"})
    if method in {"PUT", "PATCH"}:
        assert json.loads(req.content) == values
        assert set(req.url.params) == {"teamId"}
    else:
        assert not req.content
        assert dict(req.url.params) == {"teamId": "team_123", **{k: str(v) for k, v in values.items()}}
    if status == 204:
        assert result["success"] is True
    else:
        assert result["nextCursor"] == "next/+=="
        assert "never-output" not in json.dumps(result)
        assert result["credentials"][0]["name"] == "Production"


@pytest.mark.asyncio
async def test_vercel_ai_gateway_explicit_team_and_encoded_id(monkeypatch):
    calls = mock_client(monkeypatch, {"credentialId": "a/b?c"})
    await node({"operation": "get_byok_credential", "credentialId": "a/b?c", "teamId": "team_other"}, team_id="team_default").execute({})
    assert calls[0].url.raw_path == b"/ai-gateway/byok-credentials/a%2Fb%3Fc?teamId=team_other"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_vercel_ai_gateway_rejection_is_not_success(monkeypatch, status):
    calls = mock_client(monkeypatch, {"error": {"message": "Access denied " + TOKEN}}, status)
    with pytest.raises(ValueError, match=f"HTTP {status}: Access denied ") as exc:
        await node({"operation": "list_byok_credentials"}).execute({})
    assert TOKEN not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.parametrize("config", [
    {"operation": "upsert_budget", "scopeType": "project", "limitAmount": 5},
    {"operation": "archive_budget", "scopeType": "user"},
    {"operation": "archive_budget", "scopeType": "team", "projectId": "prj_123"},
    {"operation": "upsert_budget_default", "scopeType": "team", "limitAmount": 0},
    {"operation": "upsert_budget_default", "scopeType": "team", "limitAmount": float("inf")},
    {"operation": "update_byok_credential", "credentialId": "cred_123"},
    {"operation": "list_rules", "limit": 201},
])
def test_vercel_ai_gateway_invalid_inputs(config):
    with pytest.raises(ValidationError):
        node(config)


def test_vercel_ai_gateway_manual_credential_and_evidence():
    credential = gateway.VercelAiGatewayTokenCredential(access_token=TOKEN)
    assert credential.credential_type == "vercel_ai_gateway_token"
    assert gateway.VercelAiGatewayNode.connection_evidence.operation == "list_byok_credentials"
    assert node({"operation": "list_byok_credentials"}).config.config.operation == "list_byok_credentials"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"credentials": {}}, {"error": {"message": "rejected"}}])
async def test_vercel_ai_gateway_evidence_rejects_unexpected_response(monkeypatch, body):
    mock_client(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_byok_credentials"}).execute({})
