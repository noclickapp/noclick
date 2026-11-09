"""Offline native factory tests; request fixtures track the provider's API v2 contract."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import kobotoolbox_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-kobo-key-42"
CASES = json.loads((Path(__file__).parent / "fixtures/kobotoolbox/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id="kobo-test", node_type="automation-kobotoolbox", node_data={
        "config": config, "credentials": {"credential_type": "kobotoolbox_api_token", "api_token": TOKEN, **credential},
    })


def transport(monkeypatch, status, response=None, **headers):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, **({"json": response} if response is not None else {}), headers=headers)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_one_request_per_operation_exact_wire_contract(monkeypatch, case):
    requests = transport(monkeypatch, case.get("status", 200), case.get("response"))
    out = await node(case["config"]).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert request.url.host == "kf.kobotoolbox.org"
    assert request.headers["Authorization"] == "Token " + TOKEN
    assert dict(request.url.params) == case.get("params", {})
    assert (json.loads(request.content) if request.content else None) == case.get("body")
    if case.get("status") == 204:
        assert out["deleted"] and out["http_status"] == 204
    else:
        assert out["data"] == case["response"]
    if case["config"]["operation"] == "list_projects":
        assert out["next_start"] == 101 and out["items"][0]["name"] == "Field survey"
    assert TOKEN not in str(out)


@pytest.mark.asyncio
async def test_eu_identity_and_redaction(monkeypatch):
    requests = transport(monkeypatch, 200, {"username": "field-team", "echo": TOKEN, "token": TOKEN})
    out = await node({"operation": "get_account"}, server="https://eu.kobotoolbox.org").execute({})
    assert requests[0].url.host == "eu.kobotoolbox.org"
    assert out["data"] == {"username": "field-team", "echo": "[redacted]"}
    assert native.KobotoolboxNode.connection_evidence.identity_operation == "get_account"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_rejections_and_redirects_are_not_success(monkeypatch, status):
    requests = transport(monkeypatch, status, {"detail": "Invalid token."}, Location="https://example.org/")
    out = await node({"operation": "get_account"}).execute({})
    assert out == {"status": "error", "http_status": status, "error": "Invalid token."}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_unexpected_json_and_list_shape_fail(monkeypatch):
    transport(monkeypatch, 200, {"detail": "Not a results page"})
    with pytest.raises(ValueError, match="results page"):
        await node({"operation": "list_projects"}).execute({})
    transport(monkeypatch, 200, {"errors": ["bad"]})
    with pytest.raises(ValueError, match="unexpected response"):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_project", "project_id": "../me"},
    {"operation": "get_submission", "project_id": "a123", "submission_id": "1/other"},
    {"operation": "list_projects", "limit": 0},
    {"operation": "set_deployment_active", "project_id": "a123"},
    {"operation": "set_validation_status", "project_id": "a123", "submission_id": "123", "validation_status": "invented"},
])
def test_required_fields_and_path_boundaries(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_manual_credential_defaults_and_server_boundary():
    cred = native.KobotoolboxAPITokenCredential(api_token=TOKEN)
    assert cred.credential_type == "kobotoolbox_api_token"
    for server in ["https://evil.example.org", "https://kf.kobotoolbox.org.evil.org", "http://kf.kobotoolbox.org"]:
        with pytest.raises(ValidationError):
            native.KobotoolboxAPITokenCredential(api_token=TOKEN, server=server)
    assert set(native.ROUTES) == {case["config"]["operation"] for case in CASES}
