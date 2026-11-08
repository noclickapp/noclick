"""Exercise MoonClerk through the real factory using its published examples.

Only the HTTP transport is replaced; route selection, authentication, filters,
pagination, credential shaping and response parsing run as in a workflow.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import moonclerk_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-moonclerk-key-42"
FIXTURES = Path(__file__).parent / "fixtures" / "moonclerk"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="moonclerk-fixture", node_type="automation-moonclerk",
        node_data={"config": config, "credentials": {"credential_type": "moonclerk_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body=None, *, status=200, text=None, mime=native.ACCEPT):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"content-type": mime}) if text is None else httpx.Response(status, text=text, headers={"content-type": mime})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["form", "customer", "payment"])
@pytest.mark.parametrize("listing", [True, False])
async def test_moonclerk_all_six_routes_published_examples(monkeypatch, kind, listing):
    record = json.loads((FIXTURES / (kind + ".json")).read_text())["body"]
    envelope = kind + "s" if listing else kind
    requests = transport(monkeypatch, {envelope: [record] if listing else record})
    config = {"operation": ("list_" + envelope if listing else "get_" + kind)}
    if not listing:
        config["id"] = record["id"]
    output = await node(config).execute({})
    assert output["status"] == "success"
    assert output["data"] == ([record] if listing else record)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.host == "api.moonclerk.com"
    assert request.url.path == "/" + kind + "s" + ("" if listing else "/" + str(record["id"]))
    assert request.headers["Authorization"] == "Token token=" + TOKEN
    assert request.headers["Accept"] == native.ACCEPT
    assert dict(request.url.params) == ({"count": "10", "offset": "0"} if listing else {})
    if listing:
        assert output["next_offset"] is None and output["page_may_have_more"] is False
    if kind == "payment":
        assert record["amount"] == 1000 and record["fee"] == 59
        assert record["custom_fields"]["shipping_address"]["response"]["city"] == "Greenville"


@pytest.mark.asyncio
@pytest.mark.parametrize("config,expected", [
    ({"operation": "list_customers", "count": 20, "offset": 20, "form_id": 5346,
      "checkout_from": "2014-10-01", "checkout_to": "2014-10-31", "next_payment_from": "2014-10-01", "next_payment_to": "2014-10-31", "status": "active"}, "customers"),
    ({"operation": "list_payments", "count": 100, "offset": 200, "form_id": 5346,
      "customer_id": 12742, "date_from": "2014-10-01", "date_to": "2014-10-31", "status": "refunded"}, "payments"),
])
async def test_moonclerk_all_documented_filters(monkeypatch, config, expected):
    requests = transport(monkeypatch, {expected: []})
    result = await node(config).execute({})
    assert result["data"] == []
    assert dict(requests[0].url.params) == {k: str(v) for k, v in config.items() if k != "operation"}


@pytest.mark.asyncio
async def test_moonclerk_pagination_full_page_is_only_a_hint(monkeypatch):
    transport(monkeypatch, {"forms": [{"id": 234456, "title": "Monthly Subscription"}]})
    result = await node({"operation": "list_forms", "count": 1, "offset": 20}).execute({})
    assert result["next_offset"] == 21 and result["page_may_have_more"]
    assert "has_more" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 502, 503, 504, 302])
async def test_moonclerk_plain_text_errors_preserve_rejection_and_redact_key(monkeypatch, status):
    text = "HTTP Token: Access denied. " + TOKEN
    requests = transport(monkeypatch, status=status, text=text, mime="text/plain")
    result = await node({"operation": "list_forms"}).execute({})
    assert result == {"status": "error", "error": "HTTP Token: Access denied. [redacted]", "status_code": status}
    assert len(requests) == 1 and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body,mime", [({"forms": {}}, native.ACCEPT), ({"wrong": []}, native.ACCEPT), ({"forms": [None]}, native.ACCEPT), ({"forms": []}, "text/html")])
async def test_moonclerk_malformed_success_is_not_evidence(monkeypatch, body, mime):
    transport(monkeypatch, body, mime=mime)
    with pytest.raises(ValueError):
        await node({"operation": "list_forms"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "list_forms", "count": 101}, {"operation": "list_forms", "offset": -1},
    {"operation": "get_form", "id": "../customers"}, {"operation": "list_payments", "status": "active"},
    {"operation": "list_customers", "checkout_from": "2014-02-30"},
    {"operation": "list_payments", "date_from": "2014-10-31", "date_to": "2014-10-01"},
    {"operation": "create_form"},
])
def test_moonclerk_reject_unsupported_or_invalid_config(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize("value", ["https://example.com", "Token token=key", "key\r\nInjected: yes"])
def test_moonclerk_credential_rejects_headers_urls_controls(value):
    with pytest.raises(ValidationError):
        native.MoonclerkAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_moonclerk_account_specific_connection_evidence(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, {"forms": [{"id": 234456, "title": "Monthly Subscription"}]})
    result = await collect_evidence(node_type="automation-moonclerk", user_id="moonclerk-test",
        credential_data={"credential_type": "moonclerk_api_key", "api_key": TOKEN})
    assert result.reachable is True
    assert "Monthly Subscription" in str(result)


@pytest.mark.asyncio
async def test_moonclerk_timeout_and_echoed_secret(monkeypatch):
    transport(monkeypatch, {"forms": [{"id": 1, "title": TOKEN}]})
    result = await node({"operation": "list_forms"}).execute({})
    assert result["data"][0]["title"] == "[redacted]"
    def client(**kwargs):
        def reply(request):
            raise httpx.ConnectTimeout("private details " + TOKEN, request=request)
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    result = await node({"operation": "list_forms"}).execute({})
    assert result["status"] == "error" and "status_code" not in result and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reachable", [(401, False), (403, False), (429, None), (503, None)])
async def test_moonclerk_connection_rejection_vs_cannot_judge(monkeypatch, status, reachable):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, status=status, text="HTTP Token: Access denied." if status in {401, 403} else "Try later", mime="text/plain")
    result = await collect_evidence(node_type="automation-moonclerk", user_id="moonclerk-test",
        credential_data={"credential_type": "moonclerk_api_key", "api_key": TOKEN})
    assert result.reachable is reachable
    if reachable is False:
        assert "HTTP Token: Access denied." in str(result)
