"""Uplisting wire-contract regressions using published response examples, no account."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import uplisting_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/uplisting/contract.json").read_text())["cases"]
TOKEN = "uplisting-synthetic-test-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(config, client_id="test-partner"):
    return NodeFactory.create_node(node_id="uplisting-test", node_type="automation-uplisting",
        node_data={"config": config, "credentials": {"credential_type": "uplisting_api_key", "api_key": TOKEN, "client_id": client_id}})


def transport(monkeypatch, status, payload):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_documented_route_response_and_auth(monkeypatch, case):
    requests = transport(monkeypatch, case["status"], case["response"])
    result = await make_node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["response"] == case["response"]
    assert len(requests) == 1
    req = requests[0]
    assert req.url.host == "connect.uplisting.io"
    assert req.method == case["method"] and req.url.path == case["path"]
    assert req.headers["Authorization"] == "Basic " + base64.b64encode(TOKEN.encode()).decode()
    assert req.headers.get("X-Uplisting-Client-Id") == ("test-partner" if case["path"].startswith("/v2/") else None)
    if case["operation"] == "update_calendar":
        assert json.loads(req.content) == {"calendar": {"days": case["config"]["days"]}}
        assert result["queued"] is True and result["applied"] is False
    elif case["operation"] == "create_booking":
        payload = json.loads(req.content)["data"]
        assert payload["relationships"] == {"property": {"data": {"type": "properties", "id": "11780"}}}
        assert payload["attributes"] == {k:v for k,v in case["config"].items() if k not in {"operation", "property_id"}}
    elif case["operation"] == "update_booking_attributes":
        assert json.loads(req.content) == {"data": {"attributes": {"lock_code": "1234567"}}}
    elif case["operation"] == "create_custom_booking_attribute":
        assert json.loads(req.content) == {"data": {"attributes": {"name": "partner_custom_attribute_name", "description": "Describe the custom attribute here"}}}
    elif case["operation"] == "create_hook":
        assert json.loads(req.content) == {"target_url": case["config"]["target_url"], "event": "booking_created"}
    elif case["operation"] == "get_calendar":
        assert dict(req.url.params) == {"from": "2020-02-01", "to": "2021-02-01"}
    elif case["operation"] == "search_availability":
        assert dict(req.url.params) == {"city": "Philadelphia", "number_of_guests": "3"}


@pytest.mark.asyncio
async def test_partner_client_id_required_before_request(monkeypatch):
    requests = transport(monkeypatch, 200, {})
    with pytest.raises(ValueError, match="partner client ID"):
        await make_node({"operation":"list_custom_booking_attributes"}, client_id=None).execute({})
    assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_http_failures_no_retry_or_secret_reflection(monkeypatch, status):
    requests = transport(monkeypatch, status, {"message":"API refused " + TOKEN})
    with pytest.raises(ValueError) as exc:
        await make_node({"operation":"get_account"}).execute({})
    assert str(status) in str(exc.value) and TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"errors":[{"detail":"Invalid key"}]}, []])
async def test_identity_and_error_envelope_not_success(monkeypatch, body):
    transport(monkeypatch, 200, body)
    with pytest.raises(ValueError):
        await make_node({"operation":"get_account"}).execute({})


@pytest.mark.asyncio
async def test_calendar_range_wire_names_and_false_values(monkeypatch):
    requests=transport(monkeypatch, 202, {"request_id":"owned-fixture"})
    await make_node({"operation":"update_calendar", "property_id":"11780", "days":[{"from_date":"2027-01-01", "to_date":"2027-02-01", "available":False}]}).execute({})
    assert json.loads(requests[0].content) == {"calendar":{"days":[{"from":"2027-01-01", "to":"2027-02-01", "available":False}]}}


@pytest.mark.parametrize("config", [
    {"operation":"create_booking","property_id":"1","check_in":"2027-02-01","check_out":"2027-01-01"},
    {"operation":"update_calendar","property_id":"1","days":[{"available":True}]},
    {"operation":"create_hook","target_url":"http://example.com","event":"booking_created"},
    {"operation":"create_custom_booking_attribute","name":"no namespace","description":"fixture"},
])
def test_invalid_user_input_rejected(config):
    with pytest.raises((ValidationError, ValueError)):
        make_node(config)
