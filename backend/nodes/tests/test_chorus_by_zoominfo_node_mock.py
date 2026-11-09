"""Contract routes, JSON:API bodies, multipart and published response regressions."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import chorus_by_zoominfo_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-chorus-token-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/chorus-by-zoominfo/published_examples.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="chorus-test", node_type=native.ChorusByZoomInfoNode.integration_type,
        node_data={"config": config, "credentials": {"credential_type": "chorus_by_zoominfo_api_token", "api_token": TOKEN}})


def transport(monkeypatch, body=None, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_current_user"}, "GET", "/api/v1/users/me"),
    ({"operation": "list_users"}, "GET", "/v3/users"),
    ({"operation": "list_engagements", "with_trackers": True, "continuation_key": "1591110020.0 20C790A0EB9646DBB95725D7951C2506"}, "GET", "/v3/engagements"),
    ({"operation": "get_conversation", "id": "call_123", "fields": "recording.utterances"}, "GET", "/api/v1/conversations/call_123"),
    ({"operation": "delete_engagement", "engagement_id": "call_123"}, "DELETE", "/v3/engagements/call_123"),
    ({"operation": "list_teams"}, "GET", "/api/v1/teams"),
    ({"operation": "get_team", "id": "123"}, "GET", "/api/v1/teams/123"),
    ({"operation": "list_playlists", "name": "Sales + wins", "page_number": 2, "page_size": 100, "subscribed": False}, "GET", "/api/v1/playlists"),
    ({"operation": "get_playlist", "id": "123"}, "GET", "/api/v1/playlists/123"),
    ({"operation": "create_playlist", "name": "My first playlist", "description": "My first playlist description."}, "POST", "/api/v1/playlists"),
    ({"operation": "delete_playlist", "id": "123"}, "DELETE", "/api/v1/playlists/123"),
    ({"operation": "list_moments", "shared_on": "2021-01-01T00:00:00Z:2021-01-31T00:00:00Z"}, "GET", "/api/v1/moments"),
    ({"operation": "create_moment", "callid": "call_id_12345", "moment_duration": 7, "moment_time": 0.0, "note": "", "subject": "", "url_string": ""}, "POST", "/api/v1/moments"),
    ({"operation": "update_moment", "id": "11111", "moment_time": 3.0, "note": ""}, "PUT", "/api/v1/moments/11111"),
    ({"operation": "delete_moment", "id": "123"}, "DELETE", "/api/v1/moments/123"),
    ({"operation": "list_webhooks"}, "GET", "/v3/webhook"),
    ({"operation": "create_webhook", "hook_url": "https://example.com/webhook"}, "POST", "/v3/webhook"),
    ({"operation": "delete_webhook", "hook_url": "https://example.com/webhook"}, "DELETE", "/v3/webhook"),
    ({"operation": "upload_recording", "data": "data:audio/wav;base64,UklGRg==", "name": "Recording", "user": "owner@example.com"}, "POST", "/v3/upload"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", CASES, ids=["chorus-by-zoominfo:" + config["operation"] for config, _, _ in CASES])
async def test_chorus_by_zoominfo_exact_contract_requests(monkeypatch, config, method, path):
    from nodes.core import media_resolver
    monkeypatch.setattr(media_resolver, "resolve_media_input", AsyncMock(return_value=SimpleNamespace(data=b"RIFF", filename="call.wav", mime_type="audio/wav")))
    requests = transport(monkeypatch, {"data": {"id": "123", "type": "fixture", "attributes": {"name": "Account"}}})
    result = await node(config).execute({})
    assert result["status"] == "success" and len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == path and req.url.host == "chorus.ai"
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    if config["operation"] == "list_playlists":
        assert dict(req.url.params) == {"filter[name]": "Sales + wins", "page[number]": "2", "page[size]": "100", "filter[subscribed]": "false"}
    if config["operation"] == "list_moments":
        assert req.url.params["filter[shared_on]"] == config["shared_on"]
    if config["operation"] in {"create_playlist", "create_moment", "update_moment"}:
        body = json.loads(req.content)["data"]
        # The shared runtime treats blank text inputs as unset. Chorus supplies
        # the documented empty defaults when these optional attributes are omitted.
        expected = {k: v for k, v in config.items() if k not in {"operation", "id"} and v != ""}
        assert body["attributes"] == expected
        assert req.headers["content-type"] == "application/vnd.api+json"
        if "id" in config:
            assert body["id"] == config["id"]
    if config["operation"] == "delete_webhook":
        assert json.loads(req.content) == {"hook_url": config["hook_url"]}
    if config["operation"] == "upload_recording":
        assert req.headers["content-type"].startswith("multipart/form-data;")
        assert b'name="data"; filename="call.wav"' in req.content and b"RIFF" in req.content
        assert b'name="enforce_unique_meeting_id"' not in req.content
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,example", [("list_engagements", "engagements"), ("list_webhooks", "webhooks")])
async def test_chorus_by_zoominfo_published_responses_preserved(monkeypatch, operation, example):
    transport(monkeypatch, EXAMPLES[example])
    result = await node({"operation": operation}).execute({})
    assert result["data"] == EXAMPLES[example]


@pytest.mark.asyncio
async def test_chorus_by_zoominfo_async_and_empty_delete(monkeypatch):
    transport(monkeypatch, {}, 202)
    result = await node({"operation": "delete_engagement", "engagement_id": "call123"}).execute({})
    assert result["accepted_for_processing"] and "deletion_acknowledged" not in result
    transport(monkeypatch, status=204)
    result = await node({"operation": "delete_moment", "id": "123"}).execute({})
    assert result["deletion_acknowledged"] and result["data"] is None


@pytest.mark.asyncio
async def test_chorus_by_zoominfo_rejection_and_redaction(monkeypatch):
    transport(monkeypatch, {"errors": [{"detail": "Rejected " + TOKEN}]}, 401)
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_current_user"}).execute({})
    assert "401" in str(error.value) and TOKEN not in str(error.value)
    transport(monkeypatch, {"data": {"api_token": TOKEN, "password": "private", "message": TOKEN}})
    result = await node({"operation": "get_current_user"}).execute({})
    assert TOKEN not in str(result) and "private" not in str(result)


def test_chorus_by_zoominfo_manual_credential_default_and_required_fields():
    c = native.ChorusAPITokenCredential(api_token=TOKEN)
    assert c.credential_type == "chorus_by_zoominfo_api_token"
    for token in ("https://chorus.ai", "hello\nworld"):
        with pytest.raises(ValidationError):
            native.ChorusAPITokenCredential(api_token=token)
    with pytest.raises(ValidationError):
        native.CreateMoment(callid="123", moment_time=0)
    assert {c[0]["operation"] for c in CASES} == set(native.ROUTES)
