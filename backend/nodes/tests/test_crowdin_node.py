"""Crowdin catalog and request contract tests (no live Crowdin credentials)."""

import base64
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes.crowdin_node import (
    CONFIG_MODELS,
    OPERATIONS,
    CrowdinNode,
    CrowdinNodeConfig,
    _base_url,
)


def _config(operation: str, **fields):
    return CrowdinNodeConfig.model_validate(
        {
            "config": {"operation": operation, **fields},
            "credentials": {
                "credential_type": "crowdin_pat",
                "personal_access_token": "test-token",
            },
        }
    )


def _node(config: CrowdinNodeConfig):
    return CrowdinNode("crowdin-1", "automation-crowdin", {}, config, user_id="user-1")


def _transport(monkeypatch, callback):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.crowdin_node.httpx.AsyncClient",
        lambda *args, **kwargs: client(transport=httpx.MockTransport(callback)),
    )


def test_official_catalog_has_one_valid_model_per_operation():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 337
    assert {value["method"] for value in OPERATIONS.values()} == {
        "GET",
        "POST",
        "PATCH",
        "PUT",
        "DELETE",
    }
    for name, operation in OPERATIONS.items():
        assert name == operation["name"]
        assert operation["path"].startswith("/")
        assert set(operation["path_params"]) == set(
            __import__("re").findall(r"\{([^{}]+)\}", operation["path"])
        )
        assert CONFIG_MODELS[name].model_fields["operation"].default == name
    assert CrowdinNode.connection_evidence.operation == "get_current_user"
    assert CrowdinNode.scope_registry.keys_declared == frozenset(OPERATIONS)
    assert OPERATIONS["api_projects_strings_post"]["body_required_fields"] == [
        "fileId", "text"
    ]


def test_required_fields_and_enterprise_host_validation():
    with pytest.raises(ValidationError):
        _config("api_projects_get")
    with pytest.raises(ValidationError):
        _config("api_projects_post")
    with pytest.raises(ValueError, match="subdomain"):
        _base_url("evil.example.com")
    with pytest.raises(ValueError, match="subdomain"):
        _base_url("invalid-")
    assert _base_url("team-1") == "https://team-1.api.crowdin.com/api/v2"


@pytest.mark.asyncio
async def test_list_projects_with_bearer_and_query_filters(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(
            200, json={"data": [{"data": {"id": 7, "name": "Website"}}]}
        )

    _transport(monkeypatch, callback)
    node = _node(_config("api_projects_get_many", query_json='{"limit": 20}'))
    output = await node.execute({})
    assert output["operation"] == "api_projects_get_many"
    assert output["data"]["data"][0]["data"]["name"] == "Website"
    assert str(seen[0].url) == "https://api.crowdin.com/api/v2/projects?limit=20"
    assert seen[0].headers["Authorization"] == "Bearer test-token"


@pytest.mark.asyncio
async def test_create_project_sends_json_and_rejects_missing_required_keys(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(201, json={"data": {"id": 4}})

    _transport(monkeypatch, callback)
    node = _node(
        _config(
            "api_projects_post",
            body_json='{"name":"Product", "sourceLanguageId":"en"}',
        )
    )
    assert (await node.execute({}))["data"]["data"]["id"] == 4
    assert json.loads(seen[0].content) == {"name": "Product", "sourceLanguageId": "en"}
    assert seen[0].method == "POST"

    bad = _node(_config("api_projects_post", body_json='{"name":"Product"}'))
    with pytest.raises(ValueError, match="sourceLanguageId"):
        await bad.execute({})
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_add_string_requires_fields_shared_by_all_openapi_variants(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(201, json={"data": {"id": 3}})

    _transport(monkeypatch, callback)
    missing_file = _node(
        _config(
            "api_projects_strings_post",
            path_projectid="935129",
            body_json='{"text":"Hello"}',
        )
    )
    with pytest.raises(ValueError, match="fileId"):
        await missing_file.execute({})
    assert seen == []

    complete = _node(
        _config(
            "api_projects_strings_post",
            path_projectid="935129",
            body_json='{"text":"Hello","fileId":1}',
        )
    )
    assert (await complete.execute({}))["status_code"] == 201
    assert json.loads(seen[0].content) == {"text": "Hello", "fileId": 1}


@pytest.mark.asyncio
async def test_project_path_is_encoded_and_api_errors_are_clear(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(404, json={"error": {"message": "Project not found"}})

    _transport(monkeypatch, callback)
    node = _node(_config("api_projects_get", path_projectid="7/other"))
    with pytest.raises(ValueError, match="Crowdin API error 404"):
        await node.execute({})
    assert seen[0].url.raw_path.endswith(b"/projects/7%2Fother")


@pytest.mark.asyncio
async def test_storage_binary_upload_validates_and_preserves_bytes(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(201, json={"data": {"id": 99}})

    _transport(monkeypatch, callback)
    node = _node(
        _config(
            "api_storages_post",
            header_crowdin_api_filename="source.txt",
            body_base64=base64.b64encode(b"hello \x00 world").decode(),
        )
    )
    assert (await node.execute({}))["data"]["data"]["id"] == 99
    assert seen[0].headers["Crowdin-API-FileName"] == "source.txt"
    assert seen[0].headers["Content-Type"] == "application/octet-stream"
    assert seen[0].content == b"hello \x00 world"

    bad = _node(
        _config(
            "api_storages_post",
            header_crowdin_api_filename="source.txt",
            body_base64="not-base64!",
        )
    )
    with pytest.raises(ValueError, match="valid base64"):
        await bad.execute({})
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_dynamic_project_options_use_credential_and_enterprise_host(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"data": {"id": 1, "name": "Site"}},
                    {"data": {"id": 2, "name": "Mobile"}},
                ]
            },
        )

    _transport(monkeypatch, callback)
    options = await CrowdinNode.load_field_options(
        "path_projectid",
        {
            "personal_access_token": "token",
            "organization_domain": "acme",
        },
    )
    assert options == [
        {"value": "1", "label": "Site"},
        {"value": "2", "label": "Mobile"},
    ]
    assert seen[0].url.host == "acme.api.crowdin.com"
    assert seen[0].headers["Authorization"] == "Bearer token"

    filtered = await CrowdinNode.load_field_options(
        "path_projectid",
        {"personal_access_token": "token", "organization_domain": "acme"},
        search="mob",
    )
    assert filtered == [{"value": "2", "label": "Mobile"}]


@pytest.mark.asyncio
async def test_download_returns_binary_output(monkeypatch):
    from nodes.core.binary_output import BinaryOutput
    _transport(monkeypatch, lambda request: httpx.Response(
        200, content=b"download bytes", headers={"content-type": "application/octet-stream"}
    ))
    output = await _node(_config("api_projects_get", path_projectid="7")).execute({})
    assert isinstance(output["data"], BinaryOutput)
    assert output["data"].data == b"download bytes"
