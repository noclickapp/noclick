"""Factory-level Listen Notes wire, credential, error and mutation regressions."""
import json
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
import pytest
from pydantic import ValidationError

from nodes import listennotes_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-listen-key-42"
CASES = json.loads((Path(__file__).parent / "fixtures/listennotes/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="listen-fixture", node_type="automation-listennotes",
        node_data={"config": config, "credentials": {"api_key": TOKEN}})


def transport(monkeypatch, body=None, status=200, handler=None):
    requests = []
    def respond(request):
        requests.append(request)
        return handler(request) if handler else httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda x: x["config"]["operation"])
async def test_each_operation_sends_exactly_one_contract_request(monkeypatch, case):
    payload = {**case["response"], "next_offset": 10, "has_next": True, "last_timestamp_ms": 1595567004958}
    requests = transport(monkeypatch, payload)
    result = await node(case["config"]).execute({})
    assert result["data"] == payload and result["success"] is True
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url).startswith(native.BASE + case["path"])
    assert request.url.path == "/api/v2" + case["path"]
    assert request.headers["X-ListenAPI-Key"] == TOKEN
    assert request.headers["Accept"] == "application/json"
    assert dict(request.url.params) == case["query"]
    assert dict(parse_qsl(request.content.decode(), keep_blank_values=True)) == case["form"]
    if case["form"]:
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("config,expected", [
    ({"operation": "update_playlist", "id": "m1pe7z60bsw", "clear_description": True}, {"description": ""}),
    ({"operation": "update_playlist_item", "id": "m1pe7z60bsw", "item_id": 23, "clear_notes": True}, {"notes": ""}),
    ({"operation": "add_playlist_item", "id": "m1pe7z60bsw", "podcast_id": "a" * 32}, {"podcast_id": "a" * 32}),
])
async def test_clearing_and_omission_survive_runtime_config_lens(monkeypatch, config, expected):
    requests = transport(monkeypatch, {"id": "m1pe7z60bsw", "name": "Reading"} if config["operation"] == "update_playlist" else {"id": 23, "data": {"id": "a" * 32}})
    await node(config).execute({})
    assert dict(parse_qsl(requests[0].content.decode(), keep_blank_values=True)) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_refusal_and_secret_redaction(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "Denied " + TOKEN}, status)
    result = await node({"operation": "list_playlists"}).execute({})
    assert not result["success"] and result["status_code"] == status
    assert "Denied" in result["error"] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], None, {}, {"playlists": {}}, {"error": "invalid"}, {"errors": ["invalid"]}])
async def test_malformed_or_error_response_never_succeeds(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="(?:unexpected|non-JSON) response"):
        await node({"operation": "list_playlists"}).execute({})


@pytest.mark.asyncio
async def test_non_json_and_ambiguous_write_transport_failure(monkeypatch):
    transport(monkeypatch, handler=lambda r: httpx.Response(200, text="<html>bad</html>"))
    with pytest.raises(ValueError, match="non-JSON"):
        await node({"operation": "list_playlists"}).execute({})
    def fail(request):
        raise httpx.ReadTimeout("secret " + TOKEN, request=request)
    requests = transport(monkeypatch, handler=fail)
    with pytest.raises(ValueError, match="inspect writes before retrying") as exc:
        await node({"operation": "create_playlist", "name": "Reading"}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_podcast", "id": "../other"},
    {"operation": "update_playlist", "id": "m1pe7z60bsw"},
    {"operation": "create_playlist", "name": " RSS "},
    {"operation": "add_playlist_item", "id": "m1pe7z60bsw"},
    {"operation": "add_playlist_item", "id": "m1pe7z60bsw", "episode_id": "a" * 32, "podcast_id": "b" * 32},
    {"operation": "delete_playlist_item", "id": "m1pe7z60bsw", "item_id": 0},
    {"operation": "search", "q": "hello", "safe_mode": 2},
    {"operation": "search", "q": "hello", "page_size": 0},
    {"operation": "search", "q": "hello", "page_size": 11},
    {"operation": "update_playlist_item", "id": "m1pe7z60bsw", "item_id": 23},
])
def test_invalid_inputs_refused(config):
    with pytest.raises((ValueError, ValidationError)):
        native.ListenNotesNode.parse_config({"config": config, "credentials": {"api_key": TOKEN}})


def test_manual_credential_default_and_account_evidence():
    credential = native.ListenNotesAPIKeyCredential.model_validate({"api_key": "  " + TOKEN + "\n"})
    assert credential.credential_type == "listennotes_api_key" and credential.api_key == TOKEN
    assert native.ListenNotesNode.connection_evidence.operation == "list_playlists"
    assert native.ListenNotesNode.connection_evidence.proves != "reachability"
    for key in ["https://example.com/key", "<token>", "bad\r\nkey"]:
        with pytest.raises(ValidationError):
            native.ListenNotesAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,route", [
    ("search", "GET /search"),
    ("get_playlist", "GET /playlists/{id}"),
    ("add_playlist_item", "POST /playlists/{id}/items"),
    ("update_playlist_item", "PUT /playlists/{id}/items/{item_id}"),
])
async def test_provider_published_responses_preserved(monkeypatch, operation, route):
    """Examples copied whole from the provider docs, with each source beside it."""
    fixtures = json.loads((Path(__file__).parent / "fixtures/listennotes/documented_responses.json").read_text())
    payload = fixtures[route]["body"]
    assert fixtures[route]["source"].startswith("https://")
    transport(monkeypatch, payload)
    config = next(c["config"] for c in CASES if c["config"]["operation"] == operation)
    result = await node(config).execute({})
    assert result["success"] is True and result["data"] == payload
