"""Exercise Mercury through the native factory using fixture-only HTTP."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import mercury_node as mercury
from nodes.core.run_op import run_node_operation
from utils import ssrf

FIXTURES = Path(__file__).parent / "fixtures/mercury"
CASES = json.loads((FIXTURES / "cases.json").read_text())
TOKEN = "secret-token:fixture-mercury-token"
AUTH = {"credential_type": "mercury_api_token", "api_token": TOKEN}
USER = "00000000-0000-4000-8000-000000000001"
ID = "4d153fec-30ce-4460-a1ac-89beb8caba1e"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.mercury.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        code, body = reply
        if body is None:
            return httpx.Response(code, content=b"")
        if isinstance(body, bytes):
            return httpx.Response(code, content=body)
        return httpx.Response(code, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(mercury, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(
        node_type="automation-mercury", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(auth), user_id=USER,
    )


@pytest.mark.parametrize("operation", CASES)
@pytest.mark.asyncio
async def test_each_operation_is_one_contract_request(transport, operation):
    case = CASES[operation]
    requests, replies = transport
    replies.append((case["status"], case["response"]))
    result = await run(operation, deepcopy(case["config"]))
    assert result["status"] == "success", result
    assert result["http_status"] == case["status"]
    assert result["data"] == case["response"]
    assert len(requests) == 1 and replies == []
    assert requests[0].method == case["method"]
    assert requests[0].url.path == "/api/v1" + case["path"]
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_payment_idempotency_and_json_body(transport):
    requests, replies = transport
    config = deepcopy(CASES["send_money"]["config"])
    config.update(amount=12.34, idempotencyKey="invoice-2026-11-01", note="Supplier payment")
    replies.append((200, CASES["send_money"]["response"]))
    await run("send_money", config)
    body = json.loads(requests[0].content)
    assert body == {k: v for k, v in config.items() if k != "accountId"}
    assert requests[0].headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_cursor_and_repeated_transaction_filters(transport):
    requests, replies = transport
    next_id = "d1dd44d7-23bb-4ac9-8104-3e0e05e15b3e"
    payload = {"transactions": [], "page": {"nextPage": next_id}}
    replies.append((200, payload))
    result = await run("list_transactions", {"limit": 5, "start_after": ID, "status": ["pending", "sent"], "accountId": [ID, next_id]})
    query = requests[0].url.params
    assert query.get_list("status") == ["pending", "sent"]
    assert query.get_list("accountId") == [ID, next_id]
    assert query["start_after"] == ID and query["limit"] == "5"
    assert result["data"]["page"]["nextPage"] == next_id
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_metadata_null_clears_are_sent_and_omissions_stay_omitted(transport):
    requests, replies = transport
    replies.extend([(200, CASES["update_transaction"]["response"])] * 2)
    await run("update_transaction", {"transactionId": ID, "note": None})
    assert json.loads(requests[-1].content) == {"note": None}
    await run("update_transaction", {"transactionId": ID, "categoryId": None, "note": "Reconciled"})
    assert json.loads(requests[-1].content) == {"categoryId": None, "note": "Reconciled"}


@pytest.mark.asyncio
async def test_invoice_email_choice_defaults_to_dont_send(transport):
    requests, replies = transport
    replies.append((200, CASES["create_invoice"]["response"]))
    await run("create_invoice", CASES["create_invoice"]["config"])
    assert json.loads(requests[0].content)["sendEmailOption"] == "DontSend"


@pytest.mark.asyncio
async def test_nullable_invoice_number_survives_other_operation_fields(transport):
    requests, replies = transport
    replies.append((200, CASES["create_invoice"]["response"]))
    await run("create_invoice", {**CASES["create_invoice"]["config"], "invoiceNumber": None})
    assert json.loads(requests[0].content)["invoiceNumber"] is None
    with pytest.raises(ValueError):
        await run("update_invoice", {**CASES["update_invoice"]["config"], "invoiceId": ID, "invoiceNumber": None})
    assert len(requests) == 1


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 302])
@pytest.mark.asyncio
async def test_errors_are_not_success_and_token_is_redacted(transport, status):
    requests, replies = transport
    replies.append((status, {"message": "Denied " + TOKEN}))
    result = await run("list_accounts")
    assert result["success"] is False and result["status"] == "error"
    assert result["http_status"] == status
    assert result["error"] == f"Mercury returned HTTP {status}: Denied [redacted]"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_write_timeout_is_unknown_and_never_retried(transport):
    requests, replies = transport
    replies.append(httpx.ReadTimeout("Response lost"))
    result = await run("send_money", CASES["send_money"]["config"])
    assert result["success"] is False and result["write_outcome"] == "unknown"
    assert len(requests) == 1


@pytest.mark.parametrize("payload", [b"<html>Sign in</html>", {"error": "invalid_token"}, {"accounts": None}, {"accounts": {}}])
@pytest.mark.asyncio
async def test_malformed_read_never_proves_connection(transport, payload):
    transport[1].append((200, payload))
    result = await run("list_accounts")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_response_size_is_bounded(transport, monkeypatch):
    monkeypatch.setattr(mercury, "MAX_RESPONSE_BYTES", 32)
    transport[1].append((200, b" " * 33))
    assert (await run("list_accounts"))["success"] is False


@pytest.mark.parametrize("operation,config", [
    ("get_account", {"accountId": "../recipients"}),
    ("list_accounts", {"limit": 1001}),
    ("list_accounts", {"start_after": ID, "end_before": ID}),
    ("send_money", {**CASES["send_money"]["config"], "amount": 0}),
    ("send_money", {**CASES["send_money"]["config"], "paymentMethod": "domesticWire"}),
    ("create_transfer", {**CASES["create_transfer"]["config"], "destinationAccountId": CASES["create_transfer"]["config"]["sourceAccountId"]}),
    ("list_accounts", {"base_url": "https://other.example"}),
])
@pytest.mark.asyncio
async def test_invalid_config_refused_before_http(transport, operation, config):
    with pytest.raises((ValueError, ValidationError)):
        await run(operation, config)
    assert transport[0] == []


def test_manual_credential_has_default_type_and_hides_token():
    credential = mercury.MercuryAPITokenCredential(api_token=TOKEN)
    assert credential.credential_type == "mercury_api_token"
    assert TOKEN not in repr(credential)
    for bad in ["Bearer token", "line\r\nbreak", "https://other.example/token"]:
        with pytest.raises(ValueError):
            mercury.MercuryAPITokenCredential(api_token=bad)


@pytest.mark.asyncio
async def test_connection_evidence_names_the_account(transport):
    from nodes.core.connection_evidence import collect_evidence
    transport[1].append((200, {"accounts": [{"id": ID, "nickname": "Operating account"}], "page": {}}))
    result = await collect_evidence(node_type="automation-mercury", credential_data=AUTH, user_id=USER)
    assert result.reachable is True
    assert result.samples[0].label == "Operating account"
    assert len(transport[0]) == 1
