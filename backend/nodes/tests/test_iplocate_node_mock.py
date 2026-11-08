"""Exercise the real factory and documented IPLocate wire/response contracts."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import iplocate_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-iplocate-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="iplocate-test", node_type="automation-iplocate", node_data={
        "config": config, "credentials": {"credential_type": "iplocate_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", [
    ({"operation": "lookup_self"}, "GET", "/api/lookup/", None),
    ({"operation": "lookup_self_filtered", "filter": "asn.asn"}, "GET", "/api/lookup/asn.asn", None),
    ({"operation": "lookup", "ip": "8.8.8.8", "include": "asn.asn,privacy.is_vpn"}, "GET", "/api/lookup/8.8.8.8", None),
    ({"operation": "lookup_filtered", "ip": "2001:4860:4860::8888", "filter": "privacy"}, "GET", "/api/lookup/2001:4860:4860::8888/privacy", None),
    ({"operation": "batch_lookup", "ips": ["8.8.8.8", "1.1.1.1"]}, "POST", "/api/batch", ["8.8.8.8", "1.1.1.1"]),
])
async def test_five_operations_exact_requests(monkeypatch, config, method, path, body):
    requests = transport(monkeypatch, httpx.Response(200, json={"ip": "8.8.8.8"}))
    result = await node(config).execute({})
    assert result == {"status": "success", "data": {"ip": "8.8.8.8"}}
    request, = requests
    assert request.method == method and request.url.host == "iplocate.io" and request.url.path == path
    assert dict(request.url.params) == {"apikey": TOKEN, **({"include": config["include"]} if "include" in config else {})}
    assert json.loads(request.content) == body if body is not None else not request.content


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["8.8.8.8", "AS15169", "false", "null", "123"])
async def test_filtered_text_preserves_type_and_value(monkeypatch, value):
    transport(monkeypatch, httpx.Response(200, text=value))
    assert (await node({"operation": "lookup_filtered", "ip": "8.8.8.8", "filter": "ip"}).run({}))["data"] == value


@pytest.mark.asyncio
async def test_documented_json_objects_and_batch_inline_errors(monkeypatch):
    fixtures = json.loads((Path(__file__).parent / "fixtures/iplocate/contract_examples.json").read_text())
    for config, body in fixtures:
        transport(monkeypatch, httpx.Response(200, json=body))
        assert (await node(config).run({}))["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_errors_do_not_expose_key_or_follow_redirects(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={"error": "Invalid API key " + TOKEN}, headers={"Location": "https://example.test"}))
    result = await node({"operation": "lookup_self"}).run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>error</html>", headers={"Content-Type": "text/html"}), httpx.Response(200, text="bad", headers={"Content-Type": "application/json"}), httpx.Response(200, json=[]), httpx.Response(200, json={"error": "failed"})])
async def test_malformed_success_is_not_proof(monkeypatch, response):
    transport(monkeypatch, response)
    assert (await node({"operation": "lookup_self"}).run({}))["status"] == "error"


@pytest.mark.asyncio
async def test_transport_exception_does_not_expose_query_key(monkeypatch):
    def fail(request):
        raise httpx.ConnectError(str(request.url), request=request)
    transport(monkeypatch, fail)
    result = await node({"operation": "lookup_self"}).run({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.parametrize("config", [
    {"operation": "lookup", "ip": "../batch"},
    {"operation": "lookup", "ip": "fe80::1%en0"},
    {"operation": "lookup_filtered", "ip": "8.8.8.8", "filter": "ip?apikey=other"},
    {"operation": "lookup_self", "include": "ip,,asn"},
    {"operation": "batch_lookup", "ips": []},
    {"operation": "batch_lookup", "ips": ["8.8.8.8"] * 1001},
    {"operation": "batch_lookup", "ips": ["not-ip"]},
    {"operation": "lookup_self", "url": "https://evil.test"},
])
def test_invalid_config_cannot_construct_request(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credential_default_and_evidence():
    assert native.IplocateAPIKeyCredential(api_key="  " + TOKEN + "\n").credential_type == "iplocate_api_key"
    assert native.IplocateAPIKeyCredential(api_key="  " + TOKEN + "\n").api_key == TOKEN
    with pytest.raises(ValidationError):
        native.IplocateAPIKeyCredential(api_key="https://www.iplocate.io/account")
    assert native.IplocateNode.connection_evidence.proves == "reachability"
    assert native.IplocateNode.connection_evidence.operation == "lookup_self"
