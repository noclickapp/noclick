"""Exercise native Flutterwave requests, credential boundaries and response handling offline."""
import json
import base64
import hashlib
import hmac
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


WEBHOOK_FIXTURES = [json.loads((Path(__file__).parent / "fixtures/flutterwave" / name).read_text())["body"]
                    for name in ("webhook.json", "transfer_webhook.json")]


@pytest.mark.parametrize("payload", WEBHOOK_FIXTURES, ids=lambda body: body["type"])
def test_flutterwave_documented_signed_delivery_reaches_agent(payload):
    secret = "synthetic-signing-secret-36-characters"
    raw = json.dumps(payload).encode()
    signature = base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode()
    config = {"operation": "on_event", "event_type": payload["type"], "signing_secret": secret}
    cls = native.FlutterwaveNode
    assert cls.verify_webhook_signature(raw, {"Flutterwave-Signature": signature}, config)
    assert not cls.verify_webhook_signature(raw + b" ", {"flutterwave-signature": signature}, config)
    assert not cls.verify_webhook_signature(raw, {"flutterwave-signature": signature}, {**config, "signing_secret": "wrong"})
    assert cls.filter_trigger_payload(payload, config)
    assert cls.filter_trigger_payload(payload, {"operation": "on_event", "event_type": "all"})
    output = cls.resolve_trigger_payload({**payload, "_webhook": {"headers": {"authorization": TOKEN}}}, config)
    assert output == payload
    event = cls.resolve_agent_event(output)
    assert event["conversation_key"] == payload["data"]["id"]
    assert payload["type"] in event["text"] and payload["data"]["id"] in event["text"]
    assert str(payload["data"]["amount"]) in event["text"]
    assert payload["data"]["status"] in event["text"]
    assert str(payload["timestamp"]) in event["text"]
    assert "get_transfer" in event["text"] if payload["type"].startswith("transfer") else "get_charge" in event["text"]
    assert TOKEN not in str(event) and secret not in str(event)


@pytest.mark.parametrize("signature", [None, "", "sha256=abc", "é", "a" * 44])
def test_flutterwave_rejects_bad_or_missing_signature(signature):
    headers = {} if signature is None else {"flutterwave-signature": signature}
    assert not native.FlutterwaveNode.verify_webhook_signature(b"{}", headers, {"signing_secret": "secret"})
    assert not native.FlutterwaveNode.verify_webhook_signature(b"{}", headers, {})


@pytest.mark.parametrize("payload", WEBHOOK_FIXTURES, ids=lambda body: body["type"])
def test_flutterwave_wrong_event_and_missing_resource_do_not_fire(payload):
    cls = native.FlutterwaveNode
    config = {"operation": "on_event", "event_type": "refund.completed"}
    assert not cls.filter_trigger_payload(payload, config)
    assert cls.resolve_trigger_payload(payload, config)["status"] == "no_event"
    for broken in ({}, {**payload, "type": "unsupported"}, {**payload, "data": []}, {**payload, "data": {}}):
        assert not cls.filter_trigger_payload(broken, {"operation": "on_event"})
    assert not cls.filter_trigger_payload(payload, {"operation": "list_charges"})


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["all", *native.WEBHOOK_EVENTS])
@pytest.mark.parametrize("environment", ["sandbox", "production"])
async def test_flutterwave_webhook_lifecycle_exact_requests(monkeypatch, event_type, environment):
    requests = transport(monkeypatch, {"status": "success", "data": {"id": "wbk_endpoint"}})
    cls = native.FlutterwaveNode
    credential = {"access_token": TOKEN, "environment": environment}
    config = {"operation": "on_event", "event_type": event_type}
    registration = await cls._register_external_webhook(webhook_url="https://example.test/webhook", credential=credential,
                                                       config=config, node_id="flutterwave-test")
    request = requests[0]
    body = json.loads(request.content)
    assert request.method == "POST" and request.url.path == "/profile/webhook-endpoints"
    assert str(request.url).startswith(native.BASE_URLS[environment])
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert len(request.headers["X-Idempotency-Key"]) == 36 and len(request.headers["X-Trace-Id"]) == 36
    assert body == {"url": "https://example.test/webhook", "supported_event_types": list(native.WEBHOOK_EVENTS) if event_type == "all" else [event_type],
                    "status": "enabled", "description": "NoClick flutterwave-test", "secret": registration["signing_secret"]}
    assert len(registration["signing_secret"]) == 36
    assert registration["external_webhook_id"] == "wbk_endpoint"
    assert cls.parse_config({"config": {**config, **registration}}).config.signing_secret == registration["signing_secret"]
    assert cls.registration_fingerprint_fields(config) == {"event_type": event_type}
    requests = transport(monkeypatch, {}, 200)
    await cls._unregister_external_webhook(credential=credential, config={**config, **registration}, node_id="flutterwave-test")
    assert len(requests) == 1 and requests[0].method == "DELETE"
    assert requests[0].url.path == "/profile/webhook-endpoints/wbk_endpoint"
    assert str(requests[0].url).startswith(native.BASE_URLS[environment])
    assert not requests[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [({"status":"failed","message":TOKEN}, 401), ({"status":"success","data":{}}, 200), ({}, 200)])
async def test_flutterwave_does_not_accept_failed_registration(monkeypatch, body, status):
    transport(monkeypatch, body, status)
    with pytest.raises(ValueError) as error:
        await native.FlutterwaveNode._register_external_webhook(webhook_url="https://example.test/webhook",
            credential={"access_token":TOKEN}, config={"operation":"on_event"}, node_id="test")
    assert TOKEN not in str(error.value)


@pytest.mark.asyncio
async def test_flutterwave_teardown_needs_credential_and_surfaces_failure(monkeypatch):
    cls = native.FlutterwaveNode
    with pytest.raises(ValueError, match="Connect Flutterwave"):
        await cls._unregister_external_webhook(credential=None, config={"external_webhook_id":"owned"}, node_id="test")
    requests = transport(monkeypatch, {}, 500)
    with pytest.raises(ValueError, match="HTTP 500"):
        await cls._unregister_external_webhook(credential={"access_token":TOKEN}, config={"external_webhook_id":"owned"}, node_id="test")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_flutterwave_manual_trigger_run_has_no_event(monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("A manual trigger run must not call Flutterwave")
    monkeypatch.setattr(native, "guarded_async_client", forbidden)
    output = await node({"operation":"on_event"}).run({})
    assert output["status"] == "no_event" and not output["data"]
