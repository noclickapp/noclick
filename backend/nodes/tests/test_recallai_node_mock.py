"""Synthetic transport tests: one published route per action, no live credentials."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import recallai_node as native
from nodes.core.registry import NodeFactory

ID = "7e730a9a-50cc-40ab-87b6-5f3a8a454601"
KEY = "synthetic-recall-key-42"
BOT = json.loads((Path(__file__).parent / "fixtures/recallai/bot.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id="recall-fixture", node_type="automation-recallai", node_data={
        "config": config, "credentials": {"credential_type": "recallai_api_key", "api_key": KEY, **credential}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ("list_bots", {}, "GET", "/api/v1/bot/"),
    ("get_bot", {"bot_id": ID}, "GET", f"/api/v1/bot/{ID}/"),
    ("create_bot", {"meeting_url": "https://zoom.us/j/123?pwd=456", "bot_name": "Team Notetaker"}, "POST", "/api/v1/bot/"),
    ("update_bot", {"bot_id": ID, "bot_name": "Updated"}, "PATCH", f"/api/v1/bot/{ID}/"),
    ("delete_bot", {"bot_id": ID}, "DELETE", f"/api/v1/bot/{ID}/"),
    ("leave_call", {"bot_id": ID}, "POST", f"/api/v1/bot/{ID}/leave_call/"),
    ("pause_recording", {"bot_id": ID}, "POST", f"/api/v1/bot/{ID}/pause_recording/"),
    ("resume_recording", {"bot_id": ID}, "POST", f"/api/v1/bot/{ID}/resume_recording/"),
    ("send_chat_message", {"bot_id": ID, "message": "Recording in progress"}, "POST", f"/api/v1/bot/{ID}/send_chat_message/"),
    ("list_recordings", {"bot_id": ID, "cursor": "cursor+one"}, "GET", "/api/v1/recording/"),
    ("get_recording", {"recording_id": ID}, "GET", f"/api/v1/recording/{ID}/"),
    ("delete_recording", {"recording_id": ID}, "DELETE", f"/api/v1/recording/{ID}/"),
    ("list_transcripts", {"recording_id": ID}, "GET", "/api/v1/transcript/"),
    ("get_transcript", {"transcript_id": ID}, "GET", f"/api/v1/transcript/{ID}/"),
    ("delete_transcript", {"transcript_id": ID}, "DELETE", f"/api/v1/transcript/{ID}/"),
    ("list_calendars", {"email": "team@example.com"}, "GET", "/api/v2/calendars/"),
    ("get_calendar", {"calendar_id": ID}, "GET", f"/api/v2/calendars/{ID}/"),
    ("delete_calendar", {"calendar_id": ID}, "DELETE", f"/api/v2/calendars/{ID}/"),
    ("list_calendar_events", {"calendar_id": ID, "is_deleted": False}, "GET", "/api/v2/calendar-events/"),
    ("get_calendar_event", {"event_id": ID}, "GET", f"/api/v2/calendar-events/{ID}/"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path", CASES)
async def test_exact_request_contract(monkeypatch, operation, config, method, path):
    def reply(request):
        if method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"results": [BOT], "next": None, "previous": None} if operation.startswith("list_") else BOT)
    requests = transport(monkeypatch, reply)
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "us-east-1.recall.ai"
    assert request.headers["Authorization"] == "Token " + KEY
    if method == "GET":
        expected = {k: str(v).lower() if isinstance(v, bool) else v for k, v in config.items() if k not in {"event_id", "transcript_id"} and (operation.startswith("list_") or k not in {"bot_id", "calendar_id", "recording_id"})}
        if operation == "list_bots":
            expected["page"] = "1"
        assert dict(request.url.params) == expected
    elif operation in native.BODY_OPERATIONS:
        body = json.loads(request.content)
        assert "bot_id" not in body and "operation" not in body
        if operation == "send_chat_message":
            assert body == {"message": config["message"], "pin": False}
        if operation == "update_bot":
            assert body == {"bot_name": "Updated"}
    else:
        assert request.content == b""
    if method == "DELETE":
        assert result["acknowledged"] and result["deleted_id"] == ID and not result["absence_verified"]


@pytest.mark.asyncio
@pytest.mark.parametrize("region", ["us-east-1", "us-west-2", "eu-central-1", "ap-northeast-1"])
async def test_regions_and_empty_workspace_evidence(monkeypatch, region):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={"results": [], "next": None, "previous": None, "count": 0}))
    result = await node({"operation": "list_bots"}, region=region).execute({})
    assert result["data"] == [] and result["complete"] and result["count"] == 0
    assert requests[0].url.host == region + ".recall.ai"


@pytest.mark.asyncio
async def test_continuations_are_data_never_fetched(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={"results": [BOT], "next": "https://other.example/api/v1/recording/?cursor=abc%2B1", "previous": None}))
    result = await node({"operation": "list_recordings"}).execute({})
    assert len(requests) == 1 and result["next_cursor"] == "abc+1" and not result["complete"]
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={"results": [], "next": "https://us-east-1.recall.ai/api/v1/bot/?page=2"}))
    result = await node({"operation": "list_bots"}).execute({})
    assert result["next_page"] == 2 and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_errors_redact_key_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={"detail": "Denied " + KEY}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "create_bot", "meeting_url": "https://zoom.us/j/123"}).execute({})
    assert KEY not in str(exc.value) and str(status) in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_uncertain_write_not_retried(monkeypatch):
    def reply(request):
        raise httpx.ReadTimeout("timeout " + KEY, request=request)
    requests = transport(monkeypatch, reply)
    with pytest.raises(ValueError, match="inspect the resource before retrying") as exc:
        await node({"operation": "leave_call", "bot_id": ID}).execute({})
    assert KEY not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {}, {"results": {}}])
async def test_malformed_list_not_success(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "list_bots"}).execute({})


@pytest.mark.asyncio
async def test_response_secrets_redacted(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, json={**BOT, "nested": {"refresh_token": "private", "oauth_refresh_token": "private-calendar", "oauth_client_secret": "private-client", "note": KEY}}))
    result = await node({"operation": "get_bot", "bot_id": ID}).execute({})
    assert KEY not in str(result) and "private" not in str(result)


@pytest.mark.parametrize("key", ["", "Token key", "https://recall.ai/key", "<token>", "abc\nxyz"])
def test_manual_key_validation(key):
    with pytest.raises(ValidationError):
        native.RecallaiAPIKeyCredential(api_key=key)


def test_manual_credential_default_and_closed_routes():
    credential = native.RecallaiAPIKeyCredential(api_key="  " + KEY + "\n")
    assert credential.credential_type == "recallai_api_key" and credential.api_key == KEY
    with pytest.raises(ValidationError):
        native.RecallaiAPIKeyCredential(api_key=KEY, region="attacker.example")
    with pytest.raises(ValueError):
        node({"operation": "get_bot", "bot_id": "../escape"})
    with pytest.raises(ValueError):
        node({"operation": "update_bot", "bot_id": ID})
