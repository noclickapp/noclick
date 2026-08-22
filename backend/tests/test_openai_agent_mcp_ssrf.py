import pytest
import httpx

from coder.openai_agent.mcp import (
    _mcp_http_client_factory,
    call_tool,
    discover_tools,
)
from utils.ssrf import SSRFError


@pytest.mark.asyncio
async def test_mcp_discovery_blocks_private_server_url(monkeypatch):
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)

    with pytest.raises(SSRFError, match="non-public address"):
        await discover_tools({
            "url": "http://127.0.0.1:8123/mcp",
            "transport_type": "shttp",
        })


@pytest.mark.asyncio
async def test_mcp_tool_call_reports_private_server_url(monkeypatch):
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)

    result = await call_tool(
        {"url": "http://169.254.169.254/latest", "transport_type": "shttp"},
        "probe",
        {},
    )

    assert result["success"] is False
    assert "non-public address" in result["error"]


@pytest.mark.asyncio
async def test_mcp_private_server_opt_out_is_explicit(monkeypatch):
    monkeypatch.setenv("HTTP_NODE_ALLOW_PRIVATE_IPS", "true")

    # Prove the guard allows a deliberate local-dev target without opening a
    # real transport: an unsupported transport fails after URL validation.
    with pytest.raises(ValueError, match="Unsupported MCP transport_type"):
        await discover_tools({
            "url": "http://127.0.0.1:8123/mcp",
            "transport_type": "invalid",
        })


@pytest.mark.asyncio
async def test_mcp_transport_revalidates_redirect_hops(monkeypatch):
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)
    client = _mcp_http_client_factory()
    try:
        hook = client.event_hooks["request"][0]
        with pytest.raises(SSRFError, match="non-public address"):
            await hook(httpx.Request("GET", "http://127.0.0.1/internal"))
    finally:
        await client.aclose()
