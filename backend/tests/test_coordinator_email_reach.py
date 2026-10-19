"""The coordinator's own email address and how it reaches its owner, against
real Postgres: the address shares the inbound namespace with trigger nodes;
only the owner's authenticated mail becomes a turn; its email goes out on one
thread (kept on the coordinator conversation) and is billed; ``auto`` is the
last-used channel, then the web — a stated preference is a memory the
coordinator acts on by naming the channel."""

import asyncio
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from billing.usage_tracker import usage_tracker
from coder.coordinator import email_channel, reach
from coder.coordinator.email_channel import CoordinatorEmailError, set_coordinator_address
from utils.email_sending import EmailNotSent

pytestmark = pytest.mark.asyncio
DOMAIN = "noclick.app"


@pytest.fixture(autouse=True)
def _coordinators_own_address(monkeypatch):
    # An agent answering in the coordinator's place has its own address: test_coordinator_agent's.
    from utils import capabilities

    monkeypatch.delitem(capabilities._providers, capabilities.ACCOUNT_AGENT_EMAIL, raising=False)


@pytest.fixture
async def owner(postgres_db, postgres_container, monkeypatch):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", DOMAIN)
    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=4, init=setup_asyncpg_codecs,
    )
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    user_id = str(await pool.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, '{}'::jsonb) RETURNING id", email))
    try:
        yield pool, user_id, email
    finally:
        await pool.close()


async def test_the_address_shares_one_namespace_and_renames(owner):
    pool, user_id, _ = owner
    name = f"ada-{uuid.uuid4().hex[:6]}"
    assert await set_coordinator_address(pool, user_id, f"  {name.upper()}  ") == f"{name}@{DOMAIN}"
    assert await email_channel.coordinator_address(pool, user_id) == f"{name}@{DOMAIN}"
    renamed = f"{name}-assistant"
    await set_coordinator_address(pool, user_id, renamed)
    assert await email_channel.coordinator_address(pool, user_id) == f"{renamed}@{DOMAIN}"
    assert await email_channel.owner_for_address(pool, name, DOMAIN) is None  # the old name is free again

    # A trigger node's address and a coordinator's can't collide.
    workflow = await pool.fetchval("INSERT INTO workflows (owner_id, name) VALUES ($1::uuid, 'w') RETURNING id", user_id)
    taken = f"orders-{uuid.uuid4().hex[:6]}"
    await pool.execute("INSERT INTO email_reservations (user_id, workflow_id, node_id, local_part, domain) "
                       "VALUES ($1::uuid, $2, 'trigger', $3, $4)", user_id, workflow, taken, DOMAIN)
    with pytest.raises(CoordinatorEmailError, match="taken"):
        await set_coordinator_address(pool, user_id, taken)
    for bad in ("support", "agent-reply-abc", "no spaces"):
        with pytest.raises(CoordinatorEmailError):
            await set_coordinator_address(pool, user_id, bad)
    assert await email_channel.coordinator_address(pool, user_id) == f"{renamed}@{DOMAIN}"


async def test_opening_email_claims_a_readable_address_once(owner):
    pool, user_id, email = owner
    address = await email_channel.ensure_coordinator_address(pool, user_id)
    assert address == f"{email.split('@')[0]}@{DOMAIN}"
    assert await email_channel.ensure_coordinator_address(pool, user_id) == address
    assert await pool.fetchval(
        "SELECT count(*) FROM email_reservations WHERE user_id = $1::uuid AND kind = 'coordinator'", user_id) == 1
    renamed = f"r-{uuid.uuid4().hex[:8]}"
    await set_coordinator_address(pool, user_id, renamed)
    assert await email_channel.ensure_coordinator_address(pool, user_id) == f"{renamed}@{DOMAIN}"


async def test_a_taken_default_falls_back_to_the_next_name(owner):
    pool, user_id, email = owner
    local = email.split("@")[0]
    other = str(await pool.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, '{}'::jsonb) RETURNING id",
        f"{uuid.uuid4().hex[:8]}@example.com"))
    await set_coordinator_address(pool, other, local)
    assert await email_channel.ensure_coordinator_address(pool, user_id) == f"{local}-assistant@{DOMAIN}"


async def test_nothing_is_claimed_where_inbound_email_is_off(owner, monkeypatch):
    pool, user_id, _ = owner
    monkeypatch.setattr(email_channel, "get_inbound_email_domain", lambda: None)
    assert await email_channel.ensure_coordinator_address(pool, user_id) is None
    assert await email_channel.coordinator_address(pool, user_id) is None


async def test_default_names_are_readable_valid_addresses():
    assert email_channel._default_names("Dhruv.Yadav+news@gmail.com")[:2] == ["dhruv.yadav", "dhruv.yadav-assistant"]
    assert email_channel._default_names(None)[0] == "assistant"
    # A role name is reserved, so the first choice that's free to claim carries the suffix.
    assert email_channel._default_names("admin@example.com")[0] == "admin-assistant"
    assert email_channel._default_names("a..b__c@example.com")[0] == "a-b-c"


async def test_only_the_owners_authenticated_mail_becomes_a_turn(owner, monkeypatch):
    pool, user_id, email = owner
    name = f"bo-{uuid.uuid4().hex[:6]}"
    await set_coordinator_address(pool, user_id, name)
    turns = AsyncMock()
    monkeypatch.setattr(email_channel, "run_email_turn", turns)
    seen = set()
    monkeypatch.setattr("utils.app_event_dedup.was_delivered", AsyncMock(side_effect=lambda p, i: i in seen))
    monkeypatch.setattr("utils.app_event_dedup.mark_delivered", AsyncMock(side_effect=lambda p, i: seen.add(i)))
    body = "Can you pause the digest?\n\nOn Tue, the coordinator wrote:\n> earlier text"
    mail = {"from": f"Owner <{email.upper()}>", "subject": "Digest", "dkimPass": True,
            "headers": {"message-id": "<m1@example.com>"}}

    assert await email_channel.receive(pool, name, DOMAIN, {**mail, "from": "x@evil.example"}, body) == "sender is not the owner"
    assert await email_channel.receive(pool, name, DOMAIN, {**mail, "dkimPass": False, "spfPass": False}, body) \
        == "sender not authenticated"
    # A signature aligned with an owner's From address (the relay's dkimAligned) proves nothing about the
    # envelope sender, which is what's checked: under another envelope, or unauthenticated, it's refused.
    aligned = {"headerFrom": email.lower(), "dkimAligned": True}
    assert await email_channel.receive(pool, name, DOMAIN, {**mail, **aligned, "from": "bounce@mailer.example",
                                                            "dkimPass": False}, body) == "sender is not the owner"
    assert await email_channel.receive(pool, name, DOMAIN, {**mail, **aligned, "dkimPass": False, "spfPass": False},
                                       body) == "sender not authenticated"
    assert await email_channel.receive(pool, "nobody", DOMAIN, mail, body) == "unknown address"
    turns.assert_not_awaited()

    assert await email_channel.receive(pool, name, DOMAIN, mail, body) == "delivered"
    kwargs = turns.await_args.kwargs
    assert kwargs["text"] == "Can you pause the digest?" and kwargs["subject"] == "Digest" and kwargs["user_id"] == user_id
    assert kwargs["message_id"] == "<m1@example.com>"
    assert await email_channel.receive(pool, name, DOMAIN, mail, body) == "duplicate"
    assert turns.await_count == 1


async def test_mail_to_a_turned_off_address_is_dropped_before_anything_reads_it(owner, monkeypatch):
    pool, user_id, email = owner
    name = f"of-{uuid.uuid4().hex[:6]}"
    address = await set_coordinator_address(pool, user_id, name)
    turns = AsyncMock()
    monkeypatch.setattr(email_channel, "run_email_turn", turns)
    claimed = AsyncMock(return_value=False)
    monkeypatch.setattr("utils.app_event_dedup.was_delivered", claimed)
    monkeypatch.setattr("utils.app_event_dedup.mark_delivered", AsyncMock())
    mail = {"from": email, "subject": "Digest", "dkimPass": True, "headers": {"message-id": "<off@example.com>"}}

    assert await email_channel.set_inbound_email(pool, user_id, False) == {"address": address, "paused": True}
    assert await email_channel.inbound_paused(pool, user_id) is True
    assert await email_channel.receive(pool, name, DOMAIN, mail, "Pause the digest") == "email turned off"
    turns.assert_not_awaited()
    claimed.assert_not_awaited()  # not even a dedup claim: turned back on, a resend of it is read
    # The coordinator is told not to point the owner at its address.
    assert "turned off mail to it" in await reach.reach_note(pool, user_id)

    # Renaming keeps it off; turning it back on keeps the address.
    renamed = f"{name}-x"
    await set_coordinator_address(pool, user_id, renamed)
    assert await email_channel.inbound_paused(pool, user_id) is True
    assert await email_channel.set_inbound_email(pool, user_id, True) == {"address": f"{renamed}@{DOMAIN}", "paused": False}
    assert await email_channel.receive(pool, renamed, DOMAIN, mail, "Pause the digest") == "delivered"
    turns.assert_awaited_once()
    assert "turned off" not in await reach.reach_note(pool, user_id)


async def test_turning_mail_off_leaves_email_to_the_owner_and_other_accounts_alone(owner, monkeypatch):
    pool, user_id, email = owner
    await set_coordinator_address(pool, user_id, f"og-{uuid.uuid4().hex[:6]}")
    other = str(await pool.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, '{}'::jsonb) RETURNING id",
        f"{uuid.uuid4().hex[:8]}@example.com"))
    other_name = f"oh-{uuid.uuid4().hex[:6]}"
    await set_coordinator_address(pool, other, other_name)
    # An account with no address of its own has nothing to switch, and never reaches another's.
    stranger = str(await pool.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, '{}'::jsonb) RETURNING id",
        f"{uuid.uuid4().hex[:8]}@example.com"))
    with pytest.raises(CoordinatorEmailError):
        await email_channel.set_inbound_email(pool, stranger, False)

    await email_channel.set_inbound_email(pool, user_id, False)
    await email_channel.set_inbound_email(pool, user_id, False)  # turning it off twice keeps the first time
    assert await email_channel.inbound_paused(pool, other) is False

    sent = []

    async def send(**kw):
        sent.append(kw)
        return {"message_id": "<out@noclick.app>", "delivery_status": "queued"}
    monkeypatch.setattr("utils.email_sending.send_email", send)
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", AsyncMock())
    monkeypatch.setattr(usage_tracker, "track_usage_event", AsyncMock())
    await pool.execute("INSERT INTO conversations (conversation_id, user_id, events) VALUES ($1, $2::uuid, '[]')",
                       f"coordinator:{user_id}", user_id)
    out = await reach.reach_owner(pool, user_id, "Your digest ran.", channel="email")
    assert out["success"] and sent[0]["to"] == email
    # It never invites a reply into an address that ignores its mail, and the coordinator knows to say so.
    assert "Replies to this address are turned off; answer in the NoClick chat." in sent[0]["text"]
    assert "Reply to this email" not in sent[0]["text"] + sent[0]["html"]
    address = await email_channel.coordinator_address(pool, user_id)
    assert address and await reach.reach_note(pool, user_id) == reach.PROMPTS.reach_note(
        phone_only=False, address=address, paused=True)
    await email_channel.set_inbound_email(pool, user_id, True)
    await reach.reach_owner(pool, user_id, "Your digest ran again.", channel="email")
    assert "Reply to this email to talk to it." in sent[1]["text"]


async def test_email_goes_out_on_one_thread_and_is_billed(owner, monkeypatch):
    pool, user_id, email = owner
    sent, billed = [], []

    async def send(**kw):
        sent.append(kw)
        return {"message_id": f"<out{len(sent)}@noclick.app>", "delivery_status": "queued"}
    monkeypatch.setattr("utils.email_sending.send_email", send)
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", AsyncMock())
    monkeypatch.setattr(usage_tracker, "track_usage_event", AsyncMock(side_effect=lambda e, **k: billed.append(e)))

    out = await email_channel.send_owner_email(pool, user_id, "Your digest failed twice today.")
    assert out["success"] is False and "no email address yet" in out["error"]

    name = f"cy-{uuid.uuid4().hex[:6]}"
    await set_coordinator_address(pool, user_id, name)
    # Sends happen inside a coordinator turn, whose conversation holds the thread.
    await pool.execute("INSERT INTO conversations (conversation_id, user_id, events) VALUES ($1, $2::uuid, '[]')",
                       f"coordinator:{user_id}", user_id)
    first = await email_channel.send_owner_email(pool, user_id, "Your digest failed twice today.\nI paused it.")
    assert first["success"] and sent[0]["to"] == email and sent[0]["from_addr"] == f"{name}@{DOMAIN}"
    assert sent[0]["subject"] == "Your digest failed twice today." and "In-Reply-To" not in sent[0]["extra_headers"]
    await email_channel.send_owner_email(pool, user_id, "It's fixed now.")
    assert sent[1]["subject"] == "Re: Your digest failed twice today."
    assert sent[1]["extra_headers"]["In-Reply-To"] == "<out1@noclick.app>"
    assert [e.usage_subtype for e in billed] == ["email/coordinator", "email/coordinator"]
    thread = await pool.fetchval("SELECT metadata->'email_thread' FROM conversations WHERE conversation_id = $1",
                                 f"coordinator:{user_id}")
    assert thread == {"message_id": "<out2@noclick.app>", "subject": "Your digest failed twice today."}


async def test_a_first_email_is_answered_on_its_own_thread(owner, monkeypatch):
    """No conversation exists before the owner's first email; the turn creates
    it, and the reply still answers the message they sent."""
    pool, user_id, email = owner
    await set_coordinator_address(pool, user_id, f"dee-{uuid.uuid4().hex[:6]}")
    sent = []

    async def send(**kw):
        sent.append(kw)
        return {"message_id": "<reply@noclick.app>", "delivery_status": "queued"}

    async def turn(*, sink, **kw):
        await pool.execute("INSERT INTO conversations (conversation_id, user_id, events) VALUES ($1, $2::uuid, '[]')",
                           f"coordinator:{user_id}", user_id)
        await sink(type("E", (), {"message": "Paused it."})())
    monkeypatch.setattr("utils.email_sending.send_email", send)
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", AsyncMock())
    monkeypatch.setattr(usage_tracker, "track_usage_event", AsyncMock())
    monkeypatch.setattr("coder.coordinator.agent.run_coordinator_turn", turn)
    monkeypatch.setattr("utils.socket_singleton.get_sio", lambda: None)

    await email_channel.run_email_turn(pool, user_id=user_id, owner_email=email, subject="Digest",
                                       text="Pause the digest", message_id="<first@example.com>")
    assert sent[0]["extra_headers"]["In-Reply-To"] == "<first@example.com>" and sent[0]["subject"] == "Re: Digest"


def _persisting_turn(pool, user_id, reply="Yes, I can see your email."):
    """A coordinator turn that saves both events the way run_coordinator_turn composes them (test_coordinator pins
    that): ``extra`` on both, ``user_event`` on the owner's, ``reply_event`` on the reply's."""
    from types import SimpleNamespace

    from repositories.conversation import ConversationRepo

    async def turn(*, sink, text, extra, user_event, reply_event, **kw):
        repo = ConversationRepo(pool)
        for event in ({"role": "user", "message": text, **extra, **user_event},
                      {"role": "assistant", "message": reply, **extra, **reply_event}):
            if event["role"] == "assistant":
                await sink(SimpleNamespace(message=reply))
            await repo.append_chat_event(conversation_id=f"coordinator:{user_id}", user_id=user_id, workflow_id=None,
                                         node_id="__coordinator__", event=event, label=None, model=None)
    return turn


@pytest.fixture
def email_turn(owner, monkeypatch):
    """An owner whose email turn runs for real up to the mail service, which answers as ``send`` says; frames
    to the owner's open chats are kept in ``frames``."""
    pool, user_id, email = owner
    state = {"send": None, "frames": [], "billed": []}

    async def send(**kw):
        return await state["send"](**kw)

    async def broadcast(to, event, **kw):
        state["frames"].append((to, event))
        return {"success": True}
    monkeypatch.setattr("utils.email_sending.send_email", send)
    monkeypatch.setattr("utils.event_relay.broadcast_to_user_safe", broadcast)
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", AsyncMock())
    monkeypatch.setattr(usage_tracker, "track_usage_event", AsyncMock(side_effect=lambda e, **k: state["billed"].append(e)))
    monkeypatch.setattr("coder.coordinator.agent.run_coordinator_turn", _persisting_turn(pool, user_id))
    monkeypatch.setattr("utils.socket_singleton.get_sio", lambda: None)
    return pool, user_id, email, state


async def _events(pool, user_id):
    return await pool.fetchval("SELECT events FROM conversations WHERE conversation_id = $1", f"coordinator:{user_id}")


async def _email_turn(pool, user_id, email, address):
    await email_channel.run_email_turn(pool, user_id=user_id, owner_email=email, subject="Hey",
                                       text="Hey just checking if you can see this", message_id="<in@example.com>",
                                       address=address)


async def test_an_email_turn_records_where_its_reply_went(email_turn):
    pool, user_id, email, state = email_turn
    address = await set_coordinator_address(pool, user_id, f"ed-{uuid.uuid4().hex[:6]}")

    async def queued(**kw):
        return {"message_id": "<reply-1@noclick.app>", "delivery_status": "queued"}
    state["send"] = queued
    await _email_turn(pool, user_id, email, address)

    asked, replied = await _events(pool, user_id)
    assert asked["email"] == {"from": email, "to": address, "subject": "Hey"}
    receipt = dict(replied["email_reply"])
    receipt_id, at = receipt.pop("id"), receipt.pop("at")
    assert receipt_id and at
    assert receipt == {"state": "sent", "to": email, "subject": "Re: Hey", "message_id": "reply-1@noclick.app"}
    (to, frame), = state["frames"]
    assert to == user_id and frame.conversation_id == f"coordinator:{user_id}"
    assert frame.reply.state == "sent" and frame.reply.id == receipt_id and frame.reply.at == at
    assert [e.usage_subtype for e in state["billed"]] == ["email/coordinator"]


async def test_a_sent_reply_stays_sent_when_its_bookkeeping_fails(email_turn, monkeypatch):
    """The mail service took it, so a thread save or billing that fails after never turns it into "couldn't confirm"."""
    pool, user_id, email, state = email_turn
    address = await set_coordinator_address(pool, user_id, f"eq-{uuid.uuid4().hex[:6]}")

    async def queued(**kw):
        return {"message_id": "<reply-8@noclick.app>", "delivery_status": "queued"}
    state["send"] = queued
    monkeypatch.setattr(usage_tracker, "track_usage_event", AsyncMock(side_effect=ConnectionError("db down")))
    await _email_turn(pool, user_id, email, address)
    receipt = (await _events(pool, user_id))[-1]["email_reply"]
    assert receipt["state"] == "sent" and receipt["message_id"] == "reply-8@noclick.app"
    assert [f.reply.state for _, f in state["frames"]] == ["sent"]


async def test_a_reply_delivered_on_the_spot_says_delivered(email_turn):
    pool, user_id, email, state = email_turn
    address = await set_coordinator_address(pool, user_id, f"ee-{uuid.uuid4().hex[:6]}")

    async def delivered(**kw):
        return {"message_id": "<reply-2@noclick.app>", "delivery_status": "delivered"}
    state["send"] = delivered
    await _email_turn(pool, user_id, email, address)
    assert (await _events(pool, user_id))[-1]["email_reply"]["state"] == "delivered"


async def test_a_reply_the_mail_service_refused_records_why_and_bills_nothing(email_turn):
    pool, user_id, email, state = email_turn
    address = await set_coordinator_address(pool, user_id, f"ef-{uuid.uuid4().hex[:6]}")

    async def refused(**kw):
        raise EmailNotSent("Cloudflare email send failed: email.sending.error.rate_limited")
    state["send"] = refused
    await _email_turn(pool, user_id, email, address)

    receipt = (await _events(pool, user_id))[-1]["email_reply"]
    assert receipt["state"] == "failed" and receipt["reason"] == "send_failed"
    assert receipt["error"] == "Cloudflare email send failed: email.sending.error.rate_limited"
    assert receipt["to"] == email and "message_id" not in receipt
    assert state["frames"][0][1].reply.state == "failed" and state["billed"] == []


async def test_a_reply_the_credit_gate_refused_is_recorded_as_not_sent(email_turn, monkeypatch):
    from billing.exceptions import InsufficientBalanceError, insufficient_credits_message

    pool, user_id, email, state = email_turn
    address = await set_coordinator_address(pool, user_id, f"eg-{uuid.uuid4().hex[:6]}")
    sent = AsyncMock()
    state["send"] = sent
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate",
                        AsyncMock(side_effect=InsufficientBalanceError(insufficient_credits_message(0, 0.01))))
    await _email_turn(pool, user_id, email, address)

    receipt = (await _events(pool, user_id))[-1]["email_reply"]
    assert receipt["state"] == "failed" and receipt["reason"] == "credits" and "Insufficient credits" in receipt["error"]
    sent.assert_not_awaited()


async def test_a_send_that_raised_elsewhere_is_unconfirmed_not_failed(email_turn, monkeypatch):
    pool, user_id, email, state = email_turn
    address = await set_coordinator_address(pool, user_id, f"eh-{uuid.uuid4().hex[:6]}")
    monkeypatch.setattr(email_channel, "send_owner_email", AsyncMock(side_effect=ConnectionError("pool closed")))
    await _email_turn(pool, user_id, email, address)
    receipt = (await _events(pool, user_id))[-1]["email_reply"]
    assert receipt["state"] == "unknown" and receipt["reason"] == "error"


async def test_a_sent_reply_is_on_record_before_its_bookkeeping(email_turn, monkeypatch):
    """A delivery event can beat the thread save and the billing: the receipt carries the Message-ID first."""
    pool, user_id, email, state = email_turn
    address = await set_coordinator_address(pool, user_id, f"ek-{uuid.uuid4().hex[:6]}")

    async def queued(**kw):
        return {"message_id": "<reply-5@noclick.app>", "delivery_status": "queued"}
    state["send"] = queued
    seen = []

    async def bill(event, **kw):
        seen.append((await _events(pool, user_id))[-1]["email_reply"])
    monkeypatch.setattr(usage_tracker, "track_usage_event", bill)
    await _email_turn(pool, user_id, email, address)
    (at_billing,) = seen
    assert at_billing["state"] == "sent" and at_billing["message_id"] == "reply-5@noclick.app"


@pytest.mark.parametrize("error", [httpx.ReadTimeout("read timed out"), httpx.RemoteProtocolError("peer closed")])
async def test_a_send_cut_off_after_the_request_went_out_is_unconfirmed(email_turn, error):
    pool, user_id, email, state = email_turn
    address = await set_coordinator_address(pool, user_id, f"el-{uuid.uuid4().hex[:6]}")

    async def cut_off(**kw):
        raise error
    state["send"] = cut_off
    await _email_turn(pool, user_id, email, address)
    receipt = (await _events(pool, user_id))[-1]["email_reply"]
    assert receipt["state"] == "unknown" and receipt["reason"] == "error" and receipt.get("error") is None
    assert state["frames"][0][1].reply.state == "unknown" and state["billed"] == []


async def test_a_send_that_never_connected_is_not_sent(email_turn):
    pool, user_id, email, state = email_turn
    address = await set_coordinator_address(pool, user_id, f"em-{uuid.uuid4().hex[:6]}")

    async def unreachable(**kw):
        raise httpx.ConnectError("connection refused")
    state["send"] = unreachable
    await _email_turn(pool, user_id, email, address)
    receipt = (await _events(pool, user_id))[-1]["email_reply"]
    assert receipt["state"] == "failed" and receipt["reason"] == "send_failed"


async def test_message_owner_and_follow_ups_say_an_unconfirmed_email_may_have_gone(owner, monkeypatch):
    """The coordinator hears not to send it again, and a follow-up's delivery record says it couldn't be confirmed."""
    from types import SimpleNamespace

    from coder.coordinator import wakeups

    pool, user_id, _ = owner
    await set_coordinator_address(pool, user_id, f"en-{uuid.uuid4().hex[:6]}")
    await pool.execute("INSERT INTO conversations (conversation_id, user_id, events) VALUES ($1, $2::uuid, '[]')",
                       f"coordinator:{user_id}", user_id)
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", AsyncMock())
    billed = AsyncMock()
    monkeypatch.setattr(usage_tracker, "track_usage_event", billed)
    monkeypatch.setattr("utils.email_sending.send_email", AsyncMock(side_effect=httpx.ReadTimeout("slow")))

    out = await reach.reach_owner(pool, user_id, "Your digest ran.", channel="email")
    assert out["success"] is False and out["unconfirmed"] is True and out["channel"] == "email"
    assert "Don't send it again" in out["error"]
    billed.assert_not_awaited()

    recorded = []
    monkeypatch.setattr(wakeups, "emit_notification", AsyncMock())
    monkeypatch.setattr(wakeups, "CoordinatorWakeupRepo", lambda pool: SimpleNamespace(
        delivered=AsyncMock(side_effect=lambda event, phone, error: recorded.append(error))))
    await wakeups.deliver_reply(pool, {"id": "w1", "user_id": user_id, "notification": {}, "response": "Done.",
                                       "context": {"channel": "email"}, "send_to_phone": False})
    assert recorded == [wakeups.EMAIL_UNCONFIRMED]


async def test_concurrent_moves_judge_the_receipt_as_it_stands(email_turn):
    """A move that waited on another's lock judges what that one left, not what it read before waiting."""
    from repositories.conversation import ConversationRepo

    pool, user_id, email, state = email_turn
    address = await set_coordinator_address(pool, user_id, f"eo-{uuid.uuid4().hex[:6]}")

    async def queued(**kw):
        return {"message_id": "<reply-6@noclick.app>", "delivery_status": "queued"}
    state["send"] = queued
    await _email_turn(pool, user_id, email, address)
    cid = f"coordinator:{user_id}"

    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        await conn.execute("SELECT 1 FROM conversations WHERE conversation_id = $1 FOR UPDATE", cid)
        await conn.execute("UPDATE conversations SET events = jsonb_set(events, '{1,email_reply,state}', '\"delivered\"') "
                           "WHERE conversation_id = $1", cid)
        deferred = {"type": "cf.email.sending.message.deferred",
                    "payload": {"messageId": "reply-6@noclick.app", "sender": address}}
        late = asyncio.create_task(email_channel.apply_delivery_event(pool, deferred))
        await asyncio.sleep(0.5)
        assert not late.done()  # waiting on the lock
        await tx.commit()
    assert await late == "kept"
    assert (await _events(pool, user_id))[-1]["email_reply"]["state"] == "delivered"

    # An append that held the row while a move waited survives the move.
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        await conn.execute("UPDATE conversations SET events = events || '[{\"role\": \"user\", \"message\": \"later\"}]'::jsonb "
                           "WHERE conversation_id = $1", cid)
        moved = asyncio.create_task(ConversationRepo(pool).update_event_object(
            cid, user_id, field="email_reply", match={"message_id": "reply-6@noclick.app"},
            change=lambda current: {**current, "error": "noted"}))
        await asyncio.sleep(0.5)
        await tx.commit()
    assert (await moved)["error"] == "noted"
    events = await _events(pool, user_id)
    assert [e["message"] for e in events][-1] == "later" and events[1]["email_reply"]["error"] == "noted"


async def test_an_unmatched_event_logs_both_ids_and_a_malformed_one_is_ignored(email_turn, caplog):
    import logging

    pool, user_id, email, state = email_turn
    address = await set_coordinator_address(pool, user_id, f"ep-{uuid.uuid4().hex[:6]}")

    async def queued(**kw):
        return {"message_id": "<reply-7@noclick.app>", "delivery_status": "queued"}
    state["send"] = queued
    await _email_turn(pool, user_id, email, address)
    caplog.set_level(logging.INFO, logger="coder.coordinator.email_channel")
    other = {"type": "cf.email.sending.message.delivered",
             "payload": {"messageId": "0101018f-msg-1", "sender": address, "subject": "Re: Hey"}}
    assert await email_channel.apply_delivery_event(pool, other) == "unmatched"
    line = next(r.getMessage() for r in caplog.records if "coordinator_email_event_unmatched" in r.getMessage())
    assert "event_message_id=0101018f-msg-1" in line and "newest_reply_message_id=reply-7@noclick.app" in line
    assert "Re: Hey" not in line  # a subject is the owner's words, not a log's

    for malformed in ({"type": "cf.email.sending.message.bounced", "payload": "oops"},
                      {"type": "cf.email.sending.message.bounced", "payload": {"messageId": 7, "sender": address}},
                      {"type": ["x"], "payload": {}}):
        assert await email_channel.apply_delivery_event(pool, malformed) == "ignored"
    bounce_text = {"type": "cf.email.sending.message.bounced",
                   "payload": {"messageId": "reply-7@noclick.app", "sender": address, "bounce": "550"}}
    assert await email_channel.apply_delivery_event(pool, bounce_text) == "moved"
    receipt = (await _events(pool, user_id))[-1]["email_reply"]
    assert receipt["state"] == "bounced" and receipt["error"] is None  # a reason that isn't text isn't shown


async def test_delivery_events_move_a_reply_forward_and_never_back(email_turn):
    pool, user_id, email, state = email_turn
    address = await set_coordinator_address(pool, user_id, f"ei-{uuid.uuid4().hex[:6]}")

    async def queued(**kw):
        return {"message_id": "<reply-3@noclick.app>", "delivery_status": "queued"}
    state["send"] = queued
    await _email_turn(pool, user_id, email, address)
    state["frames"].clear()

    def event(kind, message_id="reply-3@noclick.app", sender=address, **payload):
        return {"type": f"cf.email.sending.message.{kind}",
                "payload": {"messageId": message_id, "sender": sender, "recipient": email, **payload}}

    deferred = event("deferred", bounce={"type": "soft", "reason": "451 4.2.0 Try again later"})
    assert await email_channel.apply_delivery_event(pool, deferred) == "moved"
    assert (await _events(pool, user_id))[-1]["email_reply"]["state"] == "delayed"
    assert await email_channel.apply_delivery_event(pool, event("delivered")) == "moved"
    receipt = (await _events(pool, user_id))[-1]["email_reply"]
    assert receipt["state"] == "delivered" and receipt["error"] is None and receipt["subject"] == "Re: Hey"
    assert [f.reply.state for _, f in state["frames"]] == ["delayed", "delivered"]

    # Late, redelivered or contradicting events leave a finished receipt as it is.
    for late in (deferred, event("delivered"), event("bounced", bounce={"type": "hard", "reason": "550 5.1.1"})):
        assert await email_channel.apply_delivery_event(pool, late) == "kept"
    assert (await _events(pool, user_id))[-1]["email_reply"]["state"] == "delivered" and len(state["frames"]) == 2

    # Other mail from the domain, someone else's address, and events that say nothing about delivery.
    assert await email_channel.apply_delivery_event(pool, event("delivered", message_id="<other@noclick.app>")) == "unmatched"
    assert await email_channel.apply_delivery_event(pool, event("delivered", sender="trigger@noclick.app")) == "unmatched"
    assert await email_channel.apply_delivery_event(pool, event("complained")) == "ignored"


async def test_a_bounce_carries_the_receiving_servers_words(email_turn):
    pool, user_id, email, state = email_turn
    address = await set_coordinator_address(pool, user_id, f"ej-{uuid.uuid4().hex[:6]}")

    async def queued(**kw):
        return {"message_id": "<reply-4@noclick.app>", "delivery_status": "queued"}
    state["send"] = queued
    await _email_turn(pool, user_id, email, address)
    rejected = {"type": "cf.email.sending.message.rejected",
                "payload": {"messageId": "<reply-4@noclick.app>", "sender": address.upper(),
                            "rejection": {"reason": "suppressed", "detail": "Recipient is suppressed"}}}
    assert await email_channel.apply_delivery_event(pool, rejected) == "moved"
    receipt = (await _events(pool, user_id))[-1]["email_reply"]
    assert receipt["state"] == "bounced" and receipt["error"] == "Recipient is suppressed"


async def test_auto_is_the_last_used_channel_and_a_named_channel_wins(owner, monkeypatch):
    pool, user_id, _ = owner
    assert await reach.resolve_channel(pool, user_id) == "web"
    await pool.execute(
        "INSERT INTO conversations (conversation_id, user_id, events) VALUES ($1, $2::uuid, $3)",
        f"coordinator:{user_id}", user_id,
        [{"role": "user", "message": "hi", "channel": "web"}, {"role": "assistant", "message": "hello"},
         {"role": "user", "message": "from my phone", "channel": "whatsapp_text"}])
    assert await reach.resolve_channel(pool, user_id) == "whatsapp"
    assert await reach.resolve_channel(pool, user_id, "email") == "email"

    monkeypatch.setattr("utils.task_notifications.emit_notification", AsyncMock())
    out = await reach.reach_owner(pool, user_id, "Heads up", channel="web")
    assert out == {"success": True, "channel": "web"}
    events = await pool.fetchval("SELECT events FROM conversations WHERE conversation_id = $1", f"coordinator:{user_id}")
    assert events[-1]["message"] == "Heads up" and events[-1]["notification"] is True
    # A link the text already carries is not added again.
    link = "https://noclick.com/b/abc"
    await reach.reach_owner(pool, user_id, f"Answer here: {link}", link=link, channel="web")
    await reach.reach_owner(pool, user_id, "Answer here:", link=link, channel="web")
    events = await pool.fetchval("SELECT events FROM conversations WHERE conversation_id = $1", f"coordinator:{user_id}")
    assert [e["message"] for e in events[-2:]] == [f"Answer here: {link}", f"Answer here:\n{link}"]


async def test_the_phone_app_is_the_one_the_owner_last_texted_on(owner, monkeypatch):
    from utils import capabilities

    from repositories.phones import PhoneRepo

    pool, user_id, _ = owner
    assert await reach.last_phone_app(pool, user_id) is None
    assert await reach.phone_text_channel(pool, user_id) == "whatsapp_text"  # WhatsApp until they text otherwise
    phone, phones = f"+1415555{uuid.uuid4().int % 10000:04d}", PhoneRepo(pool)
    await pool.execute("INSERT INTO public.user_phones (user_id, phone_e164, source) VALUES ($1::uuid, $2, 'whatsapp')",
                       user_id, phone)
    await phones.record_app(phone, "whatsapp")  # their first text, on WhatsApp
    assert await reach.last_phone_app(pool, user_id) == "whatsapp"
    await phones.record_app(phone, "imessage")  # then from their iPhone
    await pool.execute(
        "INSERT INTO conversations (conversation_id, user_id, events) VALUES ($1, $2::uuid, $3)",
        f"coordinator:{user_id}", user_id,
        [{"role": "user", "message": "hi", "channel": "whatsapp_text"},
         {"role": "user", "message": "from my iPhone", "channel": "imessage_text"},
         {"role": "user", "message": "back at my desk", "channel": "web"}])
    # The web message after it is not a phone: follow-ups for the phone still go over iMessage.
    assert await reach.last_phone_app(pool, user_id) == "imessage"
    assert await reach.phone_text_channel(pool, user_id) == "imessage_text"
    assert await reach.resolve_channel(pool, user_id) == "web"

    sent = []

    async def send(pool, user_id, text, *, link=None, channel=None):
        sent.append((text, channel))
        return {"success": True}

    monkeypatch.setitem(capabilities._providers, capabilities.OWNER_MESSAGE, send)
    out = await reach.reach_owner(pool, user_id, "Your build finished", channel="imessage")
    assert out == {"success": True, "channel": "imessage"} and sent == [("Your build finished", "imessage")]
