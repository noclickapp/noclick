"""Offline Regiondo request routing, PHP-compatible HMAC and failure handling."""
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
import nodes.regiondo_node as mod

CASES = json.loads((Path(__file__).parent / "fixtures/regiondo/requests.json").read_text())
CREDENTIAL = {"credential_type": "regiondo_api_key", "public_key": "test-public-key", "private_key": "test-private-key"}


def node(config, credential=None):
    parsed = mod.RegiondoNode.parse_config({"config": config, "credentials": credential or CREDENTIAL})
    return mod.RegiondoNode("test", "automation-regiondo", {}, config=parsed)


def mock_http(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session
    monkeypatch.setattr(mod, "guarded_async_client", client)
    monkeypatch.setattr(mod.time, "time", lambda: 1700000000)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
@pytest.mark.asyncio
async def test_regiondo_requests(monkeypatch, case):
    seen = []
    def handler(request):
        seen.append(request)
        assert request.url.host == "api.regiondo.com"
        assert request.method == case["method"]
        assert request.url.path == "/v1" + case["path"]
        assert dict(request.url.params) == case["params"]
        assert not request.content
        assert request.headers["X-API-ID"] == CREDENTIAL["public_key"]
        assert request.headers["X-API-TIME"] == "1700000000"
        message = b"1700000000test-public-key" + request.url.query
        assert request.headers["X-API-HASH"] == hmac.new(b"test-private-key", message, hashlib.sha256).hexdigest()
        if case["operation"] == "list_products":
            assert request.url.query.endswith(b"kwd=caf%C3%A9+%26+%7E+ride")
        return httpx.Response(200, json=case["response"])
    mock_http(monkeypatch, handler)
    result = await node({"operation": case["operation"], **case["config"]}).execute({})
    assert result["data"] == case["response"]
    assert len(seen) == 1


@pytest.mark.parametrize("status,payload", [(401, {"code":401,"message":"Rejected test-private-key"}),
    (429, {"message":"Rate limited"}), (200, {"result":"error","message":"Denied"}),
    (202, {"data":{"error":"Cannot cancel"}}), (302, {})])
@pytest.mark.asyncio
async def test_regiondo_errors_and_no_write_retries(monkeypatch, status, payload):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, json=payload)
    mock_http(monkeypatch, handler)
    with pytest.raises(ValueError, match="Regiondo HTTP") as exc:
        await node({"operation":"cancel_tickets","reference_ids":"r-1"}).execute({})
    assert CREDENTIAL["private_key"] not in str(exc.value)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_regiondo_explicit_pagination(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=[{"tag_id":1}]))
    result = await node({"operation":"list_tags","limit":1,"offset":12}).execute({})
    assert result["next_offset"] == 13
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=[]))
    assert (await node({"operation":"list_tags","limit":1,"offset":13}).execute({}))["next_offset"] is None


@pytest.mark.parametrize("config", [
    {"operation":"get_product","productId":"../x"}, {"operation":"list_tags","limit":251},
    {"operation":"list_tags","offset":-1}, {"operation":"cancel_tickets","reference_ids":""},
    {"operation":"get_availability","variationId":1,"dt_from":"2026-11-10","dt_to":"2026-11-01"},
])
def test_regiondo_invalid_config(config):
    with pytest.raises(ValueError):
        node(config)


def test_regiondo_connect_fields():
    cred = mod.RegiondoAPIKeyCredential(public_key=" real-public-key ", private_key="real-private-key")
    assert cred.credential_type == "regiondo_api_key"
    assert cred.public_key == "real-public-key"
    assert mod.RegiondoNode.connection_evidence.operation == "list_holds"
    assert {case["operation"] for case in CASES} == set(mod.ROUTES)
