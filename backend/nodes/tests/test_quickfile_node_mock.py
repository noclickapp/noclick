"""QuickFile REST v2 wire and polling regressions, without a live account.

Response records are synthetic values in the provider's published response
schemas (ClientSearchModel / SupplierSearchModel), not recorded API calls.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import quickfile_node as qf
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

TOKEN = "synthetic-quickfile-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="quickfile-test", node_type="automation-quickfile",
        node_data={"config": config, "credentials": {"api_token": TOKEN}})


def transport(monkeypatch, respond):
    requests = []
    real_client = httpx.AsyncClient

    def handler(request):
        requests.append(request)
        assert request.url.host == "api-beta.quickfile.co.uk"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        return respond(request)

    monkeypatch.setattr(qf.httpx, "AsyncClient", lambda **kw:
        real_client(**kw, transport=httpx.MockTransport(handler)))
    return requests


@pytest.mark.asyncio
async def test_identity_and_default_manual_credential_tag(monkeypatch):
    assert qf.QuickFileTokenCredential(api_token=TOKEN).credential_type == "quickfile_token"
    requests = transport(monkeypatch, lambda _: httpx.Response(200,
        json={"BusinessName": "Test Business", "AccNumber": "1234567890"}))
    out = await node({"operation": "get_account"}).execute({})
    assert out["data"]["BusinessName"] == "Test Business"
    assert requests[0].url.path == "/account/me"
    assert qf.QuickFileNode.connection_evidence.identity_operation == "get_account"


@pytest.mark.asyncio
async def test_invoice_body_keeps_nested_line_types_and_explicit_false(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={"id": 42}))
    config = {"operation": "create_invoice", "type": "invoice", "client_id": 7,
              "currency": "GBP", "item_lines": [{"description": "Consulting", "qty": 2,
              "unit_cost": 100, "vat_rate": 20}], "ec_vat_exempt": False}
    assert (await node(config).execute({}))["data"] == {"id": 42}
    assert requests[0].method == "POST" and requests[0].url.path == "/invoices"
    assert json.loads(requests[0].content) == {k: v for k, v in config.items() if k != "operation"}


@pytest.mark.asyncio
async def test_update_uses_one_put_and_omits_unset_fields(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={"id": 7}))
    await node({"operation": "update_client", "id": 7, "company_name": "New name"}).execute({})
    assert len(requests) == 1 and requests[0].method == "PUT"
    assert requests[0].url.path == "/clients/7"
    assert json.loads(requests[0].content) == {"company_name": "New name"}


@pytest.mark.asyncio
async def test_list_query_preserves_false_zero_and_encodes_search(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={"data": []}))
    await node({"operation": "list_clients", "company_name": "A & B + C",
                "include_deleted": False, "offset": 0, "limit": 50}).execute({})
    assert dict(requests[0].url.params) == {"company_name": "A & B + C",
        "include_deleted": "false", "offset": "0", "limit": "50"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_rejection_propagates_verbatim(monkeypatch, status):
    transport(monkeypatch, lambda _: httpx.Response(status, json={"message": "Provider rejection"}))
    with pytest.raises(ValueError, match=f"QuickFile API {status}.*Provider rejection"):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.asyncio
async def test_redirect_is_not_followed(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(302,
        headers={"Location": "https://example.org/steal"}))
    with pytest.raises(ValueError, match="redirect"):
        await node({"operation": "get_account"}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_invoice", "id": "../clients"},
    {"operation": "create_invoice", "client_id": 1, "type": "invoice", "currency": "GB"},
    {"operation": "list_clients", "limit": 101},
    {"operation": "create_purchase", "supplier_id": 1, "receipt_date": "2024-12-31", "currency": "GBP"},
])
def test_invalid_config_is_rejected(config):
    with pytest.raises(ConfigValidationError):
        qf.QuickFileNode.parse_config({"config": config})


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["client", "supplier"])
async def test_poll_baseline_new_record_dedup_and_agent_turn(monkeypatch, kind):
    page = json.loads((Path(__file__).parent / "fixtures/quickfile/poll-list.json").read_text())["body"]
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=page))
    config = {"operation": "on_new_" + kind}
    instance = node(config)
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    instance._update_node_state = update
    baseline = await instance.execute({})
    assert baseline["new_record_count"] == 0
    page["data"].append({"id": 2, "company_name": "New Business", "created_date": "2024-12-31T12:34:56Z"})
    output = await instance.execute({})
    assert output["new_record_count"] == 1 and output["data"][0]["id"] == 2
    assert instance.should_propagate_output(output, config)
    event = instance.resolve_agent_event(output)
    assert "New Business" in event["text"] and "id=2" in event["text"] and kind in event["text"]
    assert (await instance.execute({}))["new_record_count"] == 0
    assert instance.resolve_agent_event(baseline) is None
    assert dict(requests[0].url.params) == {"order_column": "created_date", "order_direction": "desc",
        "include_deleted": "false", "offset": "0", "limit": "100"}
    assert requests[0].url.path == "/" + kind + "s"
    assert poll_scope(qf.QuickFileNode, config) != poll_scope(qf.QuickFileNode,
        {"operation": "on_new_" + ("supplier" if kind == "client" else "client")})


@pytest.mark.asyncio
async def test_poll_paginates_on_fixed_host(monkeypatch):
    def respond(request):
        offset = int(request.url.params["offset"])
        rows = [{"id": i} for i in range(1, 101)] if offset == 0 else [{"id": 101}]
        return httpx.Response(200, json={"data": rows, "paging": {"next": "https://example.org/steal"}})
    requests = transport(monkeypatch, respond)
    instance = node({"operation": "on_new_client"})
    captured = []

    async def filter_unseen(rows, id_fn):
        captured.extend(id_fn(row) for row in rows)
        return rows

    instance._filter_unseen = filter_unseen
    assert (await instance.execute({}))["new_record_count"] == 101
    assert [r.url.params["offset"] for r in requests] == ["0", "100"]
    assert len(captured) == 101


@pytest.mark.asyncio
async def test_malformed_poll_does_not_advance_state(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json={"data": [{"company_name": "No ID"}]}))
    instance = node({"operation": "on_new_client"})

    async def never(*args, **kwargs):
        pytest.fail("Incomplete response must not advance seen-state")

    instance._filter_unseen = never
    with pytest.raises(ValueError, match="numeric ID"):
        await instance.execute({})


@pytest.mark.parametrize("token", ["", " ", "Bearer token", "https://example.org", "<token>", "curly–dash"])
def test_rejects_malformed_personal_token(token):
    with pytest.raises(ValidationError):
        qf.QuickFileTokenCredential(api_token=token)
