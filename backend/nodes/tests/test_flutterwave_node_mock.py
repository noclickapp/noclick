"""Exercise native Flutterwave requests, credential boundaries and response handling offline."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import flutterwave_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-flutterwave-access-42"
CASES = json.loads((Path(__file__).parent / "fixtures/flutterwave/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, environment="sandbox"):
    return NodeFactory.create_node(node_id="flutterwave-test", node_type="automation-flutterwave", node_data={
        "config": config, "credentials": {"credential_type": "flutterwave_access_token", "access_token": TOKEN, "environment": environment},
    })


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_flutterwave_exact_one_request_and_payload(monkeypatch, case):
    op = case["config"]["operation"]
    data = [{"id":"owned-id", "email":"owner@example.test"}] if op.startswith("list_") else {"id":"owned-id", "status":"pending"}
    if op == "list_transfers":
        data = {"cursor":{"next":"next+/="}, "transfers":[{"id":"owned-id"}]}
    requests = transport(monkeypatch, {"status":"success", "data":data, "meta":{"page_info":{"current_page":1,"total_pages":2}}}, 201 if case["method"] == "POST" else 200)
    result = await node(case["config"]).run({})
    assert result["status"] == "success" and result["data"] == data
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert request.url.host == "developersandbox-api.flutterwave.com"
    assert dict(request.url.params) == case["query"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert len(request.headers["X-Trace-Id"]) == 36
    if case["method"] == "POST":
        assert request.headers["X-Idempotency-Key"] == case["config"]["idempotency_key"]
        assert result["request_accepted"] is True and result["resource_status"] == "pending"
    else:
        assert "X-Idempotency-Key" not in request.headers
    if op.startswith("list_"):
        assert result["page_only"] is True


def test_flutterwave_fixture_covers_every_operation():
    assert {c["config"]["operation"] for c in CASES} == set(native.ROUTES)


@pytest.mark.asyncio
async def test_flutterwave_date_range_wire_names_and_live_origin(monkeypatch):
    requests = transport(monkeypatch, {"status":"success", "data":[]})
    result = await node({"operation":"list_refunds", "page":2, "size":20, "from_datetime":"2025-04-21T10:55:16Z", "to_datetime":"2025-05-21T10:48:18Z"}, "production").run({})
    assert result["status"] == "success"
    assert str(requests[0].url).startswith("https://f4bexperience.flutterwave.com/refunds?")
    assert dict(requests[0].url.params) == {"page":"2", "size":"20", "from":"2025-04-21T10:55:16Z", "to":"2025-05-21T10:48:18Z"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302,401,403,404,429,500])
async def test_flutterwave_provider_error_and_redaction(monkeypatch, status):
    requests = transport(monkeypatch, {"status":"failed", "message":"Refused " + TOKEN}, status)
    result = await node({"operation":"list_customers"}).run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["message"] == "Refused [redacted]" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"status":"success"}, {"status":"success","data":{}}, {"status":"failed","message":"Rejected"}])
async def test_flutterwave_invalid_or_failed_envelope_is_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    if body.get("status") == "success":
        with pytest.raises(ValueError, match="invalid data envelope"):
            await node({"operation":"list_customers"}).run({})
    else:
        assert (await node({"operation":"list_customers"}).run({}))["status"] == "error"


@pytest.mark.asyncio
async def test_flutterwave_pending_refund_is_acceptance_not_completed_money_movement(monkeypatch):
    case = next(c for c in CASES if c["config"]["operation"] == "create_refund")
    transport(monkeypatch, {"status":"success", "data":{"id":"rfd-test","status":"pending"}}, 201)
    result = await node(case["config"]).run({})
    assert result["request_accepted"] and result["resource_status"] == "pending"
    assert "completed" not in result and "readback_verified" not in result


@pytest.mark.asyncio
async def test_flutterwave_write_timeout_not_retried(monkeypatch):
    case = next(c for c in CASES if c["config"]["operation"] == "create_refund")
    requests = transport(monkeypatch, httpx.ReadTimeout("secret " + TOKEN))
    with pytest.raises(ValueError, match="write outcome is unknown") as failure:
        await node(case["config"]).run({})
    assert TOKEN not in str(failure.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_flutterwave_recursive_secret_redaction(monkeypatch):
    transport(monkeypatch, {"status":"success", "data":[{"id":"owned", "meta":{"access_token":TOKEN,"notes":"contains " + TOKEN}}]})
    result = await node({"operation":"list_customers"}).run({})
    assert result["data"][0]["meta"] == {"notes":"contains [redacted]"}
    assert TOKEN not in str(result)


@pytest.mark.parametrize("token", ["https://example.com/key", "<token>", "Bearer abc", "abc\r\ndef", "abc\x00def", "abcé"])
def test_flutterwave_rejects_invalid_manual_tokens(token):
    with pytest.raises(ValidationError):
        native.FlutterwaveAccessTokenCredential(access_token=token)


@pytest.mark.parametrize("config", [
    {"operation":"get_customer","id":"../profile/credentials"},
    {"operation":"get_customer","id":"id?query=value"},
    {"operation":"list_customers","size":51},
    {"operation":"list_customers","page":0},
    {"operation":"update_customer","id":"owned"},
    {"operation":"list_transfers","page":2},
    {"operation":"list_refunds","from_datetime":"2025-05-01T00:00:00Z","to_datetime":"2025-04-01T00:00:00Z"},
    {"operation":"create_refund","amount":1,"charge_id":"owned","reason":"duplicate"},
])
def test_flutterwave_refuses_invalid_configs(config):
    with pytest.raises(ValueError):
        native.FlutterwaveNode.parse_config({"config":config})


@pytest.mark.asyncio
async def test_flutterwave_documented_account_response(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/flutterwave/documented_responses.json").read_text())[0]
    transport(monkeypatch, fixture["body"])
    result = await node({"operation":"get_virtual_account", "id":fixture["body"]["data"]["id"]}).run({})
    assert result["data"] == fixture["body"]["data"]


@pytest.mark.asyncio
async def test_flutterwave_pending_charge_preserves_authorization_action(monkeypatch):
    # The charging-a-card guide shows top-level pending and a PIN next_action.
    case = next(c for c in CASES if c["config"]["operation"] == "create_charge")
    data = {"id":"chg_VoUhmFMhmF", "status":"pending", "next_action":{"type":"authorize", "authorization":{"type":"pin"}}}
    transport(monkeypatch, {"status":"pending", "message":"Charge requires authorization", "data":data}, 201)
    result = await node(case["config"]).run({})
    assert result["status"] == "success" and result["resource_status"] == "pending"
    assert result["data"]["next_action"]["authorization"] == {"type":"pin"}
