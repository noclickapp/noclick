"""Exercise the node through its factory against documented JSON responses."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import ip2location_io_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-ip2location-key"
BODY = json.loads((Path(__file__).parent / "fixtures/ip2location-io/geolocation.json").read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(**changes):
    return NodeFactory.create_node(node_id="ip-fixture", node_type=native.Ip2LocationIoNode.integration_type,
        node_data={"config": {"operation": "get_ip_geolocation", "ip": "8.8.8.8", **changes},
                   "credentials": {"credential_type": "ip2location_io_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_documented_lookup_and_translation(monkeypatch):
    requests = transport(monkeypatch, BODY)
    result = await node(lang="ko").execute({})
    assert result == {"status": "success", "data": BODY}
    request = requests[0]
    assert request.method == "GET" and request.url.host == "api.ip2location.io" and request.url.path == "/"
    assert dict(request.url.params) == {"key": TOKEN, "ip": "8.8.8.8", "format": "json", "lang": "ko"}
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_ipv6_and_omitted_language(monkeypatch):
    address = "2001:4860:4860::8888"
    requests = transport(monkeypatch, {**BODY, "ip": address})
    result = await node(ip=address).execute({})
    assert result["data"]["ip"] == address
    assert "lang" not in requests[0].url.params


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [({"error": {"error_code": 10001, "error_message": "Invalid API key " + TOKEN}}, 200), (BODY, 401), (BODY, 302), ([], 200), ({}, 200), ({**BODY, "ip": "1.1.1.1"}, 200)])
async def test_rejected_malformed_and_mismatched_responses(monkeypatch, body, status):
    requests = transport(monkeypatch, body, status)
    result = await node().execute({})
    assert result["status"] == "error" and "data" not in result
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.parametrize("changes", [{"ip": "not-an-ip"}, {"ip": "https://example.com"}, {"lang": "xx"}, {"operation": "write"}])
def test_invalid_inputs(changes):
    with pytest.raises((ValidationError, ValueError)):
        node(**changes)


def test_evidence_is_documented_read_and_only_reachability():
    proof = native.Ip2LocationIoNode.connection_evidence
    assert proof.operation == "get_ip_geolocation" and proof.proves == "reachability"
    assert proof.operation_arguments == {"ip": "8.8.8.8"}
