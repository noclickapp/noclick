"""SumoQuote API v2 route, payload, pagination and connection regressions.

Synthetic HTTP fixtures; no SumoQuote account or credential is used.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import sumoquote_node as native
from nodes.core.registry import NodeFactory

ID = "7cc408bd-3879-482c-b990-d8fc90a0196f"
REPORT = "950fb67e-dabb-4df2-b9ca-38d91beb2cec"
TOKEN = "sumoquote-unit-test-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="sumoquote-test", node_type="automation-sumoquote",
        node_data={"config": config, "credentials": credentials or {"credential_type": "sumoquote_api_key", "api_key": TOKEN}})


def transport(monkeypatch, *, status=200, body=None):
    requests = []
    def reply(request):
        requests.append(request)
        if status == 204:
            return httpx.Response(status)
        return httpx.Response(status, json=body if body is not None else {"data": {}, "errors": [], "continuation": None})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,extra,method,path,status", [
    ("search_projects", {"q": "Smith", "continuation": "page-two"}, "GET", "/v2/Project", 200),
    ("list_projects", {}, "GET", "/v2/Project/all", 200),
    ("get_project", {"project_id": "job/7 ?#"}, "GET", "/v2/Project/job%2F7%20%3F%23", 200),
    ("create_project", {"customerFirstName": "Jamie", "addressLine1": "123 Main St"}, "POST", "/v2/Project", 201),
    ("update_project", {"project_id": ID, "estimate": 0, "customerFirstName": "Jamie"}, "PUT", f"/v2/Project/{ID}", 204),
    ("delete_project", {"project_id": ID}, "DELETE", f"/v2/Project/{ID}", 204),
    ("list_reports", {"project_id": ID, "continuation": "page-two"}, "GET", f"/v2/Project/{ID}/Report", 200),
    ("get_report", {"project_id": ID, "report_id": REPORT}, "GET", f"/v2/Project/{ID}/Report/{REPORT}", 200),
    ("get_signature_details", {"project_id": ID, "report_id": REPORT}, "GET", f"/v2/Project/{ID}/Report/{REPORT}/signingDetail", 200),
    ("download_report", {"project_id": ID, "report_id": REPORT}, "GET", f"/v2/Project/{ID}/Report/{REPORT}/download", 200),
    ("list_users", {"continuation": "page-two"}, "GET", "/v2/User", 200),
    ("get_profile", {}, "GET", "/v2/User/me", 200),
])
async def test_operations_send_one_contract_request(monkeypatch, operation, extra, method, path, status):
    requests = transport(monkeypatch, status=status)
    result = await node({"operation": operation, **extra}).execute({})
    assert result["status"] == "success" and result["http_status"] == status
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).split("?", 1)[0] == "https://api.sumoquote.com" + path
    assert request.headers["sq-api-key"] == TOKEN
    assert "authorization" not in request.headers
    assert request.headers.get("X-SQ-Continuation") == extra.get("continuation")
    assert dict(request.url.params) == ({"q": "Smith"} if operation == "search_projects" else {})
    if method in {"PUT", "POST"}:
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {k: v for k, v in extra.items() if k != "project_id"}
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_list_preserves_opaque_pagination_and_account_records(monkeypatch):
    body = json.loads((Path(__file__).parent / "fixtures/sumoquote/projects.json").read_text())
    requests = transport(monkeypatch, body=body)
    result = await node({"operation": "list_projects"}).execute({})
    assert result["data"] == body["data"]
    assert result["continuation"] == body["continuation"]
    assert len(requests) == 1
    assert native.SumoQuoteNode.connection_evidence.operation == "list_projects"
    assert native.SumoQuoteNode.connection_evidence.identity_operation == "get_profile"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": "API key rejected"}), (200, {"errors": ["Account unavailable"]}), (302, {"message": "Redirect"}), (200, [])])
async def test_errors_and_redirects_do_not_become_success(monkeypatch, status, body):
    requests = transport(monkeypatch, status=status, body=body)
    with pytest.raises(ValueError):
        await node({"operation": "list_projects"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_provider_rejection_redacts_credential(monkeypatch):
    transport(monkeypatch, status=401, body={"message": "Rejected " + TOKEN})
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_profile"}).execute({})
    assert TOKEN not in str(exc.value)
    assert "Rejected" in str(exc.value)


@pytest.mark.asyncio
async def test_pdf_url_is_returned_without_following_it(monkeypatch):
    url = "https://files.sumoquote.com/example.pdf"
    requests = transport(monkeypatch, body={"data": {"fileUrl": url}, "errors": []})
    result = await node({"operation": "download_report", "project_id": ID, "report_id": REPORT}).execute({})
    assert result["data"]["fileUrl"] == url and len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "create_project", "customerFirstName": "Jamie"},
    {"operation": "update_project", "project_id": "not-uuid"},
    {"operation": "get_report", "project_id": ID, "report_id": "../escape"},
])
def test_required_fields_and_uuid_constraints(config):
    with pytest.raises(ValueError):
        node(config)


def test_credential_can_be_pasted_with_default_type():
    credential = native.SumoQuoteAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "sumoquote_api_key"
    for invalid in ("https://example.com/key", "bad\r\nheader", "Bearer abc"):
        with pytest.raises(ValidationError):
            native.SumoQuoteAPIKeyCredential(api_key=invalid)


@pytest.mark.asyncio
async def test_update_omits_unset_fields(monkeypatch):
    requests = transport(monkeypatch, status=204)
    await node({"operation": "update_project", "project_id": ID, "estimate": 0}).execute({})
    assert json.loads(requests[0].content) == {"estimate": 0}
