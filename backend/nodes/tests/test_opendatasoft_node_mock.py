"""Opendatasoft published examples and HTTP-boundary regressions; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import opendatasoft_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-opendatasoft-api-key-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/opendatasoft/published_examples.json").read_text())["examples"]


def node(config):
    return NodeFactory.create_node(node_id="opendatasoft-test", node_type="automation-opendatasoft",
        node_data={"config": config, "credentials": {"credential_type": "opendatasoft_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, *, status=200, mime="application/json"):
    requests = []

    def respond(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body, headers={"content-type": mime}) if mime == "application/json" else httpx.Response(status, content=body, headers={"content-type": mime})

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,config,example", [
    ("list_datasets", "/catalog/datasets", {}, "datasets-v2.1"),
    ("list_catalog_export_formats", "/catalog/exports", {}, None),
    ("list_catalog_facets", "/catalog/facets", {}, "catalog_facets"),
    ("list_records", "/catalog/datasets/geonames/records", {"dataset_id": "geonames"}, "records-v2.1"),
    ("list_dataset_export_formats", "/catalog/datasets/geonames/exports", {"dataset_id": "geonames"}, None),
    ("get_dataset", "/catalog/datasets/geonames", {"dataset_id": "geonames"}, "dataset-v2.1"),
    ("list_record_facets", "/catalog/datasets/geonames/facets", {"dataset_id": "geonames"}, "facets"),
    ("list_attachments", "/catalog/datasets/geonames/attachments", {"dataset_id": "geonames"}, "attachments"),
    ("get_record", "/catalog/datasets/geonames/records/abc", {"dataset_id": "geonames", "record_id": "abc"}, "record-v2.1"),
])
async def test_documented_json_reads(monkeypatch, operation, path, config, example):
    body = EXAMPLES[example] if example else {"links": []}
    requests = transport(monkeypatch, body)
    assert await node({"operation": operation, **config}).execute({}) == {"status": "success", "data": body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.url.host == "data.opendatasoft.com"
    assert request.url.path == "/api/explore/v2.1" + path
    expected = {"apikey": TOKEN}
    if operation in {"list_datasets", "list_records"}:
        expected.update(limit="10", offset="0")
    assert dict(request.url.params) == expected
    assert not request.content


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,config,mime,data", [
    ("export_catalog_csv", "/catalog/exports/csv", {"delimiter": ",", "with_bom": False}, "text/csv", b"name,count\ntrain,1"),
    ("export_records_csv", "/catalog/datasets/train/exports/csv", {"dataset_id": "train"}, "text/csv", b"name\ntrain"),
    ("export_records_parquet", "/catalog/datasets/train/exports/parquet", {"dataset_id": "train", "parquet_compression": "zstd"}, "application/octet-stream", b"PAR1\x00\xffPAR1"),
    ("export_records_gpx", "/catalog/datasets/train/exports/gpx", {"dataset_id": "train", "name_field": "gare"}, "application/gpx+xml", b"<gpx/>"),
])
async def test_binary_exports(monkeypatch, operation, path, config, mime, data):
    requests = transport(monkeypatch, data, mime=mime)
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success" and isinstance(result["file"], BinaryOutput)
    assert result["file"].data == data and result["file"].content_type == mime
    assert len(requests) == 1 and requests[0].url.path == "/api/explore/v2.1" + path
    assert requests[0].method == "GET"
    expected = {"apikey": TOKEN, **{k: str(v).lower() if isinstance(v, bool) else v for k, v in config.items() if k != "dataset_id"}}
    assert dict(requests[0].url.params) == expected


@pytest.mark.asyncio
async def test_odsql_and_explicit_pagination(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES["group_by_country-v2.1"])
    result = await node({"operation": "list_records", "dataset_id": "stations", "select": "count(*) as count, cou_name_en",
        "where": 'cou_name_en="France"', "group_by": "cou_name_en", "order_by": "count desc", "refine": "country:France",
        "limit": 100, "offset": 100, "lang": "fr", "include_links": True}).execute({})
    assert result["data"] == EXAMPLES["group_by_country-v2.1"]
    params = dict(requests[0].url.params)
    assert params["select"] == "count(*) as count, cou_name_en" and params["where"] == 'cou_name_en="France"'
    assert params["limit"] == "100" and params["offset"] == "100" and params["include_links"] == "true"
    assert params["group_by"] == "cou_name_en" and params["lang"] == "fr"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_http_errors_preserve_rejection_and_redact_key(monkeypatch, status):
    requests = transport(monkeypatch, ("Invalid API key " + TOKEN).encode(), status=status, mime="text/plain")
    assert await node({"operation": "list_datasets"}).execute({}) == {
        "status": "error", "http_status": status, "error": "Invalid API key [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_links_cannot_expose_key(monkeypatch):
    transport(monkeypatch, {"links": [{"href": native.BASE + "?apikey=" + TOKEN}]})
    assert TOKEN not in str(await node({"operation": "list_catalog_export_formats"}).execute({}))


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"results": None}, {"results": "invalid"}])
async def test_invalid_evidence_never_succeeds(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_datasets"}).execute({})


@pytest.mark.asyncio
async def test_network_exception_does_not_expose_credential(monkeypatch):
    transport(monkeypatch, httpx.ConnectError("Failed " + native.BASE + "?apikey=" + TOKEN))
    with pytest.raises(ValueError, match="Opendatasoft request failed") as caught:
        await node({"operation": "list_datasets"}).execute({})
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("config", [
    {"operation": "list_records"}, {"operation": "get_record", "dataset_id": "test"},
    {"operation": "list_datasets", "limit": 101}, {"operation": "list_datasets", "offset": -1},
    {"operation": "list_datasets", "url": "https://example.com"},
    {"operation": "get_dataset", "dataset_id": ".."},
    {"operation": "export_records_parquet", "dataset_id": "test", "parquet_compression": "gzip"},
])
def test_invalid_config(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_manual_credential_has_default_type():
    assert native.OpendatasoftAPIKeyCredential(api_key=TOKEN).credential_type == "opendatasoft_api_key"
    assert native.OpendatasoftNode.connection_evidence.proves == "reachability"


@pytest.mark.asyncio
async def test_poll_documented_catalog_baseline_update_and_dedup(monkeypatch):
    from copy import deepcopy
    body = deepcopy(EXAMPLES["datasets-v2.1"])
    body["total_count"] = len(body["results"])
    requests = transport(monkeypatch, body)
    instance = node({"operation": "on_dataset_updated"})
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(state)
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    monkeypatch.setattr(instance, "_update_node_state", update)
    baseline = await instance.execute({})
    assert baseline["new_dataset_count"] == 0
    assert not instance.should_propagate_output(baseline, {"operation": "on_dataset_updated"})
    body["results"][0]["metas"]["default"]["modified"] = "2026-11-10T12:00:00+00:00"
    transport(monkeypatch, body)
    changed = await instance.execute({})
    assert changed["new_dataset_count"] == 1
    assert changed["datasets"][0]["dataset_id"] == body["results"][0]["dataset_id"]
    assert instance.should_propagate_output(changed, {"operation": "on_dataset_updated"})
    assert (await instance.execute({}))["new_dataset_count"] == 0
    assert dict(requests[0].url.params)["order_by"] == "modified desc"
    assert "schedule" not in requests[0].url.params


@pytest.mark.asyncio
async def test_poll_fetches_every_page_before_dedup(monkeypatch):
    from copy import deepcopy
    row = deepcopy(EXAMPLES["datasets-v2.1"]["results"][0])
    pages = []
    async def read(self, cfg, credential):
        pages.append(cfg.model_dump())
        return {"status": "success", "data": {"total_count": 101,
            "results": [dict(row, dataset_id=str(i)) for i in range(cfg.offset, min(cfg.offset + 100, 101))]}}
    monkeypatch.setattr(native.OpendatasoftNode, "_read", read)
    instance = node({"operation": "on_dataset_updated", "where": "theme='World'"})
    async def unseen(rows, key):
        assert len(rows) == 101
        assert len({key(row) for row in rows}) == 101
        return rows
    monkeypatch.setattr(instance, "_filter_unseen", unseen)
    assert (await instance.execute({}))["new_dataset_count"] == 101
    assert [p["offset"] for p in pages] == [0, 100]
    assert all(p["where"] == "theme='World'" for p in pages)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"results": [], "total_count": 10000},
    {"results": [{"dataset_id": "missing-timestamp"}], "total_count": 1},
    {"results": [], "total_count": 1},
])
async def test_poll_refuses_incomplete_snapshot(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "on_dataset_updated"}).execute({})


def test_poll_scope_tracks_only_declared_fields():
    from nodes.core.poll_trigger import poll_scope
    config = {"operation": "on_dataset_updated", "where": "theme='World'"}
    scope = poll_scope(native.OpendatasoftNode, config)
    assert scope and scope == poll_scope(native.OpendatasoftNode, {**config, "label": "Changed label"})
    assert scope != poll_scope(native.OpendatasoftNode, {**config, "where": "theme='Other'"})
