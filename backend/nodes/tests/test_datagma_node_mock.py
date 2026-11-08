"""Offline request and failure regressions; no Datagma account is used."""
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from nodes import datagma_node as native
from nodes.core.registry import NodeFactory


TOKEN = "synthetic-datagma-key+42"
CASES = json.loads((Path(__file__).parent / "fixtures/datagma/requests.json").read_text())


def node(config, credentials=None):
    return NodeFactory.create_node(
        node_id="datagma-test", node_type="automation-datagma",
        node_data={"config": config, "credentials": credentials or {"api_key": TOKEN}},
    )


def transport(monkeypatch, *, body=None, status=200, raw=None):
    requests = []

    def reply(request):
        requests.append(request)
        if raw is not None:
            return httpx.Response(status, text=raw)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_datagma_exact_contract_requests_and_preserved_data(monkeypatch, case):
    body = case["response"]
    requests = transport(monkeypatch, body=body)
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "data": body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url).startswith(native.API_BASE + case["path"] + "?")
    assert dict(request.url.params) == {**case["query"], "apiId": TOKEN}
    assert not request.content and "authorization" not in request.headers


@pytest.mark.asyncio
async def test_datagma_credit_redacts_echoed_key_recursively(monkeypatch):
    requests = transport(monkeypatch, body={
        "email": "owner@example.test", "apiId": TOKEN, "currentCredit": "100", "plan": "1",
        "nested": [{"apiId": TOKEN, "url": "https://gateway.datagma.net/?apiId=" + quote(TOKEN, safe="")}],
    })
    result = await node({"operation": "get_credit"}).execute({})
    assert result["data"]["email"] == "owner@example.test"
    assert TOKEN not in str(result) and quote(TOKEN, safe="") not in str(result)
    assert "apiId" not in result["data"]
    assert "apiId" not in result["data"]["nested"][0]
    assert dict(requests[0].url.params) == {"apiId": TOKEN}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_datagma_http_errors_are_not_success_and_do_not_leak_keys(monkeypatch, status):
    requests = transport(monkeypatch, status=status, body={"message": "Rejected " + TOKEN})
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_credit"}).execute({})
    assert f"HTTP {status}" in str(exc.value) and TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"error": "bad key"}, {"errors": ["bad key"]}, {"status": "error", "message": "bad key"},
    {"httpStatusCode": 403}, {"code": 7, "message": "Permission denied"},
    {"success": False}, [], None,
])
async def test_datagma_error_envelopes_fail_even_on_http_200(monkeypatch, body):
    transport(monkeypatch, body=body)
    with pytest.raises(ValueError):
        await node({"operation": "get_credit"}).execute({})


@pytest.mark.asyncio
async def test_datagma_invalid_json_and_empty_credit_are_not_connection_evidence(monkeypatch):
    transport(monkeypatch, raw="<html>Sign in</html>")
    with pytest.raises(ValueError, match="non-JSON"):
        await node({"operation": "get_credit"}).execute({})
    transport(monkeypatch, body={})
    with pytest.raises(ValueError, match="account credit"):
        await node({"operation": "get_credit"}).execute({})


@pytest.mark.asyncio
async def test_datagma_transport_exception_does_not_expose_credential_url(monkeypatch):
    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("request failed apiId=" + TOKEN)

    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: FailingClient())
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_credit"}).execute({})
    assert TOKEN not in str(exc.value)


def test_datagma_manual_key_default_and_config_validation():
    credential = native.DatagmaAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.api_key == TOKEN and credential.credential_type == "datagma_api_key"
    for config in [
        {"operation": "invented"}, {"operation": "reverse_phone_lookup"},
        {"operation": "get_credit", "apiId": "override"},
        {"operation": "get_credit", "url": "https://example.test"},
    ]:
        with pytest.raises(ValueError):
            native.DatagmaNode.parse_config({"config": config})
    with pytest.raises(ValueError):
        native.DatagmaAPIKeyCredential(api_key="https://app.datagma.com/user-api")
