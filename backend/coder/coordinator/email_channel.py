"""The coordinator's own email address, and email as one of its channels.

The address (``name@<inbound domain>``) is a ``kind='coordinator'`` row in
``email_reservations``, so it can never collide with an inbound-email
trigger's. It exists once the coordinator picks a readable name the first
time email is needed (or the owner names it) and can be renamed any time.

Mail to it is a coordinator turn only when it comes from the owner's own
address AND passed DKIM or SPF at the relay: the coordinator acts on the
whole account, so a forged From must never reach it. The reply goes back on
the same thread from the same address, like any email the coordinator sends
the owner (``send_owner_email``), billed as one email send.
"""

from __future__ import annotations

import logging
import re
from email.utils import parseaddr
from typing import Any, Dict, Optional

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


async def coordinator_address(pool, user_id: str) -> Optional[str]:
    row = await pool.fetchrow(
        "SELECT local_part, domain FROM email_reservations WHERE user_id = $1::uuid AND kind = 'coordinator'",
        user_id,
    )
    return build_email_address(row["local_part"], row["domain"]) if row else None


async def set_coordinator_address(pool, user_id: str, name: str) -> str:
    """Claim (or rename to) ``name@domain`` for this account's coordinator."""
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
                await conn.execute(
                    "DELETE FROM email_reservations WHERE user_id = $1::uuid AND kind = 'coordinator'", user_id)
                await conn.execute(
                    "INSERT INTO email_reservations (user_id, kind, local_part, domain) "
                    "VALUES ($1::uuid, 'coordinator', $2, $3)", user_id, local_part, domain)
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
                           organization_id: Optional[str] = None) -> Dict[str, Any]:
    """Email the owner from the coordinator's address, on the running thread
    (replies land back in the coordinator). Credit-gated, one flat charge."""
    from billing.exceptions import InsufficientBalanceError, OwnerResolutionError
    from billing.pricing import EMAIL_SEND_PRICE
    from billing.schema import UsageEventData
    from billing.usage_tracker import usage_tracker
    from decimal import Decimal
    from utils.agent_email import render_conversational_email
    from utils.email_sending import send_via_cloudflare

    body = (body or "").strip()[:_BODY_MAX]
    if not body:
        return {"success": False, "error": "The email is empty."}
    sender = await coordinator_address(pool, user_id)
    if sender is None:
        return {"success": False, "error": "You have no email address yet. Pick a readable name with "
                                           "set_email_address (or ask the owner for one), then send again."}
    to = await get_user_email(pool, user_id)
    if not to:
        return {"success": False, "error": "The owner has no email address on the account."}
    try:
        await usage_tracker.enforce_credit_gate(user_id, organization_id=organization_id, user_resource=False,
                                                surface="coordinator_email")
    except (InsufficientBalanceError, OwnerResolutionError) as exc:
        return {"success": False, "error": str(exc)}

    thread = await _thread(pool, user_id)
    headers: Dict[str, str] = {}
    if thread["message_id"]:
        ref = thread["message_id"] if thread["message_id"].startswith("<") else f"<{thread['message_id']}>"
        headers.update({"In-Reply-To": ref, "References": ref})
        base = thread["subject"] or "NoClick"
        subject = base if base.lower().startswith("re:") else f"Re: {base}"
    else:
        subject = (subject or body.splitlines()[0]).strip()[:_SUBJECT_MAX] or "From your NoClick coordinator"
    footer = "Your NoClick coordinator. Reply to this email to talk to it."
    result = await send_via_cloudflare(
        from_addr=sender, from_name="NoClick coordinator", to=to, subject=subject,
        text=f"{body}\n\n--\n{footer}", html=render_conversational_email(body, footer),
        extra_headers=headers, auto_submitted="auto-generated",
    )
    await _remember_thread(pool, user_id, result.get("message_id"), thread["subject"] or subject)
    await usage_tracker.track_usage_event(UsageEventData(
        user_id=user_id, total_cost=Decimal(str(EMAIL_SEND_PRICE)), usage_type="api_usage",
        usage_subtype="email/coordinator", quantity=Decimal(1), unit_type="requests",
        organization_id=organization_id,
    ))
    return {"success": True, "sent_to": to, "from": sender, "delivery_status": result.get("delivery_status")}


async def receive(pool, local_part: str, domain: str, payload: Dict[str, Any], body_text: Optional[str]) -> str:
    """Handle mail to a coordinator address; returns what happened (for the
    relay's log). Anything that isn't the owner's authenticated mail is
    dropped without a turn and without telling the sender why."""
    from utils.app_event_dedup import mark_delivered, was_delivered

    user_id = await owner_for_address(pool, local_part, domain)
    if user_id is None:
        return "unknown address"
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
    await run_email_turn(pool, user_id=user_id, owner_email=owner, subject=subject, text=text, message_id=message_id)
    return "delivered"


async def run_email_turn(pool, *, user_id: str, owner_email: str, subject: str, text: str,
                         message_id: Optional[str] = None) -> None:
    from coder.coordinator.agent import run_coordinator_turn
    from utils.socket_singleton import get_sio

    pieces = []

    async def sink(event) -> None:
        if event.message:
            pieces.append(event.message)

    turn_text = f"[email, subject: {subject}]\n{text}" if subject else text
    await run_coordinator_turn(
        sio=get_sio(), sid="", user_id=user_id, user_email=owner_email, text=turn_text,
        sink=sink, extra={"channel": CHANNEL},
    )
    reply = "".join(pieces).strip()
    # After the turn: a first email creates the conversation this is kept on.
    await _remember_thread(pool, user_id, message_id, subject or "NoClick")
    if reply:
        sent = await send_owner_email(pool, user_id, reply)
        if not sent["success"]:
            logger.error("coordinator_email_reply_failed user=%s: %s", user_id, sent["error"])
    else:
        logger.warning("coordinator_email_turn_silent user=%s", user_id)
