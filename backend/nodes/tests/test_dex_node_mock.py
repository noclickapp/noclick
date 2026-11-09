"""Dex request and poll regressions. Synthetic values follow the pinned v2 schema.

Conformance separately synthesizes complete provider responses from the pinned
OpenAPI contract; these tests focus on routing, input mapping and deduplication.
"""
import json
from pathlib import Path
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import dex_node as dex
from nodes.core.registry import NodeFactory
from nodes.core.base import ConfigValidationError

CONTACT = "12345678-1234-4234-9234-123456789abc"
GROUP = "22345678-1234-4234-9234-123456789abc"
KEY = "dex_synthetic_test_key"
IDEMPOTENCY = "12345678-1234-4234-9234-123456789def"

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **fields):
    return NodeFactory.create_node(node_id="dex-test", node_type="automation-dex", node_data={
        "config": {"operation": operation, **fields},
        "credentials": {"credential_type": "dex_api_key", "api_key": KEY},
    })


def transport(monkeypatch, reply):
    calls = []
    def respond(request):
        calls.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json={"data": reply})
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as session:
            yield session
    monkeypatch.setattr(dex, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,method,path,body", [
    ("create_contact", {"first_name": "Alex", "email": "alex@example.com"}, "POST", "/v2/contacts/", {"first_name": "Alex", "contact_emails": [{"email": "alex@example.com"}]}),
    ("update_contact", {"contact_id": CONTACT, "starred": False}, "PATCH", f"/v2/contacts/{CONTACT}", {"starred": False}),
    ("create_note", {"note": "Coffee with Alex", "event_time": "2026-11-10T12:00:00Z", "contact_ids": [CONTACT]}, "POST", "/v2/timeline/notes", {"note": {"note": "Coffee with Alex", "event_time": "2026-11-10T12:00:00Z", "timeline_items_contacts": [{"contact_id": CONTACT}]}}),
    ("create_reminder", {"text": "Follow up", "due_at_date": "2026-11-11T12:00:00Z", "contact_ids": [CONTACT]}, "POST", "/v2/reminders/", {"reminder": {"text": "Follow up", "due_at_date": "2026-11-11T12:00:00Z", "reminders_contacts": [{"contact_id": CONTACT}]}}),
    ("update_reminder", {"reminder_id": CONTACT, "is_complete": True}, "PATCH", f"/v2/reminders/{CONTACT}", {"reminder": {"is_complete": True}}),
    ("create_group", {"name": "Friends"}, "POST", "/v2/groups/", {"group": {"name": "Friends"}}),
    ("create_tag", {"name": "Customer"}, "POST", "/v2/tags/", {"tag": {"name": "Customer"}}),
    ("add_contacts_to_group", {"group_id": GROUP, "contact_ids": [CONTACT]}, "POST", f"/v2/groups/{GROUP}/contacts", {"contactIds": [CONTACT]}),
    ("remove_contacts_from_group", {"group_id": GROUP, "contact_ids": [CONTACT]}, "POST", f"/v2/groups/{GROUP}/contacts/batch-remove", {"contactIds": [CONTACT]}),
    ("add_tags_to_contacts", {"contact_ids": [CONTACT], "tag_ids": [GROUP]}, "POST", "/v2/tags/contacts/add", {"contactIds": [CONTACT], "tagIds": [GROUP]}),
])
async def test_write_contract(monkeypatch, operation, fields, method, path, body):
    calls = transport(monkeypatch, {"accepted": True})
    await node(operation, idempotency_key=IDEMPOTENCY, **fields).execute({})
    assert len(calls) == 1
    req = calls[0]
    assert req.method == method and req.url.path == path
    assert req.headers["Authorization"] == f"Bearer {KEY}"
    assert req.headers["Idempotency-Key"] == IDEMPOTENCY
    assert json.loads(req.content) == body


@pytest.mark.asyncio
async def test_page_cursor_and_time_filter(monkeypatch):
    calls = transport(monkeypatch, {"contacts": [], "pagination": {"nextCursor": "opaque-next"}})
    result = await node("list_contacts", take=25, cursor="opaque-in", updated_since="2026-11-10T12:00:00+02:00").execute({})
    assert calls[0].url.params["take"] == "25"
    assert calls[0].url.params["cursor"] == "opaque-in"
    assert calls[0].url.params["where[has_updated_at][gte]"] == "2026-11-10T10:00:00Z"
    assert result["pagination"]["nextCursor"] == "opaque-next"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["on_new_contact", "on_updated_contact"])
async def test_poll_reads_all_pages_before_dedup(monkeypatch, operation):
    rows = [{"id": CONTACT, "full_name": "Alex", "updated_at": "2026-11-10T12:00:00Z"}, {"id": GROUP, "full_name": "Sam", "updated_at": "2026-11-10T13:00:00Z"}]
    def reply(req):
        second = "cursor" in req.url.params
        return httpx.Response(200, json={"data": {"contacts": [rows[int(second)]], "pagination": {"nextCursor": None if second else "next"}}})
    calls = transport(monkeypatch, reply)
    n = node(operation)
    seen = []
    async def dedup(items, key):
        seen.extend(key(item) for item in items)
        return items
    n._filter_unseen = dedup
    result = await n.execute({})
    assert len(calls) == 2 and result["contacts"] == rows
    assert seen == [r["id"] + (":" + r["updated_at"] if operation == "on_updated_contact" else "") for r in rows]
    event = n.resolve_agent_event(result)
    assert "Alex" in event["text"] and CONTACT in event["text"]
    assert n.should_propagate_output(result, {"operation": operation})
    assert not n.should_propagate_output({"contacts": []}, {"operation": operation})


@pytest.mark.asyncio
async def test_poll_refuses_repeated_cursor_without_advancing_seen(monkeypatch):
    transport(monkeypatch, {"contacts": [{"id": CONTACT}], "pagination": {"nextCursor": "same"}})
    n = node("on_new_contact")
    n._filter_unseen = AsyncMock()
    with pytest.raises(ValueError, match="repeated"):
        await n.execute({})
    n._filter_unseen.assert_not_called()


@pytest.mark.asyncio
async def test_provider_rejection_is_not_success(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(403, json={"error": {"code": "api_key_read_only", "message": "Read-only API key"}}))
    with pytest.raises(httpx.HTTPStatusError):
        await node("get_user").execute({})


@pytest.mark.asyncio
async def test_delete_204(monkeypatch):
    calls = transport(monkeypatch, lambda req: httpx.Response(204))
    assert await node("delete_contact", contact_id=CONTACT, idempotency_key=IDEMPOTENCY).execute({}) == {"deleted": True}
    assert calls[0].content == b""


def test_manual_key_default_and_invalid_inputs():
    assert dex.DexAPIKeyCredential(api_key=KEY).credential_type == "dex_api_key"
    with pytest.raises(ValidationError):
        dex.DexAPIKeyCredential(api_key="https://getdex.com/key")
    with pytest.raises(ConfigValidationError):
        node("create_tag", name="Customer")
    with pytest.raises(ConfigValidationError):
        node("get_contact", contact_id="../users/me")


@pytest.mark.asyncio
async def test_published_create_group_example(monkeypatch):
    example = json.loads((Path(__file__).parent / "fixtures/dex/create_group.json").read_text())
    transport(monkeypatch, lambda req: httpx.Response(201, json=example))
    assert await node("create_group", name="string", idempotency_key=IDEMPOTENCY).execute({}) == example["data"]
