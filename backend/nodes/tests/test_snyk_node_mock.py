"""Exercise every Snyk operation through discovery and the real request builder.

Response fixtures are provider examples from the pinned V1 contract; no network
or account is used. Failure cases protect hand connection and token handling.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import snyk_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-snyk-token-42"
CASES = json.loads((Path(__file__).parent / "fixtures/snyk/contract_examples.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="snyk-fixture", node_type="automation-snyk",
        node_data={"config": config, "credentials": credentials or {"credential_type": "snyk_api_token", "api_token": TOKEN}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_snyk_contract_routes_bodies_and_documented_responses(monkeypatch, operation):
    case = CASES[operation]
    def reply(request):
        if case["response"] is None:
            return httpx.Response(case["status"], content=b"")
        return httpx.Response(case["status"], json=case["response"])
    requests = transport(monkeypatch, reply)
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "operation": operation, "http_status": case["status"], "data": case["response"]}
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "api.snyk.io" and request.url.scheme == "https"
    assert request.method == case["method"] and request.url.path == case["path"]
    assert request.headers["authorization"] == "token " + TOKEN
    assert (json.loads(request.content) if request.content else None) == case["request_body"]
    assert dict(request.url.params) == ({"includeGroupAdmins": "false"} if operation == "list_organization_members" else {})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_snyk_http_rejections_keep_provider_text_redact_token_and_do_not_retry(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={"message": "Not authorised " + TOKEN}))
    result = await node({"operation": "list_organizations"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Not authorised" in result["error"] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>Sign in</html>"), httpx.Response(200, content=b""), httpx.Response(200, json={}), httpx.Response(200, json={"orgs": None})])
async def test_snyk_connection_rejects_missing_or_non_json_organization_list(monkeypatch, response):
    transport(monkeypatch, lambda r: response)
    with pytest.raises(ValueError):
        await node({"operation": "list_organizations"}).execute({})


@pytest.mark.asyncio
async def test_snyk_empty_organization_list_and_error_envelope(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, json={"orgs": []}))
    assert (await node({"operation": "list_organizations"}).execute({}))["data"] == {"orgs": []}
    transport(monkeypatch, lambda r: httpx.Response(200, json={"error": "Refused " + TOKEN}))
    result = await node({"operation": "list_organizations"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_snyk_nested_output_token_redaction(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, json={"orgs": [{"name": TOKEN}]}))
    result = await node({"operation": "list_organizations"}).execute({})
    assert TOKEN not in str(result) and result["data"]["orgs"][0]["name"] == "[redacted]"


@pytest.mark.parametrize("token", ["token with spaces", "token\nheader", "https://example.com/token"])
def test_snyk_bad_tokens_rejected_before_request(token):
    with pytest.raises(ValidationError):
        native.SnykAPITokenCredential(api_token=token)


@pytest.mark.parametrize("identifier", ["..", "a/b", "a?b", "a#b", "a%2fb", "a\nb"])
def test_snyk_path_components_cannot_change_routes(identifier):
    with pytest.raises(ValidationError):
        native.GetProject(org_id=identifier, project_id="project-id")


def test_snyk_manual_credential_default_and_required_update_fields():
    credential = native.SnykAPITokenCredential(api_token=TOKEN)
    assert credential.credential_type == "snyk_api_token"
    with pytest.raises(ValidationError):
        native.UpdateProject(org_id="org-id", project_id="project-id")
    with pytest.raises(ValidationError):
        native.AddProjectTag(org_id="org-id", project_id="project-id", key="bad tag", value="ok")
    assert native.SnykNode.connection_evidence.operation == "list_organizations"
