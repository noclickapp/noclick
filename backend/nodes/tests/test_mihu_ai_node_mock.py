"""Exercise Mihu Ai's request mapping through the real node factory.

Synthetic HTTP responses cover page preservation, credential rejection and write errors.
"""
import json
from pathlib import Path
import httpx
import pytest
from nodes import mihu_ai_node as native
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import _rows_from_operation

TOKEN = "synthetic-mihu-token-42"
UUID = "123e4567-e89b-12d3-a456-426614174000"
CASES = json.loads((Path(__file__).parent / "fixtures/mihu-ai/requests.json").read_text())["requests"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="mihu-fixture", node_type="automation-mihu-ai",
        node_data={"config": config, "credentials": {"api_token": TOKEN, "subdomain": "owned-workspace"}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_documented_request_and_response_preservation(monkeypatch, case):
    body = {"success": True, "data": {"uuid": UUID, "name": "John"}, "pagination": {"next_page_url": None}}
    requests = transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    result = await node(case["config"]).execute({})
    assert result["data"] == body and result["http_status"] == 200
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "owned-workspace.mihu.ai" and request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["X-Timezone"] == "UTC"


@pytest.mark.asyncio
async def test_account_evidence_and_pagination_remain_available(monkeypatch):
    body = {"success": True, "data": {"current_page": 1, "last_page": 2,
        "data": [{"uuid": UUID, "name": "John", "email": "john@example.com"}]},
        "pagination": {"page": 1, "has_more_pages": True, "next_page_url": "https://owned-workspace.mihu.ai/api/v1/contacts?page=2"}}
    requests = transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    result = await node({"operation": "list_contacts"}).execute({})
    assert _rows_from_operation(result) == body["data"]["data"]
    assert result["data"]["pagination"] == body["pagination"] and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 302, 401, 403, 404, 422, 429, 500])
async def test_provider_rejection_is_not_success_and_redacts_token(monkeypatch, status):
    requests = transport(monkeypatch, lambda request: httpx.Response(status,
        json={"success": False, "message": "Rejected " + TOKEN}, headers={"Location": "https://foreign.test"}))
    result = await node({"operation": "create_contact", "name": "John"}).execute({})
    assert result["status"] == "error" and result["success"] is False
    assert result["http_status"] == status and TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_timeout_never_retries_write_or_leaks_token(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout(TOKEN)
    requests = transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match="inspect writes before retrying") as exc:
        await node({"operation": "create_contact", "name": "John"}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_non_json_response_is_not_connection_evidence(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(ValueError, match="non-JSON"):
        await node({"operation": "list_contacts"}).execute({})


@pytest.mark.parametrize("subdomain", ["https://app.mihu.ai", "a.mihu.ai", "a/b", "localhost:80", "a@evil", "a\nX-Test: yes"])
def test_credential_rejects_foreign_hosts_and_header_injection(subdomain):
    with pytest.raises(ValueError):
        native.MihuAiTokenCredential(subdomain=subdomain, api_token=TOKEN)


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "uuid": "../other"},
    {"operation": "create_contact"},
    {"operation": "update_contact", "uuid": UUID},
    {"operation": "add_contact_tag", "uuid": UUID},
    {"operation": "add_contact_note", "uuid": UUID, "content": "hi"},
    {"operation": "initiate_call", "agentId": UUID, "prompt": {}, "participant": {"number": "123"}},
    {"operation": "list_agents", "per_page": 101},
])
def test_invalid_inputs_fail_before_network(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credential_type_default_and_shape():
    credential = native.MihuAiTokenCredential(subdomain=" Owned-Workspace ", api_token=TOKEN)
    assert credential.credential_type == "mihu_ai_api_token" and credential.subdomain == "owned-workspace"
