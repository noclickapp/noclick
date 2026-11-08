"""Infisical request contracts through the real node factory; no account needed."""
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError

from nodes import infisical_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-infisical-token"
CREDENTIAL = {"credential_type": "infisical_api_token", "api_token": TOKEN}
PROJECT = {"project_id": "project-1"}
LOCATION = {**PROJECT, "environment": "dev", "secret_path": "/app"}
SECRET = {**LOCATION, "secret_name": "DATABASE_URL"}
WIRE_LOCATION = {"projectId": "project-1", "environment": "dev", "secretPath": "/app"}
WIRE_SECRET = {**WIRE_LOCATION, "type": "shared"}
FOLDER = {"projectId": "project-1", "environment": "dev", "path": "/app"}
CASES = [
    ("list_projects", {}, "GET", "/api/v1/projects", {}, None),
    ("get_project", PROJECT, "GET", "/api/v1/projects/project-1", {}, None),
    ("create_project", {"name": "Automation", "description": "Created by workflow"}, "POST", "/api/v1/projects", {}, {"projectName": "Automation", "projectDescription": "Created by workflow"}),
    ("update_project", {**PROJECT, "name": "Changed"}, "PATCH", "/api/v1/projects/project-1", {}, {"name": "Changed"}),
    ("list_secrets", LOCATION, "GET", "/api/v4/secrets", {**WIRE_LOCATION, "recursive": "false", "includeImports": "true", "viewSecretValue": "true"}, None),
    ("get_secret", {**SECRET, "version": 2}, "GET", "/api/v4/secrets/DATABASE_URL", {**WIRE_SECRET, "version": "2", "viewSecretValue": "true"}, None),
    ("create_secret", {**SECRET, "secret_value": "postgres://example", "secret_comment": "db"}, "POST", "/api/v4/secrets/DATABASE_URL", {}, {**WIRE_SECRET, "secretValue": "postgres://example", "secretComment": "db"}),
    ("update_secret", {**SECRET, "secret_value": "changed"}, "PATCH", "/api/v4/secrets/DATABASE_URL", {}, {**WIRE_SECRET, "secretValue": "changed"}),
    ("delete_secret", SECRET, "DELETE", "/api/v4/secrets/DATABASE_URL", {}, WIRE_SECRET),
    ("list_folders", LOCATION, "GET", "/api/v2/folders", {**FOLDER, "recursive": "false"}, None),
    ("create_folder", {**LOCATION, "name": "team"}, "POST", "/api/v2/folders", {}, {**FOLDER, "name": "team"}),
    ("update_folder", {**LOCATION, "folder_id": "folder-1", "name": "team"}, "PATCH", "/api/v2/folders/folder-1", {}, {**FOLDER, "name": "team"}),
    ("delete_folder", {**LOCATION, "folder_id": "folder-1"}, "DELETE", "/api/v2/folders/folder-1", {}, {**FOLDER, "forceDelete": False}),
    ("get_environment", {**PROJECT, "environment": "dev"}, "GET", "/api/v1/projects/project-1/environments/slug/dev", {}, None),
    ("create_environment", {**PROJECT, "name": "Development", "slug": "dev", "position": 1}, "POST", "/api/v1/projects/project-1/environments", {}, {"name": "Development", "slug": "dev", "position": 1}),
    ("list_tags", PROJECT, "GET", "/api/v1/projects/project-1/tags", {}, None),
    ("get_tag", {**PROJECT, "tag_id": "tag-1"}, "GET", "/api/v1/projects/project-1/tags/tag-1", {}, None),
    ("create_tag", {**PROJECT, "slug": "production", "color": "#ff0000"}, "POST", "/api/v1/projects/project-1/tags", {}, {"slug": "production", "color": "#ff0000"}),
    ("update_tag", {**PROJECT, "tag_id": "tag-1", "slug": "production", "color": "#ff0000"}, "PATCH", "/api/v1/projects/project-1/tags/tag-1", {}, {"slug": "production", "color": "#ff0000"}),
    ("delete_tag", {**PROJECT, "tag_id": "tag-1"}, "DELETE", "/api/v1/projects/project-1/tags/tag-1", {}, None),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(config, credential=None):
    return NodeFactory.create_node(node_id="infisical-fixture", node_type="automation-infisical",
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def intercept(monkeypatch, response):
    requests, policies = [], []
    def handle(request):
        requests.append(request)
        return response(request)
    @asynccontextmanager
    async def client(**kwargs):
        policies.append(kwargs)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as session:
            yield session
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, policies


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,query,body", CASES, ids=[c[0] for c in CASES])
async def test_operation_contract(monkeypatch, operation, config, method, path, query, body):
    reply = {"secret": {"secretKey": "DATABASE_URL", "secretValue": "value"}}
    requests, policies = intercept(monkeypatch, lambda _: httpx.Response(200, json=reply))
    result = await make_node({"operation": operation, **config}).execute({})
    assert result == {"status": "success", "action": operation, "data": reply}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "us.infisical.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    assert policies == [{"timeout": 30, "follow_redirects": False, "trust_env": False}]


@pytest.mark.asyncio
async def test_region_and_empty_project_evidence(monkeypatch):
    requests, _ = intercept(monkeypatch, lambda _: httpx.Response(200, json={"projects": []}))
    result = await make_node({"operation": "list_projects"}, {**CREDENTIAL, "region": "eu"}).execute({})
    assert requests[0].url.host == "eu.infisical.com"
    assert result["data"] == {"projects": []}
    assert native.InfisicalNode.connection_evidence.operation == "list_projects"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_error_is_not_success_and_redacts_token(monkeypatch, status):
    requests, _ = intercept(monkeypatch, lambda _: httpx.Response(status, json={"message": "Rejected " + TOKEN}, headers={"Location": "https://example.com"}))
    result = await make_node({"operation": "list_projects"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_invalid_success_response(monkeypatch):
    intercept(monkeypatch, lambda _: httpx.Response(200, text="<html>not JSON</html>"))
    with pytest.raises(ValueError, match="invalid JSON"):
        await make_node({"operation": "list_projects"}).execute({})


@pytest.mark.asyncio
async def test_path_values_cannot_inject_query(monkeypatch):
    requests, _ = intercept(monkeypatch, lambda _: httpx.Response(200, json={}))
    await make_node({"operation": "get_secret", **SECRET, "secret_name": "name?projectId=other#fragment"}).execute({})
    assert requests[0].url.params["projectId"] == "project-1"
    assert requests[0].url.fragment == ""
    assert "%3FprojectId%3Dother%23fragment" in str(requests[0].url)


def test_manual_credential_and_config_validation():
    assert native.InfisicalTokenCredential(api_token=TOKEN).credential_type == "infisical_api_token"
    for changes in [{"region": "https://example.com"}, {"api_token": "Bearer token"}]:
        with pytest.raises(ValidationError):
            native.InfisicalTokenCredential.model_validate({**CREDENTIAL, **changes})
    with pytest.raises(ValidationError):
        native.CreateSecret.model_validate({"operation": "create_secret", **SECRET})
    with pytest.raises(ValidationError):
        native.GetSecret.model_validate({**SECRET, "version": 0})
