"""Shared NoClick branding for the MCP server protocol metadata.

The icon is a self-contained data URI so clients do not need an external
asset request or permissive CORS policy during initialization.
"""
import base64
import os
from functools import lru_cache

from mcp.types import Icon

NOCLICK_TITLE = "NoClick"
NOCLICK_WEBSITE_URL = "https://www.noclick.com"

_ICON_PATH = os.path.join(os.path.dirname(__file__), "assets", "noclick-icon.png")
_ICON_SIZES = ["192x192"]


@lru_cache(maxsize=1)
def _icon_data_uri() -> str:
    with open(_ICON_PATH, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def noclick_icon_dicts() -> list[dict]:
    """Icon entries as plain dictionaries for protocol responses."""
    return [{"src": _icon_data_uri(), "mimeType": "image/png", "sizes": list(_ICON_SIZES)}]


def noclick_icons() -> list[Icon]:
    """Icon objects — for FastMCP's ``icons=`` constructor arg (main server)."""
    return [Icon(**d) for d in noclick_icon_dicts()]
