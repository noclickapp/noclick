"""Daily provider examples with a synthetic JWT substitute, using an offline transport."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from nodes import daily_node as daily
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-daily-key-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/daily/responses.json").read_text())


def test_daily_response_fixtures_have_no_real_shaped_credentials():
    # Provider documentation can itself contain signed credentials. Apply the
    # export's actual scanner rather than exempting fixtures or duplicating rules.
    root = Path(__file__).resolve().parents[3]
    scanner_path = root / "scripts/scan_real_secrets.py"
    if not scanner_path.exists():
        scanner_path = root / "oss/scan_real_secrets.py"
    spec = importlib.util.spec_from_file_location("daily_secret_scanner", scanner_path)
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    fixture = Path(__file__).parent / "fixtures/daily/responses.json"
    assert not scanner.find_secrets(fixture.read_bytes())
    assert EXAMPLES["create_meeting_token"]["body"]["token"] == "daily-example-meeting-token"
    assert EXAMPLES["create_meeting_token"]["redactions"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="daily-offline", node_type="automation-daily", node_data={
        "config": config, "credentials": {"credential_type": "daily_api_key", "api_key": TOKEN}})


def mock(monkeypatch, payload, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(daily, "guarded_async_client", client)
    return requests


# Expected routes are pinned to the provider's own contract, including POST
# for a room update and the singular /meeting-tokens path.
CASES = [
    ("list_rooms", {}, "GET", "/rooms"),
    ("create_room", {"name": "my-room", "privacy": "private", "enable_chat": True}, "POST", "/rooms"),
    ("get_room", {"room_name": "my-room"}, "GET", "/rooms/my-room"),
    ("update_room", {"room_name": "my-room", "start_video_off": False}, "POST", "/rooms/my-room"),
    ("delete_room", {"room_name": "my-room"}, "DELETE", "/rooms/my-room"),
    ("get_room_presence", {"room_name": "my-room"}, "GET", "/rooms/my-room/presence"),
    ("create_meeting_token", {"room_name": "my-room", "exp": 1900000000}, "POST", "/meeting-tokens"),
    ("validate_meeting_token", {"meeting_token": "eyJhbGci.eyJyb29t.signature"}, "GET", "/meeting-tokens/eyJhbGci.eyJyb29t.signature"),
    ("list_recordings", {}, "GET", "/recordings"),
    ("get_recording", {"recording_id": "recording-1"}, "GET", "/recordings/recording-1"),
    ("delete_recording", {"recording_id": "recording-1"}, "DELETE", "/recordings/recording-1"),
    ("get_recording_link", {"recording_id": "recording-1"}, "GET", "/recordings/recording-1/access-link"),
    ("list_meetings", {}, "GET", "/meetings"),
    ("get_meeting", {"meeting_id": "meeting-1"}, "GET", "/meetings/meeting-1"),
    ("list_meeting_participants", {"meeting_id": "meeting-1"}, "GET", "/meetings/meeting-1/participants"),
    ("get_presence", {}, "GET", "/presence"),
    ("get_domain", {}, "GET", "/"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path", CASES)
async def test_provider_examples_and_exactly_one_request(monkeypatch, operation, config, method, path):
    payload = EXAMPLES[operation]["body"]
    requests = mock(monkeypatch, payload)
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success"
    assert result["data"] == (payload["data"] if "data" in payload and isinstance(payload["data"], list) else payload)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/v1" + path
    assert request.url.host == "api.daily.co" and request.url.scheme == "https"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result)
    if method != "POST":
        assert request.content == b""


@pytest.mark.asyncio
async def test_nested_room_properties_omit_unset_keep_false(monkeypatch):
    requests = mock(monkeypatch, EXAMPLES["update_room"]["body"])
    await node({"operation": "update_room", "room_name": "my-room", "privacy": "private",
                "start_video_off": False, "enable_chat": True, "max_participants": 5}).execute({})
    assert json.loads(requests[0].content) == {
        "privacy": "private", "properties": {"start_video_off": False, "enable_chat": True, "max_participants": 5}}
    assert not requests[0].url.query


@pytest.mark.asyncio
async def test_create_room_server_generated_name(monkeypatch):
    requests = mock(monkeypatch, EXAMPLES["create_room"]["body"])
    await node({"operation": "create_room"}).execute({})
    assert json.loads(requests[0].content) == {}


@pytest.mark.asyncio
async def test_token_restricted_to_room_and_expiry(monkeypatch):
    requests = mock(monkeypatch, EXAMPLES["create_meeting_token"]["body"])
    result = await node({"operation": "create_meeting_token", "room_name": "my-room", "exp": 1900000000,
                        "is_owner": False, "user_id": "user-1", "eject_at_token_exp": True}).execute({})
    assert json.loads(requests[0].content) == {"properties": {"room_name": "my-room", "exp": 1900000000,
        "is_owner": False, "user_id": "user-1", "eject_at_token_exp": True}}
    assert result["data"]["token"] == EXAMPLES["create_meeting_token"]["body"]["token"]


@pytest.mark.asyncio
async def test_cursor_and_repeated_room_filters(monkeypatch):
    requests = mock(monkeypatch, {"total_count": 42, "data": []})
    result = await node({"operation": "list_meetings", "limit": 20, "starting_after": "session-1",
        "room": ["room-a", "room-b"], "timeframe_start": 1700000000, "ongoing": False,
        "no_participants": True}).execute({})
    assert requests[0].url.params.get_list("room") == ["room-a", "room-b"]
    assert requests[0].url.params["starting_after"] == "session-1"
    assert requests[0].url.params["ongoing"] == "false"
    assert requests[0].url.params["no_participants"] == "true"
    assert requests[0].url.params["timeframe_start"] == "1700000000"
    assert result["page_only"] is True and result["data"] == [] and result["total_count"] == 42
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_participant_cursors_and_room_presence_filters(monkeypatch):
    requests = mock(monkeypatch, {"data": []})
    await node({"operation": "list_meeting_participants", "meeting_id": "meeting-1", "joined_before": "participant-1", "limit": 10}).execute({})
    assert dict(requests[0].url.params) == {"joined_before": "participant-1", "limit": "10"}
    await node({"operation": "get_room_presence", "room_name": "room-1", "userId": "a+b/=", "userName": "Alice Smith"}).execute({})
    assert requests[1].url.params["userId"] == "a+b/="
    assert requests[1].url.params["userName"] == "Alice Smith"


@pytest.mark.asyncio
async def test_recording_link_preserves_provider_capped_expiry(monkeypatch):
    payload = {**EXAMPLES["get_recording_link"]["body"], "validity_capped": True, "expires": 1900003600}
    requests = mock(monkeypatch, payload)
    result = await node({"operation": "get_recording_link", "recording_id": "recording-1", "valid_for_secs": 43200}).execute({})
    assert requests[0].url.params["valid_for_secs"] == "43200"
    assert result["data"] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_rejection_redacted_and_not_retried(monkeypatch, status):
    requests = mock(monkeypatch, {"error": "authentication-error", "info": "Rejected key " + TOKEN}, status)
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_rooms"}).execute({})
    assert str(status) in str(error.value) and "Rejected key" in str(error.value)
    assert TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_malformed_page_cannot_prove_connection(monkeypatch):
    mock(monkeypatch, {"data": {"unexpected": True}})
    with pytest.raises(ValueError, match="invalid page"):
        await node({"operation": "list_rooms"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_room", "room_name": "../other"},
    {"operation": "get_recording", "recording_id": "https://evil.test/x"},
    {"operation": "list_rooms", "starting_after": "a", "ending_before": "b"},
    {"operation": "list_meeting_participants", "meeting_id": "a", "joined_before": "a", "joined_after": "b"},
    {"operation": "create_meeting_token", "room_name": "r"},
    {"operation": "create_meeting_token", "room_name": "r", "nbf": 200, "exp": 100},
    {"operation": "get_recording_link", "recording_id": "r", "valid_for_secs": 1},
    {"operation": "list_meetings", "timeframe_start": 200, "timeframe_end": 100},
])
def test_invalid_request_rejected_before_transport(config):
    assert not daily.DailyNode.validate_config({"config": config})["valid"]


def test_manual_credential_discriminator_and_cleanup():
    credential = daily.DailyAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == "daily_api_key" and credential.api_key == TOKEN
    assert daily.DailyNode.connection_evidence.operation == "list_rooms"
