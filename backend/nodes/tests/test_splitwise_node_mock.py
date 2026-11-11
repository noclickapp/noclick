"""Splitwise wire-contract, factory, pagination and error regressions; no live account."""
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import splitwise_node as native
from nodes.core.registry import NodeFactory

KEY = "synthetic-splitwise-api-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="splitwise-test", node_type="automation-splitwise", node_data={
        "config": config,
        "credentials": credential or {"credential_type": "splitwise_api_key", "api_key": KEY},
    })


def transport(monkeypatch, body, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CONFIGS = {
    "get_current_user": {}, "get_user": {"id": 42},
    "get_groups": {}, "get_group": {"id": 42},
    "create_group": {"name": "The Brain Trust", "group_type": "trip", "simplify_by_default": False},
    "delete_group": {"id": 42},
    "add_user_to_group": {"group_id": 49012, "user_id": 7999632},
    "remove_user_from_group": {"group_id": 4012, "user_id": 940142},
    "get_friends": {}, "get_friend": {"id": 42}, "delete_friend": {"id": 42},
    "get_expenses": {"group_id": 42, "limit": 2, "offset": 4},
    "get_expense": {"id": 42},
    "create_expense": {"group_id": 42, "cost": "25", "description": "Grocery run", "currency_code": "USD", "category_id": 15},
    "update_expense": {"id": 42, "group_id": 0, "cost": "25", "description": "Grocery run", "details": "Updated notes"},
    "delete_expense": {"id": 42}, "undelete_expense": {"id": 42},
    "get_comments": {"expense_id": 4193},
    "create_comment": {"expense_id": 5123, "content": "Does this include the delivery fee?"},
    "delete_comment": {"id": 42}, "get_notifications": {"limit": 10},
    "get_currencies": {}, "get_categories": {},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_every_operation_uses_one_exact_documented_route(monkeypatch, operation):
    method, path, envelope = native.OPERATIONS[operation]
    plural = envelope in {"groups", "friends", "expenses", "comments", "notifications", "currencies", "categories"}
    body = {envelope: True if envelope == "success" else [{"id": 42}] if plural else {"id": 42, "first_name": "Ada"}}
    if operation in {"create_expense", "update_expense"}:
        body["errors"] = {}
    requests = transport(monkeypatch, body)
    result = await node({"operation": operation, **CONFIGS[operation]}).execute({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "secure.splitwise.com"
    assert request.url.path == "/api/v3.0" + path.replace("{id}", "42")
    assert request.headers["Authorization"] == "Bearer " + KEY
    assert KEY not in json.dumps(result)
    if method == "POST":
        sent = json.loads(request.content) if request.content else {}
        expected = {k: v for k, v in CONFIGS[operation].items() if k != "id"}
        if operation == "create_expense":
            expected["split_equally"] = True
        assert sent == expected
        assert result["write_acknowledged"] is True
    else:
        expected = {k: str(v) for k, v in CONFIGS[operation].items() if k != "id"}
        assert dict(request.url.params) == expected
        assert "write_acknowledged" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"success": False, "errors": {"base": ["The user has a non-zero balance"]}},
    {"success": False}, {}, {"success": "true"}, {"success": 1},
])
async def test_http_200_does_not_claim_failed_write(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "remove_user_from_group", "group_id": 4012, "user_id": 940142}).execute({})
    assert result["status"] != "success"
    assert "write_acknowledged" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"expenses": [], "errors": {}}, {"expenses": [{"id": 42}]}, {"expenses": [{"id": 42}], "errors": {"base": ["Invalid cost"]}}])
async def test_expense_writes_require_expenses_and_empty_errors(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "create_expense", **CONFIGS["create_expense"]}).execute({})
    assert result["status"] != "success"


@pytest.mark.asyncio
async def test_offset_pagination_preserves_filters_and_no_unbounded_loop(monkeypatch):
    requests = transport(monkeypatch, {"expenses": [{"id": 1}, {"id": 2}]})
    cfg = {"operation": "get_expenses", "friend_id": 123, "limit": 2, "offset": 4,
        "dated_after": "2012-05-02T13:00:00Z"}
    result = await node(cfg).execute({})
    assert result["next_offset"] == 6 and result["has_more"] is True
    assert len(requests) == 1
    assert dict(requests[0].url.params)["dated_after"] == "2012-05-02T13:00:00Z"
    transport(monkeypatch, {"expenses": []})
    result = await node({**cfg, "offset": 6}).execute({})
    assert result["next_offset"] is None and result["has_more"] is False


@pytest.mark.asyncio
async def test_rejection_preserves_provider_text_and_redacts_key(monkeypatch):
    transport(monkeypatch, {"error": "Rejected " + KEY}, status=401)
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["status"] == "error" and result["http_status"] == 401
    assert "Rejected" in result["error"] and KEY not in str(result)


@pytest.mark.asyncio
async def test_response_secret_redacted_recursively(monkeypatch):
    transport(monkeypatch, {"user": {"id": 42, "first_name": "Ada", "nested": [KEY]}})
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["status"] == "success" and KEY not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get_groups", "create_group"])
async def test_transport_failure_no_automatic_write_retry(monkeypatch, operation):
    requests = transport(monkeypatch, httpx.ReadTimeout("timeout"))
    result = await node({"operation": operation, **CONFIGS[operation]}).execute({})
    assert len(requests) == 1
    assert result["status"] == ("unknown" if operation == "create_group" else "error")


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"user": []}, {"user": {}}, []])
async def test_connection_identity_fails_closed(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["status"] == "error"


@pytest.mark.parametrize("config", [
    {"operation": "get_user", "id": "../other"},
    {"operation": "get_user", "id": 0},
    {"operation": "get_expenses", "limit": 0},
    {"operation": "get_expenses", "offset": -1},
    {"operation": "create_expense", "group_id": 1, "cost": "25.001", "description": "Groceries"},
    {"operation": "create_expense", "group_id": 1, "cost": "25", "description": "Groceries", "split_equally": False},
    {"operation": "get_current_user", "url": "https://evil.example"},
])
def test_invalid_inputs_refused(config):
    assert native.SplitwiseNode.validate_config({"config": config})["valid"] is False


@pytest.mark.parametrize("key", ["https://example.com/key", "<token>", "Bearer secret", "has\nnewline"])
def test_invalid_credentials_refused(key):
    with pytest.raises((ValidationError, ValueError)):
        native.SplitwiseAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["delete_friend", "delete_group", "undelete_expense"])
async def test_verbatim_published_success_responses(monkeypatch, operation):
    from pathlib import Path
    fixtures = json.loads((Path(__file__).parent / "fixtures/splitwise/documented_responses.json").read_text())
    body = fixtures["POST /" + operation + "/{id}"]["body"]
    transport(monkeypatch, body)
    result = await node({"operation": operation, "id": 42}).execute({})
    assert result["status"] == "success" and result["success"] is True


@pytest.mark.asyncio
async def test_update_category_remains_documented_integer(monkeypatch):
    requests = transport(monkeypatch, {"expenses": [{"id": 42}], "errors": {}})
    result = await node({"operation": "update_expense", **CONFIGS["update_expense"], "category_id": 15}).execute({})
    assert result["status"] == "success"
    assert json.loads(requests[0].content)["category_id"] == 15


def poll_response(expenses=True):
    """Unmodified response samples copied from Splitwise's rendered API docs."""
    fixtures = json.loads((Path(__file__).parent / "fixtures/splitwise/poll_responses.json").read_text())
    return fixtures["GET /get_expenses" if expenses else "GET /get_notifications"]["body"]


def poll_state(instance, state):
    async def update(mutator, **kwargs):
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    instance._update_node_state = update


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,envelope", [
    ("on_expense_changed", "expenses"), ("on_new_activity", "notifications"),
])
async def test_poll_baselines_then_delivers_documented_records_once(monkeypatch, operation, envelope):
    body = poll_response(envelope == "expenses")
    requests = transport(monkeypatch, body)
    instance = node({"operation": operation, "updated_after": "2020-07-28T20:46:00Z"})
    state = {}
    poll_state(instance, state)
    first = await instance.execute({})
    assert first[envelope] == []
    assert instance.trigger_produced_no_event(first)
    assert native.SplitwiseNode.resolve_agent_event(first) is None
    # An already armed trigger that has seen no items emits the provider's sample.
    state["seen_ids"] = []
    fresh = await instance.execute({})
    assert fresh[envelope] == body[envelope]
    assert instance.trigger_emitted_event(fresh)
    event = native.SplitwiseNode.resolve_agent_event(fresh)
    assert "Splitwise" in event["text"] and str(body[envelope][0]["id"]) in event["text"]
    assert "<strong>" not in event["text"]
    repeated = await instance.execute({})
    assert repeated[envelope] == []
    for request in requests:
        assert request.headers["Authorization"] == "Bearer " + KEY
        assert request.url.params["updated_after"] == "2020-07-28T20:46:00Z"
        assert set(request.url.params) == ({"limit", "offset", "updated_after"} if envelope == "expenses"
                                           else {"limit", "updated_after"})


@pytest.mark.asyncio
async def test_expense_poll_detects_edit_to_existing_id_and_rebaselines_scope(monkeypatch):
    body = poll_response()
    transport(monkeypatch, body)
    state = {}
    instance = node({"operation": "on_expense_changed", "group_id": 391})
    poll_state(instance, state)
    await instance.execute({})
    # Both timestamps are values documented in the expense response sample.
    edited = deepcopy(body)
    edited["expenses"][0]["updated_at"] = edited["expenses"][0]["created_at"]
    transport(monkeypatch, edited)
    result = await instance.execute({})
    assert len(result["expenses"]) == 1
    assert result["expenses"][0]["id"] == body["expenses"][0]["id"]
    assert not (await instance.execute({}))["expenses"]
    changed = node({"operation": "on_expense_changed", "friend_id": 4818})
    poll_state(changed, state)
    assert not (await changed.execute({}))["expenses"]


@pytest.mark.asyncio
async def test_expense_poll_pages_before_committing_baseline(monkeypatch):
    body = poll_response()
    requests = []
    def respond(request):
        requests.append(request)
        offset = int(request.url.params["offset"])
        return httpx.Response(200, json={"expenses": body["expenses"] * 100 if offset == 0 else []})
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs:
        httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs))
    state = {}
    instance = node({"operation": "on_expense_changed", "group_id": 391, "friend_id": 4818})
    poll_state(instance, state)
    await instance.execute({})
    assert [r.url.params["offset"] for r in requests] == ["0", "100"]
    assert all(r.url.params["group_id"] == "391" and r.url.params["friend_id"] == "4818" for r in requests)
    assert state["seen_ids"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [({}, 200), ({"expenses": [{}]}, 200),
    ({"expenses": []}, 401), ({"expenses": {}}, 200)])
async def test_failed_poll_does_not_consume_state(monkeypatch, body, status):
    transport(monkeypatch, body, status)
    instance = node({"operation": "on_expense_changed"})
    state = {}
    poll_state(instance, state)
    with pytest.raises(ValueError):
        await instance.execute({})
    assert state == {}


@pytest.mark.asyncio
async def test_expense_poll_refuses_truncated_baseline(monkeypatch):
    requests = transport(monkeypatch, {"expenses": poll_response()["expenses"] * 100})
    state = {}
    instance = node({"operation": "on_expense_changed"})
    poll_state(instance, state)
    with pytest.raises(ValueError, match="2,000"):
        await instance.execute({})
    assert len(requests) == 20 and state == {}
