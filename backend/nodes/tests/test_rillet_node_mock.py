"""Wire, failure and connection-evidence tests through the production node factory."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import rillet_node as rillet
from nodes.core.run_op import run_node_operation
from utils import ssrf

FIXTURE = json.loads((Path(__file__).parent / "fixtures/rillet/cases.json").read_text())
CASES = FIXTURE["cases"]
AUTH = {"credential_type": "rillet_api_key", "api_key": "synthetic-rillet-test-key"}
USER = "00000000-0000-4000-8000-000000000099"


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        code, payload, headers = replies.pop(0)
        if payload is None:
            return httpx.Response(code, content=b"", headers=headers)
        if isinstance(payload, bytes):
            return httpx.Response(code, content=payload, headers=headers)
        return httpx.Response(code, json=payload, headers=headers)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(rillet, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(op, config=None, auth=None):
    return await run_node_operation(node_type="automation-rillet", operation=op,
        arguments=config or {}, credential_data=deepcopy(AUTH if auth is None else auth), user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_all_contract_routes_auth_and_response_shapes(transport, case):
    requests, replies = transport
    replies.append((200, case["response"], {}))
    result = await run(case["operation"], case["config"])
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.path == case["path"]
    assert request.url.host == "api.rillet.com"
    assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
    assert request.headers["X-Rillet-API-Version"] == "4"
    assert AUTH["api_key"] not in str(request.url)
    if case["method"] == "GET":
        assert not request.content
    else:
        body = json.loads(request.content)
        assert "operation" not in body and "idempotency_key" not in body
        for name, value in case["config"].items():
            if name != "idempotency_key" and "{" + name + "}" not in rillet.ROUTES[case["operation"]][1]:
                assert body[name] == value
        if "idempotency_key" in case["config"]:
            assert request.headers["Idempotency-Key"] == case["config"]["idempotency_key"]
    if case["operation"].startswith("list_"):
        assert result["next_cursor"] == case["response"].get("pagination", {}).get("next_cursor")
        assert result["has_more"] is bool(result["next_cursor"])
    elif case["response"] is not None:
        assert result["data"] == case["response"]
    else:
        assert result["acknowledged"] is True


@pytest.mark.asyncio
async def test_query_names_and_csv_encoding_preserve_filter_values(transport):
    transport[1].append((200, {"journal_entries": [], "pagination": {}}, {}))
    uid = "0193a6f2-4c1e-7b8a-9d3f-2e5c8a1b7f40"
    result = await run("list_journal_entries", {"limit": 100, "cursor": "opaque+/=", "date_from": "2023-12-01",
        "date_to": "2023-12-31", "updated_after": "2023-01-01T00:00:00Z", "account_ids": [uid, uid], "book_id": uid})
    params = transport[0][0].url.params
    assert params["account_ids"] == uid + "," + uid
    assert params["date.gte"] == "2023-12-01" and params["date.lte"] == "2023-12-31"
    assert params["updated.gt"] == "2023-01-01T00:00:00Z" and params["cursor"] == "opaque+/="
    assert result["has_more"] is False and result["next_cursor"] is None
    transport[1].append((200, {"products": [], "pagination": {}}, {}))
    await run("list_products", {"product_types": ["PRODUCT", "BUNDLE"]})
    assert transport[0][-1].url.params["type"] == "PRODUCT,BUNDLE"
    transport[1].append((200, {"invoices": [], "pagination": {}}, {}))
    await run("list_invoices", {"overdue": False})
    assert transport[0][-1].url.params["overdue"] == "false"


@pytest.mark.asyncio
async def test_sandbox_origin_and_organization_identity(transport):
    org = next(c["response"] for c in CASES if c["operation"] == "get_organization")
    transport[1].append((200, org, {}))
    result = await run("get_organization", auth={**AUTH, "environment": "sandbox"})
    assert transport[0][0].url.host == "sandbox.api.rillet.com"
    assert result["data"]["trade_name"] == "Rillet Inc."
    assert rillet.RilletNode.connection_evidence.identity_keys == ("trade_name",)


@pytest.mark.asyncio
async def test_invoice_approval_is_a_proposal_and_never_retried(transport):
    proposal = {"invoice_id": "0193a6f2-4c1e-7b8a-9d3f-2e5c8a1b7f40", "approval_request_id": "0193a6f2-4c1e-7b8a-9d3f-2e5c8a1b7f41", "status": "PENDING"}
    transport[1].append((202, proposal, {}))
    args = next(c["config"] for c in CASES if c["operation"] == "create_invoice")
    result = await run("create_invoice", args)
    assert result == {"status": "pending_approval", "http_status": 202, "invoice_created": False, "data": proposal}
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 404, 409, 429, 500])
async def test_provider_rejection_is_verbatim_redacted_and_never_retried(transport, code):
    transport[1].append((code, {"detail": "Rillet rejected " + AUTH["api_key"]}, {"Location": "https://untrusted.example"}))
    result = await run("get_organization")
    assert result["status"] == "error" and result["http_status"] == code
    assert "Rillet rejected" in result["error"] and AUTH["api_key"] not in result["error"]
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,headers", [(b"<html>login</html>", {"Content-Type": "text/html"}),
    ({"error": "denied"}, {}), ({"unexpected": []}, {}), ({"customers": [], "pagination": {"next_cursor": 7}}, {})])
async def test_unexpected_list_response_fails(transport, payload, headers):
    transport[1].append((200, payload, headers))
    with pytest.raises(ValueError):
        await run("list_customers")


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [{"limit": 101}, {"external_reference_id": "234"}, {"url": "https://foreign.example"}])
async def test_invalid_configs_never_reach_http(transport, args):
    with pytest.raises(ValueError):
        await run("list_customers", args)
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["../escape", "a/b", "x?token=x", "https://foreign.example"])
async def test_path_identifier_is_validated_before_http(transport, identifier):
    with pytest.raises(ValueError):
        await run("get_customer", {"customer_id": identifier})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_foreign_credential_type_and_unapproved_environment_rejected(transport):
    for auth in [{**AUTH, "credential_type": "unrelated_api_key"}, {**AUTH, "environment": "https://foreign.example"}]:
        with pytest.raises(ValueError):
            await run("get_organization", auth=auth)
    assert transport[0] == []


@pytest.mark.asyncio
async def test_json_editor_keeps_typed_nested_payload_and_false_values(transport):
    case = next(c for c in CASES if c["operation"] == "create_invoice")
    args = {**case["config"], "items": json.dumps(case["config"]["items"])}
    transport[1].append((200, case["response"], {}))
    await run("create_invoice", args)
    assert json.loads(transport[0][0].content)["items"] == case["config"]["items"]
    with pytest.raises(ValueError):
        await run("create_invoice", {**args, "items": "{not json"})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_empty_202_cannot_acknowledge_sent_status(transport):
    transport[1].append((202, None, {}))
    args = next(c["config"] for c in CASES if c["operation"] == "update_invoice_sent_status")
    with pytest.raises(ValueError):
        await run("update_invoice_sent_status", args)


@pytest.mark.asyncio
async def test_incomplete_identity_cannot_prove_connection(transport):
    transport[1].append((200, {}, {}))
    with pytest.raises(ValueError, match="identity is incomplete"):
        await run("get_organization")
