"""FieldView v4 request, OAuth and polling regressions without a live account.

The field fixture is copied from the provider's published schema example. Activity
fixtures use the published required response fields; they are schema-shaped test data.
"""
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import climate_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory
from nodes.oauth.climate_oauth import OAUTH_PROVIDER

ID = "00000000-0000-0000-0000-000000000000"
TOKEN = "synthetic-climate-access-42"
KEY = "synthetic-climate-partner-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="climate-test", node_type="automation-climate", node_data={
        "config": config, "credentials": {"credential_type": "climate_oauth", "access_token": TOKEN, "api_key": KEY}})


def transport(monkeypatch, responder):
    requests = []
    def respond(request):
        requests.append(request)
        return responder(request) if callable(responder) else httpx.Response(200, json=responder)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def activity(**changes):
    return {"id": ID, "startTime": "2016-05-13T00:00:00.000Z", "endTime": "2016-05-13T00:00:00.000Z",
        "createdAt": "2016-05-13T00:00:00.000Z", "updatedAt": "2016-05-13T00:00:00.000Z", "length": 1, "fieldIds": [ID], **changes}


@pytest.mark.asyncio
async def test_climate_field_example_and_header_pagination(monkeypatch):
    field = json.loads((Path(__file__).parent / "fixtures/climate/field.json").read_text())
    calls = transport(monkeypatch, lambda req: httpx.Response(206, json={"results": [field]}, headers={"X-Next-Token": "next-page"}))
    out = await node({"operation": "list_fields", "fieldName": "Back", "limit": 5, "next_token": "previous-page"}).execute({})
    assert out["results"] == [field] and out["has_more"] and out["next_token"] == "next-page"
    assert dict(calls[0].url.params) == {"fieldName": "Back"}
    assert calls[0].headers["X-Next-Token"] == "previous-page"
    assert calls[0].headers["X-Limit"] == "5"
    assert calls[0].headers["X-Api-Key"] == KEY
    assert calls[0].headers["Authorization"] == "Bearer " + TOKEN


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", [
    ("get_field", {"fieldId": ID}, "GET", "/v4/fields/" + ID, None),
    ("get_resource_owner", {"resourceOwnerId": ID}, "GET", "/v4/resourceOwners/" + ID, None),
    ("get_boundary", {"boundaryId": ID}, "GET", "/v4/boundaries/" + ID, None),
    ("query_boundaries", {"ids": [ID]}, "POST", "/v4/boundaries/query", {"ids": [ID]}),
    ("query_upload_statuses", {"ids": [ID]}, "POST", "/v4/uploads/status/query", {"ids": [ID]}),
    ("get_upload_status", {"uploadId": ID}, "GET", "/v4/uploads/" + ID + "/status", None),
    ("get_export_status", {"exportId": ID}, "GET", "/v4/exports/" + ID + "/status", None),
    ("get_scouting_observation", {"scoutingObservationId": ID}, "GET", "/v4/layers/scoutingObservations/" + ID, None),
])
async def test_climate_single_endpoint_mapping(monkeypatch, operation, config, method, path, body):
    calls = transport(monkeypatch, {"id": ID})
    await node({"operation": operation, **config}).execute({})
    assert len(calls) == 1 and calls[0].method == method and calls[0].url.path == path
    if body is not None:
        assert json.loads(calls[0].content) == body


@pytest.mark.asyncio
async def test_climate_export_definition_and_upload_metadata(monkeypatch):
    definition = {"plantingStartDate": "2016-05-13", "plantingEndDate": "2016-05-13", "resourceOwnerId": ID}
    calls = transport(monkeypatch, lambda req: httpx.Response(201, json={"id": ID}))
    out = await node({"operation": "create_export", "contentType": "application/vnd.climate.acrsi.geojson", "definition": definition}).execute({})
    assert out["id"] == ID and json.loads(calls[0].content)["definition"] == definition
    with pytest.raises(ValueError, match="Export definition requires"):
        await node({"operation": "create_export", "contentType": "application/vnd.climate.acrsi.geojson", "definition": {}}).execute({})
    assert len(calls) == 1
    upload_calls = transport(monkeypatch, lambda req: httpx.Response(201, json=ID))
    await node({"operation": "create_upload", "md5": "1B2M2Y8AsgTpgAmY7PhCfg==", "length": 100, "metadata": {"sourceId": ID}}).execute({})
    body = json.loads(upload_calls[-1].content)
    assert body == {"contentType": "application/vnd.climate.field.geojson", "md5": "1B2M2Y8AsgTpgAmY7PhCfg==", "length": 100, "metadata": {"sourceId": ID}}


@pytest.mark.asyncio
async def test_climate_binary_chunk_range_and_no_json(monkeypatch):
    calls = transport(monkeypatch, lambda req: httpx.Response(204))
    cfg = {"operation": "upload_chunk", "uploadId": ID, "data_base64": base64.b64encode(b"test").decode(), "content_range": "bytes 0-3/4"}
    await node(cfg).execute({})
    assert calls[0].content == b"test" and calls[0].headers["Content-Type"] == "application/octet-stream"
    assert calls[0].headers["Content-Range"] == "bytes 0-3/4"
    with pytest.raises(ValueError, match="must agree"):
        await node({**cfg, "content_range": "bytes 0-4/5"}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,wire", [("planting", "asPlanted"), ("application", "asApplied"), ("harvest", "asHarvested")])
async def test_climate_poll_baseline_then_update_and_agent_turn(monkeypatch, kind, wire):
    rows = [activity()]
    calls = transport(monkeypatch, lambda req: httpx.Response(200, json={"results": rows}))
    watcher = node({"operation": "on_updated_" + kind + "_activity", "updatedAfter": "2016-05-13T00:00:00Z", "resourceOwnerId": ID})
    state = {}
    async def update(mutator, **kwargs):
        changed, result = mutator(dict(state))
        if changed is not None:
            state.clear(); state.update(changed)
        return result
    watcher._update_node_state = update
    baseline = await watcher.execute({})
    assert baseline["activities"] == [] and watcher.trigger_produced_no_event(baseline)
    rows[0] = activity(updatedAt="2016-05-14T00:00:00.000Z")
    out = await watcher.execute({})
    assert out["activities"] == rows and watcher.trigger_emitted_event(out)
    assert ID in watcher.resolve_agent_event(out)["text"] and "2016-05-14" in watcher.resolve_agent_event(out)["text"]
    assert calls[0].url.path == "/v4/layers/" + wire
    assert dict(calls[0].url.params)["resourceOwnerId"] == ID
    assert (await watcher.execute({}))["activities"] == []


@pytest.mark.asyncio
async def test_climate_poll_follows_all_pages_and_rejects_stalled_cursor(monkeypatch):
    calls = transport(monkeypatch, lambda req: httpx.Response(206, json={"results": [activity()]}, headers={"X-Next-Token": "repeated"}))
    watcher = node({"operation": "on_updated_harvest_activity"})
    watcher._filter_unseen = AsyncMock()
    with pytest.raises(ValueError, match="repeated"):
        await watcher.execute({})
    assert len(calls) == 2
    watcher._filter_unseen.assert_not_called()


@pytest.mark.asyncio
async def test_climate_empty_304_and_redacted_auth_failure(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(304))
    assert (await node({"operation": "list_fields"}).execute({}))["results"] == []
    transport(monkeypatch, lambda req: httpx.Response(401, json={"message": TOKEN + KEY}))
    with pytest.raises(ValueError) as err:
        await node({"operation": "list_fields"}).execute({})
    assert TOKEN not in str(err.value) and KEY not in str(err.value) and "401" in str(err.value)


def test_climate_schema_contract_and_scope_coverage():
    assert len(native.OPERATIONS) == 22 and len(native.TRIGGERS) == 3
    for name in native.CONFIG_MODELS:
        assert native.CLIMATE_SCOPES.require(name) is not None
    assert OAUTH_PROVIDER.token_auth == "basic" and OAUTH_PROVIDER.rotates_refresh_tokens
    assert OAUTH_PROVIDER.identity_url == native.BASE_URL + "/v4/fields"
    assert native.ClimateOAuthCredential.model_fields["credential_type"].default == "climate_oauth"
    for invalid in ["../outside", "https://example.org"]:
        with pytest.raises(ValueError):
            node({"operation": "get_field", "fieldId": invalid})


@pytest.mark.asyncio
async def test_climate_oauth_identity_requires_partner_key_and_handles_empty(monkeypatch):
    monkeypatch.setenv("CLIMATE_API_KEY", KEY)
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"results": []})
    monkeypatch.setattr(type(OAUTH_PROVIDER), "_client", lambda self, url: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    assert await OAUTH_PROVIDER.account_name(TOKEN) == "FieldView account (no fields)"
    assert requests[0].headers["X-Api-Key"] == KEY
    monkeypatch.delenv("CLIMATE_API_KEY")
    with pytest.raises(ValueError, match="partner API key"):
        await OAUTH_PROVIDER.account_name(TOKEN)


@pytest.mark.asyncio
async def test_climate_export_chunk_is_binary_and_range_bounded(monkeypatch):
    calls = transport(monkeypatch, lambda req: httpx.Response(206, content=b"data", headers={"Content-Type": "application/octet-stream", "Content-Range": "bytes 0-3/4"}))
    output = await node({"operation": "download_export_chunk", "exportId": ID, "byte_range": "bytes=0-3"}).execute({})
    assert "data_base64" not in output
    assert isinstance(output["file"], BinaryOutput)
    assert output["file"].data == b"data"
    assert output["file"].content_type == "application/octet-stream"
    assert output["file"].filename == f"fieldview-export-{ID}-0-3.bin"
    assert output["content_range"] == "bytes 0-3/4"
    assert calls[0].headers["Range"] == "bytes=0-3" and calls[0].headers["Accept"] == "*/*"


@pytest.mark.asyncio
async def test_climate_export_chunk_run_returns_stored_file_reference(monkeypatch):
    from nodes.core import binary_output
    transport(monkeypatch, lambda req: httpx.Response(206, content=b"data",
        headers={"Content-Type": "application/octet-stream", "Content-Range": "bytes 0-3/4"}))
    filename = f"fieldview-export-{ID}-0-3.bin"
    store = AsyncMock(return_value={"download_url": "https://files.example.test/export-chunk",
        "mime_type": "application/octet-stream", "name": filename, "size_bytes": 4})
    monkeypatch.setattr(binary_output, "create_resource_from_bytes", store)
    downloader = node({"operation": "download_export_chunk", "exportId": ID, "byte_range": "bytes=0-3"})
    downloader.user_id = ID
    downloader.workflow_id = ID
    output = await downloader.run({})
    assert output["file"] == {"url": "https://files.example.test/export-chunk",
        "mime_type": "application/octet-stream", "name": filename, "size_bytes": 4}
    assert output["content_range"] == "bytes 0-3/4" and "data_base64" not in output
    store.assert_awaited_once_with(user_id=ID, workflow_id=ID, node_id="climate-test",
        organization_id=None, body=b"data", content_type="application/octet-stream", filename=filename)


@pytest.mark.asyncio
async def test_climate_async_export_error_is_documented_status_data(monkeypatch):
    status = {"status": "INVALID", "error": "Invalid export definition"}
    transport(monkeypatch, status)
    output = await node({"operation": "get_export_status", "exportId": ID}).execute({})
    assert output["export"] == status and "error" not in output


@pytest.mark.asyncio
async def test_climate_upload_creation_parses_documented_uuid_string(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(201, json=ID))
    output = await node({"operation": "create_upload", "md5": "1B2M2Y8AsgTpgAmY7PhCfg==", "length": 1}).execute({})
    assert output["id"] == ID


@pytest.mark.asyncio
async def test_climate_boundary_uses_published_numeric_geojson(monkeypatch):
    geometry = json.loads((Path(__file__).parent / "fixtures/climate/field-upload.geojson").read_text())["geometry"]
    calls = transport(monkeypatch, lambda req: httpx.Response(201, json={"id": ID}))
    await node({"operation": "upload_boundary", "geometry": geometry}).execute({})
    assert json.loads(calls[0].content) == {"geometry": geometry}
    assert calls[0].url.path == "/v4/boundaries" and calls[0].method == "POST"
    with pytest.raises(ValidationError):
        native.Geometry(type="Point", coordinates=["0", "0"])


@pytest.mark.asyncio
async def test_climate_poll_accumulates_every_page_before_seen_update(monkeypatch):
    first = activity()
    second = activity(id="00000000-0000-0000-0000-000000000001")
    def respond(request):
        if request.headers.get("X-Next-Token") == "page-two":
            return httpx.Response(200, json={"results": [second]})
        return httpx.Response(206, json={"results": [first]}, headers={"X-Next-Token": "page-two"})
    requests = transport(monkeypatch, respond)
    watcher = node({"operation": "on_updated_planting_activity"})
    async def fresh(items, id_fn):
        assert len({id_fn(item) for item in items}) == 2
        return items
    watcher._filter_unseen = AsyncMock(side_effect=fresh)
    out = await watcher.execute({})
    assert out["activities"] == [first, second] and len(requests) == 2
    watcher._filter_unseen.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("expires_in,expected_seconds", [(None, 14400), (600, 600)])
async def test_climate_refresh_rotates_and_stamps_documented_expiry(monkeypatch, expires_in, expected_seconds):
    from datetime import datetime, timezone
    from urllib.parse import parse_qs
    monkeypatch.setenv("CLIMATE_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("CLIMATE_CLIENT_SECRET", "fixture-secret")
    requests = []
    def respond(request):
        requests.append(request)
        payload = {"access_token": "fixture-successor-access", "refresh_token": "fixture-successor-refresh"}
        if expires_in is not None:
            payload["expires_in"] = expires_in
        return httpx.Response(200, json=payload)
    monkeypatch.setattr(type(OAUTH_PROVIDER), "_client", lambda self, url: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    before = datetime.now(timezone.utc)
    tokens = await OAUTH_PROVIDER.refresh("fixture-original-refresh")
    seconds = (datetime.fromisoformat(tokens.expires_at) - before).total_seconds()
    assert expected_seconds - 1 <= seconds <= expected_seconds + 5
    assert tokens.refresh_token == "fixture-successor-refresh"
    assert requests[0].url == "https://api.climate.com/api/oauth/token"
    body = parse_qs(requests[0].content.decode())
    assert body == {"grant_type": ["refresh_token"], "refresh_token": ["fixture-original-refresh"]}
    assert requests[0].headers["Authorization"] == "Basic " + base64.b64encode(b"fixture-client:fixture-secret").decode()
