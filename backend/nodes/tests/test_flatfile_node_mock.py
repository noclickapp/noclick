"""Native factory and HTTP contract regressions; no live account or API key."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import flatfile_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/flatfile/requests.json").read_text())
KEY = "sk_synthetic_flatfile_key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="flatfile-test", node_type="automation-flatfile",
        node_data={"config": config, "credentials": {"credential_type": "flatfile_api_key", "api_key": KEY}})


def mock(monkeypatch, response):
    requests = []
    def send(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_flatfile_requests_and_envelopes(monkeypatch, case):
    requests = mock(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == case["response"]["data"]
    assert KEY not in str(result)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.x.flatfile.com"
    assert request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["authorization"] == "Bearer " + KEY
    assert request.headers["x-disable-hooks"] == "true"
    assert (json.loads(request.content) if request.content else None) == case["body"]
    if "pagination" in case["response"]:
        assert result["pagination"] == case["response"]["pagination"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 202, 204, 301, 302, 400, 401, 403, 404, 429, 500])
async def test_flatfile_non200_never_claims_success_or_leaks_secret(monkeypatch, status):
    requests = mock(monkeypatch, lambda request: httpx.Response(status, json={"error": KEY}, headers={"Location": "https://example.test"}))
    with pytest.raises(ValueError, match=f"HTTP {status}") as error:
        await node({"operation": "get_current_account"}).execute({})
    assert KEY not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": []}, {"data": {"success": False}}, {"data": {}, "errors": [{"message": KEY}]}])
async def test_flatfile_invalid_envelope(monkeypatch, body):
    mock(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_current_account"}).execute({})


def test_flatfile_manual_credential_default_and_schema():
    credential = native.FlatfileApiKeyCredential(api_key="  " + KEY + "  ")
    assert credential.credential_type == "flatfile_api_key" and credential.api_key == KEY
    assert KEY not in repr(credential)
    assert native.FlatfileNode.connection_evidence.operation == "list_spaces"
    assert len(CASES) == len(native.OPERATIONS) == 24
    for key in ["pk_publishable", "https://example.test", "Bearer sk_example", ""]:
        with pytest.raises(ValidationError):
            native.FlatfileApiKeyCredential(api_key=key)


@pytest.mark.parametrize("config", [
    {"operation": "get_sheet", "sheet_id": "../other"},
    {"operation": "list_sheets"},
    {"operation": "list_spaces", "page_number": 0},
    {"operation": "create_workbook"},
    {"operation": "insert_records", "sheet_id": "us_sh_123", "records": []},
    {"operation": "update_records", "sheet_id": "us_sh_123", "records": [{"values": {"email": {"value": "a"}}}]},
    {"operation": "delete_records", "sheet_id": "us_sh_123", "record_ids": []},
    {"operation": "delete_records", "sheet_id": "us_sh_123", "record_ids": ["us_rc_1"] * 101},
])
def test_flatfile_missing_required_values_and_unsafe_ids(config):
    with pytest.raises(ValueError):
        node(config)
