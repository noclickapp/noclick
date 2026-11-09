"""Lofty request serialization, account verification and provider response regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import lofty_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-lofty-key"
CREDENTIAL = {"credential_type": "lofty_api_key", "api_key": TOKEN}
FIXTURE = json.loads((Path(__file__).parent / "fixtures/lofty/contract.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="lofty-fixture", node_type="automation-lofty",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def config(operation):
    values = {"operation": operation}
    if operation in {"get_lead", "update_lead", "delete_lead", "list_notes", "create_note", "update_note", "list_tasks", "create_task", "send_email", "send_sms"}:
        values["leadId"] = 100001
    if operation in {"get_note", "update_note", "delete_note"}:
        values["noteId"] = 400000012345
    if operation in {"get_task", "update_task", "delete_task", "finish_task", "unfinish_task"}:
        values["taskId"] = 563172647619608
    if operation == "delete_lead":
        values["reason"] = "Duplicate contact"
    if operation in {"create_lead", "update_lead"}:
        values.update(firstName="Bob", tagsAdd=["Referral"], cannotText=False)
    if operation in {"create_note", "update_note", "create_task", "update_task", "send_email", "send_sms"}:
        values["content"] = "Follow up tomorrow"
    if operation == "create_task":
        values.update(type="Call", assignedRole="Agent", endAt="2026-03-01T16:00:00-08:00")
    if operation == "send_email":
        values["subject"] = "Welcome to our service"
    return values


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURE["routes"])
async def test_each_operation_sends_one_documented_request(monkeypatch, operation):
    response = {"id": 11, "memberUserId": 100234, "firstName": "Alice", "lastName": "Johnson"} if operation == "get_profile" else {"message": "success"}
    requests = transport(monkeypatch, response)
    result = await node(config(operation)).execute({})
    assert result["status"] == "success" and result["data"] == response
    assert len(requests) == 1
    request = requests[0]
    method, template = FIXTURE["routes"][operation]
    expected = template.format(leadId=100001, noteId=400000012345, taskId=563172647619608)
    assert request.method == method and request.url.path == expected
    assert request.url.host == "api.lofty.com"
    assert request.headers["Authorization"] == "token " + TOKEN
    assert request.headers["X-Error-Status"] == "true"
    assert request.headers["Content-Type"] == "application/json"
    if method in {"GET", "DELETE"}:
        assert not request.content
        if operation == "delete_lead":
            assert dict(request.url.params) == {"reason": "Duplicate contact"}
    elif request.content:
        body = json.loads(request.content)
        assert "operation" not in body
        for field in ("noteId", "taskId"):
            assert field not in body
        if operation in {"create_note", "update_note"}:
            assert body["isPin"] is False and body["leadId"] == 100001
        if operation == "update_lead":
            assert body == {"firstName": "Bob", "tagsAdd": ["Referral"], "cannotText": False}
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_paging_and_false_query_are_preserved(monkeypatch):
    body = {"leads": [], "_metadata": {"total": 0, "scrollId": "next-cursor"}}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_leads", "offset": 25, "limit": 25, "contacted": False, "scrollId": "previous"}).execute({})
    assert dict(requests[0].url.params) == {"offset": "25", "limit": "25", "contacted": "false", "scrollId": "previous"}
    assert result["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_http_failure_preserves_provider_rejection_without_key(monkeypatch, status):
    transport(monkeypatch, {"message": "Permission denied " + TOKEN}, status)
    result = await node({"operation": "get_profile"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Permission denied" in result["error"] and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_profile_proves_identity_and_empty_profile_fails(monkeypatch):
    transport(monkeypatch, {"id": 11, "memberUserId": 100234, "firstName": "Alice", "lastName": "Johnson"})
    result = await node({"operation": "get_profile"}).execute({})
    assert result["name"] == "Alice Johnson"
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match="identity"):
        await node({"operation": "get_profile"}).execute({})


@pytest.mark.asyncio
async def test_unsuccessful_business_outcome_is_error(monkeypatch):
    transport(monkeypatch, {"success": False})
    assert (await node(config("send_sms")).execute({}))["status"] == "error"


@pytest.mark.parametrize("changes", [
    {"operation": "get_lead", "leadId": 0},
    {"operation": "list_leads", "limit": 101},
    {"operation": "delete_lead", "leadId": 1},
    {"operation": "create_note", "leadId": 1, "content": " "},
    {"operation": "update_lead", "leadId": 1},
    {"operation": "update_task", "taskId": 1, "timeZoneCode": "UTC"},
    {"operation": "create_task", "leadId": 1, "type": "Call"},
    {"operation": "update_task", "taskId": 1, "endAt": "2026-03-01T16:00:00"},
    {"operation": "get_profile", "url": "https://example.com"},
])
def test_invalid_or_incomplete_configs_fail(changes):
    with pytest.raises((ValueError, ValidationError)):
        native.LoftyNode.parse_config({"config": changes, "credentials": CREDENTIAL})


def test_credential_can_be_filled_by_hand():
    credential = native.LoftyAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == "lofty_api_key" and credential.api_key == TOKEN
    with pytest.raises(ValueError):
        native.LoftyAPIKeyCredential(api_key="token " + TOKEN)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["delete_lead", "update_note", "delete_note"])
async def test_documented_empty_write_responses(monkeypatch, operation):
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    result = await node(config(operation)).execute({})
    assert result == {"status": "success", "data": None}
