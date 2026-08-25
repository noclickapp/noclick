"""Install-local endpoint resolution for the community edition.

No fallback in this module points at NoClick-operated infrastructure. Operators
must provide public URLs explicitly; failing closed avoids silently sending a
self-hosted installation's traffic to somebody else's service.
"""

from __future__ import annotations

import os
from typing import NoReturn


class HostedEndpointNotConfigured(RuntimeError):
    """A required public endpoint was not configured by this installation."""


def _configured(name: str, purpose: str) -> str:
    value = os.environ.get(name, "").strip().rstrip("/")
    if value:
        return value
    raise HostedEndpointNotConfigured(
        f"{name} is not set; configure the public {purpose} for this installation."
    )


def _missing(name: str, purpose: str) -> NoReturn:
    raise HostedEndpointNotConfigured(
        f"{name} is not set; configure the public {purpose} for this installation."
    )


def relay_base_url() -> str:
    return _configured("EVENT_RELAY_URL", "event relay URL")


def assets_base_url() -> str:
    return _configured("ASSETS_BASE_URL", "asset base URL")


def mcp_server_url() -> str:
    explicit = os.environ.get("MCP_SERVER_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    base = (
        os.environ.get("MCP_BASE_URL", "").strip()
        or os.environ.get("PUBLIC_API_URL", "").strip()
    ).rstrip("/")
    if not base:
        _missing("MCP_SERVER_URL", "MCP endpoint")
    return f"{base}/mcp"


def frontend_url() -> str:
    return _configured("FRONTEND_URL", "frontend URL")


def api_base_url() -> str:
    return _configured("PUBLIC_API_URL", "API URL")
