"""Exercise native VTEX execution with the provider's published examples."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import vtex_node as vtex
from nodes.core.run_op import run_node_operation

FIXTURES = Path(__file__).parent / "fixtures" / "vtex"
CASES = json.loads((FIXTURES / "contract_examples.json").read_text())
EVENTS = json.loads((FIXTURES / "hook_events.json").read_text())
AUTH = {
    "credential_type": "vtex_app_key",
    "account_name": "apiexamples",
    "app_key": "test-app-key",
    "app_token": "test-app-token",
}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []

    def send(request):
        requests.append(request)
        assert request.url.host == "apiexamples.vtexcommercestable.com.br"
        assert request.headers["X-VTEX-API-AppKey"] == AUTH["app_key"]
        assert request.headers["X-VTEX-API-AppToken"] == AUTH["app_token"]
        assert request.headers["Content-Type"] == "application/json"
        assert AUTH["app_token"] not in str(request.url)
        code, body = replies.pop(0)
        return (
            httpx.Response(code, json=body)
            if body is not None
            else httpx.Response(code)
        )

    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as result:
            yield result

    monkeypatch.setattr(vtex, "guarded_async_client", client)
    return requests, replies


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_published_contract_examples_through_native_factory(transport, operation):
    requests, replies = transport
    case = CASES[operation]
    replies.append((200, case["response"]))
    output = await run_node_operation(
        node_type="automation-vtex",
        operation=operation,
        arguments=case["config"],
        credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001",
    )
    assert output["status"] == "success"
    assert output["data"] == (
        case["response"] if case["response"] is not None else {"ok": True}
    )
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    path = case["path"]
    for key, location in vtex.OPERATIONS[operation]["params"]:
        if location == "path":
            path = path.replace("{" + key + "}", str(case["config"][key]))
    assert request.url.path == path
    if case["body"] is not None:
        assert json.loads(request.content) == case["body"]


@pytest.mark.parametrize(
    "account",
    [
        "https://store.vtexcommercestable.com.br",
        "bad/name",
        "a.b",
        "-invalid",
        "a@evil.test",
        "x:443",
    ],
)
def test_account_host_is_provider_bound(account):
    with pytest.raises(ValidationError):
        vtex.VTEXAppKeyCredential.model_validate({**AUTH, "account_name": account})


@pytest.mark.asyncio
async def test_list_filters_are_query_parameters(transport):
    requests, replies = transport
    replies.append((200, {"list": []}))
    await run_node_operation(
        node_type="automation-vtex",
        operation="list_orders",
        arguments={
            "page": 2,
            "per_page": 15,
            "f_status": "ready-for-handling",
            "f_creationDate": "creationDate:[2022-01-01T02:00:00.000Z TO 2022-01-02T01:59:59.999Z]",
        },
        credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001",
    )
    assert requests[0].url.params["f_status"] == "ready-for-handling"
    assert requests[0].url.params["page"] == "2"
    assert requests[0].content == b""


@pytest.mark.asyncio
async def test_hook_registration_verification_and_safe_cleanup(transport):
    requests, replies = transport
    callback = "https://hooks.example.test/vtex"
    replies.append((200, None))
    registered = await vtex.VTEXNode._register_external_webhook(
        webhook_url=callback,
        credential=AUTH,
        config={"expression": 'status = "payment-pending"'},
        node_id="n1",
    )
    body = json.loads(requests[0].content)
    assert body["filter"] == {
        "type": "FromOrders",
        "expression": 'status = "payment-pending"',
        "disableSingleFire": True,
    }
    assert body["hook"]["url"] == callback
    secret = body["hook"]["headers"]["key"]
    assert len(secret) >= 32
    event = json.dumps(EVENTS["order.updated"]["body"]).encode()
    assert vtex.VTEXNode.verify_webhook_signature(event, {"KEY": secret}, registered)
    assert not vtex.VTEXNode.verify_webhook_signature(event, {}, registered)
    assert not vtex.VTEXNode.verify_webhook_signature(
        event, {"key": "wrong"}, registered
    )
    assert not vtex.VTEXNode.verify_webhook_signature(event, {"key": secret}, {})
    # The provider authenticates the header, not the body; no fabricated HMAC.
    replies.extend([(200, {"hook": {"url": callback}}), (204, None)])
    await vtex.VTEXNode._unregister_external_webhook(
        credential=AUTH, config=registered, node_id="n1"
    )
    assert requests[-1].method == "DELETE"
    replies.append((200, {"hook": {"url": "https://other.example.test"}}))
    before = len(requests)
    await vtex.VTEXNode._unregister_external_webhook(
        credential=AUTH, config=registered, node_id="n1"
    )
    assert len(requests) == before + 1
    assert requests[-1].method == "GET"


def test_documented_ping_and_event_reach_agent():
    cls = vtex.VTEXNode
    ping = EVENTS["hook.ping"]["body"]
    assert cls.handle_webhook_handshake(json.dumps(ping).encode(), {}) == {"ok": True}
    event = EVENTS["order.updated"]["body"]
    assert cls.handle_webhook_handshake(json.dumps(event).encode(), {}) is None
    assert cls.handle_webhook_handshake(b"invalid", {}) is None
    assert not cls.filter_trigger_payload(ping, {})
    assert cls.filter_trigger_payload(event, {})
    output = cls.resolve_trigger_payload(
        {**event, "_webhook": {"headers": {"key": "private-hook-key"}}}, {}
    )
    assert "_webhook" not in output["data"]
    agent_event = cls.resolve_agent_event(output)
    assert event["OrderId"] in agent_event["text"]
    assert event["State"] in agent_event["text"]
    assert event["Origin"]["Account"] in agent_event["text"]
    assert event["LastChange"] in agent_event["text"]


@pytest.mark.asyncio
async def test_provider_rejection_is_not_success(transport):
    _, replies = transport
    replies.append((403, {"message": "Access denied by License Manager"}))
    with pytest.raises(ValueError, match="Access denied by License Manager"):
        await vtex.VTEXNode._request(AUTH, "GET", "/api/oms/pvt/orders")


@pytest.mark.asyncio
async def test_malformed_nested_json_is_refused_before_http(transport):
    requests, _ = transport
    with pytest.raises(ValueError, match="valid JSON"):
        config = vtex.VTEXNodeConfig.model_validate(
            {
                "config": {
                    "operation": "register_change",
                    "orderId": "123-01",
                    "requestId": "r1",
                    "reason": "Stock shortage",
                    "discountValue": 100,
                    "incrementValue": 100,
                    "itemsAdded_json": "bad-json",
                },
                "credentials": AUTH,
            }
        )
        await vtex.VTEXNode(
            node_id="n",
            node_type="automation-vtex",
            node_data={},
            config=config,
            sio=Mock(),
        ).execute({})
    assert not requests


@pytest.mark.asyncio
async def test_manual_connect_shows_recognizable_order_ids(transport):
    from nodes.core.connection_evidence import collect_evidence

    requests, replies = transport
    example = CASES["list_orders"]["response"]
    replies.append((200, example))
    result = await collect_evidence(
        node_type="automation-vtex",
        credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001",
    )
    assert result.reachable is True
    assert result.samples[0].label == example["list"][0]["orderId"]
    assert requests[0].method == "GET"
