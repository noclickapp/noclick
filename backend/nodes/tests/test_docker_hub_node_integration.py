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
    # The contract fixture omits upstream credential examples; retain provenance separately.
    assert catalog["source_sha256"] == "46c09f04fd8e7b3fe464c9b406a1bf8a0a6a164c87083f57ebbab64ccb7c8d3f"
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 52
    assert (
        catalog["fixture_sha256"]
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


def _documented_list(path):
    """Use Docker's saved API response, including its real event field names."""
    spec = yaml.safe_load((Path(__file__).parent / "fixtures/docker-hub/openapi.yaml").read_text())
    examples = spec["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["examples"]
    return json.loads(json.dumps(next(iter(examples.values()))["value"], default=str))


def _poll_node(operation, **config):
    return DockerHubNode(node_id="docker-poll", node_type="automation-docker-hub", node_data={},
                         config=DockerHubNodeConfig(config={"operation": operation, **config}, credentials=_pat()))


def _state_store(node):
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    node._update_node_state = update
    return state


@pytest.mark.asyncio
async def test_repository_poll_baselines_deduplicates_updates_and_repoints(monkeypatch):
    body = _documented_list("/v2/namespaces/{namespace}/repositories")
    node = _poll_node("on_repository_updated", namespace="docker")
    _state_store(node)

    def handler(request):
        if request.url.path == "/v2/auth/token":
            return _auth_response()
        assert request.url.params["ordering"] == "-last_updated"
        assert request.url.params["page_size"] == "100"
        return httpx.Response(200, json=body)

    _mock_client(monkeypatch, handler)
    baseline = await node.execute({})
    assert baseline["new_item_count"] == 0
    assert not node.should_propagate_output(baseline, {"operation": "on_repository_updated"})
    assert node.resolve_agent_event(baseline) is None
    assert (await node.execute({}))["new_item_count"] == 0
    body["results"][0]["last_updated"] = "2026-11-11T00:00:00Z"
    output = await node.execute({})
    assert output["new_item_count"] == 1
    assert node.trigger_emitted_event(output)
    assert "docker/highland_builder" in node.resolve_agent_event(output)["text"]
    assert "https://hub.docker.com/r/docker/highland_builder" in node.resolve_agent_event(output)["text"]
    assert (await node.execute({}))["new_item_count"] == 0
    node.config.config.namespace = "another-namespace"
    assert (await node.execute({}))["new_item_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["on_image_pushed", "on_new_audit_event"])
async def test_audit_polls_use_documented_event_and_filters(monkeypatch, operation):
    body = _documented_list("/v2/auditlogs/{account}")
    # The other documented event is an offload lease; only the push can fire.
    node = _poll_node(operation, account="docker", name="docker/example",
                      **({"action": "repo.tag.push"} if operation == "on_new_audit_event" else {}))
    state = _state_store(node)

    def handler(request):
        if request.url.path == "/v2/auth/token":
            return _auth_response()
        assert request.url.params["action"] == "repo.tag.push"
        assert request.url.params["name"] == "docker/example"
        assert "from" in request.url.params
        return httpx.Response(200, json=body)

    _mock_client(monkeypatch, handler)
    assert (await node.execute({}))["new_item_count"] == 0
    state["seen_ids"] = []
    result = await node.execute({})
    assert result["new_item_count"] == 1
    text = node.resolve_agent_event(result)["text"]
    for value in ("docker", "repo.tag.push", "docker/example", "latest", "sha256:"):
        assert value in text
    assert (await node.execute({}))["new_item_count"] == 0


@pytest.mark.asyncio
async def test_poll_paginates_before_persisting_and_leaves_state_on_failure(monkeypatch):
    from copy import deepcopy

    example = _documented_list("/v2/namespaces/{namespace}/repositories")["results"][0]
    node = _poll_node("on_repository_updated", namespace="docker")
    state = _state_store(node)
    seen_pages = []
    fail = False

    def handler(request):
        if request.url.path == "/v2/auth/token":
            return _auth_response()
        page = int(request.url.params["page"])
        seen_pages.append(page)
        if page == 2:
            return httpx.Response(500 if fail else 200, json={"results": []})
        return httpx.Response(200, json={"results": [dict(deepcopy(example), name=f"image-{i}") for i in range(100)]})

    _mock_client(monkeypatch, handler)
    await node.execute({})
    assert seen_pages == [1, 2]
    before = deepcopy(state)
    fail = True
    with pytest.raises(ValueError, match="Docker Hub API error 500"):
        await node.execute({})
    assert state == before


def test_trigger_schemas_and_scope_use_declared_config_only():
    from nodes.core.poll_trigger import poll_scope

    schema = DockerHubNode.get_config_schema()
    marked = {value["properties"]["operation"]["const"] for value in schema["$defs"].values()
              if value.get("properties", {}).get("operation", {}).get("x-is-trigger")}
    assert marked == {"on_repository_updated", "on_image_pushed", "on_new_audit_event"}
    config = {"operation": "on_image_pushed", "account": "docker"}
    scope = poll_scope(DockerHubNode, config)
    assert scope == poll_scope(DockerHubNode, {**config, "label": "A prettier label"})
    assert scope != poll_scope(DockerHubNode, {**config, "account": "other"})
    assert scope != poll_scope(DockerHubNode, {**config, "lookback_hours": 48})
