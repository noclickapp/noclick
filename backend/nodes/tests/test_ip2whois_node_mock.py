"""Exercise the native IP2WHOIS node with the provider's published response."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import ip2whois_node as native
from nodes.core.registry import NodeFactory

TOKEN = "test-ip2whois-license-9876"
DOCUMENTED = json.loads((Path(__file__).parent / "fixtures/ip2whois/lookup.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(domain="locaproxy.com", credentials=True):
    return NodeFactory.create_node(node_id="ip2whois-test", node_type="automation-ip2whois", node_data={
        "config": {"operation": "lookup_domain", "domain": domain},
        "credentials": {"credential_type": "ip2whois_api_key", "api_key": TOKEN} if credentials else None,
    })


def transport(monkeypatch, response):
    requests = []
    original = httpx.AsyncClient
    def reply(request):
        requests.append(request)
        if isinstance(response, Exception):
            raise response
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
async def test_documented_response_and_exact_request(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json=DOCUMENTED, headers={"content-type": "text/html; charset=UTF-8"}))
    result = await node().execute({})
    assert result == {"status": "success", "data": DOCUMENTED}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and str(request.url).startswith("https://api.ip2whois.com/v2/?")
    assert dict(request.url.params) == {"key": TOKEN, "domain": "locaproxy.com", "format": "json"}
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("code,message", [(10001, "API key not found."), (10002, "API key disabled."), (10003, "API key expired."), (10004, "Insufficient credits."), (10006, "No data found."), (10007, "Invalid domain.")])
async def test_provider_error_envelope(monkeypatch, code, message):
    transport(monkeypatch, httpx.Response(200, json={"error": {"error_code": code, "error_message": message}}))
    assert await node().execute({}) == {"status": "error", "error": message, "error_code": code}


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(302, headers={"location": "https://evil.test"}), httpx.Response(401, text=TOKEN), httpx.Response(200, text="not-json"), httpx.Response(200, json=[]), httpx.Response(200, json={}), httpx.ConnectError(TOKEN)])
async def test_fail_closed_without_key_or_false_success(monkeypatch, response):
    requests = transport(monkeypatch, response)
    result = await node().execute({})
    assert result["status"] == "error" and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_missing_credentials_and_reachability_declaration():
    with pytest.raises(ValueError, match="Connect an IP2WHOIS"):
        await node(credentials=False).execute({})
    evidence = native.Ip2WhoisNode.connection_evidence
    assert evidence.proves == "reachability"
    assert evidence.operation_arguments == {"domain": "locaproxy.com"}


@pytest.mark.parametrize("domain", ["https://locaproxy.com", "locaproxy.com/path", "loca proxy.com", "", "locaproxy.com:443"])
def test_domain_validation(domain):
    with pytest.raises(ValidationError):
        native.Ip2WhoisLookupConfig(domain=domain)
