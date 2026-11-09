"""Billetweb wire behavior using provider-authored v1 request/response examples.

Fixtures are copied from https://www.billetweb.fr/api/openapi.json?v=1141.
No live account or credentials are used.
"""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import billetweb_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures/billetweb"
CONTRACT = json.loads((FIXTURES / "contract.json").read_text())
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
KEY = "billetweb-synthetic-key-42"
CREDENTIAL = {"credential_type": "billetweb_api_key", "user_id": "1", "api_key": KEY}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="billetweb-test",
        node_type="automation-billetweb",
        node_data={"config": config, "credentials": CREDENTIAL},
    )


def transport(monkeypatch, reply):
    requests = []

    def respond(request):
        requests.append(request)
        return reply(request)

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(CONTRACT))
async def test_billetweb_provider_examples_exact_requests_and_lossless_response(
    monkeypatch, operation
):
    case = CONTRACT[operation]
    response = RESPONSES[operation]
    requests = transport(
        monkeypatch, lambda request: httpx.Response(200, json=response)
    )
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and result["data"] == response
    assert len(requests) == 1
    request = requests[0]
    resource = case["config"].get("event_id", case["config"].get("list_id"))
    assert request.url.path == case["path"].replace("{id}", str(resource))
    assert request.method == case["method"] and request.url.host == "www.billetweb.fr"
    assert (
        request.headers["Authorization"]
        == "Basic " + base64.b64encode(("1:" + KEY).encode()).decode()
    )
    assert "key" not in request.url.params and "user" not in request.url.params
    if case["method"] == "POST":
        expected = {
            k: v
            for k, v in case["config"].items()
            if k not in {"operation", "event_id", "list_id"}
        }
        assert json.loads(request.content) == expected
        assert request.headers["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_billetweb_incremental_filters_and_zero_flags_survive(monkeypatch):
    requests = transport(monkeypatch, lambda request: httpx.Response(200, json=[]))
    await node(
        {
            "operation": "list_event_attendees",
            "event_id": 1235,
            "last_update": 1583247094,
            "used": 0,
            "disabled": 0,
            "email": "jean+sync@dupont.fr",
        }
    ).execute({})
    assert dict(requests[0].url.params) == {
        "last_update": "1583247094",
        "used": "0",
        "disabled": "0",
        "email": "jean+sync@dupont.fr",
    }
    assert "%2B" in str(requests[0].url)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_billetweb_errors_preserve_provider_message_and_do_not_retry(
    monkeypatch, status
):
    requests = transport(
        monkeypatch,
        lambda request: httpx.Response(
            status,
            json={"error": "rejected", "description": "Provider refused " + KEY},
            headers={"location": "https://example.test/"},
        ),
    )
    result = await node(CONTRACT["add_orders"]["config"]).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Provider refused" in result["error"] and KEY not in str(result)
    assert result["write_outcome"] == "unverified" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"error": "denied", "description": "Access denied"}),
        httpx.Response(
            200, text="<html>Login</html>", headers={"content-type": "text/html"}
        ),
        httpx.Response(
            200, content=b"not JSON", headers={"content-type": "application/json"}
        ),
    ],
)
async def test_billetweb_error_envelopes_and_non_json_are_not_success(
    monkeypatch, response
):
    transport(monkeypatch, lambda request: response)
    assert (await node({"operation": "list_events"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_billetweb_timeout_does_not_retry_write(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    requests = transport(monkeypatch, timeout)
    result = await node(CONTRACT["add_orders"]["config"]).execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unverified"
    assert len(requests) == 1


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_availability", "event_id": "../other"},
        {"operation": "clone_event", "event_id": 1235, "name": "x"},
        {"operation": "update_event", "event_id": 1235, "data": {}},
        {"operation": "update_tickets", "event_id": 1235, "data": [{"id": 0}]},
        {"operation": "check_tickets", "event_id": 1235, "data": [{"used": 1}]},
        {
            "operation": "add_orders",
            "event_id": 1235,
            "data": [
                {"payment_type": "multiple", "products": [{"ticket": "Plein tarif"}]}
            ],
        },
        {
            "operation": "add_orders",
            "event_id": 1235,
            "data": [{"payment_type": "cash", "products": []}],
        },
        {"operation": "delete_orders", "event_id": 1235, "data": []},
    ],
)
def test_billetweb_invalid_inputs_fail_before_http(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_billetweb_manual_credential_default_and_account_evidence():
    credential = native.BilletwebAPIKeyCredential(user_id="1", api_key=KEY)
    assert credential.credential_type == "billetweb_api_key"
    assert native.BilletwebNode.connection_evidence.operation == "list_events"
    assert native.BilletwebNode.connection_evidence.proves == "account"
    for key in ["https://example.test/key", "Bearer token", KEY + ":bad"]:
        with pytest.raises(ValidationError):
            native.BilletwebAPIKeyCredential(user_id="1", api_key=key)


@pytest.mark.asyncio
async def test_billetweb_documented_empty_write_response(monkeypatch):
    requests = transport(monkeypatch, lambda request: httpx.Response(200, content=b""))
    result = await node(CONTRACT["update_event"]["config"]).execute({})
    assert result == {"status": "success", "data": None, "http_status": 200}
    assert len(requests) == 1
