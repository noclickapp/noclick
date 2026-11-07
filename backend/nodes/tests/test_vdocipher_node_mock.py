"""real native schema/factory/connect/wire fixtures; all authorizations synthetic."""
from contextlib import asynccontextmanager
from copy import deepcopy
import ast
from pathlib import Path
import json

import httpx
import pytest

from nodes import vdocipher_node as p
from nodes.core.registry import NodeFactory
from nodes.core import credential_connect, connection_evidence

KEY = {"credential_type": "vdocipher_api_secret", "api_secret": "synthetic-private-key"}
VIDEO = {"id": "fixture-video", "title": "Fixture", "description": "", "upload_time": 1700000000, "length": 25, "status": "ready", "tags": ["owned"], "posters": [{"posterUrl": "https://private.example.test/omit"}], "downloadUrl": "omit-private-url"}
POLICY = {"videoId": "fixture-new", "clientPayload": {"policy": "synthetic-policy", "key": "synthetic-key", "x-amz-signature": "synthetic-signature", "x-amz-algorithm": "AWS4-HMAC-SHA256", "x-amz-date": "20261006T000000Z", "x-amz-credential": "synthetic-credential", "uploadLink": "https://fixture-bucket.s3.amazonaws.com"}}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    replies, calls = [], []
    @asynccontextmanager
    async def client(**options):
        assert options == {"timeout": 12, "follow_redirects": False, "trust_env": False}
        class Client:
            @asynccontextmanager
            async def stream(self, method, url, **kwargs):
                calls.append((method, url, kwargs))
                status, body = replies.pop(0)
                yield httpx.Response(status, content=body if isinstance(body, bytes) else json.dumps(body).encode(), headers={"content-type": "application/json"}, request=httpx.Request(method, url))
        yield Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return replies, calls


def node(config, key=KEY):
    return NodeFactory.create_node("fixture", "automation-vdocipher", {"config": config, "credentials": deepcopy(key)}, user_id="fixture-owner")


def test_actual_schema_exact_ten_operations_and_supplied_header_secret():
    schema = p.VdoCipherNode.get_config_schema()
    operations = {schema["$defs"][ref["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for ref in schema["properties"]["config"]["oneOf"]}
    assert operations == p.OPERATIONS and len(operations) == 10
    source = Path(__file__).resolve().parents[2] / "scripts" / "generate_socket_types.py"
    helper = next(item for item in ast.parse(source.read_text()).body if isinstance(item, ast.FunctionDef) and item.name == "_assert_no_incoherent_constraints")
    namespace = {}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(source), "exec"), namespace)
    namespace["_assert_no_incoherent_constraints"]("vdocipher", schema)
    assert schema["$defs"]["CreateUpload"]["properties"]["folder_id"]["default"] is None
    assert schema["$defs"]["ListVideos"]["properties"]["limit"]["maximum"] == 40
    assert "service_url" not in schema["$defs"]["VdoCipherAPISecretCredential"]["properties"]
    assert p.VdoCipherAPISecretCredential.model_validate({"api_secret": KEY["api_secret"]}).model_dump(exclude_unset=True)["credential_type"] == KEY["credential_type"]


@pytest.mark.parametrize("bad", [True, 1, "a/b", "a%2fb", "a?x", "a,b", "https://attacker.example"])
@pytest.mark.parametrize("config", [{"operation": "get_video", "video_id": None}, {"operation": "list_videos", "folder_id": None}])
def test_real_factory_refuses_noncanonical_asset_paths(bad, config):
    config = {key: bad if value is None else value for key, value in config.items()}
    with pytest.raises(ValueError): node(config)
    assert p.VdoCipherNode.validate_config({"config": config, "credentials": KEY})["valid"] is False


def test_documented_numeric_string_asset_id_is_preserved():
    config = {"operation": "get_video", "video_id": "1234567890"}
    assert node(config).config.config.video_id == "1234567890"
    assert p.VdoCipherNode.validate_config({"config": config, "credentials": KEY})["valid"] is True


@pytest.mark.asyncio
async def test_real_factory_list_wire_current_envelope_and_projection(wire):
    replies, calls = wire
    replies.append((200, {"count": 1, "rows": [VIDEO]}))
    result = await node({"operation": "list_videos", "search": "Fixture", "tags": ["owned"], "folder_id": "root"}).execute({})
    assert result["total_count"] == 1 and result["has_more"] is False
    assert "omit" not in json.dumps(result)
    assert calls[0][0:2] == ("GET", p.BASE + "/videos")
    kwargs = calls[0][2]
    assert kwargs["headers"]["Authorization"] == "Apisecret synthetic-private-key"
    assert kwargs["params"] == {"page": 1, "limit": 20, "q": "Fixture", "tags": "owned", "folderId": "root"}
    assert "api_secret" not in kwargs["params"]


@pytest.mark.asyncio
async def test_clear_description_preserves_explicit_empty_wire_and_readback(wire):
    replies, calls = wire
    updated = {**VIDEO, "title": "Renamed", "description": ""}
    replies.extend([(200, VIDEO), (200, {"message": "updated"}), (200, updated)])
    result = await node({"operation": "update_video_metadata", "video_id": VIDEO["id"], "title": "Renamed", "clear_description": True, "expected_snapshot": p.snapshot(p.video_record(VIDEO))}).execute({})
    assert result["updated"] is True
    assert calls[1][0] == "POST" and calls[1][2]["json"] == {"title": "Renamed", "description": ""}


@pytest.mark.asyncio
async def test_delete_acknowledgement_is_separate_from_observed_absence(wire):
    replies, calls = wire
    replies.extend([(200, VIDEO), (200, {"message": "Deleted"}), (404, {"message": "missing"})])
    result = await node({"operation": "delete_video", "video_id": VIDEO["id"], "expected_title": VIDEO["title"], "expected_snapshot": p.snapshot(p.video_record(VIDEO))}).execute({})
    assert result["deletion_accepted"] and result["absence_observed"] and result["cached_playback_may_continue"]
    assert [call[0] for call in calls] == ["GET", "DELETE", "GET"]
    assert calls[1][2]["params"] == {"videos": VIDEO["id"]}


@pytest.mark.asyncio
async def test_upload_metadata_creates_empty_asset_without_following_signed_destination(wire, caplog):
    replies, calls = wire
    replies.append((200, POLICY))
    result = await node({"operation": "create_upload_policy", "title": "Disposable"}).execute({})
    assert result["asset_created"] and not result["upload_performed"] and not result["encoding_complete"]
    assert result["client_payload"] == POLICY["clientPayload"]
    assert len(calls) == 1 and calls[0][0:2] == ("PUT", p.BASE + "/videos")
    assert calls[0][2]["params"] == {"title": "Disposable"}
    assert "synthetic-policy" not in caplog.text and "synthetic-private-key" not in caplog.text


@pytest.mark.asyncio
async def test_synthetic_otp_and_playback_info_contract_without_playback(wire, caplog):
    replies, calls = wire
    replies.extend([(200, VIDEO), (200, {"otp": "synthetic-otp", "playbackInfo": "synthetic-playback-info"})])
    result = await node({"operation": "create_playback_authorization", "video_id": VIDEO["id"], "ttl": 300}).execute({})
    assert result["otp"] == "synthetic-otp" and result["sensitive_output"] and not result["playback_started"]
    assert calls[1][2]["json"] == {"ttl": 300}
    assert "synthetic-otp" not in caplog.text and "synthetic-playback-info" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["Pre-Upload", "Queued"])
async def test_not_ready_never_mints_playback_authorization(wire, status):
    replies, calls = wire
    replies.append((200, {**VIDEO, "status": status}))
    with pytest.raises(ValueError, match="ready"): await node({"operation": "create_playback_authorization", "video_id": VIDEO["id"]}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_tag_empty_200_and_empty_array_replacement_need_readback(wire):
    replies, calls = wire
    replies.extend([(200, VIDEO), (200, b""), (200, {**VIDEO, "tags": []})])
    result = await node({"operation": "set_video_tags", "video_id": VIDEO["id"], "tags": [], "expected_snapshot": p.snapshot(p.video_record(VIDEO))}).execute({})
    assert result["tags"] == [] and result["updated"]
    assert calls[1][0] == "PUT" and calls[1][2]["json"] == {"videos": [VIDEO["id"]], "tags": []}


@pytest.mark.parametrize("payload", [{"count": True, "rows": []}, {"count": 1, "data": [VIDEO]}, {"count": 2, "rows": [VIDEO, VIDEO]}, {"count": 1, "rows": []}])
def test_actual_page_refuses_wrong_envelope_duplicates_and_inconsistent_totals(payload):
    with pytest.raises(ValueError): p.video_page(payload, 1, 20)


@pytest.mark.asyncio
async def test_picker_string_ids_hmac_continuation_search_and_grant_binding(wire):
    replies, calls = wire
    rows = [{**VIDEO, "id": "fixture-" + str(i)} for i in range(40)]
    replies.append((200, {"count": 41, "rows": rows}))
    result = await p.VdoCipherNode.load_field_options("video_id", KEY, search="Fixture")
    assert all(isinstance(item["value"], str) for item in result["options"])
    with pytest.raises(ValueError): await p.VdoCipherNode.load_field_options("video_id", KEY, search="Other", page_token=result["next_page_token"])
    with pytest.raises(ValueError): await p.VdoCipherNode.load_field_options("video_id", {**KEY, "api_secret": "synthetic-replacement"}, search="Fixture", page_token=result["next_page_token"])
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_errors_are_sanitized_and_never_retried(wire, status):
    replies, calls = wire
    replies.append((status, {"message": "synthetic-private-key synthetic-otp"}))
    with pytest.raises(ValueError) as failure: await node({"operation": "list_videos"}).execute({})
    assert "synthetic" not in str(failure.value) and len(calls) == 1


@pytest.mark.asyncio
async def test_real_manual_connect_uses_actual_collector_and_empty_reachability(wire, monkeypatch):
    replies, calls = wire
    replies.append((200, {"count": 0, "rows": []}))
    credential_connect._class_index.cache_clear()
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    verdict = await credential_connect.validate_for_connect(credential_type=KEY["credential_type"], credential_data={"api_secret": KEY["api_secret"]}, user_id="fixture-owner", probe=True)
    assert verdict.ok and verdict.credential_data["credential_type"] == KEY["credential_type"]
    assert verdict.evidence.reachable is True and p.VdoCipherNode.connection_evidence.proves == "reachability" and verdict.evidence.account_label is None
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_tag_write_unspecified_body_can_be_bounded_text_before_verified_readback(wire):
    replies, calls = wire
    replies.extend([(200, VIDEO), (200, b"OK"), (200, {**VIDEO, "tags": ["owned", "added"]})])
    result = await node({"operation": "append_video_tags", "video_id": VIDEO["id"], "tags": ["added"]}).execute({})
    assert result["tags"] == ["owned", "added"] and result["updated"]
    assert calls[1][0] == "POST"


def test_signed_upload_destination_is_never_an_arbitrary_url():
    for bad in ("http://fixture-bucket.s3.amazonaws.com", "https://attacker.example", "https://name:secret@bucket.s3.amazonaws.com", "https://bucket.s3.amazonaws.com:8443", "https://127.0.0.1"):
        policy = deepcopy(POLICY)
        policy["clientPayload"]["uploadLink"] = bad
        with pytest.raises(ValueError): p.upload_policy(policy)
