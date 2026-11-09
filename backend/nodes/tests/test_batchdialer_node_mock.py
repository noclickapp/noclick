"""Offline request and documented-response regressions; no live credentials used."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import batchdialer_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/batchdialer/contract_examples.json").read_text())
KEY = "synthetic-batchdialer-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="batchdialer-test", node_type="automation-batchdialer",
        node_data={"config": config, "credentials": {"credential_type": "batchdialer_api_key", "api_key": KEY}})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_batchdialer_documented_contract_requests(monkeypatch, operation):
    case = CASES[operation]
    requests = transport(monkeypatch, httpx.Response(200, json=case["response"], headers={"X-Total-Count": "25"}))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == case["response"]
    assert result["total_count"] == "25"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    path = case["path"].replace("{contactID}", "29358").replace("{cdrID}", "29147")
    assert request.url.path == "/api" + path
    assert request.url.host == "app.batchdialer.com"
    assert request.headers["X-ApiKey"] == KEY
    assert KEY not in str(result) and KEY not in str(request.url)
    values = {k: v for k, v in case["config"].items() if k not in {"operation", "contact_id", "cdr_id"}}
    if operation in {"list_recent_calls", "list_recent_calls_v2"}:
        assert dict(request.url.params) == {k: str(v) for k, v in values.items()}
        assert not request.content
    elif operation == "list_contacts":
        assert dict(request.url.params) == {"page": "1", "pagelength": "100"}
        assert json.loads(request.content) == {"listid": 123}
    elif request.method in {"POST", "PUT"} or operation == "get_vendor_contact_ids":
        assert json.loads(request.content) == values
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_batchdialer_cursor_filters_passed_unchanged(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json={"data": [], "nextPage": "next+/="}))
    result = await node({"operation": "list_recent_calls_v2", "next_page": "cursor+/=", "direction": "inbound", "callDate": "2026-02-20T00:00:00Z"}).execute({})
    assert requests[0].url.params["next_page"] == "cursor+/="
    assert requests[0].url.params["callDate"] == "2026-02-20T00:00:00Z"
    assert result["data"]["nextPage"] == "next+/="


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_batchdialer_refusals_no_retries_and_redacted(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={"msg": "Rejected " + KEY}))
    result = await node(CASES["create_contact"]["config"]).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Rejected" in result["error"] and KEY not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_batchdialer_import_semantic_failure_and_preserved_warning(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"success": False, "msg": "Invalid contacts"}))
    result = await node(CASES["import_contacts"]["config"]).execute({})
    assert result["status"] == "error" and result["error"] == "Invalid contacts"
    transport(monkeypatch, httpx.Response(200, json={"success": False, "ids": [], "warnings": ["Existing contacts preserved"]}))
    result = await node(CASES["import_contacts"]["config"]).execute({})
    assert result["data"]["success"] is False
    assert result["data"]["warnings"] == ["Existing contacts preserved"]


@pytest.mark.parametrize("value", ["https://example.com/key", "line\nbreak", "x\r\ny", "", "<token>"])
def test_batchdialer_invalid_key(value):
    with pytest.raises((ValidationError, ValueError)):
        native.BatchDialerAPIKeyCredential(api_key=value)


def test_batchdialer_manual_type_default_and_closed_operations():
    assert native.BatchDialerAPIKeyCredential(api_key=KEY).credential_type == "batchdialer_api_key"
    with pytest.raises(ValidationError):
        native.GetContact(contact_id=-1)
    with pytest.raises(ValidationError):
        native.ListCampaigns(url="https://example.com")
    with pytest.raises(ValidationError):
        native.ListRecentCallsV2(pagelength=101)
