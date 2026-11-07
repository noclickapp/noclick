"""Bookwhen through staging's operation, lookup and connection-evidence hooks.

Provider transport and saved-credential storage are synthetic. Shared hooks are
used as shipped on staging; the node owns no credential-authority mechanism.
"""
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import bookwhen_node as native
from nodes.tests.test_bookwhen_node_mock import EVENT, TICKET, credential, page, record, transport


@pytest.mark.asyncio
async def test_operation_dispatch_loads_saved_token_and_uses_native_node(monkeypatch):
    from nodes.core import run_op
    from utils import credential_approval

    requests, _ = transport(monkeypatch, page())
    load = AsyncMock(return_value=credential())
    monkeypatch.setattr(run_op, "resolve_operation_credential", load)
    admission = AsyncMock(return_value=None)
    monkeypatch.setattr(credential_approval, "admit_node", admission)
    result = await run_op.run_node_operation(
        node_type=native.NODE_TYPE, operation="list_events", arguments={},
        credential_id="00000000-0000-4000-8000-000000000042", user_id="current-user",
    )
    assert result["status"] == "success" and result["items"][0]["id"] == EVENT
    load.assert_awaited_once()
    admission.assert_awaited_once()
    assert requests[0].url.path == "/v2/events"


@pytest.mark.asyncio
async def test_unsaved_connection_evidence_reports_only_schedule_reachability(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence

    transport(monkeypatch, page())
    evidence = await collect_evidence(
        node_type=native.NODE_TYPE, credential_data=credential(), user_id="current-user",
    )
    assert evidence.reachable is True and evidence.account_label is None
    assert native.BookwhenNode.connection_evidence.proves == "reachability"


@pytest.mark.asyncio
async def test_lookup_uses_staging_credential_loader_and_admission(monkeypatch):
    from nodes.core import run_op
    from utils import credential_approval

    requests, _ = transport(monkeypatch, page())
    load = AsyncMock(return_value=credential())
    monkeypatch.setattr(run_op, "resolve_operation_credential", load)
    admission = AsyncMock(return_value=None)
    monkeypatch.setattr(credential_approval, "admit_lookup", admission)
    result = await run_op.run_node_lookup(
        node_type=native.NODE_TYPE, field_name="event_id",
        credential_id="00000000-0000-4000-8000-000000000042", user_id="current-user",
        page_token="40", search="Yoga + café",
    )
    assert result == {"options": [{"value": EVENT, "label": "Owned fixture"}], "next_page_token": None}
    assert load.await_count == 2  # access before admission, then current credential load
    admission.assert_awaited_once()
    assert requests[0].url.params["page[offset]"] == "40"
    assert requests[0].url.params["filter[title]"] == "Yoga + café"


@pytest.mark.asyncio
async def test_ticket_picker_requires_parent_and_checks_event_relationship(monkeypatch):
    requests, _ = transport(monkeypatch, page([record("tickets")], kind="tickets"))
    with pytest.raises(ValueError):
        await native.BookwhenNode.load_field_options("ticket_id", credential(), context={})
    assert requests == []
    result = await native.BookwhenNode.load_field_options("ticket_id", credential(), context={"event_id": EVENT})
    assert result["options"][0]["value"] == TICKET
    assert requests[0].url.params["event"] == EVENT
    transport(monkeypatch, page([record("tickets", relationships={"events": {"data": []}})], kind="tickets"))
    with pytest.raises(ValueError, match="choices were not completed"):
        await native.BookwhenNode.load_field_options("ticket_id", credential(), context={"event_id": EVENT})


@pytest.mark.asyncio
async def test_refused_lookup_does_not_become_empty_success(monkeypatch):
    requests, _ = transport(monkeypatch, lambda _: httpx.Response(403, json={"errors": []}))
    with pytest.raises(ValueError, match="choices were not completed"):
        await native.BookwhenNode.load_field_options("event_id", credential())
    assert len(requests) == 1
