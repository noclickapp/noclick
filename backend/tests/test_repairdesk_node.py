"""RepairDesk v2 examples copied from the provider contract; synthetic corruptions are negative tests only."""
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from nodes.repairdesk_node import RepairDeskAPIKeyCredential

TYPE = "automation-repairdesk"
USER = "11111111-1111-4111-8111-111111111111"
RAW = {"credential_type": "repairdesk_api_key", "api_key": "repairdesk-fixture-token"}
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/repairdesk/v2-examples.json").read_text())
CASES = [
    ("list_purchase_orders", {}, "GET /purchase-orders"),
    ("get_purchase_order_stats", {}, "GET /purchase-orders/stats"),
    ("list_supplier_purchase_orders", {"supplier_id": 138}, "GET /purchase-orders/special-part/{supplier_id}"),
    ("list_purchase_order_statuses", {}, "GET /purchase-orders/statuses"),
    ("create_purchase_order_status", {"status_name": "Awaiting supplier", "color": "#3366ff"}, "POST /purchase-orders/statuses"),
    ("update_purchase_order_status", {"status_id": 12, "status_name": "Awaiting supplier (edited)"}, "PATCH /purchase-orders/statuses/{status_id}"),
    ("delete_purchase_order_status", {"status_id": 12}, "DELETE /purchase-orders/statuses/{status_id}"),
    ("get_purchase_order_settings", {}, "GET /purchase-orders/configs"),
    ("list_goods_received_notes", {}, "GET /grn"),
    ("get_grn_metadata", {}, "GET /grn/metadata"),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, overrides = [], {}
    def handle(request):
        calls.append(request)
        assert request.url.host == "api.repairdesk.co"
        assert request.headers["authorization"] == "Bearer " + RAW["api_key"]
        assert "api_key" not in request.url.params
        path = request.url.path.removeprefix("/api/web/v2")
        if path.startswith("/purchase-orders/special-part/"):
            path = "/purchase-orders/special-part/{supplier_id}"
        elif path.startswith("/purchase-orders/statuses/"):
            path = "/purchase-orders/statuses/{status_id}"
        key = request.method + " " + path
        example = overrides.get(key, EXAMPLES[key])
        return httpx.Response(example["status"], json=example["body"])
    real_client = httpx.AsyncClient
    @asynccontextmanager
    async def mocked(**kwargs):
        async with real_client(transport=httpx.MockTransport(handle), **kwargs) as instance:
            yield instance
    monkeypatch.setattr("nodes.repairdesk_node.httpx.AsyncClient", mocked)
    return calls, overrides


async def run(operation, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments,
        credential_data=deepcopy(RAW), user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,endpoint", CASES)
async def test_documented_examples_through_real_runner(transport, operation, args, endpoint):
    calls, _ = transport
    result = await run(operation, **args)
    assert result["status"] == "success"
    assert calls[-1].method == endpoint.split()[0]
    expected = EXAMPLES[endpoint]["body"]["data"]
    assert result["data"] == (expected["records"] if isinstance(expected, dict) and "records" in expected else expected)
    assert RAW["api_key"] not in json.dumps(result)


@pytest.mark.asyncio
async def test_query_arrays_dates_store_header_and_status_body(transport):
    calls, _ = transport
    await run("list_purchase_orders", store_id=7, status=["Pending", "Received"], order_dates=["2025-10-01", "2025-10-31"])
    request = calls[-1]
    assert request.headers["storeid"] == "7"
    assert request.url.params.get_list("status[]") == ["Pending", "Received"]
    assert request.url.params.get_list("order_dates[]") == ["2025-10-01", "2025-10-31"]
    assert "store_id" not in request.url.params
    await run("update_purchase_order_status", status_id=12, status_name="Awaiting supplier (edited)")
    assert calls[-1].url.path.endswith("/statuses/12")
    assert json.loads(calls[-1].content) == {"status_name": "Awaiting supplier (edited)"}


@pytest.mark.asyncio
async def test_connection_evidence_names_documented_statuses(transport):
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=RAW)
    assert evidence.reachable is True
    assert [s.label for s in evidence.samples] == ["Waiting", "Pending", "Awaiting supplier"]


@pytest.mark.parametrize("token", ["<token>", "Bearer issued-token", "https://repairdesk.co/token", "invalid\nkey"])
def test_manual_token_rejects_wrong_paste(token):
    with pytest.raises(ValidationError):
        RepairDeskAPIKeyCredential(api_key=token)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 503])
async def test_provider_errors_do_not_echo_body_or_retry(transport, status):
    calls, overrides = transport
    overrides["GET /purchase-orders/statuses"] = {"status": status, "body": {"message": RAW["api_key"]}}
    result = await run("list_purchase_order_statuses")
    assert result["status"] == "error" and str(status) in str(result)
    assert RAW["api_key"] not in json.dumps(result) and len(calls) == 1


@pytest.mark.asyncio
async def test_malformed_envelope_refused(transport):
    _, overrides = transport
    overrides["GET /purchase-orders/statuses"] = {"status": 200, "body": {"statusCode": 201, "data": []}}
    assert (await run("list_purchase_order_statuses"))["status"] == "error"


def poll(operation, **args):
    return NodeFactory.create_node("repairdesk-poll", TYPE,
        {"config": {"operation": operation, **args}, "credentials": deepcopy(RAW)}, user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,endpoint", [
    ("on_new_or_updated_purchase_order", "GET /purchase-orders"),
    ("on_new_or_updated_goods_received_note", "GET /grn"),
])
async def test_poll_baseline_change_reversion_and_scope(transport, operation, endpoint):
    calls, overrides = transport
    state = {}
    async def update(mutator, **kwargs):
        replacement, result = mutator(deepcopy(state))
        if replacement is not None:
            state.clear()
            state.update(replacement)
        return result
    async def execute(**args):
        node = poll(operation, **args)
        node._update_node_state = update
        return node, await node.execute({})
    node, baseline = await execute()
    assert baseline["event_count"] == 0 and node.trigger_produced_no_event(baseline)
    _, unchanged = await execute()
    assert unchanged["event_count"] == 0
    # Deliberately mutate the documented record to exercise updates and A→B→A.
    changed = deepcopy(EXAMPLES[endpoint])
    changed["body"]["data"]["records"][0]["notes"] = "Changed metadata for revision test"
    overrides[endpoint] = changed
    node, result = await execute()
    assert result["event_count"] == 1 and node.trigger_emitted_event(result)
    event = node.resolve_agent_event(result)
    assert "Changed metadata for revision test" in event["text"]
    assert str(result["data"][0]["id"]) in event["text"]
    overrides.pop(endpoint)
    _, reverted = await execute()
    assert reverted["event_count"] == 1
    _, repointed = await execute(supplier=138)
    assert repointed["event_count"] == 0
    assert calls[-1].url.params["sort_order"] == "DESC"
    assert calls[-1].url.params["pagesize"] == "100"
    assert calls[-1].url.params["supplier"] == "138"


@pytest.mark.asyncio
async def test_arm_time_baseline_does_not_consume_a_real_update(transport):
    state = {"seen_ids": [], "scope": None}
    node = poll("on_new_or_updated_purchase_order")
    async def update(mutator, **kwargs):
        replacement, result = mutator(deepcopy(state))
        if replacement is not None:
            state.clear()
            state.update(replacement)
        return result
    node._update_node_state = update
    node._poll_baseline_only = True
    assert (await node.execute({}))["event_count"] == 0
    node._poll_baseline_only = False
    assert (await node.execute({}))["event_count"] == 1
