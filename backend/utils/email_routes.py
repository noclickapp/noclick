"""
Inbound-email HTTP route for the inbound-email trigger node.

An operator-configured email relay receives mail for ``INBOUND_EMAIL_DOMAIN``,
HMAC-signs a JSON payload (from/to/subject/rawBase64/headers/spf/dkim), and
POSTs it here. This route:
1. Verifies the relay auth (Bearer token + optional HMAC signature)
2. Resolves the recipient local-part to a reserved workflow + trigger node
3. Parses the MIME message, stores attachments in object storage
4. Injects the parsed email as the trigger node's ``_triggerPayload`` and
   dispatches the workflow via the shared ``_execute_workflow_with_relay`` path.

Mirrors utils/webhook_routes.py (the HTTP webhook analog).
"""

import base64
import email as email_lib
import hashlib
import hmac
import json
import logging
import os
import time
from email.policy import default as email_default_policy
from email.utils import parseaddr
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, BackgroundTasks, HTTPException
from pydantic import BaseModel

from utils.database_pool import get_native_pool
from utils.email_reply import mint_reply_token
from utils.email_reservation_manager import (
    get_inbound_email_domain,
)
from utils.hosted_defaults import frontend_url
from utils.resource_store import create_resource_from_bytes
from utils.webhook_routes import _execute_workflow_with_relay
from repositories.users import get_user_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["email"])

# Same bucket every workflow resource lives in (see resource_handler.RESOURCE_BUCKET).
RESOURCE_BUCKET = "workflow-resources"
# Mirror resource_handler.MAX_UPLOAD_SIZE_BYTES (100 MB).
MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024


class EmailInboundResponse(BaseModel):
    success: bool
    message: str
    triggered: bool = False


def _verify_relay_auth(request: Request, body: bytes) -> bool:
    """Verify the email relay Bearer token and optional HMAC signature."""
    secret = os.getenv("EMAIL_RELAY_SECRET")
    if not secret:
        logger.error("[EMAIL] EMAIL_RELAY_SECRET is not configured")
        return False
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    if not hmac.compare_digest(auth[7:], secret):
        return False
    signature = request.headers.get("X-Email-Signature")
    if signature:
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return False
    return True


def _sender_allowed(from_addr: str, allowed_senders: Optional[str]) -> bool:
    """Open by default. If allowed_senders is set, the sender must match an
    exact address or an @domain entry."""
    if not allowed_senders or not allowed_senders.strip():
        return True
    from_addr = (from_addr or "").strip().lower()
    for entry in allowed_senders.split(","):
        e = entry.strip().lower()
        if not e:
            continue
        if e.startswith("@"):
            if from_addr.endswith(e):
                return True
        elif from_addr == e:
            return True
    return False


def _parse_mime(raw: bytes) -> Dict[str, Any]:
    """Extract plain text, HTML, and attachments from a raw MIME message."""
    msg = email_lib.message_from_bytes(raw, policy=email_default_policy)
    text_body: Optional[str] = None
    html_body: Optional[str] = None
    try:
        plain = msg.get_body(preferencelist=("plain",))
        if plain is not None:
            text_body = plain.get_content()
    except Exception:
        text_body = None
    try:
        html = msg.get_body(preferencelist=("html",))
        if html is not None:
            html_body = html.get_content()
    except Exception:
        html_body = None

    attachments: List[Dict[str, Any]] = []
    for part in msg.iter_attachments():
        data = part.get_payload(decode=True) or b""
        if not data:
            continue
        attachments.append({
            "filename": part.get_filename() or "attachment",
            "content_type": part.get_content_type(),
            "data": data,
        })
    return {"text": text_body, "html": html_body, "attachments": attachments}


async def _store_attachments(
    owner_id: Any,
    organization_id: Any,
    workflow_id: Any,
    node_id: str,
    attachments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Store each attachment plus workflow_resources metadata."""
    out: List[Dict[str, Any]] = []
    for att in attachments:
        data: bytes = att["data"]
        if len(data) > MAX_ATTACHMENT_BYTES:
            logger.warning(f"[EMAIL] Skipping attachment {att['filename']} ({len(data)} bytes) over size limit")
            continue
        ref = await create_resource_from_bytes(
            user_id=owner_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            node_id=node_id,
            body=data,
            content_type=att["content_type"],
            filename=att["filename"],
            metadata={"source": "email"},
        )
        record = {
            "resource_id": ref["resource_id"],
            "name": ref["name"],
            "mime_type": ref["mime_type"],
            "size_bytes": ref["size_bytes"],
            "download_url": ref["download_url"],
        }
        # Natural surfacing: the bytes are already in hand, so inline the
        # extracted text for small text-layer documents (budgeted, free CPU
        # path — this route runs on the worker app). Non-extractable or
        # oversize attachments keep their resource ref only.
        record.update(await _inline_extraction_fields(data, ref["mime_type"], ref["name"]))
        out.append(record)
    return out


async def _inline_extraction_fields(data: bytes, mime_type: str, filename: str) -> Dict[str, Any]:
    from utils.content_extraction import (
        DEFAULT_INLINE_CHAR_BUDGET, INLINE_BYTES_THRESHOLD, can_extract, extract_content,
    )

    if not can_extract(mime_type, filename) or len(data) > INLINE_BYTES_THRESHOLD * 4:
        return {}
    try:
        content = await extract_content(
            data, mime_type=mime_type, filename=filename,
            char_budget=DEFAULT_INLINE_CHAR_BUDGET,
        )
        return {"text": content.text, "text_truncated": content.truncated}
    except Exception as e:  # metadata + resource ref still stand
        return {"note": str(e)}


async def get_email_config(local_part: str, domain: str) -> Optional[dict]:
    """Resolve a reserved inbound address to its workflow + trigger node."""
    row = await get_native_pool().fetchrow(
        """
        SELECT er.id, er.user_id, er.workflow_id, er.node_id, er.local_part, er.domain,
               er.is_active, wf.workflow AS workflow_config, wf.organization_id
        FROM email_reservations er
        JOIN workflows wf ON er.workflow_id = wf.id
        WHERE er.domain = $1 AND er.local_part = $2 AND wf.deleted_at IS NULL
        """,
        domain, local_part,
    )
    return dict(row) if row else None


@router.post("/inbound")
async def receive_inbound_email(request: Request, background_tasks: BackgroundTasks) -> EmailInboundResponse:
    """Receive relayed inbound email and trigger the matching workflow."""
    configured_domain = get_inbound_email_domain()
    if not configured_domain:
        raise HTTPException(status_code=503, detail="Inbound email is not configured")

    body = await request.body()
    if not _verify_relay_auth(request, body):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    _, to_addr = parseaddr(payload.get("to") or "")
    if "@" not in to_addr:
        raise HTTPException(status_code=400, detail="Missing recipient address")
    local_part, _, domain = to_addr.lower().partition("@")
    if domain != configured_domain:
        raise HTTPException(status_code=404, detail="No workflow is listening on this address")

    # Agent-reply addresses (email_user tool) are their own routing plane —
    # resolved from agent_email_replies, never from email_reservations.
    from utils.agent_email import AGENT_REPLY_PREFIX

    if local_part.startswith(AGENT_REPLY_PREFIX):
        return await _receive_agent_reply(local_part, payload, background_tasks)

    config = await get_email_config(local_part, domain)
    if not config:
        raise HTTPException(status_code=404, detail="No workflow is listening on this address")
    if not config.get("is_active"):
        raise HTTPException(status_code=410, detail="Email trigger is disabled")

    user_id = str(config["user_id"])
    workflow_id = str(config["workflow_id"])
    node_id = config["node_id"]
    organization_id = config.get("organization_id")

    workflow_config = config.get("workflow_config") or {}
    if isinstance(workflow_config, str):
        try:
            workflow_config = json.loads(workflow_config)
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Invalid workflow configuration")

    nodes = workflow_config.get("nodes", [])
    edges = workflow_config.get("edges", [])
    trigger_node = next((n for n in nodes if n.get("id") == node_id), None)
    if not trigger_node:
        # The reservation points at a node that no longer exists — release the orphan.
        try:
            await get_native_pool().execute(
                "DELETE FROM email_reservations WHERE id = $1", config["id"]
            )
        except Exception as e:
            logger.warning(f"[EMAIL] Failed to clean up orphaned reservation {config['id']}: {e}")
        raise HTTPException(status_code=404, detail="Trigger node not found in workflow")

    node_cfg = trigger_node.setdefault("config", {})

    _, from_addr = parseaddr(payload.get("from") or "")
    if not _sender_allowed(from_addr, node_cfg.get("allowed_senders")):
        logger.info("[EMAIL] Sender did not match the trigger allowlist; skipping")
        return EmailInboundResponse(success=True, message="Sender not allowed", triggered=False)

    # Parse the MIME message and store attachments (best-effort — never block the trigger).
    parsed: Dict[str, Any] = {"text": None, "html": None, "attachments": []}
    raw_b64 = payload.get("rawBase64")
    if raw_b64:
        try:
            parsed = _parse_mime(base64.b64decode(raw_b64))
        except Exception as e:
            logger.error("[EMAIL] MIME parse failed: %s", e, exc_info=True)

    stored_attachments: List[Dict[str, Any]] = []
    if parsed["attachments"]:
        try:
            stored_attachments = await _store_attachments(
                config["user_id"], organization_id, config["workflow_id"], node_id, parsed["attachments"]
            )
        except Exception as e:
            logger.error("[EMAIL] Attachment storage failed: %s", e, exc_info=True)

    email_payload = {
        "type": "email-trigger",
        "status": "received",
        "timestamp": time.time(),
        "from": from_addr or payload.get("from"),
        "to": to_addr,
        "subject": payload.get("subject"),
        "text": parsed.get("text"),
        "html": parsed.get("html"),
        "attachments": stored_attachments,
        "headers": payload.get("headers", {}),
        "spf_pass": payload.get("spfPass"),
        "dkim_pass": payload.get("dkimPass"),
    }
    # Authorizes the agent's locked email__reply tool for THIS email only — a
    # payload fabricated in a saved config can't mint one (utils/email_reply.py).
    email_payload["reply_token"] = mint_reply_token(
        to_addr=to_addr,
        sender=email_payload["from"],
        message_id=(payload.get("headers") or {}).get("message-id"),
        timestamp=email_payload["timestamp"],
    )
    node_cfg["_triggerPayload"] = email_payload

    # Count the delivery only after the trigger node accepts it.
    try:
        await get_native_pool().execute(
            "UPDATE email_reservations SET last_received_at = NOW(), receive_count = receive_count + 1 WHERE id = $1",
            config["id"],
        )
    except Exception as e:
        logger.warning(f"[EMAIL] Failed to update stats for {config['id']}: {e}")

    background_tasks.add_task(
        _execute_workflow_with_relay,
        user_id=user_id,
        workflow_id=workflow_id,
        nodes=nodes,
        edges=edges,
        start_node_id=node_id,
    )
    logger.info("[EMAIL] Accepted inbound message for workflow %s", workflow_id)
    return EmailInboundResponse(success=True, message="Email received and workflow triggered", triggered=True)


async def _receive_agent_reply(
    local_part: str, payload: Dict[str, Any], background_tasks: BackgroundTasks,
) -> EmailInboundResponse:
    """The owner replied to an agent's email_user message: verify the sender IS
    the workflow owner, then fire the reply as an agent turn. Unauthorized or
    unresolvable mail is dropped quietly (success, not triggered) — bounce
    details would let strangers probe reply-address validity."""
    from utils.agent_email import fire_agent_email_reply_turn, resolve_reply_address

    pool = get_native_pool()
    ctx = await resolve_reply_address(pool, local_part)
    if not ctx:
        logger.info(f"[EMAIL] Agent reply to unknown address {local_part!r}; dropping")
        return EmailInboundResponse(success=True, message="Unknown reply address", triggered=False)

    _, from_addr = parseaddr(payload.get("from") or "")
    owner_email = await get_user_email(pool, ctx["user_id"])
    if not owner_email or (from_addr or "").lower() != owner_email.lower():
        logger.warning(
            f"[EMAIL] Agent reply sender {from_addr!r} is not the workflow owner; dropping"
        )
        return EmailInboundResponse(success=True, message="Sender not authorized", triggered=False)

    text = None
    raw_b64 = payload.get("rawBase64")
    if raw_b64:
        try:
            text = _parse_mime(base64.b64decode(raw_b64)).get("text")
        except Exception as e:
            logger.error(f"[EMAIL] Agent-reply MIME parse failed: {e}", exc_info=True)
    text = (text or "").strip()
    if not text:
        return EmailInboundResponse(success=True, message="Empty reply body", triggered=False)

    # The user's Message-ID becomes the thread anchor: the agent's next email
    # replies to THIS message instead of opening a new thread.
    reply_message_id = (payload.get("headers") or {}).get("message-id")
    if reply_message_id:
        try:
            await pool.execute(
                "UPDATE agent_email_replies SET last_message_id = $2 WHERE id = $1",
                ctx["id"], reply_message_id,
            )
        except Exception:
            logger.warning("[EMAIL] Agent-reply thread-anchor update failed", exc_info=True)

    background_tasks.add_task(
        fire_agent_email_reply_turn,
        pool,
        user_id=str(ctx["user_id"]),
        workflow_id=str(ctx["workflow_id"]),
        node_id=ctx["node_id"],
        conversation_id=ctx.get("conversation_id"),
        sender=from_addr,
        subject=payload.get("subject") or "",
        body=text,
    )
    logger.info(
        f"[EMAIL] Agent reply routed to {ctx['workflow_id']}/{ctx['node_id']}"
    )
    return EmailInboundResponse(success=True, message="Reply delivered to agent", triggered=True)


# ---------------------------------------------------------------------------
# One-click disable for notification emails (send-email node footer link +
# RFC 8058 List-Unsubscribe-Post). Signed, login-free, idempotent.
# ---------------------------------------------------------------------------

def _disable_page(message: str, status_code: int = 200) -> "HTMLResponse":
    """Confirmation page for the email-footer disable link — mirrors the
    notification email's look (black logo banner, white card)."""
    from fastapi.responses import HTMLResponse

    app_url = frontend_url()
    return HTMLResponse(
        status_code=status_code,
        content=f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>NoClick</title></head>
<body style="margin:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;">
<div style="max-width:480px;width:100%;margin:20px;background:#ffffff;border:1px solid #e4e4e7;">
  <div style="padding:16px 32px;background:#000000;">
    <a href="{app_url}/dashboard" style="text-decoration:none;">
      <span style="color:#ffffff;font-size:17px;font-weight:600;letter-spacing:-0.3px;vertical-align:middle;">NoClick</span>
    </a>
  </div>
  <div style="padding:28px 32px;">
    <p style="margin:0;color:#18181b;font-size:15px;line-height:1.7;">{message}</p>
  </div>
</div></body></html>"""
    )


async def _handle_disable(wf: str, node: str, sig: str):
    from utils.email_unsubscribe import disable_node_in_workflow, verify_disable_sig

    if not verify_disable_sig(wf, node, sig):
        raise HTTPException(status_code=403, detail="Invalid disable link")
    try:
        return await disable_node_in_workflow(wf, node)
    except Exception as e:
        logger.error(f"[EMAIL] Disable failed for {wf}/{node}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to disable notifications")


# Human-facing GET routes render errors as the same styled page — a clicker
# whose mail client truncated the URL should see words, not raw JSON. The
# POST routes keep JSON: RFC 8058 one-click is machine-called by mail clients.
_FRIENDLY_LINK_ERRORS = {
    403: "This link isn't valid — it may have been truncated by your email "
         "client. Try copying the full link from the email, or manage "
         "notifications from your dashboard settings.",
    500: "Something went wrong on our end — please try the link again in a "
         "moment.",
}


def _friendly_error_page(e: HTTPException) -> "HTMLResponse":
    message = _FRIENDLY_LINK_ERRORS.get(e.status_code, str(e.detail))
    return _disable_page(message, status_code=e.status_code)


@router.get("/disable")
async def disable_email_node(wf: str, node: str, sig: str):
    """Human click from the email footer: disable the node, show confirmation."""
    try:
        workflow_name = await _handle_disable(wf, node, sig)
    except HTTPException as e:
        return _friendly_error_page(e)
    if workflow_name is None:
        return _disable_page(
            "This notification source no longer exists — nothing to disable."
        )
    return _disable_page(
        f"Email notifications from the workflow “{workflow_name}” have been "
        f"disabled. You can re-enable the node anytime from the workflow canvas."
    )


@router.post("/disable")
async def disable_email_node_one_click(wf: str, node: str, sig: str):
    """RFC 8058 one-click unsubscribe (mail clients POST to List-Unsubscribe)."""
    await _handle_disable(wf, node, sig)
    return {"success": True}


async def _handle_agent_updates_disable(wf: str, node: str, sig: str):
    from utils.agent_email import disable_agent_email_updates, verify_agent_updates_disable_sig

    if not verify_agent_updates_disable_sig(wf, node, sig):
        raise HTTPException(status_code=403, detail="Invalid disable link")
    try:
        return await disable_agent_email_updates(wf, node)
    except Exception as e:
        logger.error(f"[EMAIL] Agent-updates disable failed for {wf}/{node}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to disable agent emails")


@router.get("/agent-updates/disable")
async def disable_agent_updates(wf: str, node: str, sig: str):
    """Human click from an agent email's footer: turn off the email_user tool
    for THAT agent node only — the page copy makes the narrow scope explicit."""
    try:
        result = await _handle_agent_updates_disable(wf, node, sig)
    except HTTPException as e:
        return _friendly_error_page(e)
    if result is None:
        return _disable_page(
            "This agent no longer exists — nothing to disable."
        )
    return _disable_page(
        f"Done — the agent “{result['node_label']}” in the workflow "
        f"“{result['workflow_name']}” can no longer email you. This applies to "
        f"that one agent only: other agents (in this workflow or any other) "
        f"keep their own email settings. The agent itself keeps running — it "
        f"just lost its email tool. You can turn it back on anytime via "
        f"“Allow Email Updates” in that agent's settings."
    )


@router.post("/agent-updates/disable")
async def disable_agent_updates_one_click(wf: str, node: str, sig: str):
    """RFC 8058 one-click unsubscribe (mail clients POST to List-Unsubscribe)."""
    await _handle_agent_updates_disable(wf, node, sig)
    return {"success": True}


async def _handle_notification_unsubscribe(uid: str, cat: str, sig: str) -> str:
    from utils.notifications import CATEGORY_LABELS, set_category_enabled, verify_unsubscribe_sig

    if not verify_unsubscribe_sig(uid, cat, sig):
        raise HTTPException(status_code=403, detail="Invalid unsubscribe link")
    try:
        await set_category_enabled(uid, cat, False)
    except Exception as e:
        logger.error(f"[EMAIL] Notification unsubscribe failed for {uid}/{cat}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update preferences")
    return CATEGORY_LABELS[cat]


@router.get("/notifications/unsubscribe")
async def unsubscribe_notifications(uid: str, cat: str, sig: str):
    """Human click from a system-alert footer: disable the category, confirm.
    The same signature authorizes the undo link (it signs uid+cat only)."""
    from urllib.parse import urlencode

    try:
        label = await _handle_notification_unsubscribe(uid, cat, sig)
    except HTTPException as e:
        return _friendly_error_page(e)
    undo = f"/email/notifications/resubscribe?{urlencode({'uid': uid, 'cat': cat, 'sig': sig})}"
    return _disable_page(
        f"You won't receive {label} from NoClick anymore. "
        f'Changed your mind? <a href="{undo}">Turn them back on</a> — or manage all '
        f"notification emails under Settings → Notifications in your dashboard."
    )


@router.get("/notifications/resubscribe")
async def resubscribe_notifications(uid: str, cat: str, sig: str):
    """Undo link on the unsubscribe confirmation page."""
    from utils.notifications import CATEGORY_LABELS, set_category_enabled, verify_unsubscribe_sig

    if not verify_unsubscribe_sig(uid, cat, sig):
        return _friendly_error_page(HTTPException(status_code=403, detail="Invalid link"))
    await set_category_enabled(uid, cat, True)
    return _disable_page(f"Done — you'll keep receiving {CATEGORY_LABELS[cat]}.")


@router.post("/notifications/unsubscribe")
async def unsubscribe_notifications_one_click(uid: str, cat: str, sig: str):
    """RFC 8058 one-click unsubscribe (mail clients POST to List-Unsubscribe)."""
    await _handle_notification_unsubscribe(uid, cat, sig)
    return {"success": True}
