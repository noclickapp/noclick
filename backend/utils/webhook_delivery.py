"""Where a webhook delivery reaches this backend: its public URL, and the
relay a development backend may sit behind.

A delivery for webhook ``{id}`` arrives one of two ways. Directly: the operator
configured one externally reachable address (PUBLIC_WEBHOOK_URL,
WEBHOOK_URL_BASE or PUBLIC_API_URL) and this backend's ``/webhook/{id}`` route
serves it. Or through a wildcard-subdomain front door: the URL is
``https://{id}.<domain>`` (WEBHOOK_DOMAIN, or the domain the platform registers
at start-up), and a backend that is not that front door's origin — a
developer's machine — runs a relay client that keeps a session open and names
the ids it wants forwarded.

The relay client is a registration (`register_relay_client`). Without one,
every relay function's honest answer is "nothing to do, and nothing is wrong":
deliveries arrive here directly, so there is no connection that could be down.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol

# Three names for one address, in the order they were introduced: the explicit
# webhook base, the local-dev override that predates it, and the API URL — which
# on a single-origin installation is the same host anyway. APP_WEBHOOK_BASE_URL
# is deliberately not among them: it names the app-level receiver (Slack/
# HubSpot/Discord events for the whole app), and letting it stand in for the
# per-workflow base would rewrite every minted webhook URL the moment it is set.
_BASE_VARS = ("PUBLIC_WEBHOOK_URL", "WEBHOOK_URL_BASE", "PUBLIC_API_URL")


class RelayClient(Protocol):
    def is_connected(self) -> bool: ...
    def session_id(self) -> Optional[str]: ...
    async def register(self, webhook_id: str, user_id: Optional[str] = None) -> bool: ...
    async def unregister(self, webhook_id: str) -> bool: ...
    async def register_user(self, user_id: str) -> int: ...
    async def unregister_user(self, user_id: str) -> int: ...
    async def reconnect(self) -> bool: ...


_wildcard_domain: Optional[str] = None
_relay: Optional[RelayClient] = None


def get_webhook_base_url() -> str:
    for var in _BASE_VARS:
        value = os.environ.get(var)
        if value:
            return value.rstrip("/")
    return ""


def set_wildcard_webhook_domain(domain: Optional[str]) -> None:
    """The domain a wildcard front door serves ``{id}.<domain>`` on. A
    configured WEBHOOK_DOMAIN still wins over it."""
    global _wildcard_domain
    _wildcard_domain = domain


def get_webhook_url(webhook_id: str) -> str:
    base = get_webhook_base_url()
    if base:
        # The base is the backend's origin, as for every other webhook route
        # (app events append /webhook/app/<provider> to the same value). The
        # delivery route lives under /webhook, and a front door that only
        # proxies that prefix answers a bare /{id} with the app's 404 page — a
        # schedule that reached zero, said "Running", and never ran. A base that
        # already names the prefix is honoured rather than doubled.
        if base.endswith("/webhook"):
            base = base[: -len("/webhook")]
        return f"{base}/webhook/{webhook_id}"
    domain = os.environ.get("WEBHOOK_DOMAIN") or _wildcard_domain
    if domain:
        return f"https://{webhook_id}.{domain}"
    raise RuntimeError(
        "PUBLIC_WEBHOOK_URL is not configured; set it to the externally "
        "reachable API URL used for webhook deliveries"
    )


def register_relay_client(client: RelayClient) -> None:
    """Install the relay client this backend registers its webhooks with."""
    global _relay
    _relay = client


def relay_in_use() -> bool:
    """True when deliveries reach this backend through a relay it must
    register with, rather than directly."""
    return _relay is not None


def get_session_id() -> Optional[str]:
    return _relay.session_id() if _relay else None


def is_relay_connected() -> bool:
    """Whether deliveries can reach this backend right now. With no relay to
    be down, True: answering False would make every registration path report
    a working webhook as unreachable."""
    return _relay.is_connected() if _relay else True


async def register_webhook(webhook_id: str, user_id: Optional[str] = None) -> bool:
    return await _relay.register(webhook_id, user_id) if _relay else True


async def unregister_webhook(webhook_id: str) -> bool:
    return await _relay.unregister(webhook_id) if _relay else True


async def register_user_webhooks(user_id: str) -> int:
    return await _relay.register_user(user_id) if _relay else 0


async def unregister_user_webhooks(user_id: str) -> int:
    return await _relay.unregister_user(user_id) if _relay else 0


async def reconnect_relay_client() -> bool:
    return await _relay.reconnect() if _relay else True


def clear() -> None:
    """Reset registration state (tests)."""
    global _relay, _wildcard_domain
    _relay = None
    _wildcard_domain = None
