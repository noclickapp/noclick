"""Run GoCardless through the real factory using the publisher's HTTP examples.

Transport assertions cover request envelopes, account environments, paging,
idempotency and failure behavior without a real token or money movement.
"""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import gocardless_node as gc
from nodes.core.registry import NodeFactory
from utils import ssrf

FIXTURES = json.loads((Path(__file__).parent / "fixtures/gocardless/documented.json").read_text())
AUTH = {"credential_type": "gocardless_access_token", "access_token": "gc-test-secret-12345"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(gc, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


def node(config, auth=None):
    return NodeFactory.create_node(node_id="gc-test", node_type="automation-gocardless",
        node_data={"config": deepcopy(config), "credentials": deepcopy(auth or AUTH)})


@pytest.mark.asyncio
@pytest.mark.parametrize("case", FIXTURES, ids=lambda c: c["operation"])
async def test_documented_operation(transport, case):
    requests, replies = transport
    replies.append((case["status"], case["response"]))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.url.host == "api.gocardless.com"
    assert request.method == case["method"] and request.url.path == case["path"]
    assert request.headers["GoCardless-Version"] == "2015-07-06"
    assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
    assert AUTH["access_token"] not in str(request.url)
    config = deepcopy(case["config"])
    config.pop("operation")
    if request.method != "GET":
        for key in list(config):
            if "{" + key + "}" in gc.OPERATIONS[case["operation"]][1]:
                config.pop(key)
        idempotency_key = config.pop("idempotency_key", None)
        if idempotency_key:
            assert request.headers["Idempotency-Key"] == idempotency_key
        if case["operation"].startswith("create_"):
            linked = "payment" if case["resource"] == "refunds" else "mandate"
            config["links"] = {linked: config.pop(linked + "_id")}
        if case["operation"] == "create_subscription":
            config["interval"] = 1  # Documented default interval.
        assert json.loads(request.content) == {case["resource"]: config}
    else:
        assert not request.content
    if case["operation"].startswith("list_"):
        assert result["items"] == case["response"][case["resource"]]
        assert result["next_page_token"] == case["response"]["meta"]["cursors"]["after"]
    else:
        assert result["data"] == case["response"][case["resource"]]


@pytest.mark.asyncio
async def test_sandbox_and_pagination(transport):
    requests, replies = transport
    replies.append((200, {"customers": [{"id": "CU123"}], "meta": {"cursors": {"before": None, "after": "CU456"}}}))
    result = await node({"operation": "list_customers", "after": "CU100", "limit": 1}, {**AUTH, "environment": "sandbox"}).execute({})
    assert requests[0].url.host == "api-sandbox.gocardless.com"
    assert dict(requests[0].url.params) == {"after": "CU100", "limit": "1"}
    assert result["has_more"] and result["next_page_token"] == "CU456"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 429, 500])
async def test_rejections_and_no_retry(transport, code):
    requests, replies = transport
    replies.append((code, {"error": {"message": "Access denied " + AUTH["access_token"]}}))
    result = await node({"operation": "cancel_payment", "payment_id": "PM123"}).execute({})
    assert len(requests) == 1
    assert result["status"] == "error" and result["http_status"] == code
    assert AUTH["access_token"] not in json.dumps(result)
    assert result["write_outcome_unknown"] == (code >= 500)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"payments": {"id": "PM999"}}, {"payments": []}, {"error": {"message": "no"}}])
async def test_malformed_or_wrong_identity(transport, body):
    _, replies = transport
    replies.append((200, body))
    with pytest.raises(ValueError):
        await node({"operation": "get_payment", "payment_id": "PM123"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_payment", "payment_id": "../customers"},
    {"operation": "list_customers", "limit": 501},
    {"operation": "create_refund", "payment_id": "PM123", "amount": 100, "idempotency_key": "one"},
    {"operation": "create_payment", "mandate_id": "MD123", "amount": -1, "currency": "GBP", "idempotency_key": "one"},
    {"operation": "cancel_payment", "payment_id": "PM123", "metadata": {"a": "1", "b": "2", "c": "3", "d": "4"}},
])
def test_invalid_input(config):
    with pytest.raises(ValidationError):
        gc.GoCardlessFullConfig(config=config, credentials=AUTH)


@pytest.mark.asyncio
async def test_empty_update_never_sends(transport):
    requests, _ = transport
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_payment", "payment_id": "PM123"}).execute({})
    assert not requests


def test_manual_credential_default_and_cleaning():
    c = gc.GoCardlessTokenCredential(access_token="  gc-test-secret-12345  ")
    assert c.credential_type == "gocardless_access_token" and c.access_token == AUTH["access_token"]
    with pytest.raises(ValidationError):
        gc.GoCardlessTokenCredential(access_token="Bearer gc-test-secret-12345")
