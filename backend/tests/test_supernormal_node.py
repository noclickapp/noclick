"""UNRUN Supernormal real factory/identity collector, scope and privacy fixtures.

Synthetic HTTP/repository boundaries establish no live account or entitlement.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from nodes.supernormal_node import SupernormalNode, _credential

TYPE = "automation-supernormal"
USER = "11111111-1111-4111-8111-111111111111"
KEY = "22222222-2222-4222-8222-222222222222"
RAW = {"credential_type": "supernormal_api_token", "api_token": "synthetic-supernormal-issued-token", "scopes": ["user:read", "recordings:read", "calendar_events:read"], "expected_user_id": "userfixture1"}
IDENTITY = {"id": "userfixture1", "first_name": "Fixture", "last_name": "Owner", "email": "PRIVATE-EMAIL", "avatar_url": "https://attacker.invalid/avatar"}
RECORDING = {"id": "recordingfixture1", "title": "Fixture meeting", "status": "done", "recorded_at": "2026-01-01T10:00:00Z", "duration_seconds": 120, "participants_count": 2, "owner": {**IDENTITY, "id": "sharedowner1"}, "summary": "PRIVATE-TEXT https://media.example.invalid/recording?signature=PRIVATE-SIGNATURE", "notes": "PRIVATE-NOTES", "meeting_summary": "PRIVATE-SUMMARY", "download_url": "https://media.example.invalid/signed"}
TRANSCRIPT = [{"start": 0.5, "end": 2.0, "content": "PRIVATE-SPOKEN https://media.example.invalid/signed?token=PRIVATE", "original_speaker": "PRIVATE-SPEAKER", "assigned_speaker_name": "PRIVATE-NAME", "author_name": "PRIVATE-NAME"}]


@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}

    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.scheme == "https" and request.url.host == "api.supernormal.com"
        assert request.headers["X-API-TOKEN"] == RAW["api_token"] and "authorization" not in request.headers
        assert request.headers["Content-Type"] == "application/json" and RAW["api_token"] not in str(request.url)
        path = request.url.path.removeprefix("/api/v1")
        values = {"/user": IDENTITY, "/recordings": {"recordings": [RECORDING], "meta": {"current_page": int(request.url.params.get("page", "1")), "next_page": 2 if request.url.params.get("page", "1") == "1" else None, "total_pages": 2}}, "/recordings/recordingfixture1": RECORDING, "/recordings/recordingfixture1/transcript": TRANSCRIPT, "/user/calendar_events": [{"id": "eventfixture1", "name": "Upcoming fixture", "start": "2026-10-07T10:00:00Z", "end": "2026-10-07T11:00:00Z", "platform_name": "zoom", "scheduled_to_record": False, "url": "https://meeting.example.invalid/PRIVATE", "post_id": "PRIVATE"}]}
        status, value = replies.get(path, (200, values[path]))
        if callable(value): value = value(request)
        return httpx.Response(status, json=value)

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance

    monkeypatch.setattr("nodes.supernormal_node.guarded_async_client", client)
    return calls, replies


async def run(operation, credential=None, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(credential or RAW), user_id=USER)


@pytest.mark.asyncio
async def test_real_native_factory_header_identity_and_collector(transport):
    calls, _ = transport
    result = await run("get_user")
    assert result["status"] == "success" and result["data"]["user"]["id"] == "userfixture1" and result["principal_identity_proven"] is True
    assert "PRIVATE" not in json.dumps(result)
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is True and evidence.account_label == "Fixture Owner" and SupernormalNode.connection_evidence.proves == "account"
    assert "PRIVATE" not in json.dumps(asdict(evidence)) and all(r.url.path == "/api/v1/user" for r in calls)


@pytest.mark.asyncio
async def test_canvas_factory_saved_metadata_is_accepted(transport):
    node = NodeFactory.create_node("fixture-node", TYPE, {"credentials": deepcopy(RAW), "config": {"operation": "get_user", "label": "Fixture", "disabled": False, "_settings": {}}}, user_id=USER)
    assert (await node.execute({}))["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"id": ""}, [], {"id": "https://attacker.invalid/user"}])
async def test_empty_or_wrong_identity_never_false_proof(transport, payload):
    _, replies = transport
    replies["/user"] = (200, payload)
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is None and not evidence.account_label and not evidence.samples


@pytest.mark.asyncio
async def test_actual_expected_user_binding_refuses_before_meeting_data(transport):
    calls, replies = transport
    replies["/user"] = (200, {**IDENTITY, "id": "different-user"})
    result = await run("list_recordings")
    assert result["status"] == "error" and len(calls) == 1 and calls[0].url.path == "/api/v1/user"


@pytest.mark.asyncio
async def test_unknown_expected_user_not_filled_from_current_app(transport):
    result = await run("get_user", credential={**RAW, "expected_user_id": None})
    assert result["status"] == "success" and result["verified_user_id"] == "userfixture1"


@pytest.mark.asyncio
async def test_recordings_exact_paging_visibility_and_private_projection(transport):
    calls, _ = transport
    result = await run("list_recordings", visibility="shared_with_me")
    assert result["status"] == "success" and result["next_page_token"] == "2"
    assert calls[-1].url.params["visibility"] == "shared_with_me" and calls[-1].url.params["page"] == "1"
    assert "per_page" not in calls[-1].url.params and "PRIVATE" not in json.dumps(result) and "https://" not in json.dumps(result)
    assert result["data"][0]["owner_id"] == "sharedowner1"  # shared access is not falsely restricted to self
    last = await run("list_recordings", page=2)
    assert last["has_more"] is False and last["next_page_token"] is None


@pytest.mark.asyncio
async def test_transcript_parent_and_safe_defaults_explicit_text(transport):
    calls, _ = transport
    result = await run("get_transcript", recording_id="recordingfixture1")
    assert result["data"] == [{"start": 0.5, "end": 2.0}]
    assert [r.url.path for r in calls] == ["/api/v1/user", "/api/v1/recordings/recordingfixture1", "/api/v1/recordings/recordingfixture1/transcript"]
    text = await run("get_transcript", recording_id="recordingfixture1", include_text=True, include_speaker_names=True)
    assert "PRIVATE-SPOKEN" in text["data"][0]["content"] and "[link omitted]" in text["data"][0]["content"]
    assert "https://" not in json.dumps(text) and text["data"][0]["author_name"] == "PRIVATE-NAME"
    notes = await run("get_recording", recording_id="recordingfixture1", include_meeting_text=True)
    assert notes["data"]["notes"] == "PRIVATE-NOTES" and "PRIVATE-SIGNATURE" not in json.dumps(notes) and "https://" not in json.dumps(notes)


@pytest.mark.asyncio
async def test_wrong_recording_parent_blocks_transcript(transport):
    calls, replies = transport
    replies["/recordings/recordingfixture1"] = (200, {**RECORDING, "id": "different-recording"})
    assert (await run("get_transcript", recording_id="recordingfixture1"))["status"] == "error"
    assert all(not r.url.path.endswith("/transcript") for r in calls)


@pytest.mark.asyncio
async def test_bounded_calendar_window_and_closed_projection(transport):
    calls, _ = transport
    result = await run("list_upcoming_calendar_events", from_date="2026-10-07T00:00:00Z", to_date="2026-10-08T00:00:00Z")
    assert result["status"] == "success" and "PRIVATE" not in json.dumps(result)
    assert set(calls[-1].url.params) == {"from", "to"} and result["pagination_documented"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,op,args", [("recordings:read", "list_recordings", {}), ("calendar_events:read", "list_upcoming_calendar_events", {"from_date": "2026-10-07T00:00:00Z", "to_date": "2026-10-08T00:00:00Z"})])
async def test_missing_actual_scopes_refused_before_http(transport, scope, op, args):
    calls, _ = transport
    result = await run(op, credential={**RAW, "scopes": [s for s in RAW["scopes"] if s != scope]}, **args)
    assert result["status"] == "error" and result["executed"] is False and not calls


@pytest.mark.parametrize("change", [{"credential_type": "other_token"}, {"access_token": "synthetic"}, {"base_url": "https://attacker.invalid"}, {"refresh_token": ""}, {"scopes": []}, {"scopes": ["recordings:read"]}, {"scopes": ["user:read", "user:read"]}])
def test_raw_family_scopes_and_mixed_grant_precede_defaults(change):
    with pytest.raises(ValueError): _credential({**RAW, **change})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(204, None), (200, {"recordings": [], "meta": {"current_page": 1, "next_page": "https://attacker.invalid", "total_pages": 2}}), (403, {"message": "synthetic-supernormal-issued-token PRIVATE"}), (429, {"message": "PRIVATE"})])
async def test_provider_status_pagination_or_error_has_no_echo_retry(transport, status, payload):
    calls, replies = transport
    replies["/recordings"] = (status, payload)
    result = await run("list_recordings")
    assert result["status"] == "error" and "data" not in result and len(calls) == 2
    assert "PRIVATE" not in json.dumps(result) and RAW["api_token"] not in json.dumps(result)
