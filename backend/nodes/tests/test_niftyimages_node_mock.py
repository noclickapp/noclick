"""HTTP-boundary regressions for NiftyImages; all accounts and responses are synthetic."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import niftyimages_node as native
from nodes.core.registry import NodeFactory

TOKEN = "niftyimages-synthetic-key-42"
CASES = json.loads((Path(__file__).parent / "fixtures/niftyimages/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="fixture", node_type="automation-niftyimages",
        node_data={"config": config, "credentials": {"credential_type": "niftyimages_api_key", "api_key": TOKEN}})


def transport(monkeypatch, status, response):
    requests = []
    def respond(request):
        requests.append(request)
        if isinstance(response, Exception):
            raise response
        return httpx.Response(status, json=response) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c['config']['operation'])
async def test_niftyimages_factory_exact_provider_request_and_response(monkeypatch, case):
    requests = transport(monkeypatch, case["http_status"], case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "dev.niftyimages.com"
    assert request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in request.content.decode()
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert TOKEN not in str(result)
    if case["http_status"] == 204:
        assert result["acknowledged"] is True
    elif "nextCursor" in case["response"]:
        assert result["data"] == case["response"]["data"]
        assert result["next_cursor"] == case["response"]["nextCursor"]
        assert result["has_more"] == (case["response"]["nextCursor"] is not None)
    else:
        assert result["data"] == case["response"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_niftyimages_failures_preserve_provider_message_and_redact_key(monkeypatch, status):
    requests = transport(monkeypatch, status, {"detail": "Rejected " + TOKEN})
    result = await node({"operation": "rename_image", "image_id": 418344, "name": "Spring launch hero"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Rejected [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{}, {"data": []}, {"data": [], "nextCursor": 42}, {"data": [], "nextCursor": None, "error": "failed"}, []])
async def test_niftyimages_malformed_page_is_not_success(monkeypatch, response):
    transport(monkeypatch, 200, response)
    assert (await node({"operation": "list_stores"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_niftyimages_unsafe_write_timeout_never_retries(monkeypatch):
    requests = transport(monkeypatch, 200, httpx.ReadTimeout("unconfirmed"))
    result = await node({"operation": "add_record", "store_id": "loyalty", "record": {"points": 4200}}).execute({})
    assert result["status"] == "error" and "before retrying" in result["error"]
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "search_locations", "map_id": 1},
    {"operation": "search_locations", "map_id": 1, "address": "Market", "uniqueId": "sf-store"},
    {"operation": "search_locations", "map_id": 1, "lat": 37.7937},
    {"operation": "add_location", "map_id": 1},
    {"operation": "get_store", "store_id": ".."},
    {"operation": "get_record", "store_id": "loyalty", "record_id": "."},
    {"operation": "get_image", "image_id": 0},
    {"operation": "create_store", "name": "Empty", "properties": []},
    {"operation": "batch_upsert_records", "store_id": "loyalty", "records": [{}] * 101},
])
def test_niftyimages_rejects_invalid_operations_before_network(config):
    with pytest.raises((ValueError, ValidationError)):
        native.NiftyimagesNode.parse_config({"config": config})


def test_niftyimages_discovery_and_manual_key_evidence_contract():
    from nodes.core.registry import NODE_REGISTRY
    assert NODE_REGISTRY["automation-niftyimages"] is native.NiftyimagesNode
    assert native.NiftyimagesNode.connection_evidence.operation == "list_stores"
    assert native.NiftyimagesNode.connection_evidence.identity_operation == "check_connection"
    assert len(CASES) == 25
    credential = native.NiftyimagesAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.api_key == TOKEN
    assert credential.credential_type == "niftyimages_api_key"
    for key in ("https://example.com/key", "Bearer " + TOKEN, "<token>"):
        with pytest.raises(ValidationError):
            native.NiftyimagesAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
async def test_niftyimages_opaque_record_id_is_one_encoded_path_segment(monkeypatch):
    from urllib.parse import quote
    opaque = "https://example.com/customer?account=1#main"
    requests = transport(monkeypatch, 200, {"id": opaque})
    result = await node({"operation": "get_record", "store_id": "loyalty", "record_id": opaque}).execute({})
    assert result["status"] == "success"
    assert requests[0].url.raw_path == ("/v2/stores/loyalty/records/" + quote(opaque, safe="")).encode()
    assert not requests[0].url.query and not requests[0].url.fragment
