"""UNRUN actual native schema/factory/connect/collector/wire and projection fixtures.

Everything is synthetic; no vendor examples, public demos or account requests.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
import json

import httpx
import pytest
from pydantic import ValidationError
from nodes import immich_node as p
from nodes.core.registry import NodeFactory
from nodes.core import credential_connect
from nodes.core.connection_evidence import collect_evidence

KEY = {"credential_type": "immich_api_key", "api_key": "synthetic_private_api_key", "instance_origin": "https://instance.example.test"}
AID = "c7C7c7C7-d8d8-4e4e-9f9f-c7c7c7c7c7c7"
BID = "d9d9d9d9-e7e7-4d4d-8c8c-d9d9d9d9d9d9"
ALBUM = {"id": AID, "assetCount": 21, "createdAt": "synthetic-raw-created-date", "updatedAt": "synthetic-raw-updated-date", "isActivityEnabled": False, "albumName": "Private album", "description": "private-description", "albumThumbnailAssetId": "private-image", "albumUsers": [{"userId": "private-user", "role": "private-role"}], "hasSharedLink": True, "shared": True, "assets": [{"url": "https://private.invalid/media", "fileName": "private-name"}], "contributorCounts": {"private-user": 29}}
SAFE = {k: ALBUM[k] for k in ("id", "assetCount", "createdAt", "updatedAt", "isActivityEnabled")}


@pytest.fixture
def ensure_native_db_pool():
    yield


def wire(monkeypatch, responses=None, *, status=200, raw=None, mime="application/json"):
    calls = []
    responses = deepcopy(responses) if responses is not None else {}
    @asynccontextmanager
    async def client(**options):
        assert options == {"timeout": 12, "follow_redirects": False, "trust_env": False}
        class Client:
            @asynccontextmanager
            async def stream(self, method, url, **kwargs):
                assert method == "GET" and "?" not in url
                assert kwargs["headers"]["x-api-key"] == KEY["api_key"] and "Authorization" not in kwargs["headers"]
                assert KEY["api_key"] not in url and KEY["api_key"] not in repr(kwargs)
                path = url.removeprefix(KEY["instance_origin"] + "/api")
                assert path in {"/albums", "/albums/" + AID}
                calls.append(path)
                payload = responses.get(path, [ALBUM] if path == "/albums" else ALBUM)
                if callable(payload): payload = payload(len(calls))
                body = raw if raw is not None else json.dumps(payload).encode()
                yield httpx.Response(status, content=body, headers={"content-type": mime}, request=httpx.Request(method, url))
        yield Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return calls


def node(operation, **config):
    return NodeFactory.create_node("synthetic-node", "automation-immich", {"config": {"operation": operation, **config}, "credentials": KEY})


def test_actual_native_schema_has_exact_two_nontrigger_operations():
    schema = p.ImmichNode.get_config_schema()
    refs = schema["properties"]["config"].get("oneOf", schema["properties"]["config"].get("anyOf"))
    models = [schema["$defs"][r["$ref"].rsplit("/", 1)[-1]] for r in refs]
    assert sorted(m["properties"]["operation"]["const"] for m in models) == ["get_album", "list_albums"]
    for model in models:
        assert model["properties"]["operation"]["x-is-trigger"] is False
        assert model["properties"]["include_names"]["default"] is False
        assert not set(model["properties"]) & {"assetId", "id", "isOwned", "isShared", "name", "key", "slug", "page", "cursor", "url", "method"}
    credential = schema["$defs"]["ImmichAPIKeyCredential"]
    assert credential["properties"]["api_key"]["ui:widget"] == "password"
    assert "x-oauth-provider" not in credential
    assert schema["$defs"]["GetAlbum"]["properties"]["album_id"]["pattern"] == p.UUID4_PATTERN


@pytest.mark.parametrize("bad", [True, 601, 601.0, "601", " "+AID, AID+" ", "legacy-hash", "c7c7c7c7-d8d8-1e4e-9f9f-c7c7c7c7c7c7", "c7c7c7c7-d8d8-4e4e-7f9f-c7c7c7c7c7c7"])
def test_only_exact_current_uuid4_ids_are_admitted(bad):
    with pytest.raises(ValueError): p.GetAlbum(album_id=bad)
    with pytest.raises(ValueError): p.record({**SAFE, "id": bad})
    assert p.GetAlbum(album_id=AID).album_id == AID


@pytest.mark.asyncio
async def test_actual_factory_detail_witnesses_catalog_detail_catalog_and_safe_projection(monkeypatch):
    calls = wire(monkeypatch)
    result = await node("get_album", album_id=AID).execute({})
    assert result == SAFE
    assert calls == ["/albums", "/albums/" + AID, "/albums"]
    assert not set(result) & {"albumName", "assets", "albumUsers", "hasSharedLink", "shared", "description", "count", "total"}
    assert result["assetCount"] == 21  # Resource-linked count, not the one-row catalog length.


@pytest.mark.asyncio
async def test_name_validation_is_opt_in_and_omitted_payload_fields_not_required(monkeypatch):
    wire(monkeypatch, {"/albums": [SAFE], "/albums/" + AID: SAFE})
    assert await node("get_album", album_id=AID).execute({}) == SAFE
    with pytest.raises(ValueError): await node("get_album", album_id=AID, include_names=True).execute({})
    wire(monkeypatch)
    assert (await node("list_albums", include_names=True).execute({}))["items"] == [{**SAFE, "albumName": "Private album"}]


@pytest.mark.parametrize("field", ["id", "assetCount", "createdAt", "updatedAt", "isActivityEnabled"])
def test_every_selected_required_witness_must_be_present(field):
    row = deepcopy(SAFE)
    del row[field]
    with pytest.raises(ValueError): p.record(row)


@pytest.mark.parametrize("field,value", [("assetCount", True), ("assetCount", 1.0), ("assetCount", "21"), ("assetCount", -1), ("assetCount", 9007199254740992), ("createdAt", 123), ("updatedAt", None), ("isActivityEnabled", 1), ("isActivityEnabled", "false")])
def test_required_scalar_fields_never_coerce_or_default(field, value):
    with pytest.raises(ValueError): p.record({**SAFE, field: value})
    assert p.record({**SAFE, "assetCount": 9007199254740991})["assetCount"] == 9007199254740991


@pytest.mark.asyncio
async def test_local_cap_unknown_completion_without_array_length_count(monkeypatch):
    for rows in ([], [ALBUM]):
        wire(monkeypatch, {"/albums": rows})
        result = await node("list_albums").execute({})
        assert result["completion_verified"] is False and result["truncated"] is False
        assert not set(result) & {"count", "total", "has_more"}
    rows = [{**SAFE, "id": f"{n+2001:08x}-d8d8-4e4e-9f9f-c7c7c7c7c7c7"} for n in range(101)]
    wire(monkeypatch, {"/albums": rows})
    result = await node("list_albums").execute({})
    assert len(result["items"]) == 100 and result["truncated"] is True
    with pytest.raises(ValueError, match="100"): await p.ImmichNode.load_field_options("album_id", KEY)
    with pytest.raises(ValueError, match="100"): await node("get_album", album_id=AID).execute({})


@pytest.mark.asyncio
async def test_actual_picker_preserves_case_and_current_uuid_membership(monkeypatch):
    calls = wire(monkeypatch)
    selected = await p.ImmichNode.load_field_options("album_id", KEY, search="c7")
    assert selected == {"options": [{"value": AID, "label": "Album " + AID}], "next_page_token": None}
    assert p.GetAlbum(album_id=selected["options"][0]["value"]).album_id == AID
    assert calls == ["/albums"]
    calls.clear()
    with pytest.raises(ValueError): await node("get_album", album_id=AID.lower()).execute({})
    assert calls == ["/albums"]  # No case normalization and no detail request.
    calls.clear()
    with pytest.raises(ValueError): await p.ImmichNode.load_field_options("album_id", KEY, page_token="invented")
    assert calls == []


@pytest.mark.asyncio
async def test_lost_catalog_or_mismatched_detail_suppresses_result(monkeypatch):
    seen = 0
    def catalog(_index):
        nonlocal seen
        seen += 1
        return [ALBUM] if seen == 1 else []
    calls = wire(monkeypatch, {"/albums": catalog})
    with pytest.raises(ValueError, match="selected album unavailable"): await node("get_album", album_id=AID).execute({})
    assert calls == ["/albums", "/albums/" + AID, "/albums"]
    calls = wire(monkeypatch, {"/albums/" + AID: {**SAFE, "id": BID}})
    with pytest.raises(ValueError, match="different album ID"): await node("get_album", album_id=AID).execute({})
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 302])
async def test_refusal_is_bounded_status_only_without_key_or_body(monkeypatch, status):
    calls = wire(monkeypatch, status=status, raw=(KEY["api_key"] + " private-user private-media").encode())
    with pytest.raises(ValueError) as error: await node("list_albums").execute({})
    assert f"HTTP {status}" in str(error.value) and "cause unknown" in str(error.value)
    assert KEY["api_key"] not in str(error.value) and "private-user" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b'[{"assetCount":1,"assetCount":1}]', b'[{"assetCount":NaN}]', b'{"items":[]}', b'null'])
async def test_wrong_envelope_duplicate_or_nonfinite_refused(monkeypatch, raw):
    calls = wire(monkeypatch, raw=raw)
    with pytest.raises(ValueError): await node("list_albums").execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_actual_connect_and_collector_empty_catalog_only_reachability(monkeypatch):
    calls = wire(monkeypatch, {"/albums": []})
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    visible = {k: v for k, v in KEY.items() if k != "credential_type"}
    verdict = await credential_connect.validate_for_connect(credential_type=p.TYPE, credential_data=visible, user_id="synthetic-owner")
    assert verdict.ok is True and verdict.credential_data["credential_type"] == p.TYPE
    assert verdict.evidence.is_empty_but_working and verdict.evidence.account_label is None
    evidence = await collect_evidence(node_type="automation-immich", credential_data=KEY, user_id="synthetic-owner")
    assert evidence.is_empty_but_working and evidence.account_label is None
    assert p.ImmichNode.connection_evidence.proves == "reachability"
    assert calls == ["/albums", "/albums"]


@pytest.mark.parametrize("origin", ["http://instance.example.test", "https://localhost", "https://127.0.0.1", "https://10.0.0.1", "https://instance.example.test/api", "https://user:pass@instance.example.test", "https://instance.example.test?key=x"])
def test_origin_rejects_private_host_credentials_paths_and_queries(origin):
    with pytest.raises(ValueError): p.ImmichAPIKeyCredential(instance_origin=origin, api_key=KEY["api_key"])


def test_raw_type_and_private_credential_errors():
    value = p.ImmichAPIKeyCredential(instance_origin=KEY["instance_origin"], api_key=KEY["api_key"])
    assert value.model_dump(exclude_unset=True)["credential_type"] == p.TYPE
    assert KEY["api_key"] not in repr(value)
    with pytest.raises(ValueError): p.guard({**KEY, "credential_type": "foreign"})
    with pytest.raises(ValidationError) as error: p.ImmichAPIKeyCredential(instance_origin=KEY["instance_origin"], api_key="secret bad whitespace")
    assert "secret bad whitespace" not in str(error.value)


@pytest.mark.asyncio
async def test_private_network_override_is_refused_before_provider(monkeypatch):
    calls = wire(monkeypatch)
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "true")
    with pytest.raises(ValueError, match="could not be established"):
        await node("list_albums").execute({})
    assert calls == []
