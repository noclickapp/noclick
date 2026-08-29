"""Public webhook URLs for a self-hosted installation.

The hosted service reaches a workflow's webhook through a wildcard-subdomain
relay, so a delivery lands on `{webhook_id}.<relay domain>` wherever the backend
happens to be running. A self-hosted backend is reachable directly, at one
address its operator already configured, and its own `/webhook/{webhook_id}`
route serves deliveries — so the URL is that origin plus the route, and the
relay's connection management has nothing to manage.

The relay client's functions stay here as no-ops rather than disappearing: they
are called from shared code (server startup, webhook registration, the
reconnect action in the workflow handler), and each one's honest answer in this
edition is "nothing to do, and nothing is wrong".
"""

import os
from typing import Optional

# Three names for one address, in the order they were introduced: the explicit
# webhook base, the local-dev override that predates it, and the API URL — which
# on a single-origin installation is the same host anyway.
_BASE_VARS = ("PUBLIC_WEBHOOK_URL", "WEBHOOK_URL_BASE", "PUBLIC_API_URL")


def get_webhook_base_url() -> str:
    for var in _BASE_VARS:
        value = os.environ.get(var)
        if value:
            return value.rstrip("/")
    return ""


def get_webhook_url(webhook_id: str) -> str:
    base = get_webhook_base_url()
    if not base:
        raise RuntimeError(
            "PUBLIC_WEBHOOK_URL is not configured; set it to the externally "
            "reachable API URL used for webhook deliveries"
        )
    # The base is the backend's origin, as for every other webhook route
    # (Discord app events append /webhook/app/discord to the same value). The
    # delivery route lives under /webhook, and a front door that only proxies
    # that prefix answers a bare /{id} with the app's 404 page — a schedule
    # that reached zero, said "Running", and never ran. A base that already
    # names the prefix is honoured rather than doubled.
    if base.endswith("/webhook"):
        base = base[: -len("/webhook")]
    return f"{base}/webhook/{webhook_id}"


def get_session_id() -> Optional[str]:
    return None


def is_relay_connected() -> bool:
    """True: deliveries arrive at the backend directly, so there is no relay
    connection that could be down. Answering False would make every registration
    path report a working webhook as unreachable."""
    return True


async def register_webhook(webhook_id: str, user_id: Optional[str] = None) -> bool:
    return True


async def unregister_webhook(webhook_id: str) -> bool:
    return True


async def register_user_webhooks(user_id: str) -> int:
    return 0


async def unregister_user_webhooks(user_id: str) -> int:
    return 0


async def start_relay_client(webhook_handler=None) -> Optional[str]:
    return None


async def stop_relay_client() -> None:
    return None


async def reconnect_relay_client() -> bool:
    return True
