"""Telegram's receive trigger on the push-trigger lifecycle.

A bot hears nobody until its webhook points at NoClick. The trigger used to be
registered only by its config panel's loader, so nothing headless (the
platform's ``OnEvent``, the builder, the nightly resync) could register it, a
run re-registered it on every execution, its teardown read a key the
credential doesn't have, and deliveries carried no secret. It now registers
through ``ExternalWebhookTriggerMixin``: ``setWebhook`` with a secret Telegram
sends back, a refusal when another trigger already holds the bot (a bot has
one webhook), and a teardown that leaves a webhook pointed elsewhere alone.
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.telegram_node import (
    SECRET_HEADER,
    WEBHOOK_OPERATIONS,
    TelegramBotTokenCredential,
    TelegramNode,
    TelegramNodeConfig,
    TelegramReceiveConfig,
)
from utils.webhook_manager import WebhookManager

pytestmark = pytest.mark.asyncio

TOKEN = "123456:ABC-test-token"
BASE = "https://hooks.example.test"
OURS = "0b6f2a4e-1c3d-4e5f-8a9b-0c1d2e3f4a5b"
OTHER = "7d8e9f0a-1b2c-4d3e-9f8a-7b6c5d4e3f2a"
URL = f"{BASE}/webhook/{OURS}"
CRED = {"credential_type": "telegram_bot_token", "token": TOKEN}


@pytest.fixture(autouse=True)
def bot(monkeypatch):
    """Where Telegram says the bot's one webhook points (nowhere, at first)."""
    monkeypatch.setenv("PUBLIC_WEBHOOK_URL", BASE)
    state = {"url": ""}

    async def webhook_info(token):
        return {"success": True, "info": {"url": state["url"]}}

    monkeypatch.setattr("nodes.telegram_node.get_telegram_webhook_info", webhook_info)
    return state


def _node(config):
    return TelegramNode(node_id="n1", node_type="automation-telegram", node_data={},
                        config=TelegramNodeConfig(config=config, credentials=TelegramBotTokenCredential(token=TOKEN)),
                        sio=None, sid=None, workflow_id="wf")


def _update(chat_id=777, message_id=42, key="message", **extra):
    return {"update_id": 9, key: {"message_id": message_id, "chat": {"id": chat_id},
                                  "from": {"id": 1, "first_name": "Ada"}, "text": "hi", **extra}}


async def test_receive_is_a_push_trigger_the_lifecycle_registers_by_itself():
    assert issubclass(TelegramNode, ExternalWebhookTriggerMixin)
    for operation in WEBHOOK_OPERATIONS:
        assert WebhookManager.operation_requires_webhook("automation-telegram", operation), operation
    # What the platform's event catalog keys on: NoClick registers it, with no URL for anyone to paste.
    assert WebhookManager.registers_itself("automation-telegram", "receive_webhook_messages", "telegram_bot_token")
    assert not WebhookManager.operation_requires_webhook("automation-telegram", "send_message_to_chat")


async def test_registration_sets_the_webhook_with_a_secret_and_records_the_bot(monkeypatch):
    holder = AsyncMock(return_value=None)
    monkeypatch.setattr("utils.webhook_manager.registration_holder", holder)
    with patch("nodes.telegram_node.set_telegram_webhook", AsyncMock(return_value={"success": True})) as set_hook:
        extra = await TelegramNode._register_external_webhook(
            webhook_url=URL, credential=CRED, config={"webhook_id": OURS}, node_id="n1")
    token, url, secret = set_hook.await_args.args
    assert (token, url) == (TOKEN, URL)
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret)  # Telegram's secret_token alphabet
    # The bot's id is the record: the next registration on the same bot finds this row.
    assert extra == {"external_webhook_id": "123456", "signing_secret": secret}
    holder.assert_awaited_once_with("123456", WEBHOOK_OPERATIONS, except_webhook_id=OURS)


async def test_a_bot_wakes_one_trigger(monkeypatch):
    """A second trigger on the same bot is refused by name: setWebhook would
    take the bot's updates from the first, which would still read registered."""
    monkeypatch.setattr("utils.webhook_manager.registration_holder", AsyncMock(return_value='"Support desk"'))
    with patch("nodes.telegram_node.set_telegram_webhook", AsyncMock()) as set_hook:
        with pytest.raises(RuntimeError, match='already sends its messages to "Support desk"'):
            await TelegramNode._register_external_webhook(
                webhook_url=URL, credential=CRED, config={"webhook_id": OURS}, node_id="n2")
    set_hook.assert_not_awaited()


async def test_the_trigger_telegram_points_the_bot_at_now_holds_it(monkeypatch, bot):
    """A trigger registered before the bot was recorded on its row still holds
    the bot: Telegram's own answer decides first, so a duplicate reached first
    by a resync can't take the bot from the trigger that hears it today."""
    from tests.mocks.mock_asyncpg import MockNativePool

    live = MockNativePool({"FROM webhooks w": {"workflow_id": "wf0", "name": "Front desk"}})
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: live)
    bot["url"] = f"{BASE}/webhook/{OTHER}"
    with patch("nodes.telegram_node.set_telegram_webhook", AsyncMock()) as set_hook:
        with pytest.raises(RuntimeError, match='already sends its messages to "Front desk"'):
            await TelegramNode._register_external_webhook(
                webhook_url=URL, credential=CRED, config={"webhook_id": OURS}, node_id="n2")
    set_hook.assert_not_awaited()
    sql, *args = live.fetchrow.await_args.args
    assert "w.is_active" in sql and args == [OTHER, OURS]

    # Pointed at its own address, at someone's server, or at nothing live: it registers.
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: MockNativePool({}))
    for url in (URL, "https://their-app.example.test/tg", f"{BASE}/webhook/{OTHER}"):
        bot["url"] = url
        with patch("nodes.telegram_node.set_telegram_webhook", AsyncMock(return_value={"success": True})) as set_hook:
            await TelegramNode._register_external_webhook(
                webhook_url=URL, credential=CRED, config={"webhook_id": OURS}, node_id="n1")
        set_hook.assert_awaited_once()


async def test_a_registration_telegram_refuses_fails_with_its_words(monkeypatch):
    monkeypatch.setattr("utils.webhook_manager.registration_holder", AsyncMock(return_value=None))
    refused = {"success": False, "error": "Telegram API error: Unauthorized"}
    with patch("nodes.telegram_node.set_telegram_webhook", AsyncMock(return_value=refused)):
        with pytest.raises(ValueError, match="Unauthorized"):
            await TelegramNode._register_external_webhook(
                webhook_url=URL, credential=CRED, config={"webhook_id": OURS}, node_id="n1")
    with pytest.raises(ValueError, match="bot token is required"):
        await TelegramNode._register_external_webhook(
            webhook_url=URL, credential={}, config={"webhook_id": OURS}, node_id="n1")
    with pytest.raises(RuntimeError, match="not provisioned"):
        await TelegramNode._register_external_webhook(webhook_url=URL, credential=CRED, config={}, node_id="n1")


@pytest.mark.parametrize("config", [
    {"webhook_url": URL},  # the config's mirror
    {"webhook_id": OURS},  # the row's id, when the mirror never landed
])
async def test_teardown_clears_the_webhook_while_it_is_ours(monkeypatch, config):
    info = AsyncMock(return_value={"success": True, "info": {"url": URL}})
    with patch("nodes.telegram_node.get_telegram_webhook_info", info), \
            patch("nodes.telegram_node.delete_telegram_webhook", AsyncMock(return_value={"success": True})) as delete:
        await TelegramNode.cleanup_external_webhook(None, "wf", "n1", config, CRED)
    delete.assert_awaited_once_with(TOKEN)


async def test_teardown_leaves_a_webhook_pointed_elsewhere(monkeypatch):
    """The bot's owner pointed it at their own server since: removing the
    trigger must not cut that server off."""
    elsewhere = AsyncMock(return_value={"success": True, "info": {"url": "https://their-app.example.test/tg"}})
    with patch("nodes.telegram_node.get_telegram_webhook_info", elsewhere), \
            patch("nodes.telegram_node.delete_telegram_webhook", AsyncMock()) as delete:
        await TelegramNode.cleanup_external_webhook(None, "wf", "n1", {"webhook_url": URL}, CRED)
    delete.assert_not_awaited()
    # A teardown that can't see where the webhook points fails, so the row keeps its record to retry.
    unknown = AsyncMock(return_value={"success": False, "error": "Timeout connecting to Telegram API"})
    with patch("nodes.telegram_node.get_telegram_webhook_info", unknown):
        with pytest.raises(ValueError, match="Timeout"):
            await TelegramNode.cleanup_external_webhook(None, "wf", "n1", {"webhook_url": URL}, CRED)


async def test_a_delivery_must_carry_the_registrations_secret():
    armed = {"operation": "receive_webhook_messages", "signing_secret": "s3cret_-token"}
    assert TelegramNode.verify_webhook_signature(b"{}", {SECRET_HEADER: "s3cret_-token"}, armed)
    assert not TelegramNode.verify_webhook_signature(b"{}", {SECRET_HEADER: "guess"}, armed)
    assert not TelegramNode.verify_webhook_signature(b"{}", {}, armed)
    # Registered before secrets: accepted until the lifecycle registers it again with one.
    assert TelegramNode.verify_webhook_signature(b"{}", {}, {"operation": "receive_webhook_messages"})


async def test_what_a_noclick_node_sends_never_fires_a_receive_trigger():
    """Two bots administering one channel each hear the other's posts: every
    message the Bot API answers a call with is fingerprinted at send."""
    node = _node(TelegramReceiveConfig())
    response = MagicMock(status_code=200)
    response.json.return_value = {"ok": True, "result": {"message_id": 5, "chat": {"id": -100}}}
    client = AsyncMock()
    client.request.return_value = response
    with patch("httpx.AsyncClient") as client_class, \
            patch("nodes.telegram_node.record_self_post", AsyncMock()) as record:
        client_class.return_value.__aenter__.return_value = client
        await node._make_request("POST", "sendPhoto", TelegramBotTokenCredential(token=TOKEN), {"chat_id": -100})
        response.json.return_value = {"ok": True, "result": [
            {"message_id": 6, "chat": {"id": -100}}, {"message_id": 7, "chat": {"id": -100}}]}
        await node._make_request("POST", "sendMediaGroup", TelegramBotTokenCredential(token=TOKEN), {})
    assert [c.args for c in record.await_args_list] == [
        ("telegram", "-100:5"), ("telegram", "-100:6"), ("telegram", "-100:7")]

    receive = {"operation": "receive_webhook_messages"}
    with patch("nodes.telegram_node.is_self_post", AsyncMock(return_value=True)) as seen:
        reason = await TelegramNode.drop_trigger_event(_update(-100, 5, key="channel_post"), receive)
    assert reason and "-100:5" in reason
    seen.assert_awaited_once_with("telegram", "-100:5")
    with patch("nodes.telegram_node.is_self_post", AsyncMock(return_value=False)):
        assert await TelegramNode.drop_trigger_event(_update(), receive) is None
    assert await TelegramNode.drop_trigger_event(_update(), {"operation": "setup_telegram_channel_guided"}) is None


async def test_receive_fires_are_budgeted_per_chat():
    receive = {"operation": "receive_webhook_messages"}
    assert TelegramNode.trigger_fire_budget_channel(_update(chat_id=777), receive) == "777"
    assert TelegramNode.trigger_fire_budget_channel(_update(chat_id=-100, key="edited_channel_post"), receive) == "-100"
    pressed = {"update_id": 3, "callback_query": {"id": "q", "data": "ok", "message": {"chat": {"id": 888}}}}
    assert TelegramNode.trigger_fire_budget_channel(pressed, receive) == "888"
    assert TelegramNode.trigger_fire_budget_channel(_update(), {"operation": "send_message_to_chat"}) is None


async def test_a_run_with_no_update_says_no_event_came():
    out = await _node(TelegramReceiveConfig()).execute({})
    assert out["status"] == "no_event" and "Message the bot" in out["message"]


async def test_a_headless_registration_hands_its_row_id_and_records_a_refusal(monkeypatch):
    """The lifecycle's register (reconcile, restores, the platform's triggers)
    tells the hook which row is its own, and a refusal reaches the step as its
    trigger_error, as a panel open shows it, instead of only a log line."""
    monkeypatch.setattr(WebhookManager, "get_or_create_webhook", AsyncMock(return_value={
        "webhook_id": OURS, "webhook_url": URL, "external_webhook_id": None}))
    monkeypatch.setattr(WebhookManager, "persist_registration_state", AsyncMock())
    merged = AsyncMock()
    monkeypatch.setattr(WebhookManager, "merge_node_config_patch", merged)
    register = AsyncMock(side_effect=RuntimeError('This bot already sends its messages to "Desk".'))
    monkeypatch.setattr(TelegramNode, "_register_external_webhook", register)

    ok = await WebhookManager._register_single_node(
        None, wf_uuid="wf", user_id="u", node_class=TelegramNode, node_type="automation-telegram",
        node_id="n1", node_config={"operation": "receive_webhook_messages"}, credential=CRED,
        credential_id="cred-1", current_op="receive_webhook_messages")
    assert ok is False
    assert register.await_args.kwargs["config"]["webhook_id"] == OURS
    merged.assert_awaited_once_with(None, "wf", "n1", {
        "trigger_registered": False, "trigger_error": 'This bot already sends its messages to "Desk".'})
