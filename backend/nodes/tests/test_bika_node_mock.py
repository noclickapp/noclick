"""Native factory tests; synthetic credentials and official-contract-shaped JSON."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import bika_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-bika-token"
PARENT = {"space_id": "spc123", "database_id": "dat123"}
RECORD = {"id": "rec123", "fields": {"Name": "Task", "Done": False}, "createdAt": "2026-01-01T00:00:00.000Z"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="bika-test", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": {"credential_type": native.FAMILY, "api_token": TOKEN}})


def mock(monkeypatch, payload, status=200):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def envelope(data):
    return {"success": True, "code": 200, "message": "SUCCESS", "data": data}


CASES = [
    ({"operation": "list_spaces"}, "GET", "/v1/spaces", [{"id": "spc123", "name": "Work"}]),
    ({"operation": "get_space", "space_id": "spc123"}, "GET", "/v1/spaces/spc123", {"id": "spc123", "name": "Work"}),
    ({"operation": "get_profile"}, "GET", "/v1/user/profile", None),
    ({"operation": "list_records", **PARENT}, "GET", "/v2/spaces/spc123/resources/databases/dat123/records", {"records": [RECORD], "hasMore": False}),
    ({"operation": "get_record", **PARENT, "record_id": "rec123"}, "GET", "/v2/spaces/spc123/resources/databases/dat123/records/rec123", RECORD),
    ({"operation": "create_records", **PARENT, "records": [{"fields": RECORD["fields"]}]}, "POST", "/v2/spaces/spc123/resources/databases/dat123/records", {"records": [RECORD]}),
    ({"operation": "update_records", **PARENT, "records": [{"id": "rec123", "fields": {"Done": True}}]}, "PUT", "/v2/spaces/spc123/resources/databases/dat123/records", {"records": [RECORD]}),
    ({"operation": "update_record", **PARENT, "record_id": "rec123", "fields": {"Done": True, "Name": None}}, "PUT", "/v2/spaces/spc123/resources/databases/dat123/records/rec123", RECORD),
    ({"operation": "delete_records", **PARENT, "record_ids": ["rec123", "rec456"]}, "DELETE", "/v2/spaces/spc123/resources/databases/dat123/records", [{"id": "rec123", "deleted": True}, {"id": "rec456", "deleted": True}]),
    ({"operation": "delete_record", **PARENT, "record_id": "rec123"}, "DELETE", "/v2/spaces/spc123/resources/databases/dat123/records/rec123", {"id": "rec123", "deleted": True}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,data", CASES)
async def test_bika_all_operations_native_factory(monkeypatch, config, method, path, data):
    payload = envelope(data) if data is not None else {"id": "usr123", "name": "Account", "email": None, "avatar": {"type": "PRESET", "url": "/avatar"}}
    requests = mock(monkeypatch, payload)
    out = await node(config).execute({})
    assert out["status"] == "success" and out["data"] == (data if data is not None else payload)
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == "/api/openapi/bika" + path
    assert req.url.host == "bika.ai" and req.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(out)
    if method in {"PUT", "POST"}:
        body = json.loads(req.content)
        assert body["fieldKey"] == "name"
        if config["operation"] == "update_record":
            assert body["fields"] == config["fields"]
        else:
            assert body["records"] == config["records"]
    if config["operation"] == "delete_records":
        assert req.url.params.get_list("records") == config["record_ids"]
        assert req.content == b""


@pytest.mark.asyncio
async def test_bika_pagination_filters_and_field_selection(monkeypatch):
    requests = mock(monkeypatch, envelope({"records": [RECORD], "hasMore": True, "offset": "opaque/+next"}))
    cfg = {"operation": "list_records", **PARENT, "offset": "prior", "page_size": 25,
        "fields": ["Name", "Done"], "filter": 'Name=="A + B"', "field_key": "id", "max_records": 300}
    out = await node(cfg).execute({})
    assert out["has_more"] and out["next_offset"] == "opaque/+next"
    assert requests[0].url.params.get_list("fields") == ["Name", "Done"]
    assert requests[0].url.params["filter"] == cfg["filter"]
    assert requests[0].url.params["pageSize"] == "25" and requests[0].url.params["offset"] == "prior"
    assert requests[0].url.params["fieldKey"] == "id" and requests[0].url.params["cellFormat"] == "json"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,status", [(envelope([]), 401), (envelope([]), 429), ({"success": False, "code": 403, "message": TOKEN}, 200), ([], 200)])
async def test_bika_rejects_errors_without_token_or_retry(monkeypatch, payload, status):
    requests = mock(monkeypatch, payload, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_spaces"}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_bika_connection_rejection_preserves_provider_words(monkeypatch):
    mock(monkeypatch, {"message": "Access token has expired"}, 401)
    with pytest.raises(ValueError, match="Bika HTTP 401: Access token has expired"):
        await node({"operation": "list_spaces"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("page", [{"records": [], "hasMore": True}, {"records": [], "hasMore": True, "offset": "prior"}, {"records": [], "hasMore": "false"}])
async def test_bika_rejects_unusable_pages(monkeypatch, page):
    mock(monkeypatch, envelope(page))
    with pytest.raises(ValueError):
        await node({"operation": "list_records", **PARENT, "offset": "prior"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_space", "space_id": "../other"},
    {"operation": "get_space", "space_id": ".."},
    {"operation": "delete_record", **PARENT, "record_id": "a/b"},
    {"operation": "create_records", **PARENT, "records": []},
    {"operation": "update_records", **PARENT, "records": [{"fields": {}}]},
    {"operation": "delete_records", **PARENT, "record_ids": ["rec"] * 11},
])
def test_bika_rejects_bad_targets_and_batches(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_bika_discovery_and_manual_credential_default():
    assert native.NODE_TYPE in NODE_REGISTRY
    assert native.BikaAPITokenCredential(api_token=TOKEN).credential_type == native.FAMILY
    assert native.BikaNode.connection_evidence.operation == "list_spaces"
