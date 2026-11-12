"""The WhatsApp receive_message trigger's chat allowlist (``chat_ids``).

A QR-linked number belongs to many chats, and every delivered message that
passes the trigger filter is a billed agent turn. An agent meant for one group
must not be woken by every other group the number is in, so ``chat_ids``
names the chats that fire: when set it alone decides (a listed group fires
with group messages off, an unlisted chat never fires); empty keeps the old
behaviour exactly.
"""
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from coder.workflow.operation_catalog import validate_node_config
from nodes.whatsapp_node import WhatsAppNode
from utils import capabilities, webhook_routes
from utils.capabilities import ACCOUNT_UNCLAIMED, TRIGGER_DELIVERY

RECEIVE = {"operation": "receive_message"}
GROUP = "120000000000000001@g.us"
OTHER_GROUP = "222@g.us"
DM = "12025550101@c.us"


def _event(chat_id, *, from_me=False, remote_jid=None, remote_jid_alt=""):
    """Minimal WAHooks 'message' envelope as delivered to the webhook."""
    return {
        "event": "message",
        "session": "s",
        "payload": {
            "from": chat_id,
            "fromMe": from_me,
            "body": "hello",
            "_data": {"key": {
                "fromMe": from_me,
                "remoteJid": remote_jid if remote_jid is not None else chat_id,
                "remoteJidAlt": remote_jid_alt,
            }},
        },
    }


def _fires(event, **config):
    return WhatsAppNode.filter_trigger_payload(event, {**RECEIVE, **config})


# ── A listed chat fires, everything else is dropped ───────────────────────────

def test_a_listed_group_fires_with_group_messages_left_off():
    assert _fires(_event(GROUP), chat_ids=[GROUP]) is True
    assert _fires(_event(GROUP), chat_ids=[GROUP], include_group_messages="false") is True


def test_an_unlisted_group_is_dropped_even_with_group_messages_on():
    assert _fires(_event(OTHER_GROUP), chat_ids=[GROUP], include_group_messages="true") is False


def test_a_direct_message_from_an_unlisted_chat_is_dropped():
    assert _fires(_event(DM), chat_ids=[GROUP]) is False


def test_a_listed_direct_chat_fires():
    assert _fires(_event(DM), chat_ids=[GROUP, DM]) is True


@pytest.mark.parametrize("listed", ["+1 202-555-0101", "12025550101@s.whatsapp.net", DM])
def test_a_direct_chat_matches_however_it_is_spelled(listed):
    # Phone chats arrive as @c.us or @s.whatsapp.net; a typed number names the same chat.
    assert _fires(_event(DM), chat_ids=[listed]) is True
    assert _fires(_event("12025550101@s.whatsapp.net"), chat_ids=[listed]) is True


def test_an_lid_chat_matches_its_listed_phone_jid():
    event = _event("12025550102@lid", remote_jid_alt="12025550101@s.whatsapp.net")
    assert _fires(event, chat_ids=[DM]) is True
    assert _fires(event, chat_ids=["12025550102@lid"]) is True
    assert _fires(event, chat_ids=["12025550108@c.us"]) is False


def test_listing_a_chat_never_lifts_the_hard_drops():
    assert _fires(_event(GROUP, from_me=True), chat_ids=[GROUP]) is False
    assert _fires(_event("status@broadcast"), chat_ids=["status@broadcast"]) is False
    assert _fires(_event("120000000000000002@newsletter"), chat_ids=["120000000000000002@newsletter"]) is False


def test_cloud_api_deliveries_are_untouched():
    # The field is QR-only; Cloud API envelopes keep passing through.
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"messages": [{"from": "12025550104", "text": {"body": "hi"}}]}}]}],
    }
    assert _fires(payload, chat_ids=[GROUP]) is True


# ── No allowlist = the behaviour before it existed ────────────────────────────

@pytest.mark.parametrize("unset", [{}, {"chat_ids": []}, {"chat_ids": None}, {"chat_ids": [""]}])
def test_without_a_list_the_group_toggle_still_decides(unset):
    assert _fires(_event(DM), **unset) is True
    assert _fires(_event(GROUP), **unset) is False
    assert _fires(_event(GROUP), **unset, include_group_messages="true") is True


# ── The field the builder, MCP and the panel write ────────────────────────────

def test_the_field_is_a_qr_chat_picker_on_the_existing_chat_loader():
    props = WhatsAppNode.get_config_schema()["$defs"]["WhatsAppReceiveMessageConfig"]["properties"]
    field = props["chat_ids"]
    assert field["type"] == "array" and field["items"] == {"type": "string"}
    assert field["x-dynamic-options"]["field_name"] == "chat_id"
    assert field["x-supported-credential-types"] == ["whatsapp_qr"]


def test_ai_written_configs_validate():
    def check(config):
        return validate_node_config("automation-whatsapp", "receive_message", {**RECEIVE, **config})

    assert check({"chat_ids": [GROUP, "+12025550101"]}) is None
    assert check({"chat_ids": []}) is None
    assert check({}) is None
    assert "valid list" in check({"chat_ids": GROUP})


# ── Through the real delivery route: an unlisted chat never runs ──────────────

WORKFLOW = str(uuid.uuid4())
WEBHOOK = str(uuid.uuid4())


@pytest.fixture
def route(monkeypatch):
    node = {"id": "wa", "type": "automation-whatsapp",
            "config": {**RECEIVE, "webhook_id": WEBHOOK, "chat_ids": [GROUP], "include_group_messages": "true"}}
    monkeypatch.setattr(webhook_routes, "get_webhook_config", AsyncMock(return_value={
        "id": WEBHOOK, "user_id": str(uuid.uuid4()), "workflow_id": WORKFLOW, "node_id": "wa",
        "secret": None, "is_active": True, "workflow_config": {"nodes": [node], "edges": []},
    }))
    run = AsyncMock(return_value=None)
    monkeypatch.setattr(webhook_routes, "_execute_workflow_with_relay", run)
    monkeypatch.setattr(webhook_routes, "update_webhook_stats", lambda *_: None)
    monkeypatch.setattr("utils.fire_budget.over_fire_budget", AsyncMock(return_value=False))
    monkeypatch.delitem(capabilities._providers, TRIGGER_DELIVERY, raising=False)
    monkeypatch.delitem(capabilities._providers, ACCOUNT_UNCLAIMED, raising=False)
    app = FastAPI()
    app.include_router(webhook_routes.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"), run


async def test_the_route_drops_an_unlisted_group_before_any_run(route):
    client, run = route
    async with client:
        response = await client.post(f"/webhook/{WEBHOOK}", json=_event(OTHER_GROUP))
    assert response.status_code == 200
    assert response.json()["message"] == "Webhook received but event action does not match trigger filter"
    run.assert_not_awaited()


async def test_the_route_runs_the_listed_group(route):
    client, run = route
    async with client:
        response = await client.post(f"/webhook/{WEBHOOK}", json=_event(GROUP))
    assert response.json()["message"] == "Webhook received and workflow triggered"
    assert run.await_count == 1
