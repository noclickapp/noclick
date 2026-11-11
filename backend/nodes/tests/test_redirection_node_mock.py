"""Exercise factory execution against official documented responses and wire contracts."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import redirection_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / "fixtures/redirection/documented.json").read_text())
TOKEN = "test-redirection-token-42"
PROJECT = "060201ae-88ad-4043-bd02-4661be4fcbd0"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="redirection-fixture", node_type="automation-redirection",
        node_data={"config": config, "credentials": {"credential_type": "redirection_api_token", "api_token": TOKEN}})


def transport(monkeypatch, body=None, status=200, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body", [
    ("get_organization", FIXTURE["organization"]),
    ("list_rules", FIXTURE["rules"]), ("list_drafts", FIXTURE["drafts"]),
    ("create_redirection", FIXTURE["created_redirection"]),
])
async def test_documented_responses(monkeypatch, operation, body):
    config = {"operation": operation}
    if operation != "get_organization": config["project_id"] = PROJECT
    if operation == "create_redirection": config.update(source="/blog/some-source-url", target="/blog/blog-post-new-url", status_code=302)
    requests = transport(monkeypatch, body, 201 if operation == "create_redirection" else 200)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == body
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN
    assert requests[0].headers["Accept"] == "application/json"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(FIXTURE["requests"]))
async def test_every_operation_method_path_and_required_query(monkeypatch, operation):
    config = {"operation": operation}
    contract = FIXTURE["requests"][operation]
    method, path = contract["method"], contract["path"]
    if "{id}" in path:
        resource = path.split("/")[1].removesuffix("s")
        path = path.replace("{id}", "{" + resource + "_id}")
    if "{project_id}" in path or operation in {"list_rules", "list_drafts", "list_domains", "list_instances", "create_redirection", "create_rule", "update_rule", "create_domain"}:
        config["project_id"] = PROJECT
    for name in ["rule", "draft", "domain", "instance"]:
        if "{" + name + "_id}" in path: config[name + "_id"] = name + "-42"
    if operation == "create_project": config["name"] = "Site migration"
    if operation == "create_domain": config["domain"] = "example.com"
    if operation == "create_redirection": config.update(source="/old", target="/new", status_code=308)
    if operation in {"create_rule", "update_rule"}:
        config.update(trigger={"source": "/old"}, actions=[{"type": "redirection", "location": "/new", "statusCode": 301}])
    if operation in native.PAGED: config["search_after_id"] = "previous-42"
    if operation in {"list_rules", "list_drafts"}: config.update(enabled=False, tags=["CMS", "blog"], trigger_url="/old+a?x=1")
    status = contract["status"]
    body = [] if operation.startswith("list_") or operation == "get_rule_statistics" else {"id": "42"}
    requests = transport(monkeypatch, body, status)
    result = await node(config).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    expected_path = path
    for key, value in config.items(): expected_path = expected_path.replace("{" + key + "}", str(value))
    assert request.method == method and request.url.path == expected_path
    assert request.url.host == "api.redirection.io" and request.url.scheme == "https"
    if operation in native.PAGED:
        assert request.url.params["projectId"] == PROJECT and request.url.params["searchAfterId"] == "previous-42"
    if operation in {"list_rules", "list_drafts"}:
        assert request.url.params["enabled"] == "false" and request.url.params.get_list("tags") == ["CMS", "blog"]
        assert request.url.params["triggerUrl"] == "/old+a?x=1"
    if method in {"POST", "PUT"} and operation != "publish_project":
        sent = json.loads(request.content)
        assert "operation" not in sent and "project_id" not in sent and "rule_id" not in sent
        if "project_id" in config: assert sent["project"] == "/projects/" + PROJECT
        if operation == "create_redirection": assert sent["statusCode"] == 308
        if operation == "create_domain": assert sent["backendAllowInvalidCertificate"] is True
    else:
        assert request.content == b""


@pytest.mark.asyncio
async def test_paging_returns_provider_cursor_without_extra_requests(monkeypatch):
    body = [{"id": f"rule-{i}"} for i in range(100)]
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_rules", "project_id": PROJECT}).execute({})
    assert result["has_more"] and result["next_search_after_id"] == "rule-99" and len(requests) == 1
    transport(monkeypatch, [])
    result = await node({"operation": "list_rules", "project_id": PROJECT, "search_after_id": "rule-99"}).execute({})
    assert result["has_more"] is False and result["next_search_after_id"] is None
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="non-advancing"):
        await node({"operation": "list_rules", "project_id": PROJECT, "search_after_id": "rule-99"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 409, 429, 500])
async def test_provider_failure_preserved_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"detail": "Token rejected: " + TOKEN}, status, {"Retry-After": "60"})
    result = await node({"operation": "publish_project", "project_id": PROJECT}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Token rejected" in result["error"] and TOKEN not in str(result)
    assert result["retry_after"] == "60" and len(requests) == 1


def test_manual_credential_and_schema_guards():
    credential = native.RedirectionTokenCredential.model_validate({"api_token": "  real-token-42  "})
    assert credential.credential_type == "redirection_api_token" and credential.api_token == "real-token-42"
    for token in ["Bearer abc", "https://example.com/key", "<token>"]:
        with pytest.raises(ValidationError): native.RedirectionTokenCredential(api_token=token)
    for config in [{"operation": "get_rule", "rule_id": "../projects"},
                   {"operation": "create_redirection", "project_id": PROJECT, "source": "/a", "target": "/b", "status_code": 200},
                   {"operation": "list_rules"}]:
        assert native.RedirectionNode.validate_config({"config": config})["valid"] is False
