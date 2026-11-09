"""Offline wire regressions using the pinned publisher's v3 request examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import lusha_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures/lusha"
CONTRACT = json.loads((FIXTURES / "contract.json").read_text())
INPUTS = json.loads((FIXTURES / "inputs.json").read_text())
TOKEN = "lusha-synthetic-test-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="lusha-fixture", node_type="automation-lusha", node_data={
        "config": config,
        "credentials": credentials or {"credential_type": "lusha_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", INPUTS)
async def test_pinned_routes_methods_auth_and_complete_payload(monkeypatch, operation):
    expected = CONTRACT["operations"][operation]
    config = INPUTS[operation]
    # Include job state, credits and page metadata: no implicit polling/pagination.
    response = {"results": [{"id": "4389064654"}], "billing": {"creditsCharged": 2},
                "pagination": {"page": 0, "size": 25, "total": 100},
                "job": {"id": "job-1", "status": "pending"}}
    status = 201 if operation.startswith("create_") else 200
    requests = transport(monkeypatch, lambda request: httpx.Response(status, json=response))
    result = await node(config).execute({})
    assert result == {"status": "success", "operation": operation, "data": response}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == expected["method"]
    assert request.url.host == "api.lusha.com"
    assert request.url.path == expected["path"].replace("{table_id}", config.get("table_id", ""))
    assert request.headers["api_key"] == TOKEN and "authorization" not in request.headers
    if expected["method"] == "GET" or operation in {"delete_contacts_table", "delete_companies_table"}:
        assert not request.content
        query = {k: str(v) for k, v in config.items() if k not in {"operation", "table_id"}}
        if operation.endswith("table_entities"):
            query = {"page": "0", "size": "100", **query}
        assert dict(request.url.params) == query
    else:
        assert not request.url.query
        sent = json.loads(request.content)
        # Every documented input field is sent, including explicit false values.
        for key, value in config.items():
            if key not in {"operation", "table_id"}:
                assert sent[key] == value
        assert "table_id" not in sent and "operation" not in sent
        if operation.startswith("remove_"):
            assert request.method == "DELETE" and "owner" in sent


@pytest.mark.asyncio
async def test_editor_json_false_flags_and_omitted_patch_fields(monkeypatch):
    requests = transport(monkeypatch, {"data": {"tableId": "482910", "status": "active"}})
    await node({"operation": "update_contacts_table", "table_id": "482910",
                "owner": '{"email":"user@example.com"}', "archived": False}).execute({})
    assert json.loads(requests[0].content) == {"owner": {"email": "user@example.com"}, "archived": False}
    assert len(requests) == 1
    requests = transport(monkeypatch, {"results": []})
    await node({"operation": "enrich_contacts", "ids": '["4389064654"]',
                "reveal": '["emails"]', "waterfallEnabled": False}).execute({})
    assert json.loads(requests[0].content) == {"ids": ["4389064654"], "reveal": ["emails"], "waterfallEnabled": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 204, 301, 400, 401, 402, 403, 404, 429, 500])
async def test_errors_preserve_provider_rejection_redact_key_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, lambda request: httpx.Response(status, json={"message": "Rejected " + TOKEN},
        headers={"Location": "https://example.invalid/"}))
    result = await node({"operation": "get_account_usage"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Rejected [redacted]"}
    assert len(requests) == 1 and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [[], None, {"error": "failed"}, {"errors": ["failed"]}])
async def test_invalid_success_and_error_envelopes_are_rejected(monkeypatch, response):
    transport(monkeypatch, lambda request: httpx.Response(200, json=response))
    with pytest.raises(ValueError):
        await node({"operation": "get_account_usage"}).execute({})


@pytest.mark.asyncio
async def test_connection_reads_account_and_uses_only_manually_entered_key(monkeypatch):
    credential = native.LushaAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "lusha_api_key"
    requests = transport(monkeypatch, {"credits": {"total": 10000, "used": 1500, "remaining": 8500}})
    result = await node({"operation": "get_account_usage"}, credential.model_dump()).execute({})
    assert result["data"]["credits"]["remaining"] == 8500
    assert requests[0].url.path == "/v3/account/usage"
    assert native.LushaNode.connection_evidence.operation == "get_account_usage"


@pytest.mark.parametrize("config", [
    {"operation": "get_contacts_table", "table_id": "482910"},
    {"operation": "create_contacts_table", "name": "Owned table", "owner": {}},
    {"operation": "remove_contacts_table_entities", "table_id": "482910", "entityIds": ["10042851"]},
    {"operation": "get_companies_table", "table_id": "../account/usage", "email": "user@example.com"},
    {"operation": "get_companies_table", "table_id": "..", "email": "user@example.com"},
    {"operation": "search_contacts", "contacts": []},
    {"operation": "enrich_contacts", "ids": ["1"] * 101},
    {"operation": "prospecting_contacts", "pagination": {"page": 1001, "size": 5}, "filters": {}},
    {"operation": "get_account_usage", "url": "https://example.invalid/"},
])
def test_required_ownership_path_bounds_and_closed_config(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_credential_picker_metadata_is_not_a_provider_parameter():
    parsed = native.LushaNode.parse_config({"config": {"operation": "get_account_usage", "credentialIds": {"lusha_api_key": "saved-key"}}, "credentials": {"api_key": TOKEN}})
    assert parsed.config.model_dump() == {"operation": "get_account_usage"}
