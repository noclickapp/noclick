"""Operator-configured outbound email transport.

No request is made unless ``RESEND_API_KEY`` and ``FROM_EMAIL`` are supplied by
the installation. Shared workflow and reply call sites use this module without
depending on NoClick's hosted mail infrastructure.
"""

from __future__ import annotations

import asyncio
import os
from email.utils import parseaddr
from typing import Any, Dict, List, Optional


async def resolve_attachment_entries(
    entries: Optional[List[str]],
) -> Optional[List[Dict[str, Any]]]:
    """Resolve workflow resources into the configured provider's attachment shape."""
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
    """Send one message through the operator's Resend account."""
    import resend

    api_key = os.getenv("RESEND_API_KEY")
    configured_sender = os.getenv("FROM_EMAIL")
    if not api_key or not configured_sender:
        raise RuntimeError("RESEND_API_KEY and FROM_EMAIL are required for outbound email")
    configured_address = parseaddr(configured_sender)[1] or configured_sender
    allowed_domain = os.getenv("INBOUND_EMAIL_DOMAIN", "").lower().strip()
    from_domain = from_addr.rsplit("@", 1)[-1].lower() if "@" in from_addr else ""
    if from_addr != configured_address and from_domain != allowed_domain:
        raise RuntimeError(
            "from_addr must match FROM_EMAIL or the configured INBOUND_EMAIL_DOMAIN"
        )

    resend.api_key = api_key
    headers = {
        "Auto-Submitted": auto_submitted,
        "X-Auto-Response-Suppress": "All",
        **(extra_headers or {}),
    }
    sender = f"{from_name} <{from_addr}>" if from_name else from_addr
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
    message_id = response.get("id") if isinstance(response, dict) else None
    return {
        "message_id": message_id,
        "delivery_status": "accepted",
        "to": to,
        "from": from_addr,
    }
