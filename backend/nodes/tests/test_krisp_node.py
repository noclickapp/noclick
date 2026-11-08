"""Krisp node contracts against staging hooks and mocked provider HTTP."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import krisp_node as ks
from nodes.core.registry import NODE_REGISTRY, NodeFactory

NODE = "automation-krisp"
USER = "fixture-user"
MEETING, OTHER = "meeting_fixture", "meeting_other"
KEY = "krsp_u_" + "a" * 96
CURRENT_KEY = "krsp_u_" + "b" * 96

@pytest.fixture
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "krisp_api_key", "api_key": KEY, "scopes": ["read"],
        "expires_at": None, **updates}


def identity(**updates):
    return {"id": 94231, "team_id": 1872, "workspace_id": 503, "email": "fixture@example.test",
        "first_name": "Fixture", "last_name": None, "avatar": "https://private.invalid/avatar", **updates}


def meeting(**updates):
    return {"id": MEETING, "title": "Fixture meeting", "started_at": "2026-10-06T13:00:00-04:00",
        "duration": 71, "status": "ready", "source": None, "tags": ["Fixture tag"], "ownership": "owned",
        "recording_url": "https://private.invalid/signed", "transcript": {"private": True}, **updates}


def page(field="meetings", rows=None, cursor=None, total=None):
    rows = [meeting()] if rows is None else rows
    return {field: rows, "next_cursor": cursor, "total": len(rows) if total is None else total}


def action(**updates):
    return {"id": "ai_fixture", "meeting_id": MEETING, "title": "Fixture action", "completed": False,
        "due_date": None, "meeting_title": "Fixture meeting", "meeting_started_at": None,
        "assignee": {"first_name": "Fixture", "email": "fixture@example.test", "photo": "https://private.invalid/photo"}, **updates}


def make_node(operation, data=None, **config):
    return NodeFactory.create_node("fixture", NODE, {"config": {"operation": operation, **config},
        "credentials": credential() if data is None else data}, user_id=USER)


@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(calls=[], client_options=[], responses=[])
    async def respond(request):
        state.calls.append(request)
        assert state.responses, "Unexpected HTTP request"
        status, payload = state.responses.pop(0)
        return httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
    def client(**kwargs):
        state.client_options.append(kwargs)
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(ks, "guarded_async_client", client)
    return state


def test_actual_factory_schema_operations_and_key_bounds():
    assert NODE_REGISTRY[NODE] is ks.KrispNode
    schema = ks.KrispNode.get_config_schema()
    ops = {schema["$defs"][ref["$ref"].split("/")[-1]]["properties"]["operation"]["const"]
        for ref in schema["properties"]["config"]["oneOf"]}
    assert len(ops) == 10 and {"get_identity", "get_meeting_transcript", "list_meeting_action_items"} <= ops
    assert not any(word in op for op in ops for word in ("import", "join", "upload", "edit", "send"))
    key = schema["$defs"]["KrispAPIKeyCredential"]
    assert key["required"] == ["api_key"]
    assert key["properties"]["api_key"]["minLength"] == key["properties"]["api_key"]["maxLength"] == 103
    fields = schema["$defs"]["KrispGetTranscriptConfig"]["properties"]
    assert fields["meeting_id"]["x-resource-type"] == "krisp_meeting"
    assert fields["include_speaker_names"]["default"] is False
    for config in ({"operation": "get_meeting", "meeting_id": "../private"},
            {"operation": "list_meetings", "limit": 101}, {"operation": "list_action_items", "limit": 201},
            {"operation": "list_meetings", "from_time": "2026-10-06"},
            {"operation": "list_meetings", "from_time": "2026-10-07T00:00:00Z", "to_time": "2026-10-06T00:00:00Z"},
            {"operation": "get_meeting", "meeting_id": MEETING, "include": "recording"}):
        with pytest.raises(ValidationError):
            ks.KrispNodeConfig(config=config, credentials=credential())


@pytest.mark.parametrize("updates", [{"credential_type": "other"}, {"api_key": "bad"},
    {"api_key": KEY + "\nprivate"}, {"scopes": ["write"]}, {"scopes": ["admin"]},
    {"expected_team_id": True}, {"expected_user_id": "../other"},
    {"expires_at": "2026-10-06"}, {"expires_at": "2000-10-06T12:00:00Z"}])
def test_raw_family_scope_actual_expiry_and_expected_context(updates):
    with pytest.raises(ValueError) as failure:
        ks._credential(credential(**updates))
    assert KEY not in str(failure.value) and "private" not in str(failure.value)


@pytest.mark.asyncio
async def test_fixed_root_identity_and_default_metadata_exclude_capabilities(http):
    http.responses = [(200, identity()), (200, meeting(duration=None))]
    out = (await make_node("get_meeting", meeting_id=MEETING).execute({}))["meeting"]
    assert out["started_at"] == "2026-10-06T13:00:00-04:00" and out["duration"] is None
    assert "recording_url" not in out and "transcript" not in out
    assert [request.url.path for request in http.calls] == ["/v1/me", "/v1/meetings/" + MEETING]
    assert all(str(request.url).startswith(ks.API_ROOT + "/") for request in http.calls)
    assert all(request.headers["Authorization"] == "Bearer " + KEY for request in http.calls)
    assert all(KEY not in str(request.url) and request.method == "GET" for request in http.calls)
    assert http.calls[-1].url.params["fields"] == ks.DETAIL_FIELDS


@pytest.mark.asyncio
async def test_real_identity_mismatch_stops_before_meeting_reads(http):
    http.responses = [(200, identity())]
    with pytest.raises(RuntimeError, match="identity"):
        await make_node("list_meetings", data=credential(expected_workspace_id="999")).execute({})
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_processed_meeting_filters_and_selected_current_tag(http):
    http.responses = [(200, identity()), (200, [{"id": "tag_fixture", "name": "Fixture tag", "color": None}]), (200, page())]
    await make_node("list_meetings", ownership="mine", query="Fixture", from_time="2026-10-01T00:00:00Z",
        to_time="2026-10-06T23:00:00Z", tag_id="tag_fixture").execute({})
    params = http.calls[-1].url.params
    assert params["ownership"] == "mine" and params["q"] == "Fixture" and params["tags"] == "tag_fixture"
    assert params["from"] == "2026-10-01T00:00:00Z" and "transcript" not in params["fields"]
    http.responses = [(200, identity()), (200, [])]
    before = len(http.calls)
    with pytest.raises(ValueError, match="tag"):
        await make_node("list_meetings", tag_id="tag_other").execute({})
    assert len(http.calls) == before + 2


@pytest.mark.asyncio
async def test_parent_action_page_empty_match_retains_global_cursor(http):
    http.responses = [(200, identity()), (200, meeting()),
        (200, page("action_items", [action(meeting_id=OTHER)], cursor="opaque-next", total=19))]
    out = await make_node("list_meeting_action_items", meeting_id=MEETING, completed=False).execute({})
    assert out["items"] == [] and out["next_page_token"] and out["reported_total"] == 19
    assert out["complete"] is False and "global page" in out["coverage"]
    assert http.calls[-1].url.params["completed"] == "false"
    assert "meeting_id" not in http.calls[-1].url.params and "assignee" not in http.calls[-1].url.params["fields"]
    before = len(http.calls)
    for args in ({"meeting_id": OTHER}, {"meeting_id": MEETING, "completed": True},
            {"meeting_id": MEETING, "data": credential(api_key=CURRENT_KEY)}):
        args.setdefault("completed", False)
        with pytest.raises(ValueError, match="page token"):
            await make_node("list_meeting_action_items", page_token=out["next_page_token"], **args).execute({})
    assert len(http.calls) == before
    http.responses = [(200, identity()), (200, meeting()), (200, page("action_items", [action()], total=19))]
    final = await make_node("list_meeting_action_items", meeting_id=MEETING, completed=False,
        page_token=out["next_page_token"]).execute({})
    assert final["items"][0]["completed"] is False and final["items"][0]["due_date"] is None
    assert final["next_page_token"] is None and final["complete"] is False
    assert http.calls[-1].url.params["cursor"] == "opaque-next"


@pytest.mark.asyncio
async def test_cursor_rechecks_actual_user_team_and_workspace(http):
    http.responses = [(200, identity()), (200, page(cursor="opaque-next"))]
    first = await make_node("list_meetings").execute({})
    http.responses = [(200, identity(team_id=999))]
    before = len(http.calls)
    with pytest.raises(RuntimeError, match="account context changed"):
        await make_node("list_meetings", page_token=first["next_page_token"]).execute({})
    assert len(http.calls) == before + 1


@pytest.mark.asyncio
async def test_notes_custom_block_tree_and_null_false_preserved(http):
    notes = {"blocks": [{"type": "custom_heading", "children": [{"type": "action_item", "text": "Fixture",
        "completed": False, "due_date": None, "assignee": {"first_name": "Fixture", "photo": "https://private.invalid"}}]}]}
    http.responses = [(200, identity()), (200, meeting(notes=notes))]
    out = await make_node("get_meeting_notes", meeting_id=MEETING).execute({})
    block = out["notes"]["blocks"][0]
    assert block["type"] == "custom_heading" and block["children"][0]["completed"] is False
    assert block["children"][0]["due_date"] is None and "photo" not in block["children"][0]["assignee"]
    assert http.calls[-1].url.params["fields"].endswith(",notes") and "include" not in http.calls[-1].url.params
    http.responses = [(200, identity()), (200, meeting(notes=None))]
    assert (await make_node("get_meeting_notes", meeting_id=MEETING).execute({}))["notes"] is None


@pytest.mark.asyncio
async def test_transcript_original_seconds_indexes_and_name_opt_in(http):
    transcript = {"language": None, "segments": [{"speaker": 7, "text": "Fixture", "start": 0.25, "end": 3.75}],
        "speakers": {"7": {"first_name": "Fixture", "last_name": None, "email": "private@example.test", "photo": "private"}}}
    http.responses = [(200, identity()), (200, meeting(transcript=transcript))]
    out = await make_node("get_meeting_transcript", meeting_id=MEETING).execute({})
    assert out["time_unit"] == "seconds" and out["transcript"]["segments"] == transcript["segments"]
    assert "speakers" not in out["transcript"] and out["transcript"]["language"] is None
    http.responses = [(200, identity()), (200, meeting(transcript=transcript))]
    named = await make_node("get_meeting_transcript", meeting_id=MEETING, include_speaker_names=True).execute({})
    assert named["transcript"]["speakers"] == {"7": {"first_name": "Fixture", "last_name": None}}


@pytest.mark.asyncio
async def test_participants_tag_names_and_explicit_action_assignee(http):
    http.responses = [(200, identity()), (200, meeting(participants=[action()["assignee"]]))]
    out = await make_node("get_meeting_participants", meeting_id=MEETING).execute({})
    assert out["participants"][0]["email"] == "fixture@example.test" and "photo" not in out["participants"][0]
    http.responses = [(200, identity()), (200, meeting())]
    assert (await make_node("get_meeting_tags", meeting_id=MEETING).execute({}))["tag_names"] == ["Fixture tag"]
    http.responses = [(200, identity()), (200, page("action_items", [action()]))]
    items = await make_node("list_action_items", include_assignee=True).execute({})
    assert "photo" not in items["items"][0]["assignee"] and "completed" not in http.calls[-1].url.params
    assert "assignee" in http.calls[-1].url.params["fields"]


@pytest.mark.asyncio
async def test_real_picker_search_cursor_and_bounded_tag_array(http):
    http.responses = [(200, identity()), (200, page(rows=[], cursor="next", total=2))]
    first = await ks.KrispNode.load_field_options("meeting_id", credential(), search="Fixture")
    assert first["options"] == [] and first["next_page_token"] and http.calls[-1].url.params["q"] == "Fixture"
    before = len(http.calls)
    with pytest.raises(ValueError):
        await ks.KrispNode.load_field_options("meeting_id", credential(), search="changed", page_token=first["next_page_token"])
    with pytest.raises(ValueError):
        await ks.KrispNode.load_field_options("tag_id", credential(), page_token=first["next_page_token"])
    assert len(http.calls) == before
    http.responses = [(200, identity()), (200, [{"id": "tag_fixture", "name": "Fixture tag", "color": None}])]
    tags = await ks.KrispNode.load_field_options("tag_id", credential(), search="Fixture")
    assert tags == {"options": [{"value": "tag_fixture", "label": "Fixture tag"}], "next_page_token": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(409, {"error": "private"}), (401, {"error": KEY}),
    (403, {"error": "private"}), (429, {"error": KEY}), (500, {}),
    (200, {"error": KEY}), (200, {}), (200, meeting(id=OTHER))])
async def test_processing_provider_error_or_malformed_data_cannot_succeed(http, status, payload):
    http.responses = [(200, identity()), (status, payload)]
    with pytest.raises(RuntimeError) as failure:
        await make_node("get_meeting", meeting_id=MEETING).execute({})
    assert KEY not in str(failure.value) and "private" not in str(failure.value)
    assert len(http.calls) == 2
    if status == 409:
        assert isinstance(failure.value, ks.KrispProcessingError) and failure.value.http_status == 409


@pytest.mark.asyncio
async def test_missing_notes_and_invalid_page_do_not_become_empty_success(http):
    http.responses = [(200, identity()), (200, meeting())]
    with pytest.raises(RuntimeError, match="omitted"):
        await make_node("get_meeting_notes", meeting_id=MEETING).execute({})
    http.responses = [(200, identity()), (200, {"meetings": [], "total": 0})]
    with pytest.raises(RuntimeError, match="pagination"):
        await make_node("list_meetings").execute({})


@pytest.mark.asyncio
async def test_saved_credential_uses_staging_loader(monkeypatch, http):
    current = credential(api_key=CURRENT_KEY, scopes=["read", "write"], expected_team_id="1872")
    loader = AsyncMock(return_value=current)
    monkeypatch.setattr(ks, "load_credential", loader)
    out = await ks.KrispNode.freshen_credential(credential(), pool="pool", user_id=USER, credential_id="saved")
    assert out["api_key"] == CURRENT_KEY and out["expected_team_id"] == "1872"
    loader.assert_awaited_once_with("pool", USER, "saved", raise_on_error=True)
    loader.return_value = None
    with pytest.raises(ValueError, match="connection"):
        await ks.KrispNode.freshen_credential(credential(), user_id=USER, credential_id="saved")
    assert http.calls == []


@pytest.mark.asyncio
async def test_access_validation_uses_key_holder_identity(http):
    http.responses = [(200, identity())]
    assert await ks.KrispNode.validate_credential_access(credential()) == {"valid": True}
    http.responses = [(200, identity(team_id=999))]
    with pytest.raises(RuntimeError, match="identity"):
        await ks.KrispNode.validate_credential_access(credential(expected_team_id="1872"))


@pytest.mark.asyncio
async def test_actual_manual_connect_collector_empty_meetings_identity_fallback(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    invalid = await credential_connect.validate_for_connect(credential_type="krisp_api_key",
        credential_data=credential(api_key="bad"), user_id=USER)
    assert not invalid.ok and "api_key" in invalid.field_errors and http.calls == []
    http.responses = [(200, identity()), (200, page(rows=[])), (200, identity())]
    valid = await credential_connect.validate_for_connect(credential_type="krisp_api_key",
        credential_data=credential(), user_id=USER)
    assert valid.ok and valid.node_type == NODE and ks.KrispNode.connection_evidence.proves == "account"
    assert valid.evidence.account_label == "fixture@example.test" and valid.evidence.reachable is True



@pytest.mark.asyncio
@pytest.mark.parametrize("operation,example,field", [
    ("get_meeting_participants", "Default", "participants"),
    ("get_meeting_notes", "WithTranscriptAndNotes", "notes"),
    ("get_meeting_transcript", "WithTranscriptAndNotes", "transcript"),
])
async def test_provider_documented_detail_examples(http, operation, example, field):
    # Exact provider examples: https://meeting-api-docs.krisp.ai/reference/get_meetings-id.md
    raw = json.loads((Path(__file__).parent / "fixtures" / "krisp" / (example + ".json")).read_text())
    http.responses = [(200, identity()), (200, raw)]
    out = await make_node(operation, meeting_id=raw["id"]).execute({})
    assert out[field] is not None
    assert field in http.calls[-1].url.params["fields"].split(",")


@pytest.mark.asyncio
async def test_omitted_requested_participants_remain_an_error(http):
    raw = json.loads((Path(__file__).parent / "fixtures" / "krisp" / "WithTranscriptAndNotes.json").read_text())
    http.responses = [(200, identity()), (200, raw)]
    with pytest.raises(RuntimeError, match="participant list"):
        await make_node("get_meeting_participants", meeting_id=raw["id"]).execute({})
