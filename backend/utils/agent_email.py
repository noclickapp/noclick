"""The agent → owner email channel (email_user platform tool).

When the owner is away, an agent emails them — builder links, credential asks,
questions, failure reports — in a concise informal voice. Replying to the
email talks BACK to the agent: the From/Reply-To address is a per-conversation
capability (`agent-reply-{id}@<configured-domain>`, row in agent_email_replies) that
the inbound relay resolves and fires as an agent turn. The unsubscribe link is
per-(workflow, node): it flips that agent's enable_email_updates config flag
only, mirroring the send-email node's HMAC one-click.

Containment mirrors the other outbound-email surfaces: recipient is ALWAYS the
workflow owner's auth email (never a config field), flat per-send charge
(billing.pricing.EMAIL_SEND_PRICE) behind the owner's credit gate, and a
per-execution cap plus a per-node daily cap. Iteration fan-out normally omits
the ambient tool entirely; the execution cap is the distributed backstop.
"""
import hashlib
import hmac
import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from repositories.users import get_user_email

logger = logging.getLogger(__name__)

AGENT_REPLY_PREFIX = "agent-reply-"
AGENT_EMAIL_EXECUTION_CAP = 1
AGENT_EMAIL_DAILY_CAP = 10

_SUBJECT_MAX = 200
_BODY_MAX = 8000


def _relay_secret() -> str:
    secret = os.getenv("EMAIL_RELAY_SECRET")
    if not secret:
        raise RuntimeError("EMAIL_RELAY_SECRET is not configured")
    return secret


# ── per-node unsubscribe (scoped to the email tool, not the node) ────────────


def mint_agent_updates_disable_sig(workflow_id: str, node_id: str) -> str:
    # Purpose-salted so a send-email-node disable link can't flip this flag.
    msg = f"agent-updates-disable|{workflow_id}|{node_id}"
    return hmac.new(_relay_secret().encode(), msg.encode(), hashlib.sha256).hexdigest()


def verify_agent_updates_disable_sig(workflow_id: str, node_id: str, sig: str) -> bool:
    if not workflow_id or not node_id or not sig:
        return False
    return hmac.compare_digest(mint_agent_updates_disable_sig(workflow_id, node_id), str(sig))


def build_agent_updates_disable_url(workflow_id: str, node_id: str) -> str:
    from utils.email_unsubscribe import DISABLE_LINK_BASE

    query = urlencode({
        "wf": workflow_id, "node": node_id,
        "sig": mint_agent_updates_disable_sig(workflow_id, node_id),
    })
    return f"{DISABLE_LINK_BASE}/email/agent-updates/disable?{query}"


async def disable_agent_email_updates(workflow_id: str, node_id: str) -> Optional[Dict[str, str]]:
    """Flip enable_email_updates='false' on ONE agent node's saved config.
    Returns {workflow_name, node_label} on success, None when the workflow or
    node no longer exists. Other agents (and this agent's other capabilities)
    are untouched — the unsubscribe page says so explicitly."""
    import json

    from utils.database_pool import get_native_pool

    pool = get_native_pool()
    row = await pool.fetchrow(
        "SELECT name, workflow FROM workflows WHERE id = $1 AND deleted_at IS NULL",
        workflow_id,
    )
    if not row:
        return None
    blob = row["workflow"]
    if isinstance(blob, str):
        try:
            blob = json.loads(blob)
        except json.JSONDecodeError:
            return None
    nodes = (blob or {}).get("nodes") or []
    node = next((n for n in nodes if n.get("id") == node_id), None)
    if node is None:
        return None
    node.setdefault("config", {})["enable_email_updates"] = "false"
    # Dict passed raw — the runtime pool's jsonb codec serializes it
    # (json.dumps here double-encodes).
    await pool.execute(
        "UPDATE workflows SET workflow = $1, updated_at = NOW() WHERE id = $2",
        blob, workflow_id,
    )
    label = (node.get("config") or {}).get("label") or node.get("id") or "the agent"
    logger.info(f"[AgentEmail] email updates disabled for {node_id} in {workflow_id}")
    return {"workflow_name": row["name"] or "your workflow", "node_label": label}


# ── reply channel ────────────────────────────────────────────────────────────


async def _get_or_create_reply_row(
    pool, *, user_id: str, workflow_id: str, node_id: str, conversation_id: Optional[str],
) -> Dict[str, Any]:
    """The durable per-(workflow, node, conversation) reply row: id anchors the
    `agent-reply-{id}@domain` address, thread_subject/last_message_id anchor
    the MAIL THREAD (reuse keeps both the address and the thread stable)."""
    select = """
        SELECT id, thread_subject, last_message_id FROM agent_email_replies
        WHERE workflow_id = $1::uuid AND node_id = $2
          AND conversation_id IS NOT DISTINCT FROM $3
        LIMIT 1
    """
    row = await pool.fetchrow(select, workflow_id, node_id, conversation_id)
    if not row:
        import asyncpg

        try:
            row = await pool.fetchrow(
                """
                INSERT INTO agent_email_replies (user_id, workflow_id, node_id, conversation_id)
                VALUES ($1::uuid, $2::uuid, $3, $4)
                RETURNING id, thread_subject, last_message_id
                """,
                user_id, workflow_id, node_id, conversation_id,
            )
        except asyncpg.UniqueViolationError:
            # Concurrent mint for the same scope — adopt the winner's row.
            row = await pool.fetchrow(select, workflow_id, node_id, conversation_id)
    return dict(row)


def _reply_address_for(reply_id) -> str:
    from utils.email_reservation_manager import require_inbound_email_domain

    return f"{AGENT_REPLY_PREFIX}{reply_id.hex}@{require_inbound_email_domain()}"


async def mint_reply_address(
    pool, *, user_id: str, workflow_id: str, node_id: str, conversation_id: Optional[str],
) -> str:
    """A durable per-conversation reply capability: `agent-reply-{id}@domain`."""
    row = await _get_or_create_reply_row(
        pool, user_id=user_id, workflow_id=workflow_id,
        node_id=node_id, conversation_id=conversation_id,
    )
    return _reply_address_for(row["id"])


async def resolve_reply_address(pool, local_part: str) -> Optional[Dict[str, Any]]:
    """The (user, workflow, node, conversation) behind an agent-reply address."""
    raw = local_part[len(AGENT_REPLY_PREFIX):]
    try:
        import uuid as _uuid

        reply_id = _uuid.UUID(raw)
    except ValueError:
        return None
    row = await pool.fetchrow(
        """
        SELECT id, user_id, workflow_id, node_id, conversation_id
        FROM agent_email_replies WHERE id = $1
        """,
        reply_id,
    )
    return dict(row) if row else None


async def fire_agent_email_reply_turn(
    pool, *, user_id: str, workflow_id: str, node_id: str,
    conversation_id: Optional[str], sender: str, subject: str, body: str,
) -> None:
    """Deliver the user's email reply as an agent turn — the email channel's
    inbound half. Message shape mirrors trigger-event delivery."""
    conversation_key = None
    if conversation_id:
        parts = conversation_id.split(":", 3)
        if len(parts) == 4 and parts[0] == "ck":
            conversation_key = parts[3]

    import uuid as _uuid

    from utils.socket_singleton import get_sio
    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
    from wss.receiver.client_events import WorkflowExecuteRequest

    message = (
        f"--- Email reply from the user ({sender}) ---\n"
        f"Subject: {subject}\n\n{body.strip()[:_BODY_MAX]}\n\n"
        "(This arrived BY EMAIL — the user is in their inbox, not the chat. "
        "Answer with the email_user tool so they actually see it — compose "
        "your reply in your own words, never echo their message back; your "
        "email will continue this same thread.)"
    )
    overrides: Dict[str, Any] = {"message": message, "mockedOutput": None}
    if conversation_key:
        overrides["conversation_key"] = conversation_key
    request = WorkflowExecuteRequest(
        request_id=f"email-reply-{_uuid.uuid4().hex[:8]}",
        workflow_id=str(workflow_id),
        start_node_id=node_id,
        trigger_source="agent_email_reply",
        conversation_id=conversation_id,
        config_overrides={node_id: overrides},
    )
    handler = WorkflowExecutionHandler(get_sio())
    await handler.handle_execute(sid="", request=request, caller_user_id=str(user_id))
    logger.info("[AgentEmail] reply turn fired for %s/%s", workflow_id, node_id)


# ── outbound send ────────────────────────────────────────────────────────────


async def _execution_cap_hit(
    workflow_id: str, node_id: str, execution_id: Optional[str],
) -> bool:
    """One send per workflow execution, atomically shared by parallel items.

    Fail open on Redis errors, matching the daily-cap availability policy. The
    counter is reserved before billing/delivery so racing iteration items
    cannot all pass the gate and send before any one of them finishes.
    """
    if not execution_id:
        return False
    try:
        from utils.redis_client import get_shared_redis

        redis = get_shared_redis()
        if redis is None:
            return False
        key = f"nc:agent_email:execution:{workflow_id}:{node_id}:{execution_id}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 26 * 3600)
        return count > AGENT_EMAIL_EXECUTION_CAP
    except Exception:
        logger.warning("[AgentEmail] execution-cap check unavailable — allowing", exc_info=True)
        return False


async def _daily_cap_hit(workflow_id: str, node_id: str) -> bool:
    """Per-node daily counter; fail CLOSED at the cap, OPEN on Redis errors
    (one extra email beats silently eating an away-user escalation)."""
    from datetime import datetime, timezone

    try:
        from utils.redis_client import get_shared_redis

        redis = get_shared_redis()
        if redis is None:
            return False
        key = f"nc:agent_email:{workflow_id}:{node_id}:{datetime.now(timezone.utc):%Y%m%d}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 26 * 3600)
        return count > AGENT_EMAIL_DAILY_CAP
    except Exception:
        logger.warning("[AgentEmail] daily-cap check unavailable — allowing", exc_info=True)
        return False


# Stock labels the FE assigns to unnamed agents — a designation, not a name;
# an inbox sender called "Agent Chat" reads like a bot glitch.
_DEFAULT_AGENT_LABELS = {"agent", "agent chat", "ai agent", "assistant"}


def _render_email(
    *, body: str, workflow_name: str, node_label: str, disable_url: str,
) -> str:
    """Concise, informal, human — the agent's words verbatim as real
    paragraphs with clickable links, a provenance footer, and a visible
    "Unsubscribe" link (the literal word matters: Gmail and spam filters key
    on it, alongside the List-Unsubscribe headers). Deliberately NOT the
    branded notification shell — this should read like a colleague's email.
    The body is ENTIRELY the model's voice (intro included, steered by the
    tool description); only the header fields + footer are platform-owned."""
    import html as _html
    import re as _re

    def _linkify(escaped: str) -> str:
        # Runs on already-escaped text; hrefs keep the &amp; encoding (valid
        # HTML). break-all so long bridge/credential URLs wrap on mobile.
        return _re.sub(
            r"https?://[^\s<]+",
            lambda m: (
                f'<a href="{m.group(0)}" '
                f'style="color:#2563eb;word-break:break-all;">{m.group(0)}</a>'
            ),
            escaped,
        )

    newline = "\n"
    paragraphs = "".join(
        f'<p style="margin:0 0 14px;">'
        f'{_linkify(_html.escape(p.strip())).replace(newline, "<br>")}</p>'
        for p in body.split("\n\n")
        if p.strip()
    )
    return f"""<div style="margin:0 auto;max-width:560px;padding:8px 4px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:15px;line-height:1.65;color:#1a1a1a;">
{paragraphs}
<div style="margin-top:30px;padding-top:14px;border-top:1px solid #e4e4e7;font-size:12px;color:#8b8b93;line-height:1.7;">
Sent by your agent “{_html.escape(node_label)}” in the NoClick workflow “{_html.escape(workflow_name)}”.<br>
Reply directly to this email to talk to the agent.<br>
<a href="{disable_url}" style="color:#8b8b93;text-decoration:underline;">Unsubscribe</a> — stops emails from this agent only; other agents are unaffected.
</div></div>"""


async def send_agent_email(
    pool,
    *,
    user_id: str,
    organization_id: Optional[str],
    workflow_id: str,
    node_id: str,
    conversation_id: Optional[str],
    subject: str,
    body: str,
    execution_id: Optional[str] = None,
) -> Dict[str, Any]:
    """The email_user tool's engine: owner-resolved recipient, credit gate +
    flat charge, execution/daily caps, reply-capable sender, one-click headers."""
    from utils.email_reservation_manager import get_inbound_email_domain

    if not get_inbound_email_domain():
        return {
            "success": False,
            "error": (
                "Agent email is disabled on this installation. The operator must "
                "configure INBOUND_EMAIL_DOMAIN and its inbound mail relay first."
            ),
        }

    subject = (subject or "").strip()[:_SUBJECT_MAX]
    body = (body or "").strip()[:_BODY_MAX]
    if not subject or not body:
        return {"success": False, "error": "subject and body are both required"}

    if await _execution_cap_hit(workflow_id, node_id, execution_id):
        return {
            "success": False,
            "error": (
                "This agent already emailed the owner during this workflow execution. "
                "Do not retry or email once per item; aggregate further updates for a "
                "later execution."
            ),
        }

    if await _daily_cap_hit(workflow_id, node_id):
        return {
            "success": False,
            "error": (
                f"Daily email cap reached for this agent ({AGENT_EMAIL_DAILY_CAP}/day). "
                "Fold further updates into your next reply instead."
            ),
        }

    to_email = await get_user_email(pool, user_id)
    if not to_email:
        return {"success": False, "error": "workflow owner has no email on file"}

    # Credit gate + flat charge — same containment as the send-email node.
    from billing.exceptions import InsufficientBalanceError, OwnerResolutionError
    from billing.pricing import EMAIL_SEND_PRICE
    from billing.usage_tracker import usage_tracker

    try:
        await usage_tracker.enforce_credit_gate(
            user_id, organization_id=organization_id,
            user_resource=False, surface="agent_email",
        )
    except (InsufficientBalanceError, OwnerResolutionError) as exc:
        return {"success": False, "error": str(exc)}

    prov = await pool.fetchrow(
        """
        SELECT name, (
            SELECT n->'config'->>'label'
            FROM jsonb_array_elements(workflow->'nodes') n
            WHERE n->>'id' = $2 LIMIT 1
        ) AS node_label
        FROM workflows WHERE id = $1::uuid
        """,
        workflow_id, node_id,
    )
    workflow_name = (prov and prov["name"]) or "Untitled"
    node_label = (prov and prov["node_label"]) or "Agent"
    row = await _get_or_create_reply_row(
        pool, user_id=user_id, workflow_id=workflow_id,
        node_id=node_id, conversation_id=conversation_id,
    )
    reply_addr = _reply_address_for(row["id"])
    disable_url = build_agent_updates_disable_url(workflow_id, node_id)

    # One conversation = one mail thread. A prior message id means we're mid-
    # thread: reply onto it (Re: subject + In-Reply-To/References) instead of
    # opening a new thread.
    last_message_id = row.get("last_message_id")
    extra_headers = {
        "List-Unsubscribe": f"<{disable_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    if last_message_id:
        ref = last_message_id if last_message_id.startswith("<") else f"<{last_message_id}>"
        extra_headers["In-Reply-To"] = ref
        extra_headers["References"] = ref
        base_subject = row.get("thread_subject") or subject
        if base_subject.lower().startswith("re:"):
            subject = base_subject
        else:
            subject = f"Re: {base_subject}"

    from utils.email_sending import send_email

    # Sender display name: a stock label ("Agent Chat") is not a name — the
    # workflow is the identity the owner recognizes in their inbox.
    if node_label.strip().lower() in _DEFAULT_AGENT_LABELS:
        from_name = f"{workflow_name} — NoClick agent"
    else:
        from_name = f"{node_label} (NoClick agent)"

    result = await send_email(
        from_addr=reply_addr,
        from_name=from_name,
        to=to_email,
        subject=subject,
        text=(
            f"{body}\n\n--\n"
            f"Sent by your agent “{node_label}” in the NoClick workflow "
            f"“{workflow_name}”.\n"
            f"Reply directly to this email to talk to the agent.\n"
            f"Unsubscribe (stops emails from this agent only): {disable_url}"
        ),
        html=_render_email(
            body=body, workflow_name=workflow_name,
            node_label=node_label, disable_url=disable_url,
        ),
        extra_headers=extra_headers,
        # Replies are wanted — don't suppress like pure notifications do.
        auto_submitted="auto-generated",
    )

    # Anchor the thread for follow-ups: our message id becomes the reply
    # target, and the first subject becomes the thread subject.
    try:
        await pool.execute(
            """
            UPDATE agent_email_replies
            SET last_message_id = COALESCE($2, last_message_id),
                thread_subject = COALESCE(thread_subject, $3)
            WHERE id = $1
            """,
            row["id"], result.get("message_id"), subject,
        )
    except Exception:
        logger.warning("[AgentEmail] thread-state update failed", exc_info=True)

    from decimal import Decimal

    from billing.schema import UsageEventData

    await usage_tracker.track_usage_event(UsageEventData(
        user_id=user_id,
        organization_id=organization_id,
        total_cost=EMAIL_SEND_PRICE,
        usage_type="api_usage",
        usage_subtype="email/agent_update",
        quantity=Decimal("1"),
        unit_type="requests",
        user_resource=False,
        metadata={
            "workflow_id": str(workflow_id), "node_id": node_id,
            "execution_id": str(execution_id) if execution_id else None,
            "subject": subject[:100],
            "message_id": result.get("message_id"),
            "delivery_status": result.get("delivery_status"),
        },
    ))

    return {
        "success": True,
        "delivery_status": result.get("delivery_status"),
        "message": (
            (
                "Sent as a reply in the existing email thread with the owner"
                if last_message_id
                else "Email sent — this OPENED a new thread with the owner"
            )
            + f" ({to_email}). They can reply directly — replies arrive as "
            "your next message. Sent emails count against a daily cap, so "
            "batch updates when you can."
        ),
    }
