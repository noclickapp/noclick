"""Exercise Sidetracker through the real factory with offline HTTP.

The fixture pins provider operationIds; tests cover payloads and rejected reads.
"""
import json
import re
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import sidetracker_node as native
from nodes.core.registry import NodeFactory

CONTRACT = json.loads((Path(__file__).parent / "fixtures/sidetracker/operations.json").read_text())
TOKEN = "fixture-sidetracker-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="sidetracker-test", node_type="automation-sidetracker",
        node_data={"config": config, "credentials": {"credential_type": "sidetracker_api_token", "api_token": TOKEN}})


def mock_http(monkeypatch, response):
    requests = []
    def send(request):
        requests.append(request)
        assert request.url.host == "app.sidetracker.io"
        assert request.headers["Authorization"] == "Token " + TOKEN
        assert TOKEN not in str(request.url)
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,contract", CONTRACT.items())
async def test_sidetracker_contract_routes(monkeypatch, operation, contract):
    config = {"operation": operation, **{key: "resource-123" for key in re.findall(r"\{(\w+)\}", contract["path"])}}
    if operation == "create_list":
        config.update(name="New Tracking List", description="A list for tracking various events.",
            preset="tracking", columns=["SessionID", "IpAddress", "Country", "Browser"])
    requests = mock_http(monkeypatch, httpx.Response(contract["status"]))
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] is None
    assert len(requests) == 1 and requests[0].method == contract["method"]
    assert requests[0].url.path == re.sub(r"\{\w+\}", "resource-123", contract["path"])
    if operation == "create_list":
        assert dict(requests[0].url.params) == {"preset": "tracking"}
        assert json.loads(requests[0].content) == {k: v for k, v in config.items() if k != "operation"}
    else:
        assert not requests[0].content


@pytest.mark.asyncio
async def test_sidetracker_preserves_page_and_repeats_filters(monkeypatch):
    page = {"count": 101, "next": "https://app.sidetracker.io/api/lists?page=2", "previous": None,
        "results": [{"unique_id": "list-1", "name": "Campaign leads"}]}
    requests = mock_http(monkeypatch, httpx.Response(200, json=page))
    result = await node({"operation": "list_lists", "page": 1, "page_size": 100}).execute({})
    assert result["data"] == page and len(requests) == 1
    assert dict(requests[0].url.params) == {"page": "1", "page_size": "100"}
    requests = mock_http(monkeypatch, httpx.Response(200, json={"results": []}))
    await node({"operation": "list_conversions", "tag": ["paid", "organic"], "sales_status": ["CUSTOMER"],
        "daterange": "2026-08-01 to 2026-08-20"}).execute({})
    assert requests[0].url.params.get_list("tag") == ["paid", "organic"]
    assert requests[0].url.params["daterange"] == "2026-08-01 to 2026-08-20"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 404, 429, 500])
async def test_sidetracker_http_failures(monkeypatch, code):
    mock_http(monkeypatch, httpx.Response(code, json={"detail": "Rejected"}))
    with pytest.raises(httpx.HTTPError):
        await node({"operation": "list_lists"}).execute({})


@pytest.mark.asyncio
async def test_sidetracker_error_envelope_and_malformed_json(monkeypatch):
    for response in [httpx.Response(200, json={"status": "error"}), httpx.Response(200, text="<html>Login</html>")]:
        mock_http(monkeypatch, response)
        with pytest.raises(ValueError):
            await node({"operation": "list_lists"}).execute({})


@pytest.mark.parametrize("token", ["Token abc", "bad\r\nheader", "https://example.com/key", "<token>"])
def test_sidetracker_bad_tokens(token):
    with pytest.raises(ValueError):
        native.SidetrackerTokenCredential(api_token=token)


def test_sidetracker_manual_connect_and_preset_validation():
    assert native.SidetrackerTokenCredential(api_token=TOKEN).credential_type == "sidetracker_api_token"
    with pytest.raises(ValidationError):
        native.SidetrackerCreateListConfig(name="test", preset="checks", columns=["SessionID"])
    with pytest.raises(ValidationError):
        native.SidetrackerGetListConfig(unique_id="..")
