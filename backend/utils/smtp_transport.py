"""One SMTP connection rule for everything that sends over SMTP — the
instance's outbound transport and its settings probe, and a mailbox someone
connected (the IMAP/SMTP node) — so a login that a probe accepted is the
login a send will use."""

from __future__ import annotations

import smtplib
import socket
import ssl
from typing import Callable, Optional


class TlsUnavailable(smtplib.SMTPException):
    """The server would take the password unencrypted, so it is never sent."""


def tls_context() -> ssl.SSLContext:
    """The TLS every mail connection verifies its server with (tests trust a local server's certificate here)."""
    return ssl.create_default_context()


class _Dialled:
    """Dials ``address`` (an IP checked by ``utils.ssrf``) in place of resolving the host again, while TLS still
    verifies the host's own name: resolving twice would let a second answer point somewhere else. ``on_socket``
    sees the socket before any byte is exchanged, so a caller's deadline can shut it mid-handshake."""

    def __init__(self, host: str, port: int, *, address: str, on_socket: Optional[Callable] = None, **kwargs):
        self._address, self._on_socket = address, on_socket
        super().__init__(host, port, **kwargs)

    def _get_socket(self, host, port, timeout):
        sock = socket.create_connection((self._address, port), timeout, self.source_address)
        if self._on_socket is not None:
            self._on_socket(sock)
        if isinstance(self, smtplib.SMTP_SSL):
            return self.context.wrap_socket(sock, server_hostname=self._host)
        return sock


class _DialledSMTP(_Dialled, smtplib.SMTP):
    pass


class _DialledSMTPSSL(_Dialled, smtplib.SMTP_SSL):
    pass


def smtp_client(
    host: str,
    port: int,
    timeout: float = 15.0,
    *,
    security: Optional[str] = None,
    address: Optional[str] = None,
    on_socket: Optional[Callable[[socket.socket], None]] = None,
) -> smtplib.SMTP:
    """A connected SMTP client.

    ``security`` None is the instance's own server, which its operator chose:
    implicit TLS on 465, STARTTLS wherever offered. ``"ssl"`` (implicit TLS) and
    ``"starttls"`` are a connected mailbox's, where STARTTLS is required: a
    server that doesn't offer it never receives the password (``TlsUnavailable``).
    ``address`` dials that IP for ``host``, handing the socket to ``on_socket`` first.
    """
    implicit = security == "ssl" or (security is None and port == 465)
    if address is None:
        if implicit:
            return smtplib.SMTP_SSL(host, port, timeout=timeout, context=tls_context())
        client = smtplib.SMTP(host, port, timeout=timeout)
    elif implicit:
        return _DialledSMTPSSL(host, port, address=address, on_socket=on_socket, timeout=timeout,
                               context=tls_context())
    else:
        client = _DialledSMTP(host, port, address=address, on_socket=on_socket, timeout=timeout)
    try:
        client.ehlo()
        if client.has_extn("starttls"):
            client.starttls(context=tls_context())
            client.ehlo()
        elif security == "starttls":
            raise TlsUnavailable(
                f"{host} doesn't offer STARTTLS on port {port}, so the password would cross the network "
                "unencrypted. Use its SSL/TLS port (usually 465)."
            )
    except BaseException:
        client.close()
        raise
    return client

