"""Contract tests for every Doppler operation against captured HTTP requests."""

import json
from unittest.mock import patch

import httpx
import pytest

from nodes.doppler_node import (
    CreateConfig, CreateEnvironment, CreateProject, DeleteSecret, DopplerNode,
    DopplerNodeConfig, DopplerTokenCredential, DownloadSecrets, GetConfig,
    GetProject, GetSecret, GetTokenInfo, ListConfigs, ListEnvironments,
    ListProjects, ListSecretNames, ListSecrets, SetSecrets,
)


def make_node(operation):
    return DopplerNode(
        node_id="test", node_type="automation-doppler", node_data={},
        config=DopplerNodeConfig(config=operation, credentials=DopplerTokenCredential(token="dp.test")),
        sio=None, sid=None, workflow_id=None, user_id=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,query,body", [
    (GetTokenInfo(), "GET", "/v3/me", {}, None),
    (ListProjects(page=2, per_page=5), "GET", "/v3/projects", {"page": "2", "per_page": "5"}, None),
    (GetProject(project="app"), "GET", "/v3/projects/project", {"project": "app"}, None),
    (CreateProject(name="app", description="App"), "POST", "/v3/projects", {}, {"name": "app", "description": "App"}),
    (CreateProject(name="PROJECT_NAME"), "POST", "/v3/projects", {}, {"name": "PROJECT_NAME"}),
    (ListEnvironments(project="app"), "GET", "/v3/environments", {"project": "app"}, None),
    (CreateEnvironment(project="app", name="Production", slug="prd"), "POST", "/v3/environments", {"project": "app"}, {"name": "Production", "slug": "prd", "personal_configs": False}),
    (ListConfigs(project="app"), "GET", "/v3/configs", {"project": "app", "page": "1", "per_page": "20"}, None),
    (GetConfig(project="app", config="dev"), "GET", "/v3/configs/config", {"project": "app", "config": "dev"}, None),
    (CreateConfig(project="app", environment="dev", name="dev_alice"), "POST", "/v3/configs", {}, {"project": "app", "environment": "dev", "name": "dev_alice"}),
    (ListSecretNames(project="app", config="dev"), "GET", "/v3/configs/config/secrets/names", {"project": "app", "config": "dev"}, None),
    (ListSecrets(project="app", config="dev", names="A,B"), "GET", "/v3/configs/config/secrets", {"project": "app", "config": "dev", "secrets": "A,B"}, None),
    (GetSecret(project="app", config="dev", name="A"), "GET", "/v3/configs/config/secret", {"project": "app", "config": "dev", "name": "A"}, None),
    (DownloadSecrets(project="app", config="dev", names="A"), "GET", "/v3/configs/config/secrets/download", {"project": "app", "config": "dev", "format": "json", "secrets": "A"}, None),
    (SetSecrets(project="app", config="dev", secrets_json='{"A":"sensitive-value"}'), "POST", "/v3/configs/config/secrets", {}, {"project": "app", "config": "dev", "secrets": {"A": "sensitive-value"}}),
    (DeleteSecret(project="app", config="dev", name="A"), "DELETE", "/v3/configs/config/secret", {"project": "app", "config": "dev", "name": "A"}, None),
])
async def test_operation_contract(operation, method, path, query, body):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"secret": "sensitive-value", "ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with patch("nodes.doppler_node.httpx.AsyncClient", return_value=client):
        result = await make_node(operation).execute({})

    assert result["status"] == "success"
    assert result["action"] == operation.operation
    assert result["timing_ms"]["api_request"] >= 0
    request = captured[0]
    assert request.method == method
    assert request.url.path == path
    assert dict(request.url.params) == query
    assert request.headers["Authorization"] == "Bearer dp.test"
    assert json.loads(request.content) == body if body is not None else request.content == b""
    if isinstance(operation, (SetSecrets, DeleteSecret)):
        assert "sensitive-value" not in json.dumps(result)


@pytest.mark.asyncio
async def test_api_errors_do_not_echo_secret_material():
    def handler(request):
        return httpx.Response(400, json={"error": "invalid sensitive-value"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with patch("nodes.doppler_node.httpx.AsyncClient", return_value=client):
        result = await make_node(SetSecrets(project="app", config="dev", secrets_json='{"A":"sensitive-value"}')).execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 400
    assert "sensitive-value" not in json.dumps(result)


@pytest.mark.asyncio
async def test_unexpected_non_json_response_is_sanitized():
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="unexpected sensitive-value")
    ))
    with patch("nodes.doppler_node.httpx.AsyncClient", return_value=client):
        result = await make_node(GetTokenInfo()).execute({})
    assert result["status"] == "error"
    assert result["error"] == "Doppler returned a non-JSON response"
    assert "sensitive-value" not in json.dumps(result)


@pytest.mark.parametrize("value", ["{}", "[]", '{"A":1}', "not json"])
def test_secret_payload_must_be_string_map(value):
    with pytest.raises(ValueError):
        SetSecrets(project="app", config="dev", secrets_json=value)


@pytest.mark.asyncio
async def test_project_and_config_options_are_account_scoped():
    def handler(request):
        if request.url.path == "/v3/projects":
            return httpx.Response(200, json={"projects": [{"name": "app"}]})
        assert dict(request.url.params)["project"] == "app"
        return httpx.Response(200, json={"configs": [{"name": "dev"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with patch("nodes.doppler_node.httpx.AsyncClient", return_value=client):
        projects = await DopplerNode.load_field_options("project", {"token": "dp.test"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with patch("nodes.doppler_node.httpx.AsyncClient", return_value=client):
        configs = await DopplerNode.load_field_options("config", {"token": "dp.test"}, {"project": "app"})
    assert projects == [{"value": "app", "label": "app"}]
    assert configs == [{"value": "dev", "label": "dev"}]
