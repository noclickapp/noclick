"""Exercise Visualping's real node through the factory with intercepted HTTP.

Synthetic responses cover routing, paging, partial writes and credential evidence
without signing into an account or changing a real monitor.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import visualping_node as native
from nodes.core.registry import NodeFactory

TOKEN = "visualping-test-key-493"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/visualping/responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="visualping-fixture", node_type="automation-visualping",
        node_data={"config": config, "credentials": {"credential_type": "visualping_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["describe_user", "list_workspaces"])
async def test_account_read_and_evidence(monkeypatch, op):
    calls = transport(monkeypatch, FIXTURE["account"])
    result = await node({"operation": op}).execute({})
    assert result["status"] == "success" and result["email"] == "user@example.com"
    assert calls[0].url == native.ACCOUNT_URL + "/describe-user"
    assert calls[0].headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result)
    if op == "list_workspaces":
        assert result["items"] == [{"id": 137389, "name": "Monitoring", "role": "ADMIN"}]
        assert "data" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("op,extra,query", [
    ("list_jobs", {}, {}),
    ("search_jobs", {"search": "Google News"}, {"fullTextSearchFilter": "Google News"}),
    ("list_changed_jobs", {}, {"eventFilter": "changed", "dateFilter": "since_yesterday"}),
    ("list_paused_jobs", {}, {"activeFilter": "0"}),
])
async def test_job_lists_filters_and_pagination(monkeypatch, op, extra, query):
    calls = transport(monkeypatch, FIXTURE["list"])
    result = await node({"operation": op, "workspace_id": 137389, **extra}).execute({})
    assert result["status"] == "success" and result["items"][0]["id"] == 123456
    assert result["next_page_index"] == 1
    assert calls[0].method == "GET" and calls[0].url.host == "job.api.visualping.io"
    assert dict(calls[0].url.params) == {"workspaceId": "137389", "pageIndex": "0", "pageSize": "100", "mode": "normal", **query}
    transport(monkeypatch, {**FIXTURE["list"], "jobs": [], "totalPages": 0})
    assert (await node({"operation": op, **extra}).execute({}))["next_page_index"] is None


@pytest.mark.asyncio
async def test_count_jobs_uses_counts_only(monkeypatch):
    calls = transport(monkeypatch, {k: v for k, v in FIXTURE["list"].items() if k != "jobs"})
    result = await node({"operation": "count_jobs"}).execute({})
    assert result["data"]["totalJobs"] == 101 and "items" not in result
    assert dict(calls[0].url.params) == {"mode": "counts_only"}


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["get_job", "get_job_history"])
async def test_job_details_and_history(monkeypatch, op):
    calls = transport(monkeypatch, FIXTURE["job"])
    result = await node({"operation": op, "job_id": 123456, "workspace_id": 137389}).execute({})
    assert result["status"] == "success" and result["data"]["id"] == "123456"
    assert calls[0].url.path == "/v2/jobs/123456" and calls[0].url.params["workspaceId"] == "137389"
    if op == "get_job_history":
        assert set(result["data"]) == {"id", "history", "changes"}
    transport(monkeypatch, {**FIXTURE["job"], "id": "999"})
    assert (await node({"operation": op, "job_id": 123456}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_create_sends_all_required_fields_and_native_types(monkeypatch):
    calls = transport(monkeypatch, {"id": "internal", "jobid": "123456"})
    result = await node({"operation": "create_job", "url": "https://example.com", "workspace_id": 137389, "label_ids": [121, 345]}).execute({})
    assert result["status"] == "success" and result["job_id"] == "123456" and result["write_acknowledged"]
    request = calls[0]
    assert request.method == "POST" and request.url.path == "/v2/jobs" and not request.url.query
    assert json.loads(request.content) == {"workspaceId": 137389, "url": "https://example.com", "mode": "ALL", "active": True,
        "interval": "1440", "trigger": "1", "target_device": "4", "wait_time": 0, "labelIds": [121, 345]}


@pytest.mark.asyncio
@pytest.mark.parametrize("op,extra,expected", [
    ("update_job", {"description": "Price monitor"}, {"description": "Price monitor"}),
    ("pause_job", {}, {"active": False}),
    ("resume_job", {}, {"active": True}),
    ("set_job_frequency", {"interval": "15"}, {"interval": "15"}),
    ("set_job_keywords", {"keywords": "price,stock", "keyword_action": "ADDED"}, {"keywords": "price,stock", "keyword_action": "ADDED"}),
    ("set_job_labels", {"label_ids": []}, {"labelIds": []}),
])
async def test_partial_updates_do_not_reset_other_settings(monkeypatch, op, extra, expected):
    calls = transport(monkeypatch, FIXTURE["update"])
    result = await node({"operation": op, "job_id": 123456, "workspace_id": 137389, "organisation_id": 137388, **extra}).execute({})
    assert result["status"] == "success" and result["write_acknowledged"]
    assert len(calls) == 1 and calls[0].method == "PUT" and calls[0].url.path == "/v2/jobs/123456"
    assert json.loads(calls[0].content) == {"workspaceId": 137389, "organisationId": 137388, **expected}


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [True, False])
async def test_delete_reports_provider_acknowledgement(monkeypatch, changed):
    calls = transport(monkeypatch, {"changed": changed, "deletedJobIds": [123456] if changed else []})
    result = await node({"operation": "delete_job", "job_id": 123456, "workspace_id": 137389}).execute({})
    assert result["write_acknowledged"] is changed
    assert calls[0].method == "DELETE" and calls[0].url.path == "/v2/jobs/123456"
    assert dict(calls[0].url.params) == {"workspaceId": "137389"} and not calls[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_provider_errors_remain_errors_and_preserve_rejection(monkeypatch, status):
    calls = transport(monkeypatch, {"message": "API key rejected", "token": TOKEN}, status)
    result = await node({"operation": "describe_user"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "API key rejected" in result["error"] and TOKEN not in str(result) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,extra,body", [
    ("describe_user", {}, {}),
    ("list_jobs", {}, {"totalJobs": 1}),
    ("get_job_history", {"job_id": 123456}, {"id": "123456"}),
    ("create_job", {"url": "https://example.com"}, {}),
    ("delete_job", {"job_id": 123456}, {}),
    ("pause_job", {"job_id": 123456}, {"updates": "unknown"}),
])
async def test_malformed_responses_do_not_report_success(monkeypatch, operation, extra, body):
    transport(monkeypatch, body)
    assert (await node({"operation": operation, **extra}).execute({}))["status"] == "error"


@pytest.mark.parametrize("config", [
    {"operation": "create_job", "url": "file:///tmp/private"},
    {"operation": "update_job", "job_id": 123456},
    {"operation": "get_job", "job_id": "../other"},
    {"operation": "list_jobs", "date_filter": "since_custom_date"},
    {"operation": "set_job_frequency", "job_id": 1, "interval": "-1"},
    {"operation": "list_jobs", "page_index": -1},
    {"operation": "list_jobs", "page_size": 0},
])
def test_invalid_configs_rejected(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_credential_and_evidence_contract():
    parsed = native.VisualpingAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert parsed.api_key == TOKEN
    with pytest.raises((ValueError, ValidationError)):
        native.VisualpingAPIKeyCredential(api_key="Bearer " + TOKEN)
    assert native.VisualpingNode.connection_evidence.operation == "list_workspaces"
    assert native.VisualpingNode.connection_evidence.identity_operation == "describe_user"
