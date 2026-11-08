"""Native execution against Tapfiliate's published 1.6 examples, without accounts."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import tapfiliate_node as tap
from nodes.core.run_op import run_node_operation
from utils import ssrf

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/tapfiliate/responses.json").read_text())
AUTH = {"credential_type": "tapfiliate_api_key", "api_key": "fixture-secret-key"}
USER = "00000000-0000-4000-8000-000000000001"
INPUTS = {
    "get_affiliate": {"affiliate_id": "janejameson"},
    "create_affiliate": {"firstname": "Ramone", "lastname": "Referra", "email": "ramona@referra.com", "password": "fixture-password"},
    "delete_affiliate": {"affiliate_id": "janejameson"},
    "get_customer": {"id": "cu_eXampl3"},
    "create_customer": {"customer_id": "USER789", "coupon": "JANE10OFF", "status": "trial"},
    "update_customer": {"id": "cu_eXampl3", "customer_id": "USER456"},
    "delete_customer": {"id": "cu_eXampl3"},
    "get_conversion": {"conversion_id": 1},
    "create_conversion": {"external_id": "ORD005", "amount": 100, "currency": "EUR", "coupon": "JANE10OFF"},
    "update_conversion": {"conversion_id": 1, "amount": 17.95, "external_id": "ORD123"},
    "delete_conversion": {"conversion_id": 1},
    "get_commission": {"commission_id": 1},
    "approve_commission": {"commission_id": 1},
    "disapprove_commission": {"commission_id": 1},
}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        status, body, *extra = replies.pop(0)
        headers = extra[0] if extra else {}
        return httpx.Response(status, headers=headers, **({"content": body} if isinstance(body, bytes) else {"json": body}))

    native = ssrf.guarded_async_client
    monkeypatch.setattr(tap, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, config=None, auth=AUTH):
    return await run_node_operation(node_type="automation-tapfiliate", operation=operation,
        arguments=config or {}, credential_data=dict(auth), user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_tapfiliate_documented_examples_through_native_factory(wire, operation):
    requests, replies = wire
    example = EXAMPLES[operation]
    config = INPUTS.get(operation, {})
    replies.append((example["status"], example["body"] if example["body"] is not None else b""))
    result = await run(operation, config)
    assert result["status"] == "success"
    assert result["data"] == example["body"]
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == example["method"]
    assert str(request.url).split("?")[0] == tap.BASE + example["route"].format(**config)
    assert request.headers["X-Api-Key"] == AUTH["api_key"]
    assert request.headers["Accept"] == "application/json"
    assert AUTH["api_key"] not in str(request.url)
    if operation.startswith("list_"):
        assert result["next_page"] is None and result["page"] == 1
    if operation in {"create_customer", "create_conversion"}:
        assert dict(request.url.params) == {"override_max_cookie_time": "false"}
    if operation == "update_conversion":
        assert dict(request.url.params) == {"recalculate_commissions": "false"}
    if request.method in {"POST", "PATCH"}:
        assert json.loads(request.content) == {k: v for k, v in config.items() if k not in {"id", "conversion_id", "affiliate_id"}}
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_tapfiliate_pagination_and_filters(wire):
    requests, replies = wire
    replies.append((200, [], {"Link": '<https://api.tapfiliate.com/1.6/conversions/?page=3>; rel="next"'}))
    result = await run("list_conversions", {"page": 2, "external_id": "ORD123", "pending": False})
    assert dict(requests[0].url.params) == {"page": "2", "external_id": "ORD123", "pending": "false"}
    assert result["next_page"] == 3
    replies.append((200, []))
    await run("list_commissions", {"paid": False, "status": "pending"})
    assert dict(requests[-1].url.params) == {"paid": "0", "status": "pending"}


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://evil.test/1.6/programs/?page=2", "https://api.tapfiliate.com/1.6/affiliates/?page=2", "https://api.tapfiliate.com/1.6/programs/?page=1", "https://api.tapfiliate.com/1.6/programs/?page=2&page=3"])
async def test_tapfiliate_rejects_bad_pagination_links_without_following(wire, url):
    wire[1].append((200, [], {"Link": '<' + url + '>; rel="next"'}))
    with pytest.raises(ValueError, match="pagination"):
        await run("list_programs")
    assert len(wire[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_tapfiliate_provider_errors_redacted_no_retry(wire, status):
    wire[1].append((status, {"message": "Authentication Failed. " + AUTH["api_key"]}))
    with pytest.raises(ValueError) as error:
        await run("list_programs")
    assert f"HTTP {status}" in str(error.value)
    assert AUTH["api_key"] not in str(error.value)
    assert len(wire[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body,headers", [(b"<html>not JSON</html>", {"Content-Type": "text/html"}), (b"{broken", {"Content-Type": "application/json"}), ({"error": "denied"}, {}), (["wrong"], {})])
async def test_tapfiliate_rejects_malformed_read_responses(wire, body, headers):
    wire[1].append((200, body, headers))
    with pytest.raises(ValueError):
        await run("list_programs")


@pytest.mark.asyncio
async def test_tapfiliate_scrubs_returned_secrets_and_accepts_empty_lists(wire):
    wire[1].append((200, [{"id": "p", "title": AUTH["api_key"], "password": "hidden"}]))
    result = await run("list_programs")
    assert result["data"] == [{"id": "p", "title": "[redacted]"}]
    wire[1].append((200, []))
    assert (await run("list_programs"))["data"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config", [
    ("get_affiliate", {"affiliate_id": "../other"}),
    ("get_conversion", {"conversion_id": 0}),
    ("get_commission", {"commission_id": True}),
    ("create_customer", {"customer_id": "USER123"}),
    ("create_conversion", {"external_id": "ORD123", "amount": 10}),
    ("update_conversion", {"conversion_id": 1}),
    ("list_conversions", {"date_from": "2026-02-30"}),
    ("list_conversions", {"date_from": "2026-05-01", "date_to": "2026-04-01"}),
])
async def test_tapfiliate_invalid_inputs_never_send_http(wire, operation, config):
    with pytest.raises(ValueError):
        await run(operation, config)
    assert not wire[0]


@pytest.mark.asyncio
async def test_tapfiliate_connection_evidence_is_account_program_read(wire):
    from nodes.core.connection_evidence import collect_evidence
    wire[1].append((200, EXAMPLES["list_programs"]["body"]))
    evidence = await collect_evidence(node_type="automation-tapfiliate", user_id=USER, credential_data=AUTH)
    assert evidence.reachable is True
    assert evidence.samples[0].label == "John's affiliate program"
    assert wire[0][0].method == "GET" and wire[0][0].url.path == "/1.6/programs/"


@pytest.mark.parametrize("key", ["https://example.test/key", "<token>", "bad\nkey", "Bearer key"])
def test_tapfiliate_bad_manual_keys(key):
    with pytest.raises(ValueError):
        tap.TapfiliateAPIKeyCredential(api_key=key)
