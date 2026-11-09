"""SNCF published examples and HTTP-boundary regressions; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import sncf_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-sncf-api-key-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/sncf/published_examples.json").read_text())["examples"]


def node(config):
    return NodeFactory.create_node(node_id="sncf-test", node_type="automation-sncf",
        node_data={"config": config, "credentials": {"credential_type": "sncf_api_key", "api_key": TOKEN}})


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
    assert request.method == "GET" and request.url.host == "ressources.data.sncf.com"
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
    with pytest.raises(ValueError, match="SNCF request failed") as caught:
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
    assert native.SncfAPIKeyCredential(api_key=TOKEN).credential_type == "sncf_api_key"
    assert native.SncfNode.connection_evidence.proves == "reachability"
