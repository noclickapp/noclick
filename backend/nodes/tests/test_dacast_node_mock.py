"""Prepared Dacast native wire, parent witness and privacy regressions.

Actual factory/dispatcher/connect/schema seams use synthetic HTTP boundaries.
These fixtures are UNRUN and prove no account, entitlement or UI result.
"""
from copy import deepcopy
import json
from types import SimpleNamespace
import httpx
import pytest
from nodes import dacast_node as p
from nodes.core.registry import NodeFactory, NODE_REGISTRY
from nodes.core.run_op import run_node_operation

USER = "00000000-0000-4000-8000-000000000001"
VIDEO = "00000000-0000-4000-8000-000000000010"
SECOND = "00000000-0000-4000-8000-000000000011"
CHANNEL = "00000000-0000-4000-8000-000000000020"
PLAYLIST = "00000000-0000-4000-8000-000000000030"
FOLDER = "1259852"
FOREIGN = "00000000-0000-4000-8000-000000000099"
PRIVATE = "SYNTHETIC_PRIVATE_MARKER"


def blob(**changes):
    return {"credential_type": p.FAMILY, "api_key": "synthetic-issued-key", "include_labels": False,
        "approved_resources_json": json.dumps({"channels": [CHANNEL], "videos": [VIDEO, SECOND], "folders": [FOLDER], "playlists": [PLAYLIST]}), **changes}


def media(uid=VIDEO, **changes):
    return {"id": uid, "title": PRIVATE, "online": True, "creation_date": "2026-08-20T12:28:18Z",
        "config": {"stream_name": PRIVATE}, "password": PRIVATE, "hls": PRIVATE, "hds": PRIVATE, "rtmp": PRIVATE,
        "share_code": {"facebook": PRIVATE}, "custom_data": PRIVATE, "description": PRIVATE, "ads": PRIVATE,
        "pictures": {"thumbnail": [PRIVATE]}, "asset_id": PRIVATE, "filename": PRIVATE,
        "renditions": [{"id": PRIVATE}], "user_id": PRIVATE, **changes}


def video(uid=VIDEO):
    return media(uid, stream_id=CHANNEL, duration="00:00:30", container="mpeg-4", vcodec="h264", acodec="aac",
                 video_width=1280, video_height=720, disk_usage=16897018, filesize="14006984")


def folder(uid=FOLDER):
    return {"id": uid, "name": PRIVATE, "created_at": "1787244076", "path": "/" + PRIVATE, "user_id": PRIVATE}


def page(family, rows, total=None, more=False):
    return {"data": rows, "totalCount" if family == "channels" else "total_count": str(len(rows) if total is None else total),
            "paging": {"next": "https://unrelated.invalid/" + PRIVATE if more else None, "last": PRIVATE, "first": PRIVATE, "previous": None}}


def option(value):
    return {"value": value, "label": value, "metadata": {"completion": "provider_paging_reported", "identity_verified": False}}


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(queue=[], calls=[], after_headers=None, after_body=None)
    class Response:
        def __init__(self, payload, status, ctype):
            self.status_code, self.headers = status, {"content-type": ctype, "location": PRIVATE}
            self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        async def __aenter__(self):
            if state.after_headers: state.after_headers()
            return self
        async def __aexit__(self, *_): return False
        async def aiter_bytes(self):
            yield self.payload
            if state.after_body: state.after_body()
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        def stream(self, method, url, **kwargs):
            state.calls.append((method, url, deepcopy(kwargs)))
            assert state.queue, "Unexpected request beyond synthetic boundary"
            value = state.queue.pop(0)
            if isinstance(value, BaseException): raise value
            return Response(*value) if isinstance(value, tuple) else Response(value, 200, "application/json")
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return state


async def execute(config, data=None, inputs=None):
    node = NodeFactory.create_node("fixture", p.NODE_TYPE, {"config": config, "credentials": data or blob()}, user_id=USER)
    return await node.execute(inputs or {})


@pytest.mark.asyncio
async def test_real_factory_dispatcher_header_contract_ignores_input_config(wire):
    assert NODE_REGISTRY[p.NODE_TYPE] is p.DacastNode
    wire.queue = [page("channels", [media(CHANNEL)]), page("channels", [])]
    result = await execute({"operation": "check_connection"}, inputs={"operation": "lookup_stream", "include_labels": True})
    assert result["witness_verified"] and not result["identity_verified"] and not result["account_ownership_verified"]
    result = await run_node_operation(node_type=p.NODE_TYPE, operation="check_connection", arguments={}, user_id=USER, credential_data=blob())
    assert result["witness_verified"] and result["received_count"] == 0
    for method, url, kwargs in wire.calls:
        assert method == "GET" and url == p.ROOT + "/channel" and kwargs["params"] == {"page": 1, "per_page": 1}
        assert kwargs["headers"] == {"X-Api-Key": "synthetic-issued-key", "X-Format": "default", "Accept": "application/json", "Content-Type": "application/json"}


@pytest.mark.asyncio
async def test_actual_connect_empty_catalog_is_reachability_not_account_identity(wire, monkeypatch):
    from nodes.core import credential_connect as cc
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(cc, "_collect_evidence", collect_evidence)
    wire.queue = [page("channels", []), {"data": []}]
    result = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(), user_id=USER)
    assert result.evidence.reachable is True and result.evidence.account_label is None
    assert "verified_as" not in result.verified_metadata()
    unknown = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(), user_id=USER)
    assert unknown.evidence.reachable is None and not unknown.verified_metadata()


@pytest.mark.asyncio
async def test_all_closed_reads_omit_settings_capabilities_custom_content_and_profile(wire):
    cases = [({"operation": "list_channels"}, [page("channels", [media(CHANNEL), media(FOREIGN)])]),
        ({"operation": "list_videos"}, [page("videos", [video()])]),
        ({"operation": "get_video", "video_id": VIDEO}, [video()]),
        ({"operation": "list_folders"}, [page("folders", [folder()])]),
        ({"operation": "get_folder", "folder_id": FOLDER}, [folder()]),
        ({"operation": "list_playlists"}, [page("playlists", [media(PLAYLIST, content={"list": [PRIVATE]})])])]
    for config, responses in cases:
        wire.queue = responses
        result = await execute(config)
        assert result["status"] == "success" and result["resource_access_verified"] and not result["identity_verified"]
        assert PRIVATE not in json.dumps(result) and not wire.queue
        if config["operation"] == "list_channels": assert result["filtered_count"] == 1
    assert all(method == "GET" and url.startswith(p.ROOT + "/") for method, url, _ in wire.calls)
    assert {url.removeprefix(p.ROOT) for _, url, _ in wire.calls} == {"/channel", "/vod", "/vod/" + VIDEO, "/folder", "/folder/" + FOLDER, "/playlists"}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["unapproved-video", "unapproved-channel", "missing-channel", "foreign-child", "wrong-parent", "ordinary-vod"])
async def test_recording_detail_requires_approved_video_current_catalog_and_returned_parent(wire, kind):
    cfg = {"operation": "get_video", "video_id": VIDEO, "channel_id": CHANNEL}
    child = video()
    if kind == "unapproved-video": cfg["video_id"] = FOREIGN
    if kind == "unapproved-channel": cfg["channel_id"] = FOREIGN
    if kind == "foreign-child": child["id"] = FOREIGN
    if kind == "wrong-parent": child["stream_id"] = FOREIGN
    if kind == "ordinary-vod": child.pop("stream_id")
    wire.queue = [page("channels", [] if kind == "missing-channel" else [media(CHANNEL)]), child]
    with pytest.raises((ValueError, RuntimeError)): await execute(cfg)
    assert len(wire.calls) == (0 if kind.startswith("unapproved") else 1 if kind == "missing-channel" else 2)


@pytest.mark.asyncio
async def test_recording_success_and_documented_filter_witness_do_not_claim_ownership(wire):
    wire.queue = [page("channels", [media(CHANNEL)]), video(), page("channels", [media(CHANNEL)]), page("videos", [video()])]
    result = await execute({"operation": "get_video", "video_id": VIDEO, "channel_id": CHANNEL})
    assert result["parent_link_verified"] and result["channel_id"] == CHANNEL and "stream_id" not in result["data"]
    result = await execute({"operation": "list_videos", "channel_id": CHANNEL, "online": False, "start_date": "2026-01-01", "end_date": "2026-10-01"})
    assert result["filter_channel_witness_verified"] and "parent_link_verified" not in result
    assert wire.calls[-1][2]["params"] == {"page": 1, "per_page": 25, "stream_id": CHANNEL, "online": "false", "start_date": "2026-01-01", "end_date": "2026-10-01"}


@pytest.mark.asyncio
async def test_exact_count_keys_size_aliases_and_safe_numeric_continuation(wire):
    wire.queue = [page("channels", [media(CHANNEL)], total=30, more=True), page("playlists", [media(PLAYLIST)]),
                  page("videos", [video()], total=250, more=True), page("videos", [video(SECOND)], total=250, more=True)]
    result = await execute({"operation": "list_channels", "per_page": 1})
    assert result["provider_total_count"] == 30 and result["has_more"] and result["next_page"] == 2
    await execute({"operation": "list_playlists", "per_page": 10})
    assert wire.calls[-1][2]["params"] == {"page": 1, "per_page": 10}
    first = await p.DacastNode.load_field_options("video_id", blob(), search="Session")
    second = await p.DacastNode.load_field_options("video_id", blob(), page_token=first["next_page_token"], search="Session")
    assert first["options"] == [option(VIDEO)] and second["options"] == [option(SECOND)] and second["next_page_token"] == "3"
    assert [call[2]["params"] for call in wire.calls[-2:]] == [{"page": 1, "per_page": 100, "title": "Session"}, {"page": 2, "per_page": 100, "title": "Session"}]
    assert all(PRIVATE not in url and "unrelated.invalid" not in url for _, url, _ in wire.calls)
    with pytest.raises(ValueError): await p.DacastNode.load_field_options("video_id", blob(), page_token="https://unrelated.invalid/")


@pytest.mark.asyncio
async def test_channel_witness_bounded_scan_does_not_claim_absence_after_truncation(wire):
    wire.queue = [page("channels", [media(f"00000000-0000-4000-8000-{i:012d}")], total=1000, more=True) for i in range(101, 106)]
    with pytest.raises(RuntimeError, match="absence and completion are unverified"):
        await execute({"operation": "get_video", "video_id": VIDEO, "channel_id": CHANNEL})
    assert len(wire.calls) == 5 and not any("/channel/" in url for _, url, _ in wire.calls)


@pytest.mark.asyncio
async def test_saved_names_opt_in_and_numeric_folder_detail_id(wire):
    wire.queue = [folder(), folder()]
    hidden = await execute({"operation": "get_folder", "folder_id": FOLDER}, inputs={"include_labels": True})
    shown = await execute({"operation": "get_folder", "folder_id": FOLDER}, blob(include_labels=True))
    assert "name" not in hidden["data"] and shown["data"]["name"] == PRIVATE
    assert not ({"path", "user_id", "password", "hls"} & shown["data"].keys())


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {"data": []}, page("videos", []), page("channels", [media(CHANNEL), media(CHANNEL)]),
    page("channels", [{**media(CHANNEL), "id": True}]), page("channels", [{**media(CHANNEL), "online": "true"}]),
    {**page("channels", []), "totalCount": 0}, {**page("channels", []), "paging": {}},
    page("channels", [], total=10, more=True)])
async def test_exact_route_envelopes_counts_unique_ids_and_completion_refuse_unknown(wire, payload):
    wire.queue = [payload]
    with pytest.raises(RuntimeError): await execute({"operation": "check_connection"})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,ctype", [(401, "application/json"), (403, "application/json"), (404, "application/json"),
    (202, "application/json"), (204, "application/json"), (302, "application/json"), (429, "application/json"),
    (500, "application/json"), (200, "text/html")])
async def test_errors_and_folder_500_never_become_empty_or_not_found(wire, status, ctype):
    wire.queue = [({"detail": PRIVATE}, status, ctype)]
    with pytest.raises((ValueError, RuntimeError)) as caught: await execute({"operation": "get_folder", "folder_id": FOLDER})
    assert PRIVATE not in str(caught.value) and len(wire.calls) == 1
    if status == 500: assert "did not complete" in str(caught.value) and "not found" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b'{"data":[],"data":[]}', b'[NaN]', b' ' * 2_000_001, httpx.ReadTimeout(PRIVATE)])
async def test_invalid_large_json_and_transport_errors_omit_provider_text(wire, payload):
    wire.queue = [payload]
    with pytest.raises(RuntimeError) as caught: await execute({"operation": "check_connection"})
    assert PRIVATE not in str(caught.value) and len(wire.calls) == 1


def test_actual_schema_is_seven_reads_manual_key_and_distinct_uuid_folder_ids():
    schema = p.DacastNode.get_config_schema()
    model = schema["$defs"]["DacastAPIKeyCredential"]
    assert model["title"] == "Dacast API Key" and "x-credential-type" not in model
    assert model["properties"]["api_key"]["ui:widget"] == "password" and model["properties"]["include_labels"]["default"] is False
    assert set(schema["properties"]["config"]["discriminator"]["mapping"]) == set(p.OPS) and len(p.OPS) == 8
    assert p.DacastNode.validate_config({"config": {"operation": "check_connection"}})["valid"] is True
    for changes in ({"credential_type": None}, {"credential_type": "dacast_oauth"}, {"api_key": "Bearer " + PRIVATE},
        {"password": PRIVATE}, {"approved_resources_json": '{"channels":[],"videos":[],"folders":["bad"],"playlists":[]}'}, {"include_labels": "true"}):
        raw = {"config": {"operation": "check_connection"}, "credentials": blob(**changes)}
        assert p.DacastNode.validate_config(raw)["valid"] is False
        with pytest.raises(ValueError) as caught: p.DacastNode.parse_config(raw)
        assert PRIVATE not in str(caught.value)
    for invalid in (True, 0, 101):
        with pytest.raises(ValueError): p.ListVideos(per_page=invalid)
    for invalid in ("0", "01", VIDEO, "https://invalid/", 1259852):
        with pytest.raises(ValueError): p.resource_id(invalid, "folders")
    with pytest.raises(ValueError): p.ListVideos(start_date="2026-02-30")
    with pytest.raises(ValueError): p.ListVideos(start_date="2026-10-01", end_date="2026-01-01")
