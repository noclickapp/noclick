"""Exercise mailbox wire semantics and poll state without a provider account.

The response fixtures copy the provider's published examples. Pagination and
item IDs vary in individual tests to model subsequent pages and deliveries.
"""
import copy
import json
from pathlib import Path

import httpx
import pytest

from nodes import us_global_mail_node as mod

FIXTURES = Path(__file__).parent / "fixtures" / "us-global-mail"
SCAN_ID = "b3ba0f4f-9ae6-4256-8b70-cd5f404756a9"


def node(config, key="usgmk_test_fixture"):
    data = {"config": config, "credentials": {"api_key": key}}
    return mod.USGlobalMailNode("usgm-test", "automation-us-global-mail", data,
                                mod.USGlobalMailNode.parse_config(data))


def transport(monkeypatch, handler):
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(mod, "guarded_async_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("key,host", [("usgmk_live_fixture", "api.usglobalmail.com"),
                                        ("usgmk_test_fixture", "api-sandbox.usglobalmail.com")])
async def test_account_evidence_and_environment(monkeypatch, key, host):
    def handle(request):
        assert request.method == "GET"
        assert request.url.host == host
        assert request.url.path == "/v1/account"
        assert request.headers["authorization"] == "Bearer " + key
        assert not request.content
        return httpx.Response(200, json={"id": SCAN_ID, "name": "John Smith", "email": "john@example.com", "created_at": "2024-01-15T09:30:00Z"})
    transport(monkeypatch, handle)
    result = await node({"operation": "get_account"}, key).execute({})
    assert result["data"]["name"] == "John Smith"
    assert mod.USGlobalMailNode.connection_evidence.identity_operation == "get_account"


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,expected", [({"is_read": False}, {"is_read": False}),
    ({"destination_folder_id": None}, {"folder_id": None}),
    ({"destination_folder_id": "42", "is_read": True}, {"folder_id": "42", "is_read": True})])
async def test_mail_update_preserves_false_and_explicit_unfile(monkeypatch, changes, expected):
    def handle(request):
        assert request.method == "PATCH"
        assert request.url.path == "/v1/mails/111111"
        assert json.loads(request.content) == expected
        return httpx.Response(200, json={"id": "111111"})
    transport(monkeypatch, handle)
    await node({"operation": "update_mail", "mail_id": "111111", **changes}).execute({})


@pytest.mark.asyncio
async def test_query_arrays_and_cursor_are_not_coalesced(monkeypatch):
    def handle(request):
        assert request.url.params.get_list("status") == ["inbox", "archived"]
        assert request.url.params["cursor"] == "opaque+/="
        assert request.url.params["is_read"] == "false"
        return httpx.Response(200, json={"data": [], "next_cursor": "next", "total_count": 10})
    transport(monkeypatch, handle)
    out = await node({"operation": "list_mails", "status": ["inbox", "archived"],
                      "cursor": "opaque+/=", "is_read": "false"}).execute({})
    assert out["data"]["next_cursor"] == "next"


@pytest.mark.asyncio
async def test_scan_request_is_one_billable_call_and_does_not_expedite(monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        assert request.method == "POST" and request.url.path == "/v1/scans"
        assert json.loads(request.content) == {"mail_id": "111111", "type": "open", "is_expedited": False}
        return httpx.Response(201, json={"id": SCAN_ID})
    transport(monkeypatch, handle)
    out = await node({"operation": "create_scan", "mail_id": "111111", "type": "open"}).execute({})
    assert out["data"]["id"] == SCAN_ID and len(calls) == 1


@pytest.mark.asyncio
async def test_delete_folder_accepts_empty_204(monkeypatch):
    def handle(request):
        assert request.method == "DELETE" and request.url.path == "/v1/folders/42"
        return httpx.Response(204)
    transport(monkeypatch, handle)
    assert (await node({"operation": "delete_folder", "folder_id": "42"}).execute({}))["data"] == {"deleted": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_error_is_not_success_or_retried_and_key_is_redacted(monkeypatch, status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"detail": "Rejected usgmk_test_fixture"})
    transport(monkeypatch, handle)
    with pytest.raises(ValueError, match=f"HTTP {status}: Rejected \\[redacted\\]"):
        await node({"operation": "get_account"}).execute({})
    assert len(calls) == 1


@pytest.mark.parametrize("config", [{"operation": "update_mail", "mail_id": "111111"},
    {"operation": "update_folder", "folder_id": "42"},
    {"operation": "create_scan", "mail_id": "not-a-number", "type": "scan"},
    {"operation": "get_scan", "scan_id": "not-a-uuid"},
    {"operation": "create_folder", "name": "Invoices", "color": "red"}])
def test_invalid_or_empty_mutations_fail_before_io(config):
    with pytest.raises(ValueError):
        node(config)


def stateful(instance, state):
    async def update(mutator, **kwargs):
        new, value = mutator(copy.deepcopy(state))
        if new is not None:
            state.clear()
            state.update(new)
        return value
    instance._update_node_state = update


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fixture", [("on_new_mail", "mails"), ("on_completed_scan", "scans")])
async def test_documented_poll_baseline_new_item_dedup_and_agent_event(monkeypatch, operation, fixture):
    original = json.loads((FIXTURES / f"{fixture}.json").read_text())["body"]
    item = original["data"][0]
    pages = [{**original, "next_cursor": None}]
    queries = []
    def handle(request):
        queries.append(request.url.params)
        assert request.url.params["sort"] == "newest"
        assert request.url.params["limit"] == "100"
        if fixture == "mails":
            assert request.url.params["arrived"] == "week"
        else:
            assert request.url.params["status"] == "completed"
            assert request.url.params["scanned"] == "week"
        return httpx.Response(200, json=pages[1] if request.url.params.get("cursor") else pages[0])
    transport(monkeypatch, handle)
    instance = node({"operation": operation})
    state = {}
    stateful(instance, state)
    baseline = await instance.execute({})
    assert baseline["new_count"] == 0 and instance.trigger_produced_no_event(baseline)
    fresh_item = {**item, "id": "next-id"}
    pages[:] = [{**original, "next_cursor": "second", "total_count": 2},
                {"data": [fresh_item], "next_cursor": None, "total_count": 2}]
    result = await instance.execute({})
    assert result["data"] == [fresh_item] and instance.trigger_emitted_event(result)
    event = mod.USGlobalMailNode.resolve_agent_event(result)
    assert "next-id" in event["text"]
    assert ("from string to string" if fixture == "mails" else "for mail string") in event["text"]
    assert (await instance.execute({}))["new_count"] == 0
    assert mod.USGlobalMailNode.resolve_agent_event({"operation": operation, "data": []}) is None


@pytest.mark.asyncio
async def test_nonadvancing_cursor_does_not_consume_poll_state(monkeypatch):
    page = json.loads((FIXTURES / "mails.json").read_text())["body"]
    page["total_count"] = 3
    transport(monkeypatch, lambda request: httpx.Response(200, json=page))
    instance = node({"operation": "on_new_mail"})
    state = {"seen_ids": []}
    stateful(instance, state)
    with pytest.raises(ValueError, match="nonadvancing cursor"):
        await instance.execute({})
    assert state == {"seen_ids": []}


@pytest.mark.asyncio
async def test_poll_duplicates_emit_once_and_truncation_does_not_consume_state(monkeypatch):
    page = json.loads((FIXTURES / "mails.json").read_text())["body"]
    item = page["data"][0]
    page.update(data=[item, item], total_count=2, next_cursor=None)
    transport(monkeypatch, lambda request: httpx.Response(200, json=page))
    instance = node({"operation": "on_new_mail"})
    state = {"seen_ids": []}
    stateful(instance, state)
    assert (await instance.execute({}))["new_count"] == 1
    before = copy.deepcopy(state)
    page.update(data=[{**item, "id": "unconsumed"}], total_count=3)
    with pytest.raises(ValueError, match="pagination ended before"):
        await instance.execute({})
    assert state == before
