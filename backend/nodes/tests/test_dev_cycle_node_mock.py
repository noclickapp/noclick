"""Offline DevCycle request, response, failure and manual credential contracts."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import dev_cycle_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-management-token-42"
CASES = json.loads((Path(__file__).parent / "fixtures/dev-cycle/requests.json").read_text())["cases"]


def credential():
    return {"credential_type": native.CREDENTIAL, "access_token": TOKEN}


def node(config):
    return NodeFactory.create_node(node_id="dev-cycle-fixture", node_type="automation-dev-cycle",
                                   node_data={"config": config, "credentials": credential()})


def transport(monkeypatch, body, status=200, raw=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if raw is None else httpx.Response(status, content=raw)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_dev_cycle_exact_contract_requests(monkeypatch, case):
    op = case["config"]["operation"]
    body = [{"_id": "61450f3daec96f5cf4a49946", "name": "Delivery App", "key": "delivery-app"}] if op.startswith("list_") else {"key": "show-new-dashboard", "type": "Boolean", "status": "active"}
    requests = transport(monkeypatch, body, 201 if case["method"] == "POST" else 200,
                         raw=b"" if case["method"] == "DELETE" else None)
    result = await node(case["config"]).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url.copy_with(query=None)) == native.BASE + case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert result["status"] == "success"
    if op.startswith("list_"):
        assert result["items"] == body and result["page"] == 2 and result["per_page"] == 10
    elif case["method"] == "DELETE":
        assert result["deleted"] is True
    else:
        assert result["data"] == body


@pytest.mark.asyncio
async def test_dev_cycle_false_query_and_no_redirects(monkeypatch):
    requests = transport(monkeypatch, [])
    await node({"operation": "list_features", "project": "delivery-app", "includeLatestUpdate": False}).execute({})
    assert requests[0].url.params["includeLatestUpdate"] == "false"
    requests = transport(monkeypatch, {}, 302)
    with pytest.raises(native._ProviderError, match="302"):
        await node({"operation": "list_projects"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,valid", [(401, False), (403, False), (429, None), (500, None)])
async def test_dev_cycle_manual_access_rejections(monkeypatch, status, valid):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await native.DevCycleNode.validate_credential_access(credential())
    assert result["valid"] is valid and TOKEN not in str(result)
    assert len(requests) == 1 and requests[0].url.path == "/v1/projects"


@pytest.mark.asyncio
@pytest.mark.parametrize("body,raw", [({}, None), ([], b"<html>error</html>"), ({"error": "not allowed"}, None)])
async def test_dev_cycle_connection_malformed_is_unverified(monkeypatch, body, raw):
    transport(monkeypatch, body, raw=raw)
    assert (await native.DevCycleNode.validate_credential_access(credential()))["valid"] is None


@pytest.mark.asyncio
async def test_dev_cycle_connect_without_type_and_recognizable_evidence(monkeypatch):
    from nodes.core.credential_connect import shape_credential
    shaped, errors, resolved = shape_credential(native.CREDENTIAL, {"access_token": TOKEN})
    assert not errors and resolved[1] is native.DevCycleAccessToken
    assert native.DevCycleAccessToken.model_validate(shaped).credential_type == native.CREDENTIAL
    rows = [{"_id": "61450f3daec96f5cf4a49946", "key": "delivery-app", "name": "Delivery App"}]
    transport(monkeypatch, rows)
    assert (await native.DevCycleNode.validate_credential_access(shaped))["valid"] is True
    assert native.DevCycleNode.connection_evidence.operation == "list_projects"
    assert (await node({"operation": "list_projects"}).execute({}))["items"] == rows


@pytest.mark.parametrize("config", [
    {"operation": "get_project", "project": "../bad"},
    {"operation": "get_project", "project": ".."},
    {"operation": "get_project", "project": "https://evil.test"},
    {"operation": "get_project", "project": "bad?x=1"},
    {"operation": "list_projects", "page": 0},
    {"operation": "list_projects", "perPage": 1001},
    {"operation": "list_projects", "search": "ab"},
    {"operation": "create_project", "key": "UPPER", "name": "Delivery"},
    {"operation": "create_environment", "project": "delivery-app", "key": "test", "name": "Test"},
    {"operation": "update_feature_status", "project": "delivery-app", "feature": "new-dash", "status": "inactive"},
    {"operation": "create_feature", "project": "delivery-app", "key": "new-dash", "name": "Dashboard", "configurations": {}},
    {"operation": "get_project", "project": "delivery-app", "unknown": True},
])
def test_dev_cycle_invalid_config(config):
    assert native.DevCycleNode.validate_config({"config": config, "credentials": credential()})["valid"] is False


@pytest.mark.asyncio
async def test_dev_cycle_empty_patch_fails_before_network(monkeypatch):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_variable", "project": "delivery-app", "variable": "show-new-dashboard"}).execute({})
    assert not requests


@pytest.mark.parametrize("token", ["Bearer secret", "https://bad.test/key", "a\nb", "<token>", ""])
def test_dev_cycle_rejects_bad_secrets(token):
    with pytest.raises(ValidationError):
        native.DevCycleAccessToken(access_token=token)


@pytest.mark.asyncio
async def test_dev_cycle_nested_secret_redaction(monkeypatch):
    transport(monkeypatch, {"description": TOKEN, "nested": [TOKEN]})
    result = await node({"operation": "get_project", "project": "delivery-app"}).execute({})
    assert TOKEN not in json.dumps(result)


def test_dev_cycle_variation_rejects_top_level_null_but_preserves_nested_json():
    with pytest.raises(ValidationError):
        native.VariationDefinition(key="variation-1", name="Enabled", variables={"flag": None})
    variation = native.VariationDefinition(key="variation-1", name="Enabled", variables={"flag": False, "settings": {"unset": None}})
    assert variation.variables == {"flag": False, "settings": {"unset": None}}
