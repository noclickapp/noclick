"""Exercise native dispatch, contract field names, error propagation and connect evidence."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import swarmsyncai_node as api
from nodes.core.run_op import run_node_operation

KEY = "fixture-swarmsyncai-key"
AUTH = {"credential_type": "swarmsyncai_api_key", "api_key": KEY}
AGENT = "00000000-0000-4000-8000-000000000001"
IDENTITY = json.loads((Path(__file__).parent / "fixtures/swarmsyncai/identity.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []

    async def handler(request):
        calls.append(request)
        assert request.url.host == "api.swarmsync.ai"
        assert request.headers["x-agent-api-key"] == KEY
        assert KEY not in str(request.url)
        return replies.pop(0)

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs) as value:
            yield value

    monkeypatch.setattr(api, "guarded_async_client", client)
    return calls, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-swarmsyncai", operation=operation,
        arguments=arguments or {}, credential_data=AUTH, user_id=AGENT)


CASES = [
    ("get_identity", {}, "GET", "/auth/me"),
    ("list_agents", {"search": "research"}, "GET", "/agents"),
    ("get_agent", {"agent_id": "agent-1"}, "GET", "/agents/agent-1"),
    ("list_needs", {"status": "OPEN"}, "GET", "/needs"),
    ("get_need", {"need_id": "need-1"}, "GET", "/needs/need-1"),
    ("get_matching_needs", {"agent_id": "agent-1"}, "GET", "/needs/for-agent/agent-1"),
    ("create_need", {"title": "Research task", "description": "Research this market", "required_capabilities": ["research"], "budget_cents": 500}, "POST", "/needs"),
    ("subscribe_to_need", {"need_id": "need-1", "subscriber_agent_id": AGENT}, "POST", "/needs/need-1/subscribe"),
    ("respond_to_need", {"need_id": "need-1", "responder_agent_id": AGENT, "message": "I can help", "proposed_price_cents": 250}, "POST", "/needs/need-1/respond"),
    ("get_need_matches", {"need_id": "need-1"}, "GET", "/needs/need-1/matches"),
    ("list_need_responses", {"need_id": "need-1"}, "GET", "/needs/need-1/responses"),
    ("cancel_need", {"need_id": "need-1"}, "POST", "/needs/need-1/cancel"),
    ("get_need_work_order", {"need_id": "need-1"}, "GET", "/needs/need-1/work-order"),
    ("list_work_orders", {"agent_id": "agent-1"}, "GET", "/needs/work-orders/for-agent/agent-1"),
    ("list_my_needs", {}, "GET", "/needs/my"),
    ("list_message_inbox", {}, "GET", "/agents/messages/inbox"),
    ("list_messages", {"agent_id": "agent-1", "direction": "sent", "limit": 20}, "GET", "/agents/agent-1/messages"),
    ("send_message", {"agent_id": "agent-2", "sender_agent_id": "agent-1", "message": "Please review this task", "in_reply_to": "message-1"}, "POST", "/agents/agent-2/message"),
    ("message_need_creator", {"need_id": "need-1", "sender_agent_id": "agent-1", "message": "Please clarify this task"}, "POST", "/needs/need-1/message-creator"),
    ("list_negotiations", {"agent_id": AGENT}, "GET", "/ap2/negotiations/my"),
    ("get_negotiation", {"negotiation_id": "neg-1"}, "GET", "/ap2/negotiations/neg-1"),
    ("cancel_negotiation", {"negotiation_id": "neg-1"}, "PATCH", "/ap2/negotiations/neg-1/cancel"),
    ("list_transactions", {"agent_id": AGENT}, "GET", "/ap2/transactions/my"),
    ("get_transaction", {"transaction_id": "txn-1"}, "GET", "/ap2/transactions/txn-1"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path", CASES)
async def test_native_dispatch(transport, operation, arguments, method, path):
    calls, replies = transport
    payload = IDENTITY if operation == "get_identity" else {"items": [{"id": "item-1"}], "total": 1}
    replies.append(httpx.Response(201 if method == "POST" else 200, json=payload))
    result = await run(operation, arguments)
    assert result["status"] == "success" and result["data"] == payload
    assert len(calls) == 1 and calls[0].method == method and calls[0].url.path == path
    if operation == "create_need":
        assert json.loads(calls[0].content) == {"title": "Research task", "description": "Research this market", "requiredCapabilities": ["research"], "budgetCents": 500}
    if operation == "respond_to_need":
        assert json.loads(calls[0].content) == {"responderAgentId": AGENT, "message": "I can help", "proposedPriceCents": 250}
    if operation == "send_message":
        assert json.loads(calls[0].content) == {"senderAgentId": "agent-1", "message": "Please review this task", "inReplyTo": "message-1"}
    if operation == "list_transactions":
        assert calls[0].url.params["agentId"] == AGENT
    if operation == "list_messages":
        assert dict(calls[0].url.params) == {"direction": "sent", "limit": "20"}


@pytest.mark.asyncio
async def test_account_evidence_and_rejection(transport):
    from nodes.core.connection_evidence import collect_evidence
    _, replies = transport
    replies.append(httpx.Response(200, json=IDENTITY))
    result = await collect_evidence(node_type="automation-swarmsyncai", credential_data=AUTH, user_id=AGENT)
    assert result.reachable is True and result.account_label == "Fixture Agent"
    replies.append(httpx.Response(401, json={"statusCode": 401, "message": "Invalid agent API key", "error": "Unauthorized"}))
    result = await collect_evidence(node_type="automation-swarmsyncai", credential_data=AUTH, user_id=AGENT)
    assert result.reachable is False and "Invalid agent API key" in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [200, 401, 403, 429, 500])
async def test_error_envelopes_never_report_success(transport, code):
    calls, replies = transport
    replies.append(httpx.Response(code, json={"statusCode": 401, "message": "Rejected " + KEY, "error": "Unauthorized"}))
    result = await run("get_identity")
    assert result["status"] == "error" and "Rejected" in result["message"]
    assert KEY not in json.dumps(result) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {"data": []}, {"id": "new-need"}, None])
async def test_response_shapes_preserved(transport, payload):
    transport[1].append(httpx.Response(200, json=payload))
    result = await run("list_my_needs")
    assert result["data"] == payload


@pytest.mark.asyncio
async def test_no_redirect_or_non_json_success(transport):
    transport[1].append(httpx.Response(302, headers={"location": "https://other.test"}))
    assert (await run("get_identity"))["status"] == "error"
    assert len(transport[0]) == 1
    transport[1].append(httpx.Response(200, text="<html>Sign in</html>"))
    with pytest.raises(ValueError, match="non-JSON"):
        await run("get_identity")


@pytest.mark.parametrize("value", ["../secret", "a/b", "a%2fb", "a?query", "a#fragment", "..", "a\n"])
def test_path_injection_rejected(value):
    with pytest.raises(ValidationError):
        api.GetNeed(need_id=value)


def test_manual_connect_default_and_secret_validation():
    assert api.SwarmsyncaiAPIKeyCredential(api_key=KEY).credential_type == "swarmsyncai_api_key"
    for value in ["https://example.com/key", "key\nvalue", "Bearer some-key"]:
        with pytest.raises(ValidationError):
            api.SwarmsyncaiAPIKeyCredential(api_key=value)


@pytest.mark.parametrize("changes", [{"budget_cents": 0}, {"title": "ab"}, {"required_capabilities": []}])
def test_create_need_contract_bounds(changes):
    values = {"title": "Research task", "description": "Research this market", "required_capabilities": ["research"], "budget_cents": 500}
    with pytest.raises(ValidationError):
        api.CreateNeed(**{**values, **changes})
