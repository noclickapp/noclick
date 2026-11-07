"""Docker Hub catalog, credential, and HTTP request contracts."""

import json
from pathlib import Path

import httpx
import pytest
import yaml

from nodes import docker_hub_node
from nodes.docker_hub_node import (
    CONFIG_MODELS,
    OPERATIONS,
    DockerHubNode,
    DockerHubNodeConfig,
    DockerHubPATCredential,
    DockerHubSCIMCredential,
)


ORIGINAL_CLIENT = httpx.AsyncClient


def _mock_client(monkeypatch, handler):
    monkeypatch.setattr(
        docker_hub_node.httpx,
        "AsyncClient",
        lambda *args, **kwargs: ORIGINAL_CLIENT(
            *args,
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )


def _pat():
    return DockerHubPATCredential(
        identifier="noclickqa", personal_access_token="dckr_pat_secret"
    )


def _auth_response():
    return httpx.Response(200, json={"access_token": "short-lived-jwt"})


def test_catalog_matches_pinned_official_openapi():
    source = Path(__file__).parent / "fixtures/docker-hub/openapi.yaml"
    spec = yaml.safe_load(source.read_text())
    catalog = docker_hub_node._catalog
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 52
    assert (
        catalog["source_sha256"]
        == __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    )
    for op in catalog["operations"]:
        assert op["method"].lower() in spec["paths"][op["path"]]
        assert op["path_params"] == __import__("re").findall(
            r"\{([^{}]+)\}", op["path"]
        )
    assert {op["auth"] for op in catalog["operations"]} == {"pat", "scim"}
    assert DockerHubNode.connection_evidence.operation == "test_connection"
    schema = DockerHubNode.get_config_schema()
    assert schema["x-agent-tool-provider"] is True
    assert "DockerHubPATCredential" in schema["$defs"]
    assert "DockerHubSCIMCredential" in schema["$defs"]


@pytest.mark.asyncio
async def test_connection_evidence_exchanges_pat_without_returning_jwt(monkeypatch):
    def handler(request):
        assert request.url == "https://hub.docker.com/v2/auth/token"
        assert json.loads(request.read()) == {
            "identifier": "noclickqa",
            "secret": "dckr_pat_secret",
        }
        return _auth_response()

    _mock_client(monkeypatch, handler)
    config = DockerHubNodeConfig(
        config={"operation": "test_connection"},
        credentials={
            "credential_type": "docker_hub_pat",
            "identifier": "noclickqa",
            "personal_access_token": "dckr_pat_secret",
        },
    )
    node = DockerHubNode(
        node_id="docker-test",
        node_type="automation-docker-hub",
        node_data={},
        config=config,
    )
    result = await node.execute({})
    assert result["account"] == "noclickqa"
    assert "short-lived-jwt" not in json.dumps(result)
    assert "dckr_pat_secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_repository_list_encodes_namespace_and_query(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/v2/auth/token":
            return _auth_response()
        assert request.headers["authorization"] == "Bearer short-lived-jwt"
        assert request.method == "GET"
        assert request.url.raw_path.startswith(
            b"/v2/namespaces/team%2Fwest/repositories"
        )
        assert request.url.params["page_size"] == "5"
        return httpx.Response(
            200, json={"results": [{"name": "image"}]}, headers={"X-Next-Page": "2"}
        )

    _mock_client(monkeypatch, handler)
    result = await DockerHubNode._request(
        _pat(),
        "list_namespace_repositories",
        {
            "path_namespace": "team/west",
            "query_json": '{"page_size":5}',
        },
    )
    assert len(requests) == 2
    assert result["data"]["results"][0]["name"] == "image"
    assert result["pagination"] == {"x-next-page": "2"}


@pytest.mark.asyncio
async def test_repository_create_checks_required_body_and_uses_json(monkeypatch):
    def handler(request):
        if request.url.path == "/v2/auth/token":
            return _auth_response()
        assert request.method == "POST"
        assert request.url.path == "/v2/namespaces/noclickqa/repositories"
        assert json.loads(request.read()) == {
            "name": "qa-image",
            "namespace": "noclickqa",
        }
        return httpx.Response(201, json={"name": "qa-image"})

    _mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="Request Body is required"):
        await DockerHubNode._request(
            _pat(),
            "create_repository",
            {
                "path_namespace": "noclickqa",
                "body_json": "",
            },
        )
    result = await DockerHubNode._request(
        _pat(),
        "create_repository",
        {
            "path_namespace": "noclickqa",
            "body_json": '{"name":"qa-image","namespace":"noclickqa"}',
        },
    )
    assert result["status_code"] == 201


@pytest.mark.asyncio
async def test_scim_credential_only_calls_scim_endpoint(monkeypatch):
    def handler(request):
        assert request.url == "https://hub.docker.com/v2/scim/2.0/ServiceProviderConfig"
        assert request.headers["authorization"] == "Bearer scim-secret"
        return httpx.Response(200, json={"schemas": []})

    _mock_client(monkeypatch, handler)
    credential = DockerHubSCIMCredential(scim_token="scim-secret")
    result = await DockerHubNode._request(credential, "test_connection", {})
    assert result["account"] == "SCIM organization"
    with pytest.raises(ValueError, match="personal or organization"):
        await DockerHubNode._request(
            credential, "list_namespace_repositories", {"path_namespace": "x"}
        )
    with pytest.raises(ValueError, match="SCIM provisioning"):
        await DockerHubNode._request(_pat(), "get_v2_scim20_users", {})


@pytest.mark.asyncio
async def test_validation_and_vendor_errors_do_not_expose_token(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/v2/auth/token":
            return _auth_response()
        return httpx.Response(403, json={"message": "Rejected dckr_pat_secret"})

    _mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="namespace is required"):
        await DockerHubNode._request(_pat(), "list_namespace_repositories", {})
    assert requests == []
    with pytest.raises(ValueError, match="Unknown query parameters"):
        await DockerHubNode._request(
            _pat(),
            "list_namespace_repositories",
            {
                "path_namespace": "x",
                "query_json": '{"redirect_url":"https://example.com"}',
            },
        )
    with pytest.raises(ValueError, match="Query Parameters must be a JSON object"):
        await DockerHubNode._request(
            _pat(),
            "list_namespace_repositories",
            {
                "path_namespace": "x",
                "query_json": "[]",
            },
        )
    with pytest.raises(ValueError, match="Docker Hub API error 403") as error:
        await DockerHubNode._request(
            _pat(),
            "list_namespace_repositories",
            {
                "path_namespace": "x",
            },
        )
    assert "dckr_pat_secret" not in str(error.value)


@pytest.mark.asyncio
async def test_success_response_cannot_echo_credential_or_jwt(monkeypatch):
    def handler(request):
        if request.url.path == "/v2/auth/token":
            return _auth_response()
        return httpx.Response(
            200,
            json={"nested": ["dckr_pat_secret", {"token": "short-lived-jwt"}]},
        )

    _mock_client(monkeypatch, handler)
    result = await DockerHubNode._request(
        _pat(), "list_namespace_repositories", {"path_namespace": "noclickqa"}
    )
    assert result["data"] == {"nested": ["[REDACTED]", {"token": "[REDACTED]"}]}


@pytest.mark.asyncio
async def test_non_json_response_returns_binary_output(monkeypatch):
    from nodes.core.binary_output import BinaryOutput

    def handler(request):
        if request.url.path == "/v2/auth/token":
            return _auth_response()
        return httpx.Response(200, content=b"username,role\njonsnow,member\n", headers={"Content-Type": "text/csv"})

    _mock_client(monkeypatch, handler)
    result = await DockerHubNode._request(
        _pat(), "get_v2_orgs_by_org_name_members_export", {"path_org_name": "docker"}
    )
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == b"username,role\njonsnow,member\n"


@pytest.mark.asyncio
async def test_invalid_json_response_is_rejected(monkeypatch):
    def handler(request):
        if request.url.path == "/v2/auth/token":
            return _auth_response()
        return httpx.Response(200, content=b"not-json", headers={"Content-Type": "application/json"})

    _mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="Docker Hub returned invalid JSON"):
        await DockerHubNode._request(
            _pat(), "list_namespace_repositories", {"path_namespace": "docker"}
        )
