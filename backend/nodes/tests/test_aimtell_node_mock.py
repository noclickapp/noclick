"""Exercise Aimtell's native factory against provider-published examples.

Fixtures preserve twenty operation examples, including booleans and queued
acknowledgements, to detect routing, encoding and parser regressions.
"""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import aimtell_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/aimtell/contract_examples.json").read_text())
TOKEN = "synthetic-aimtell-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(config):
    return NodeFactory.create_node(node_id="aimtell-test", node_type="automation-aimtell",
        node_data={"config": config, "credentials": {"credential_type": "aimtell_api_key", "api_key": TOKEN}})


def mock_client(monkeypatch, response, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_published_examples_and_exact_routes(monkeypatch, case):
    requests = mock_client(monkeypatch, case["response"])
    result = await make_node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request, cfg = requests[0], case["config"]
    identifier = next((cfg[k] for k in ("campaign_id", "site_id", "segment_id") if k in cfg), None)
    expected = case["path_template"].replace("{id}", str(identifier)).replace("{idSite}", str(identifier))
    assert request.method == case["method"] and request.url.path == expected
    assert request.url.host == "api.aimtell.com"
    assert request.headers["X-Authorization-Api-Key"] == TOKEN
    assert TOKEN not in str(result) and "auth_token" not in str(result)
    if case["operation"] == "send_push":
        assert json.loads(request.content) == {"idSite": 456, "title": "Example Title", "body": "Example body text", "link": "https://example.com/landing-page", "alias": "email==jack@example.com", "push_ttl": 604800}
        assert result["queued"] and result["delivery_verified"] is False
    if case["operation"] == "create_campaign":
        body = json.loads(request.content)
        assert body["idSite"] == "179" and body["status"] == "1"
        assert "site_id" not in body
    if case["operation"] == "delete_variable":
        assert json.loads(request.content) == {"name": "domain"}
    if case["operation"] == "get_campaign_results":
        assert dict(request.url.params) == {"startDate": "03/05/2017", "endDate": "03/09/2017", "includeShared": "1"}
    if case["operation"] == "list_subscribers":
        assert dict(request.url.params) == {"limit": "2", "skip": "0", "include": "attributes,notifications", "segmentId": "123", "subscriberId": "exampleSubscriberId"}
        assert result["next_skip"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 429, 500])
async def test_provider_errors_do_not_become_connection_success(monkeypatch, status):
    mock_client(monkeypatch, {"result": "error", "message": "Invalid token."}, status)
    result = await make_node({"operation": "list_sites"}).execute({})
    assert result == {"status": "error", "error": "Invalid token.", "http_status": status}


@pytest.mark.asyncio
async def test_pagination_and_token_redaction(monkeypatch):
    requests = mock_client(monkeypatch, [{"id": 123, "name": "Site", "auth_token": "provider-secret", "nested": {"access_token": "other"}, "value": TOKEN}])
    result = await make_node({"operation": "list_sites", "limit": 1, "skip": 3}).execute({})
    assert dict(requests[0].url.params) == {"limit": "1", "skip": "3"}
    assert result["next_skip"] == 4
    assert result["data"] == [{"id": 123, "name": "Site", "nested": {}, "value": "[redacted]"}]
    mock_client(monkeypatch, [])
    assert (await make_node({"operation": "list_sites"}).execute({}))["next_skip"] is None


@pytest.mark.parametrize("config", [
    {"operation": "send_push", "site_id": 1, "title": "T", "body": "B", "link": "https://example.com"},
    {"operation": "send_push", "site_id": 1, "title": "T", "body": "B", "link": "https://example.com", "alias": "invalid"},
    {"operation": "update_campaign", "campaign_id": "1"},
    {"operation": "update_segment", "segment_id": "1"},
    {"operation": "list_sites", "limit": 0},
])
def test_invalid_writes_and_pages(config):
    assert native.AimtellNode.validate_config({"config": config})["valid"] is False


@pytest.mark.asyncio
async def test_json_shape_rejected(monkeypatch):
    mock_client(monkeypatch, {"unexpected": True})
    with pytest.raises(ValueError, match="resource list"):
        await make_node({"operation": "list_sites"}).execute({})


def test_credential_shaping_and_wrong_family():
    assert native.AimtellAPIKeyCredential(api_key="  real-key-123  ").api_key == "real-key-123"
    with pytest.raises(ValidationError):
        native.AimtellAPIKeyCredential(api_key="https://example.com")
    with pytest.raises(ValidationError):
        native.AimtellAPIKeyCredential(credential_type="other", api_key=TOKEN)
