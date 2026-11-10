"""Exercise YNAB's real node factory and HTTP boundary without an account.

Synthetic fixtures pin all supported routes, write wrappers, milliunits and
delta cursors. Negative cases verify errors cannot become connection evidence.
"""
import json
from pathlib import Path

import httpx
import pytest

from nodes import ynab_node as ynab
from nodes.core.connection_evidence import collect_evidence
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-ynab-personal-access-token"
CREDENTIAL = {"credential_type": "ynab_personal_access_token", "access_token": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/ynab/operations.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []

    def send(request):
        requests.append(request)
        assert request.url.host == "api.ynab.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs)

    monkeypatch.setattr(ynab, "guarded_async_client", client)
    return requests, replies


def node(config, credentials=CREDENTIAL):
    return NodeFactory.create_node(node_id="ynab-fixture", node_type="automation-ynab",
        node_data={"config": config, "credentials": credentials})


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_ynab_operations_use_exact_provider_contract(transport, case):
    requests, replies = transport
    replies.append((case["status"], case["response"]))
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "operation": case["config"]["operation"], "data": case["response"]["data"]}
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert (request.method, request.url.path) == (case["method"], case["path"])
    assert (json.loads(request.content) if request.content else None) == case["body"]
    params = {key: str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in case["config"].items()
        if key in {"include_accounts", "since_date", "until_date", "type", "last_knowledge_of_server"}}
    assert dict(request.url.params) == (params if request.method == "GET" else {})
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_ynab_connection_evidence_names_real_account_plans(transport):
    requests, replies = transport
    replies.append((200, {"data": {"plans": [{"id": "household", "name": "Household"}]}}))
    result = await collect_evidence(node_type="automation-ynab", user_id="00000000-0000-4000-8000-000000000001", credential_data=CREDENTIAL)
    assert result.reachable is True
    assert [sample.label for sample in result.samples] == ["Household"]
    assert requests[0].url.path == "/v1/plans"


@pytest.mark.asyncio
async def test_ynab_plan_picker_search_uses_the_same_read(transport):
    _, replies = transport
    replies.append((200, {"data": {"plans": [{"id": "p1", "name": "Home"}, {"id": "p2", "name": "Business"}]}}))
    assert await ynab.YnabNode.load_field_options("plan_id", CREDENTIAL, search="home") == [{"value": "p1", "label": "Home"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 409, 429, 500])
async def test_ynab_provider_errors_keep_status_and_redact_token(transport, status):
    requests, replies = transport
    replies.append((status, {"error": {"id": "rejected", "name": "not_authorized", "detail": "Provider rejected " + TOKEN}}))
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_user"}).execute({})
    assert f"HTTP {status}" in str(error.value)
    assert "Provider rejected [redacted]" in str(error.value)
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_ynab_rejected_token_is_failed_connection_evidence(transport):
    _, replies = transport
    replies.append((401, {"error": {"id": "401", "name": "unauthorized", "detail": "Unauthorized"}}))
    result = await collect_evidence(node_type="automation-ynab", user_id="00000000-0000-4000-8000-000000000001", credential_data=CREDENTIAL)
    assert result.reachable is False and "Unauthorized" in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": {}}, {"data": {"user": []}}, {"data": {"user": {}}, "error": {"name": "bad"}}])
async def test_ynab_invalid_success_envelopes_do_not_pass(transport, payload):
    _, replies = transport
    replies.append((200, payload))
    with pytest.raises(ValueError):
        await node({"operation": "get_user"}).execute({})


@pytest.mark.parametrize("token", ["https://app.ynab.com/settings", "Bearer abc", "abc\nxyz", "<token>", "", "key\u00a0abc"])
def test_ynab_bad_credentials_are_refused(token):
    with pytest.raises(ValueError):
        ynab.YnabPersonalAccessTokenCredential(access_token=token)


@pytest.mark.parametrize("config", [
    {"operation": "get_plan", "plan_id": "../other"},
    {"operation": "get_transaction", "plan_id": "plan", "transaction_id": "a/b"},
    {"operation": "create_account", "plan_id": "p", "name": "Cash", "type": "cash", "balance": 1.25},
    {"operation": "create_account", "plan_id": "p", "name": "Cash", "type": "cash", "balance": True},
    {"operation": "get_month", "plan_id": "p", "month": "2016-13-01"},
])
def test_ynab_invalid_ids_amounts_and_dates_are_refused(config):
    with pytest.raises(ValueError):
        node(config)


def test_ynab_token_paste_noise_is_trimmed():
    assert ynab.YnabPersonalAccessTokenCredential(access_token="  " + TOKEN + "\n").access_token == TOKEN


TRIGGERS = [
    ("on_new_or_updated_transaction", "list_transactions", "transactions"),
    ("on_new_or_updated_scheduled_transaction", "list_scheduled_transactions", "scheduled_transactions"),
]


def delta_example(action, member, *, knowledge=100):
    # These payload fields are the TransactionDetail / ScheduledTransactionDetail
    # schemas in https://api.ynab.com/papi/open_api_spec.yaml. Reuse the action
    # HTTP fixtures so the trigger and action exercise the same API envelope.
    from copy import deepcopy
    data = deepcopy(next(case["response"]["data"] for case in CASES
                         if case["config"]["operation"] == action))
    data["server_knowledge"] = knowledge
    assert data[member]
    for item in data[member]:
        item.update(account_id="00000000-0000-4000-8000-000000000001",
                    account_name="Checking", category_id=None, category_name=None,
                    payee_name=None, amount=-12500, memo="Groceries", deleted=False,
                    subtransactions=[])
        item.pop("name", None)
        if member == "transactions":
            item.update(date="2016-12-01", approved=True, cleared="uncleared")
        else:
            item.update(date_first="2016-12-01", date_next="2016-12-01", frequency="monthly")
    return data


@pytest.fixture
def poll_state(monkeypatch):
    state = {}

    async def update(self, mutator, **kwargs):
        updated, result = mutator(dict(state))
        if updated is not None:
            state.clear()
            state.update(updated)
        return result

    monkeypatch.setattr(ynab.YnabNode, "_update_node_state", update)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,action,member", TRIGGERS)
async def test_ynab_delta_triggers_baseline_updates_reversions_deletions_and_empty_ticks(
        transport, poll_state, operation, action, member):
    from copy import deepcopy
    requests, replies = transport
    instance = node({"operation": operation, "plan_id": "last-used"})
    original = delta_example(action, member)
    replies.append((200, {"data": original}))
    first = await instance.execute({})
    assert first[member] == []
    assert instance.trigger_produced_no_event(first)
    assert instance.resolve_agent_event(first) is None
    assert poll_state["server_knowledge"] == 100
    assert not requests[-1].url.params
    for knowledge, memo, deleted in [(101, "Changed memo", False), (102, original[member][0].get("memo"), False), (103, None, True)]:
        changed = deepcopy(original)
        changed["server_knowledge"] = knowledge
        changed[member][0].update(memo=memo, deleted=deleted)
        replies.append((200, {"data": changed}))
        result = await instance.execute({})
        assert result[member] == changed[member]
        assert result["changed_count"] == len(changed[member])
        assert dict(requests[-1].url.params) == {"last_knowledge_of_server": str(knowledge - 1)}
        assert instance.trigger_emitted_event(result)
        assert instance.should_propagate_output(result, {"operation": operation})
        text = instance.resolve_agent_event(result)["text"]
        assert "last-used" in text and str(changed[member][0]["id"]) in text
        assert "Deleted" in text if deleted else "New or updated" in text
        assert "milliunits" in text and TOKEN not in text
    replies.append((200, {"data": {member: [], "server_knowledge": 104}}))
    empty = await instance.execute({})
    assert empty["changed_count"] == 0
    assert not instance.should_propagate_output(empty, {"operation": operation})
    assert poll_state["server_knowledge"] == 104


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,action,member", TRIGGERS)
async def test_ynab_delta_trigger_scope_rotation_and_arm_do_not_consume_events(
        transport, poll_state, operation, action, member):
    _, replies = transport
    instance = node({"operation": operation, "plan_id": "last-used"})
    replies.append((200, {"data": delta_example(action, member)}))
    await instance.execute({})
    before = dict(poll_state)
    instance._poll_baseline_only = True
    replies.append((200, {"data": delta_example(action, member, knowledge=101)}))
    assert (await instance.execute({}))["changed_count"] == 0
    assert poll_state == before
    instance = node({"operation": operation, "plan_id": "different-plan"})
    replies.append((200, {"data": delta_example(action, member, knowledge=1)}))
    assert (await instance.execute({}))["changed_count"] == 0
    assert poll_state["scope"] != before["scope"]
    assert poll_state["server_knowledge"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,action,member", TRIGGERS)
async def test_ynab_delta_trigger_error_never_advances_cursor(
        transport, poll_state, operation, action, member):
    _, replies = transport
    instance = node({"operation": operation, "plan_id": "default"})
    replies.append((200, {"data": delta_example(action, member)}))
    await instance.execute({})
    before = dict(poll_state)
    for status, body in [(429, {"error": {"name": "Too many requests"}}),
                         (200, {"data": {member: [], "server_knowledge": 99}}),
                         (200, {"data": {member: [], "server_knowledge": None}}),
                         (200, {"data": {member: [{}], "server_knowledge": 101}})]:
        replies.append((status, body))
        with pytest.raises(ValueError):
            await instance.execute({})
        assert poll_state == before


@pytest.mark.asyncio
async def test_ynab_overlapping_delta_poll_emits_once(transport, poll_state, monkeypatch):
    _, replies = transport
    instance = node({"operation": "on_new_or_updated_transaction", "plan_id": "default", "since_date": "2016-12-01"})
    replies.append((200, {"data": delta_example("list_transactions", "transactions")}))
    await instance.execute({})
    real_request = ynab.YnabNode._request

    async def racing_request(cls, *args, **kwargs):
        data = await real_request(*args, **kwargs)
        # Another tick has already committed and emitted this cursor.
        poll_state["server_knowledge"] = data["server_knowledge"]
        return data

    monkeypatch.setattr(ynab.YnabNode, "_request", classmethod(racing_request))
    replies.append((200, {"data": delta_example("list_transactions", "transactions", knowledge=101)}))
    result = await instance.execute({})
    assert result["changed_count"] == 0
    assert poll_state["server_knowledge"] == 101
    assert dict(transport[0][-1].url.params) == {"last_knowledge_of_server": "100", "since_date": "2016-12-01"}
