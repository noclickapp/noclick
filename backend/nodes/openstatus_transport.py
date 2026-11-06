"""Public-only transport for the OpenStatus API's fixed origin.
Staging's generic guard permits private hosts on self-hosted installs; supplied
OpenStatus keys must keep a public DNS boundary even under that override.
"""
import httpcore
import httpx
from utils import ssrf


class _PublicBackend(ssrf._PinnedNetworkBackend):
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        addresses = await ssrf._resolve_host_addresses(host, port, permit_non_public=False)
        last_error = None
        for address in addresses:
            try:
                return await self._backend.connect_tcp(address, port, timeout=timeout,
                    local_address=local_address, socket_options=socket_options)
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise last_error


def guarded_async_client(*, require_public, transport=None, **kwargs):
    if require_public is not True:
        raise ValueError("OpenStatus requires public API transport")

    async def guard(request):
        ssrf.assert_exact_url_origin(str(request.url), "https://api.openstatus.dev")
        await ssrf._resolve_host_addresses(request.url.host, request.url.port or 443, permit_non_public=False)

    if transport is None:
        transport = httpx.AsyncHTTPTransport(trust_env=False)
        if not hasattr(transport._pool, "_network_backend"):
            raise RuntimeError("OpenStatus transport does not expose a pinnable network backend")
        transport._pool._network_backend = _PublicBackend(backend=httpcore.AnyIOBackend())
    return httpx.AsyncClient(transport=transport, event_hooks={"request": [guard]}, **kwargs)
