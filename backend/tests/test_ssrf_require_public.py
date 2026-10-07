"""Prepared strict-public request-hook, DNS and pinned-dial regressions.

Every address, HTTP response and backend stream is synthetic. No socket or DNS
access occurs in these fixtures; a root-authorized offline lane must execute them.
"""
import asyncio
import socket
from contextvars import ContextVar
from unittest.mock import AsyncMock

import httpx
import pytest

from utils import ssrf


@pytest.fixture(autouse=True)
def legacy_override(monkeypatch):
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: True)


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.8", "169.254.169.254", "::1", "fc00::42", "fe80::42", "::ffff:127.0.0.1"])
async def test_strict_public_hook_blocks_literals_despite_legacy_override(address):
    calls = []
    url = "https://" + ("[" + address + "]" if ":" in address else address) + "/api/articles"
    async with ssrf.guarded_async_client(require_public=True, transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))) as client:
        with pytest.raises(ssrf.SSRFError):
            await client.get(url)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("addresses", [["8.8.8.8", "10.0.0.1"], ["2606:4700:4700::1111", "::1"], [], ["169.254.169.254"]])
async def test_actual_resolver_rejects_any_nonpublic_or_empty_answer_before_mock_transport(monkeypatch, addresses):
    calls = []
    lookup = AsyncMock(return_value=[(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443, 0, 0) if ":" in ip else (ip, 443)) for ip in addresses])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    async with ssrf.guarded_async_client(require_public=True, transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))) as client:
        with pytest.raises(ssrf.SSRFError):
            await client.get("https://cms.example.test/api/articles")
    lookup.assert_awaited_once_with("cms.example.test", 443, type=socket.SOCK_STREAM)
    assert calls == []


@pytest.mark.asyncio
async def test_strict_actual_resolver_failure_never_falls_back_to_hostname_dial(monkeypatch):
    lookup = AsyncMock(side_effect=OSError("Synthetic DNS unavailable"))
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    backend = AsyncMock()
    with pytest.raises(ssrf.SSRFError):
        await ssrf._PinnedNetworkBackend(require_public=True, backend=backend).connect_tcp("cms.example.test", 443)
    backend.connect_tcp.assert_not_awaited()


@pytest.mark.asyncio
async def test_actual_request_hook_blocks_redirect_to_private_target_and_preserves_extra_hook(monkeypatch):
    lookup = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    calls, hooks = [], []
    async def extra(request): hooks.append(str(request.url))
    def response(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://[::1]/private"})
    async with ssrf.guarded_async_client(require_public=True, follow_redirects=True, event_hooks={"request": [extra]}, transport=httpx.MockTransport(response)) as client:
        with pytest.raises(ssrf.SSRFError):
            await client.get("https://cms.example.test/api/articles")
    assert len(calls) == len(hooks) == 1


@pytest.mark.asyncio
async def test_exact_url_trust_cannot_bypass_strict_public_boundary():
    url = "https://127.0.0.1/private"
    async with ssrf.guarded_async_client(require_public=True, trusted_exact_urls=[url], transport=httpx.MockTransport(lambda request: pytest.fail("No transport allowed"))) as client:
        with pytest.raises(ssrf.SSRFError): await client.get(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["8.8.8.8", "2606:4700:4700::1111"])
async def test_actual_strict_dial_uses_only_resolved_public_literal(monkeypatch, address):
    lookup = AsyncMock(return_value=[(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    backend = AsyncMock()
    stream = object()
    backend.connect_tcp.return_value = stream
    context = ContextVar("fixture-exact-url", default=("cms.example.test", 443))
    pinned = ssrf._PinnedNetworkBackend(require_public=True, backend=backend, trusted_dial_context=context)
    assert await pinned.connect_tcp("cms.example.test", 443, timeout=5) is stream
    backend.connect_tcp.assert_awaited_once_with(address, 443, timeout=5, local_address=None, socket_options=None)


@pytest.mark.asyncio
async def test_rebinding_between_actual_hook_and_pinned_dial_never_dials_private_answer(monkeypatch):
    lookup = AsyncMock(side_effect=[[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))], [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 443, 0, 0))]])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    await ssrf.assert_url_allowed("https://cms.example.test/api/articles", require_public=True)
    backend = AsyncMock()
    with pytest.raises(ssrf.SSRFError):
        await ssrf._PinnedNetworkBackend(require_public=True, backend=backend).connect_tcp("cms.example.test", 443)
    assert lookup.await_count == 2
    backend.connect_tcp.assert_not_awaited()


@pytest.mark.asyncio
async def test_default_legacy_opt_out_and_exact_trust_remain_unchanged():
    async with ssrf.guarded_async_client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        assert (await client.get("https://127.0.0.1/test")).status_code == 200
    backend = AsyncMock()
    await ssrf._PinnedNetworkBackend(backend=backend).connect_tcp("legacy.internal", 443)
    backend.connect_tcp.assert_awaited_once_with("legacy.internal", 443, timeout=None, local_address=None, socket_options=None)


@pytest.mark.asyncio
async def test_strict_factory_binds_actual_transport_backend_and_keeps_proxy_mount_fences():
    client = ssrf.guarded_async_client(require_public=True, trust_env=False)
    assert isinstance(client._transport, ssrf._PinnedAsyncHTTPTransport)
    assert client._transport._pool._network_backend._require_public is True
    await client.aclose()
    transport = httpx.AsyncHTTPTransport()
    for kwargs in ({"proxy": "http://example.test"}, {"mounts": {}}, {"transport": transport}):
        with pytest.raises(ValueError): ssrf.guarded_async_client(require_public=True, **kwargs)
    await transport.aclose()
