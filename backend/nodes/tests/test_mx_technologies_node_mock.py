"""MX request contracts and manual credential regressions; no live account calls."""
import base64
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import mx_technologies_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/mx-technologies/requests.json").read_text())
CREDENTIAL = {"credential_type": "mx_technologies_api_key", "client_id": "synthetic-client-id", "api_key": "synthetic-api-key"}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id="mx-fixture", node_type="automation-mx-technologies",
        node_data={"config": config, "credentials": {**CREDENTIAL, **credential}})


def transport(monkeypatch, status, body):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_documented_request_mapping(monkeypatch, case):
    requests = transport(monkeypatch, case["status"], case["response"])
    result = await node(case["config"]).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    cfg = case["config"]
    assert request.url.path == case["path"].format(**cfg)
    assert request.url.host == "int-api.mx.com"
    assert request.headers["Accept-Version"] == "v20260929"
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"synthetic-client-id:synthetic-api-key").decode()
    if case["body"]:
        assert json.loads(request.content) == case["body"]
    else:
        assert request.content == b""
    if case["method"] == "GET" and cfg["operation"].startswith("list_"):
        assert dict(request.url.params) == {"page": "1", "records_per_page": "25"}
    assert result == ({"success": True, "http_status": 204} if case["status"] == 204 else case["response"])


@pytest.mark.asyncio
async def test_explicit_production_paging_date_filters_and_encoding(monkeypatch):
    requests = transport(monkeypatch, 200, {"transactions": [], "pagination": {"current_page": 3, "total_pages": 4}})
    result = await node({"operation": "list_transactions", "user_identifier": "user/id?x", "page": 3,
        "records_per_page": 100, "from_date": "2026-10-01", "to_date": "2026-10-31"}, environment="production").execute({})
    assert requests[0].url.host == "api.mx.com"
    assert requests[0].url.raw_path.startswith(b"/users/user%2Fid%3Fx/transactions?")
    assert dict(requests[0].url.params) == {"page": "3", "records_per_page": "100", "from_date": "2026-10-01", "to_date": "2026-10-31"}
    assert result["pagination"]["total_pages"] == 4
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_failure_is_not_success_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, status, {"error": "rejected synthetic-api-key"})
    with pytest.raises(ValueError, match=f"HTTP {status}") as exc:
        await node({"operation": "create_user", "id": "customer"}).execute({})
    assert "synthetic-api-key" not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_connection_evidence_uses_account_specific_users(monkeypatch):
    assert native.MxTechnologiesNode.connection_evidence.operation == "list_users"
    transport(monkeypatch, 200, {"users": [{"guid": "USR-owned", "email": "customer@example.com"}]})
    result = await node({"operation": "list_users"}).execute({})
    assert result["users"][0]["email"] == "customer@example.com"


def test_manual_credential_defaults_and_closed_operations():
    assert native.MxTechnologiesApiKeyCredential(client_id="client", api_key="key").credential_type == "mx_technologies_api_key"
    for cfg in [{"operation": "create_user"}, {"operation": "update_transaction", "user_guid": "u", "transaction_guid": "t"},
                {"operation": "list_users", "page": 0}, {"operation": "list_users", "records_per_page": 1001},
                {"operation": "list_users", "url": "https://evil.invalid"}, {"operation": "read_user", "user_identifier": ".."}]:
        with pytest.raises((ValueError, ValidationError)):
            node(cfg)
    for changes in [{"api_key": "https://example.com/key"}, {"client_id": "bad:client"}, {"environment": "other"}]:
        with pytest.raises(ValidationError):
            native.MxTechnologiesApiKeyCredential.model_validate({**CREDENTIAL, **changes})
