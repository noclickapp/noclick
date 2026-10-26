"""The coordinator's own email address, and email as one of its channels.

The address (``name@<inbound domain>``) is a ``kind='coordinator'`` row in
``email_reservations``, so it can never collide with an inbound-email
trigger's. It exists once the owner opens it in the chat's Connect menu (a
readable name from their own address), the coordinator picks one, or the
owner names it, and can be renamed any time.

Mail to it is a coordinator turn only when it comes from the owner's own
address AND passed DKIM or SPF at the relay: the coordinator acts on the
whole account, so a forged From must never reach it. The owner can turn mail
to it off (``set_inbound_email``): the address stays theirs, and mail to it is
dropped before anything reads it. The reply goes back on
the same thread from the same address, like any email the coordinator sends
the owner (``send_owner_email``), billed as one email send.

An instance with no inbound mail domain gives the coordinator no address, but
still emails the owner from its own sender address (``instance_sender``); they
answer in the chat.

Where an agent answers the owner in the coordinator's place, its address
(``ACCOUNT_AGENT_EMAIL``) is the one these read, claim, rename and switch.
"""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any, Awaitable, Callable, Dict, Optional

import asyncpg

from repositories.users import get_user_email
from utils.email_reservation_manager import (
    build_email_address,
    get_inbound_email_domain,
    validate_local_part,
)

logger = logging.getLogger(__name__)

CHANNEL = "email"
DEDUP_PROVIDER = "coordinator_email"
_SUBJECT_MAX = 150
_BODY_MAX = 20_000
_QUOTE_START = re.compile(r"^(On .+ wrote:|-{2,}\s*Original Message\s*-{2,}|From: .+)$", re.M)


class CoordinatorEmailError(ValueError):
    """Something the owner should hear about in plain words."""


def _agent_email():
    """The email of the agent that answers an owner in the coordinator's place (``ACCOUNT_AGENT_EMAIL``), if any."""
    from utils.capabilities import ACCOUNT_AGENT_EMAIL, capability

    return capability(ACCOUNT_AGENT_EMAIL)


async def _agent_reach(pool, user_id: str, *, ensure: bool = False) -> Optional[Dict[str, Any]]:
    """The address of the agent that answers this owner, else None (the coordinator keeps its own)."""
    agent_email = _agent_email()
    return await agent_email.reach(pool, user_id, ensure=ensure) if agent_email else None


async def coordinator_address(pool, user_id: str) -> Optional[str]:
    if (agent := await _agent_reach(pool, user_id)) is not None:
        return agent["address"]
    row = await pool.fetchrow(
        "SELECT local_part, domain FROM email_reservations WHERE user_id = $1::uuid AND kind = 'coordinator'",
        user_id,
    )
    return build_email_address(row["local_part"], row["domain"]) if row else None


def instance_sender() -> Optional[str]:
    """On an instance with no inbound mail domain (so no address of the coordinator's own) that sends email, the
    address its mail goes out from: the coordinator emails the owner from it, and replies to it never reach it."""
    from utils.email_sending import configured_sender_address, outbound_email_configured

    if get_inbound_email_domain() or not outbound_email_configured():
        return None
    return configured_sender_address() or None


def _default_names(owner_email: Optional[str]) -> list[str]:
    """Readable first choices for a new address, from the owner's own address, then with a short suffix."""
    local = (owner_email or "").split("@")[0].split("+")[0].lower()
    base = re.sub(r"[._-]{2,}", "-", re.sub(r"[^a-z0-9._-]", "", local)).strip("._-")[:40] or "assistant"
    names = [base, f"{base}-assistant", *(f"{base}-{secrets.token_hex(2)}" for _ in range(4))]
    return [name for name in names if validate_local_part(name)[0]]


async def ensure_coordinator_address(pool, user_id: str) -> Optional[str]:
    """The coordinator's address, claiming a readable one the first time it's wanted; None where inbound email is off."""
    if (agent := await _agent_reach(pool, user_id, ensure=True)) is not None:
        return agent["address"]
    existing = await coordinator_address(pool, user_id)
    if existing:
        return existing
    domain = get_inbound_email_domain()
    if not domain:
        return None
    for local_part in _default_names(await get_user_email(pool, user_id)):
        try:
            await pool.execute(
                "INSERT INTO email_reservations (user_id, kind, local_part, domain) VALUES ($1::uuid, 'coordinator', $2, $3)",
                user_id, local_part, domain)
        except asyncpg.UniqueViolationError:
            # The name is taken, or another tab claimed this account's address first.
            claimed = await coordinator_address(pool, user_id)
            if claimed:
                return claimed
            continue
        logger.info("coordinator_email_address user=%s address=%s@%s (default)", user_id, local_part, domain)
        return build_email_address(local_part, domain)
    raise CoordinatorEmailError("Couldn't find a free address; pick a name.")


async def set_coordinator_address(pool, user_id: str, name: str) -> str:
    """Claim (or rename to) ``name@domain`` for this account's coordinator."""
    agent_email = _agent_email()
    if agent_email and (renamed := await agent_email.rename(pool, user_id, name)) is not None:
        return renamed
    domain = get_inbound_email_domain()
    if not domain:
        raise CoordinatorEmailError("Email isn't set up on this instance.")
    local_part = (name or "").strip().lower().split("@")[0]
    valid, error = validate_local_part(local_part)
    if not valid:
        raise CoordinatorEmailError(error)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # A rename keeps whether mail to the address is taken.
                paused = await conn.fetchval(
                    "DELETE FROM email_reservations WHERE user_id = $1::uuid AND kind = 'coordinator' "
                    "RETURNING inbound_paused_at", user_id)
                await conn.execute(
                    "INSERT INTO email_reservations (user_id, kind, local_part, domain, inbound_paused_at) "
                    "VALUES ($1::uuid, 'coordinator', $2, $3, $4)", user_id, local_part, domain, paused)
    except asyncpg.UniqueViolationError:
        raise CoordinatorEmailError(f"{local_part}@{domain} is taken; pick another name.") from None
    logger.info("coordinator_email_address user=%s address=%s@%s", user_id, local_part, domain)
    return build_email_address(local_part, domain)


async def owner_for_address(pool, local_part: str, domain: str) -> Optional[str]:
    value = await pool.fetchval(
        "SELECT user_id FROM email_reservations WHERE domain = $1 AND local_part = $2 AND kind = 'coordinator'",
        domain, local_part,
    )
    return str(value) if value else None


async def email_reach(pool, user_id: str) -> Dict[str, Any]:
    """The coordinator's address as the Connect menu shows it: ``email``, ``email_paused`` (the owner turned its mail
    off; the address stays theirs) and ``email_from_anyone`` (anyone's mail wakes it, as the agent answering in its
    place may take; the coordinator itself answers only the owner's)."""
    if (agent := await _agent_reach(pool, user_id)) is not None:
        return {"email": agent["address"], "email_paused": agent["paused"], "email_from_anyone": agent["anyone"]}
    return {"email": await coordinator_address(pool, user_id), "email_paused": await inbound_paused(pool, user_id),
            "email_from_anyone": False}


async def inbound_paused(pool, user_id: str) -> bool:
    """Whether the owner turned off mail to the coordinator's address."""
    if (agent := await _agent_reach(pool, user_id)) is not None:
        return agent["paused"]
    return bool(await pool.fetchval(
        "SELECT inbound_paused_at IS NOT NULL FROM email_reservations WHERE user_id = $1::uuid AND kind = 'coordinator'",
        user_id))


async def set_inbound_email(pool, user_id: str, on: bool) -> Dict[str, Any]:
    """Take mail to the coordinator's address, or ignore it. Off keeps the address reserved, so turning it back on
    needs no new name; mail the coordinator sends the owner goes out either way."""
    agent_email = _agent_email()
    if agent_email and (switched := await agent_email.take_mail(pool, user_id, on)) is not None:
        return switched
    row = await pool.fetchrow(
        "UPDATE email_reservations SET inbound_paused_at = CASE WHEN $2 THEN NULL "
        "ELSE COALESCE(inbound_paused_at, now()) END "
        "WHERE user_id = $1::uuid AND kind = 'coordinator' RETURNING local_part, domain, inbound_paused_at",
        user_id, on,
    )
    if row is None:
        raise CoordinatorEmailError("There's no email address to turn on or off yet.")
    logger.info("coordinator_email_inbound user=%s on=%s", user_id, on)
    return {"address": build_email_address(row["local_part"], row["domain"]), "paused": row["inbound_paused_at"] is not None}


def _new_text(body: str) -> str:
    """What the owner wrote, without the thread quoted under it."""
    match = _QUOTE_START.search(body)
    text = body[:match.start()] if match else body
    return "\n".join(line for line in text.splitlines() if not line.startswith(">")).strip()


async def _thread(pool, user_id: str) -> Dict[str, Optional[str]]:
    """The email thread with the owner: operational state kept on the
    coordinator conversation, never a preference."""
    thread = await pool.fetchval(
        "SELECT metadata->'email_thread' FROM conversations WHERE conversation_id = $1 AND user_id = $2::uuid",
        f"coordinator:{user_id}", user_id,
    ) or {}
    return {"message_id": thread.get("message_id"), "subject": thread.get("subject")}


async def _remember_thread(pool, user_id: str, message_id: Optional[str], subject: str) -> None:
    await pool.execute(
        """UPDATE conversations SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('email_thread',
             jsonb_build_object('message_id', COALESCE($3, metadata->'email_thread'->>'message_id'), 'subject', $4::text))
           WHERE conversation_id = $1 AND user_id = $2::uuid""",
        f"coordinator:{user_id}", user_id, message_id, subject,
    )


async def send_owner_email(pool, user_id: str, body: str, *, subject: Optional[str] = None,
                           organization_id: Optional[str] = None,
                           on_sent: Optional[Callable[[Dict[str, Any]], Awaitable[Any]]] = None) -> Dict[str, Any]:
    """Email the owner from the coordinator's address, on the running thread
    (replies land back in the coordinator). Credit-gated, one flat charge.
    ``on_sent`` hears the answer the moment the mail service accepts it, before
    the bookkeeping, so the message's id is on record before its first event.
    A send whose outcome isn't known comes back ``unconfirmed``."""
    import httpx

    from billing.exceptions import InsufficientBalanceError, OwnerResolutionError
    from billing.pricing import EMAIL_SEND_PRICE
    from billing.schema import UsageEventData
    from billing.usage_tracker import usage_tracker
    from decimal import Decimal
    from utils.agent_email import render_conversational_email
    from utils.email_sending import EmailNotSent, send_email

    body = (body or "").strip()[:_BODY_MAX]
    if not body:
        return {"success": False, "reason": "empty", "error": "The email is empty."}
    own = await coordinator_address(pool, user_id)
    sender = own or instance_sender()
    if sender is None:
        return {"success": False, "reason": "no_address",
                "error": "You have no email address yet. Pick a readable name with "
                         "set_email_address (or ask the owner for one), then send again."}
    to = await get_user_email(pool, user_id)
    if not to:
        return {"success": False, "reason": "no_owner_email", "error": "The owner has no email address on the account."}
    try:
        await usage_tracker.enforce_credit_gate(user_id, organization_id=organization_id, user_resource=False,
                                                surface="coordinator_email")
    except (InsufficientBalanceError, OwnerResolutionError) as exc:
        return {"success": False, "reason": "credits", "error": str(exc)}

    thread = await _thread(pool, user_id)
    headers: Dict[str, str] = {}
    if thread["message_id"]:
        ref = thread["message_id"] if thread["message_id"].startswith("<") else f"<{thread['message_id']}>"
        headers.update({"In-Reply-To": ref, "References": ref})
        base = thread["subject"] or "NoClick"
        subject = base if base.lower().startswith("re:") else f"Re: {base}"
    else:
        subject = (subject or body.splitlines()[0]).strip()[:_SUBJECT_MAX] or "From your NoClick coordinator"
    # Where a reply would go nowhere (the instance's own address, or mail to the coordinator's turned off), say
    # where to answer instead.
    if own is None:
        footer = "Your NoClick coordinator. Answer in the NoClick chat."
    elif await inbound_paused(pool, user_id):
        footer = "Your NoClick coordinator. Replies to this address are turned off; answer in the NoClick chat."
    else:
        footer = "Your NoClick coordinator. Reply to this email to talk to it."
    try:
        result = await send_email(
            from_addr=sender, from_name="NoClick coordinator", to=to, subject=subject,
            text=f"{body}\n\n--\n{footer}", html=render_conversational_email(body, footer),
            extra_headers=headers, auto_submitted="auto-generated",
        )
    except (EmailNotSent, httpx.ConnectError, httpx.ConnectTimeout) as exc:
        # Refused, or never reached: nothing went out.
        logger.error("coordinator_email_send_failed user=%s: %s", user_id, exc)
        return {"success": False, "reason": "send_failed", "error": str(exc)}
    except Exception as exc:
        # A timeout or a dropped connection once the request was out: the mail service may have accepted it.
        logger.exception("coordinator_email_send_unconfirmed user=%s", user_id)
        return {"success": False, "unconfirmed": True, "reason": "error", "sent_to": to,
                "error": f"The mail service didn't confirm the email ({type(exc).__name__}), so it may have gone "
                         "out. Don't send it again unless the owner asks."}
    sent = {"success": True, "sent_to": to, "from": sender, "subject": subject,
            "sent_at": datetime.now(timezone.utc).isoformat(), "message_id": result.get("message_id"),
            "delivery_status": result.get("delivery_status")}
    if on_sent is not None:
        try:
            await on_sent(sent)
        except Exception:
            logger.exception("coordinator_email_on_sent_failed user=%s", user_id)
    await _remember_thread(pool, user_id, result.get("message_id"), thread["subject"] or subject)
    from utils.email_sending import message_usd

    await usage_tracker.track_usage_event(UsageEventData(
        user_id=user_id, total_cost=Decimal(str(EMAIL_SEND_PRICE)), cost_usd=message_usd(), usage_type="api_usage",
        usage_subtype="email/coordinator", quantity=Decimal(1), unit_type="requests",
        organization_id=organization_id,
    ))
    return sent


async def receive(pool, local_part: str, domain: str, payload: Dict[str, Any], body_text: Optional[str]) -> str:
    """Handle mail to a coordinator address; returns what happened (for the
    relay's log). Anything that isn't the owner's authenticated mail is
    dropped without a turn and without telling the sender why."""
    from utils.app_event_dedup import mark_delivered, was_delivered

    user_id = await owner_for_address(pool, local_part, domain)
    if user_id is None:
        return "unknown address"
    # The address is the account's agent's now: reading it settles one the coordinator left behind.
    if await _agent_reach(pool, user_id) is not None:
        logger.info("coordinator_email_answered_by_agent user=%s", user_id)
        return "an agent answers this account"
    if await inbound_paused(pool, user_id):
        logger.info("coordinator_email_off user=%s", user_id)
        return "email turned off"
    owner = await get_user_email(pool, user_id)
    _, sender = parseaddr(payload.get("from") or "")
    if not owner or sender.lower() != owner.lower():
        logger.warning("coordinator_email_not_owner user=%s sender=%r", user_id, sender)
        return "sender is not the owner"
    if not (payload.get("dkimPass") or payload.get("spfPass")):
        logger.warning("coordinator_email_unauthenticated user=%s", user_id)
        return "sender not authenticated"
    headers = payload.get("headers") or {}
    message_id = headers.get("message-id")
    if message_id:
        if await was_delivered(DEDUP_PROVIDER, message_id):
            return "duplicate"
        await mark_delivered(DEDUP_PROVIDER, message_id)
    text = _new_text(body_text or "")
    if not text:
        return "empty"
    subject = (payload.get("subject") or "").strip()
    await run_email_turn(pool, user_id=user_id, owner_email=owner, subject=subject, text=text, message_id=message_id,
                         address=build_email_address(local_part, domain))
    return "delivered"


# How far a reply's email got. A receipt only moves forward: a late or redelivered event never takes it back.
_RANK = {"sending": 0, "sent": 1, "delayed": 2, "delivered": 3, "bounced": 3, "failed": 3, "unknown": 3}
# What the send API's answer says about the recipient (utils.email_sending.send_email).
_SENT_STATES = {"delivered": "delivered", "bounced": "bounced", "queued": "sent", "accepted": "sent"}
RECEIPT = "email_reply"


def _message_id(value: Optional[str]) -> Optional[str]:
    return (value or "").strip().strip("<>") or None


async def _record_receipt(pool, user_id: str, match: Dict[str, Any], update: Dict[str, Any]) -> Optional[str]:
    """Move the receipt on the reply's own event (found by ``match``) and tell the owner's open chats. Returns
    "moved", "kept" (it was already as far along) or None (no reply carries it)."""
    from repositories.conversation import ConversationRepo
    from utils.event_relay import broadcast_to_user_safe
    from wss.sender.events import CoordinatorEmailReply, CoordinatorEmailReplyEvent

    found = []

    def forward(current: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        found.append(current)
        if _RANK[update["state"]] <= _RANK.get(current.get("state"), 0):
            return None
        return {**current, **update}

    conversation_id = f"coordinator:{user_id}"
    receipt = await ConversationRepo(pool).update_event_object(
        conversation_id, user_id, field=RECEIPT, match=match, change=forward)
    if receipt is None:
        return "kept" if found else None
    await broadcast_to_user_safe(user_id, CoordinatorEmailReplyEvent(
        conversation_id=conversation_id, reply=CoordinatorEmailReply(**receipt)))
    return "moved"


def _outcome(sent: Dict[str, Any]) -> Dict[str, Any]:
    """What a send_owner_email answer records on the receipt."""
    if sent["success"]:
        return {"state": _SENT_STATES.get(sent.get("delivery_status"), "sent"), "subject": sent.get("subject"),
                "at": sent.get("sent_at"), "message_id": _message_id(sent.get("message_id"))}
    if sent.get("unconfirmed"):
        return {"state": "unknown", "reason": "error"}
    # The model-facing words for a missing address aren't the owner's; the gate's and the mail service's are.
    return {"state": "failed", "reason": sent["reason"],
            "error": sent["error"] if sent["reason"] in ("credits", "send_failed") else None}


async def run_email_turn(pool, *, user_id: str, owner_email: str, subject: str, text: str,
                         message_id: Optional[str] = None, address: Optional[str] = None) -> None:
    """One email from the owner as a coordinator turn, its reply emailed back. The reply's event carries a
    receipt (``email_reply``) that says whether the email went out, where, and later whether it arrived."""
    from coder.coordinator.agent import run_coordinator_turn
    from utils.socket_singleton import get_sio

    pieces = []

    async def sink(event) -> None:
        if event.message:
            pieces.append(event.message)

    receipt_id = uuid.uuid4().hex
    turn_text = f"[email, subject: {subject}]\n{text}" if subject else text
    await run_coordinator_turn(
        sio=get_sio(), sid="", user_id=user_id, user_email=owner_email, text=turn_text,
        sink=sink, extra={"channel": CHANNEL},
        user_event={"email": {"from": owner_email, "to": address, "subject": subject or None}},
        reply_event={RECEIPT: {"id": receipt_id, "state": "sending", "to": owner_email}},
    )
    reply = "".join(pieces).strip()
    # After the turn: a first email creates the conversation this is kept on.
    await _remember_thread(pool, user_id, message_id, subject or "NoClick")
    if not reply:
        logger.warning("coordinator_email_turn_silent user=%s", user_id)
        return
    accepted = False

    async def record(sent: Dict[str, Any]) -> None:
        nonlocal accepted
        accepted = accepted or sent["success"]
        if await _record_receipt(pool, user_id, {"id": receipt_id}, _outcome(sent)) is None:
            logger.error("coordinator_email_receipt_missing user=%s receipt=%s", user_id, receipt_id)

    try:
        # A sent reply is recorded the moment the mail service accepts it, so its first event finds it.
        sent = await send_owner_email(pool, user_id, reply, on_sent=record)
    except Exception:
        if accepted:
            # The mail service took it and the receipt says so: only the thread save or billing after it failed.
            logger.exception("coordinator_email_reply_bookkeeping_failed user=%s", user_id)
            return
        # Raised before the mail service answered, so whether it went out isn't known.
        logger.exception("coordinator_email_reply_unconfirmed user=%s", user_id)
        await _record_receipt(pool, user_id, {"id": receipt_id}, {"state": "unknown", "reason": "error"})
        return
    if not sent["success"]:
        logger.error("coordinator_email_reply_failed user=%s: %s", user_id, sent["error"])
        await record(sent)


# Cloudflare Email Sending's lifecycle events (developers.cloudflare.com/email-service/platform/event-subscriptions),
# as the receipt states they move a reply to. A complaint says nothing about delivery.
_EVENT_STATES = {
    "cf.email.sending.message.delivered": "delivered",
    "cf.email.sending.message.deferred": "delayed",
    "cf.email.sending.message.bounced": "bounced",
    "cf.email.sending.message.failed": "bounced",
    "cf.email.sending.message.rejected": "bounced",
}


async def apply_delivery_event(pool, event: Dict[str, Any]) -> str:
    """Move a coordinator reply's receipt on a mail service event about it: the sender address names the account,
    the Message-ID the reply. Returns what happened (for the route's tally)."""
    def obj(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def text(value: Any) -> Optional[str]:
        return value if isinstance(value, str) and value.strip() else None

    state = _EVENT_STATES.get(text(event.get("type")) or "")
    payload = obj(event.get("payload"))
    message_id = _message_id(text(payload.get("messageId")))
    if state is None or message_id is None:
        return "ignored"
    local_part, _, domain = (text(payload.get("sender")) or "").lower().partition("@")
    user_id = await owner_for_address(pool, local_part, domain) if domain else None
    if user_id is None:
        return "unmatched"  # mail some other surface sent from this domain
    reason = text(obj(payload.get("bounce")).get("reason")) or text(obj(payload.get("rejection")).get("detail")) \
        or text(obj(payload.get("failure")).get("reason"))
    update = {"state": state, "error": reason[:300] if reason and state != "delivered" else None}
    outcome = await _record_receipt(pool, user_id, {"message_id": message_id}, update)
    if outcome is None:
        # Beside the newest reply's Message-ID (from the send API), so a mismatch in the two ids' forms shows.
        from repositories.conversation import ConversationRepo

        newest = await ConversationRepo(pool).latest_event_object(f"coordinator:{user_id}", user_id, RECEIPT) or {}
        logger.info("coordinator_email_event_unmatched user=%s type=%s event_message_id=%s newest_reply_message_id=%s",
                    user_id, event.get("type"), message_id, newest.get("message_id"))
        return "unmatched"
    logger.info("coordinator_email_event user=%s type=%s message_id=%s receipt=%s", user_id, event.get("type"),
                message_id, outcome)
    return outcome
