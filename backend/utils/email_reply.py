"""
Outbound reply path for the inbound-email trigger (the agent's ``email__reply``
tool — see nodes/agent/email_reply.py for the tool glue).

Containment model: an agent may ONLY reply to the email that started the run.
The recipient and threading context are derived server-side from the fired
trigger's payload and authenticated by an HMAC reply token minted by the
inbound route (utils/email_routes.py) at receipt. A payload fabricated in a
saved workflow config (or replayed after the TTL) fails verification, so the
reply capability cannot be repurposed into an arbitrary-recipient send.

Replies go out FROM the workflow's reserved address over the shared
operator-configured email transport (utils/email_sending.py).
"""

import hashlib
import hmac
import os
import time
from email.utils import parseaddr
from typing import Any, Dict, Optional

from utils.email_reservation_manager import get_inbound_email_domain

# A reply only makes sense in the run the email started; the TTL just bounds
# replay of a captured genuine payload (long agent runs included).
REPLY_TOKEN_TTL_SECONDS = 48 * 3600


def _relay_secret() -> str:
    secret = os.getenv("EMAIL_RELAY_SECRET")
    if not secret:
        raise RuntimeError("EMAIL_RELAY_SECRET is not configured")
    return secret


def mint_reply_token(
    *, to_addr: str, sender: str, message_id: Optional[str], timestamp: float
) -> str:
    """HMAC over the reply-defining fields of a genuinely received email."""
    msg = f"{(to_addr or '').lower()}|{(sender or '').lower()}|{message_id or ''}|{int(timestamp)}"
    return hmac.new(_relay_secret().encode(), msg.encode(), hashlib.sha256).hexdigest()


def verify_reply_token(
    token: Any, *, to_addr: str, sender: str, message_id: Optional[str], timestamp: Any
) -> bool:
    """True only for an untampered, unexpired token over the same fields."""
    if not token or not timestamp:
        return False
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return False
    if time.time() - ts > REPLY_TOKEN_TTL_SECONDS:
        return False
    expected = mint_reply_token(
        to_addr=to_addr, sender=sender, message_id=message_id, timestamp=ts
    )
    return hmac.compare_digest(expected, str(token))


def build_reply_context(output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Locked reply context from a fired email-trigger output.

    Returns None when the output can't anchor a verified reply (no parseable
    sender, no reserved address, or no reply token) — the tool is then simply
    not offered to the agent.
    """
    _, sender = parseaddr(str(output.get("from") or ""))
    _, reserved = parseaddr(str(output.get("to") or ""))
    token = output.get("reply_token")
    timestamp = output.get("timestamp")
    if "@" not in sender or "@" not in reserved or not token or not timestamp:
        return None
    headers = output.get("headers") or {}
    if not isinstance(headers, dict):
        headers = {}
    return {
        "to": sender,
        "from_addr": reserved,
        "subject": output.get("subject"),
        # Relay headers are lowercased by the Email Worker.
        "message_id": headers.get("message-id"),
        "references": headers.get("references"),
        "auto_submitted": str(headers.get("auto-submitted") or "").lower(),
        "precedence": str(headers.get("precedence") or "").lower(),
        "reply_token": token,
        "timestamp": timestamp,
    }


def reply_refusal(context: Dict[str, Any]) -> Optional[str]:
    """Why this email must not be replied to, or None when a reply is allowed."""
    if not verify_reply_token(
        context.get("reply_token"),
        to_addr=context.get("from_addr", ""),
        sender=context.get("to", ""),
        message_id=context.get("message_id"),
        timestamp=context.get("timestamp"),
    ):
        return (
            "this run does not carry a valid reply authorization — replies are "
            "only possible in runs started by a real inbound email (token "
            "missing, tampered, or expired)"
        )
    # Replying to another reserved address would let two workflows trigger
    # each other in a loop; reserved addresses aren't real mailboxes anyway.
    inbound_domain = get_inbound_email_domain()
    if inbound_domain and context["to"].lower().endswith(f"@{inbound_domain}"):
        return (
            f"the sender is a {inbound_domain} trigger address; replying could "
            "create a workflow loop"
        )
    # RFC 3834: never auto-reply to automated mail (vacation responders,
    # notification streams) — processing it is fine, answering it loops.
    if context["auto_submitted"] not in ("", "no"):
        return "the email is marked auto-submitted (automated sender); replying could create a mail loop"
    if context["precedence"] in ("bulk", "list", "junk"):
        return f"the email has Precedence: {context['precedence']} (bulk/list mail); replying could create a mail loop"
    return None


def build_reply_subject(original: Optional[str], override: Optional[str]) -> str:
    if override and override.strip():
        return override.strip()
    base = (original or "").strip()
    if not base:
        return "Re: your email"
    return base if base.lower().startswith("re:") else f"Re: {base}"


async def send_email_reply(
    context: Dict[str, Any],
    body: str,
    subject: Optional[str] = None,
    attachment_resource_ids: Optional[list] = None,
) -> Dict[str, Any]:
    """Send the locked reply via the shared configured email transport. Caller is
    responsible for guards (reply_refusal) and billing."""
    from utils.email_body import prepare_email_body
    from utils.email_sending import resolve_attachment_entries, send_email

    extra_headers: Dict[str, str] = {}
    message_id = context.get("message_id")
    if message_id:
        extra_headers["In-Reply-To"] = message_id
        references = context.get("references")
        extra_headers["References"] = (
            f"{references} {message_id}" if references else message_id
        )
    # Markdown/HTML autodetect; replies stay unbranded (plain wrapper) so they
    # read like personal correspondence.
    body_html, body_text = prepare_email_body(body)
    html = (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,'
        "'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;"
        f'font-size:14px;line-height:1.6;color:#18181b;">{body_html}</div>'
    )
    return await send_email(
        from_addr=context["from_addr"],
        to=context["to"],
        subject=build_reply_subject(context.get("subject"), subject),
        text=body_text,
        html=html,
        extra_headers=extra_headers,
        attachments=await resolve_attachment_entries(attachment_resource_ids),
        # RFC 3834 value for replies specifically.
        auto_submitted="auto-replied",
    )
