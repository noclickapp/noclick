"""Pins the shared MCP ``serverInfo`` branding (icon / title / website).

The main FastMCP server advertises ``Implementation.icons`` via
``mcp_adapter.branding`` — one source of truth so a
NoClick connector renders the brand consistently once Claude honors the spec. The
icon is a self-contained PNG data URI (no external fetch, works through the OAuth gate).
"""
import base64

import pytest

from mcp_adapter.branding import (
    NOCLICK_TITLE,
    NOCLICK_WEBSITE_URL,
    noclick_icon_dicts,
    noclick_icons,
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png_from_data_uri(src: str) -> bytes:
    assert src.startswith("data:image/png;base64,"), src[:40]
    return base64.b64decode(src.split(",", 1)[1])


def test_icon_is_a_self_contained_png_data_uri():
    dicts = noclick_icon_dicts()
    assert len(dicts) == 1
    d = dicts[0]
    assert d["mimeType"] == "image/png"
    assert d["sizes"] == ["192x192"]
    assert _png_from_data_uri(d["src"])[:8] == _PNG_MAGIC


def test_fastmcp_icon_objects_mirror_the_dicts():
    icons = noclick_icons()
    assert len(icons) == 1
    assert icons[0].src == noclick_icon_dicts()[0]["src"]
    assert icons[0].mimeType == "image/png"


@pytest.mark.asyncio
async def test_main_server_serverinfo_advertises_icon_and_website():
    from fastmcp import FastMCP, Client

    m = FastMCP(name="noclick", version="1.0.0",
                website_url=NOCLICK_WEBSITE_URL, icons=noclick_icons())
    async with Client(m) as c:
        si = c.initialize_result.serverInfo
        assert si.websiteUrl == NOCLICK_WEBSITE_URL
        assert si.icons and _png_from_data_uri(si.icons[0].src)[:8] == _PNG_MAGIC


