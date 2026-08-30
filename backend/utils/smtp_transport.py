"""One SMTP connection rule for everything that talks to the instance's mail
server — the outbound transport and the settings probe — so a login that the
probe accepted is the login a send will use."""

from __future__ import annotations

import smtplib
import ssl


def smtp_client(host: str, port: int, timeout: float = 15.0) -> smtplib.SMTP:
    """A connected SMTP client — implicit TLS on 465, STARTTLS wherever offered."""
    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
    client = smtplib.SMTP(host, port, timeout=timeout)
    client.ehlo()
    if client.has_extn("starttls"):
        client.starttls(context=ssl.create_default_context())
        client.ehlo()
    return client
