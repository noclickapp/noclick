"""Outbound email: one seam, ``send_email``.

Every outbound surface sends through it: the agent's locked ``email__reply``
tool (utils/email_reply.py), the send-email node, agent updates
(utils/agent_email.py) and the coordinator's own email. Every message carries
RFC 3834 loop-suppression headers so well-behaved auto-responders don't
answer workflow mail back into a trigger.

By default a message goes out the way the installation configured: a Resend
account (``RESEND_API_KEY``) or an SMTP server (``SMTP_HOST`` and friends, the
same variables the auth service's mail uses), always FROM ``FROM_EMAIL`` or the
inbound email domain. Both can be set in the environment or under Settings →
Self-hosted. A platform with a transport of its own registers it with
``register_email_transport``.
"""

from __future__ import annotations

import asyncio
import base64
import os
import smtplib
import socket
from decimal import Decimal
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from typing import Any, Dict, List, Optional, Protocol

from utils.smtp_transport import smtp_client

NOT_CONFIGURED = (
    "Outbound email isn't configured for this instance. Add an SMTP server "
    "(or a Resend key) and a sender address under Settings → Self-hosted."
)


class EmailNotSent(RuntimeError):
    """The transport refused the message (an error response, or nothing configured to send with): it was not sent.
    Any other exception from a send, a timeout above all, leaves open whether it went."""


class EmailTransport(Protocol):
    # What one message costs its vendor, recorded on each send's charge (None: no rate to name).
    message_usd: Optional[Decimal]

    async def send(
        self, *, from_addr: str, to: str, subject: str, text: str, html: Optional[str],
        from_name: Optional[str], headers: Dict[str, str], attachments: Optional[list],
    ) -> Dict[str, Any]:
        """Send one message; ``{message_id, delivery_status, to, from}``."""


def outbound_email_configured() -> bool:
    """Whether a send could go anywhere — the readiness the credential panel shows."""
    return bool(os.getenv("FROM_EMAIL", "").strip()) and bool(
        os.getenv("RESEND_API_KEY", "").strip() or os.getenv("SMTP_HOST", "").strip()
    )


def configured_sender_address() -> str:
    """The bare address in FROM_EMAIL ("Name <a@b>" or "a@b"), or ""."""
    configured = os.getenv("FROM_EMAIL", "").strip()
    return parseaddr(configured)[1] or configured


class ConfiguredTransport:
    """The installation's own Resend account or SMTP server, which bill its
    operator directly: this instance has no rate to name."""

    message_usd: Optional[Decimal] = None

    async def send(self, *, from_addr, to, subject, text, html, from_name, headers, attachments) -> Dict[str, Any]:
        if not outbound_email_configured():
            raise EmailNotSent(NOT_CONFIGURED)
        allowed_domain = os.getenv("INBOUND_EMAIL_DOMAIN", "").lower().strip()
        from_domain = from_addr.rsplit("@", 1)[-1].lower() if "@" in from_addr else ""
        if from_addr != configured_sender_address() and from_domain != allowed_domain:
            raise EmailNotSent("from_addr must match FROM_EMAIL or the configured INBOUND_EMAIL_DOMAIN")
        sender = formataddr((from_name, from_addr)) if from_name else from_addr
        if os.getenv("RESEND_API_KEY", "").strip():
            message_id = await _send_via_resend(sender, to, subject, text, html, headers, attachments)
        else:
            message_id = await asyncio.to_thread(_send_via_smtp, sender, to, subject, text, html, headers, attachments)
        return {"message_id": message_id, "delivery_status": "accepted", "to": to, "from": from_addr}


_transport: EmailTransport = ConfiguredTransport()


def register_email_transport(transport: EmailTransport) -> None:
    """Send every message through ``transport`` instead of the configured one."""
    global _transport
    _transport = transport


def message_usd() -> Optional[Decimal]:
    """What one message costs the transport's vendor."""
    return _transport.message_usd


async def resolve_attachment_entries(
    entries: Optional[List[str]],
) -> Optional[List[Dict[str, Any]]]:
    """Resolve workflow resources into ``{content (base64), filename, content_type}``
    entries, which every transport takes. Caps (10MB per file, 20MB per send) are
    enforced by the shared resolver, which raises ValueError rather than skipping."""
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
    """Send one message through the registered transport. Raises ``EmailNotSent``
    when it was refused; returns ``{message_id, delivery_status, to, from}``, where
    delivery_status is delivered / queued / bounced / accepted."""
    headers = {
        "Auto-Submitted": auto_submitted,
        "X-Auto-Response-Suppress": "All",
        **(extra_headers or {}),
    }
    return await _transport.send(
        from_addr=from_addr, to=to, subject=subject, text=text, html=html, from_name=from_name,
        headers=headers, attachments=attachments,
    )


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
    try:
        response = await asyncio.to_thread(resend.Emails.send, params)
    except resend.exceptions.ResendError as exc:
        # Resend answered with a 4xx: it refused the message. Anything else (no answer,
        # one the SDK couldn't read, a 5xx) leaves open whether it went.
        code = str(exc.code)
        if exc.error_type != "HttpClientError" and code.isdigit() and 400 <= int(code) < 500:
            raise EmailNotSent(f"Resend refused the message: {exc.message}") from exc
        raise
    return response.get("id") if isinstance(response, dict) else None


# What an SMTP server says when it refuses outright: nothing was sent. A dropped
# connection or a timeout mid-send stays an open question and is raised as it is.
_SMTP_REFUSALS = (
    smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError,
    smtplib.SMTPAuthenticationError, smtplib.SMTPHeloError, smtplib.SMTPConnectError,
    smtplib.SMTPNotSupportedError, ConnectionRefusedError, socket.gaierror,
)


def _smtp_refusal(host: str, exc: BaseException) -> str:
    """The server's own words for a refusal."""
    if isinstance(exc, (ConnectionRefusedError, socket.gaierror)):
        return f"Could not reach {host}: {exc.strerror or exc}"
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        replies = exc.recipients.values()
    elif isinstance(exc, smtplib.SMTPResponseException):
        replies = [(exc.smtp_code, exc.smtp_error)]
    else:
        return f"{host} refused the message: {exc}"
    words = "; ".join(
        f"{code} {text.decode(errors='replace') if isinstance(text, bytes) else text}".strip() for code, text in replies
    )
    return f"{host} refused the message: {words}"


def _send_via_smtp(sender, to, subject, text, html, headers, attachments) -> Optional[str]:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    # Ours to set over SMTP, and what a reply's In-Reply-To names to keep the thread.
    message["Message-ID"] = make_msgid(domain=parseaddr(sender)[1].rpartition("@")[2] or None)
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
    try:
        with smtp_client(host, port) as client:
            if username:
                client.login(username, os.getenv("SMTP_PASSWORD", ""))
            client.send_message(message)
    except _SMTP_REFUSALS as exc:
        raise EmailNotSent(_smtp_refusal(host, exc)) from exc
    return message["Message-ID"]
