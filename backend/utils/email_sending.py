"""Operator-configured outbound email transport.

A self-hosted installation sends through whichever it configured: a Resend
account (``RESEND_API_KEY``) or an SMTP server (``SMTP_HOST`` and friends — the
same variables the auth service's mail uses), always FROM ``FROM_EMAIL``. Both
can be set in the environment or under Settings → Self-hosted. Shared workflow
and reply call sites use this module without depending on NoClick's hosted mail
infrastructure.
"""

from __future__ import annotations

import asyncio
import base64
import os
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from typing import Any, Dict, List, Optional

from utils.smtp_transport import smtp_client

NOT_CONFIGURED = (
    "Outbound email isn't configured for this instance. Add an SMTP server "
    "(or a Resend key) and a sender address under Settings → Self-hosted."
)


def outbound_email_configured() -> bool:
    """Whether a send could go anywhere — the readiness the credential panel shows."""
    return bool(os.getenv("FROM_EMAIL", "").strip()) and bool(
        os.getenv("RESEND_API_KEY", "").strip() or os.getenv("SMTP_HOST", "").strip()
    )


def configured_sender_address() -> str:
    """The bare address in FROM_EMAIL ("Name <a@b>" or "a@b"), or ""."""
    configured = os.getenv("FROM_EMAIL", "").strip()
    return parseaddr(configured)[1] or configured


async def resolve_attachment_entries(
    entries: Optional[List[str]],
) -> Optional[List[Dict[str, Any]]]:
    """Resolve workflow resources into the transport's attachment shape."""
    from nodes.core.media_resolver import resolve_attachments

    return [
        {
            "content": media.base64,
            "filename": media.filename,
            "content_type": media.mime_type,
        }
        for media in await resolve_attachments(entries or [])
    ] or None


async def send_email(
    *,
    from_addr: str,
    to: str,
    subject: str,
    text: str,
    html: Optional[str] = None,
    from_name: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None,
    attachments: Optional[list] = None,
    auto_submitted: str = "auto-generated",
) -> Dict[str, Any]:
    """Send one message through the installation's configured transport."""
    if not outbound_email_configured():
        raise RuntimeError(NOT_CONFIGURED)
    allowed_domain = os.getenv("INBOUND_EMAIL_DOMAIN", "").lower().strip()
    from_domain = from_addr.rsplit("@", 1)[-1].lower() if "@" in from_addr else ""
    if from_addr != configured_sender_address() and from_domain != allowed_domain:
        raise RuntimeError(
            "from_addr must match FROM_EMAIL or the configured INBOUND_EMAIL_DOMAIN"
        )

    headers = {
        "Auto-Submitted": auto_submitted,
        "X-Auto-Response-Suppress": "All",
        **(extra_headers or {}),
    }
    sender = formataddr((from_name, from_addr)) if from_name else from_addr
    if os.getenv("RESEND_API_KEY", "").strip():
        message_id = await _send_via_resend(sender, to, subject, text, html, headers, attachments)
    else:
        message_id = await asyncio.to_thread(_send_via_smtp, sender, to, subject, text, html, headers, attachments)
    return {
        "message_id": message_id,
        "delivery_status": "accepted",
        "to": to,
        "from": from_addr,
    }


async def _send_via_resend(sender, to, subject, text, html, headers, attachments) -> Optional[str]:
    import resend

    resend.api_key = os.getenv("RESEND_API_KEY", "").strip()
    params: Dict[str, Any] = {
        "from": sender,
        "to": [to],
        "subject": subject,
        "text": text,
        "headers": headers,
    }
    if html:
        params["html"] = html
    if attachments:
        params["attachments"] = attachments
    response = await asyncio.to_thread(resend.Emails.send, params)
    return response.get("id") if isinstance(response, dict) else None


def _send_via_smtp(sender, to, subject, text, html, headers, attachments) -> Optional[str]:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    for name, value in headers.items():
        message[name] = value
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    for entry in attachments or []:
        maintype, _, subtype = (entry.get("content_type") or "application/octet-stream").partition("/")
        message.add_attachment(
            base64.b64decode(entry["content"]),
            maintype=maintype,
            subtype=subtype or "octet-stream",
            filename=entry.get("filename") or "attachment",
        )
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587") or 587)
    username = os.getenv("SMTP_USERNAME", "").strip()
    with smtp_client(host, port) as client:
        if username:
            client.login(username, os.getenv("SMTP_PASSWORD", ""))
        client.send_message(message)
    return message["Message-ID"]
