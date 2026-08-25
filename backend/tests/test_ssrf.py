"""Unit coverage for the shared outbound-connection SSRF policy."""

import asyncio
import socket
from contextvars import ContextVar
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from utils.ssrf import (
    _PinnedNetworkBackend,
    SSRFError,
    allow_private_hosts,
    assert_exact_url_origin,
    assert_host_allowed,
    assert_url_allowed,
    guarded_async_client,
    normalize_https_origin,
    normalize_provider_https_origin,
    normalize_provider_subdomain,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://graph.microsoft.com/v1.0/me/drive/root/delta?$deltatoken=abc",
        "https://GRAPH.MICROSOFT.COM:443/v1.0/users?$skiptoken=abc",
    ],
)
def test_exact_origin_accepts_only_the_canonical_provider_origin(url):
    assert_exact_url_origin(url, "https://graph.microsoft.com")


@pytest.mark.parametrize(
    "url",
    [
        "http://graph.microsoft.com/v1.0/me",
        "https://graph.microsoft.com.evil.example/v1.0/me",
        "https://graph.microsoft.com@evil.example/v1.0/me",
        "https://graph.microsoft.com:8443/v1.0/me",
        "https://127.0.0.1/v1.0/me",
        "/v1.0/me",
    ],
)
def test_exact_origin_rejects_bearer_exfiltration_targets(url):
    with pytest.raises(SSRFError, match="outside"):
        assert_exact_url_origin(url, "https://graph.microsoft.com")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://API.Example.com/", "https://api.example.com"),
        ("https://api.example.com:443", "https://api.example.com"),
        ("https://api.example.com:8443/", "https://api.example.com:8443"),
        ("https://bücher.example/", "https://xn--bcher-kva.example"),
        ("https://[2001:4860:4860::8888]:8443", "https://[2001:4860:4860::8888]:8443"),
    ],
)
def test_https_origin_normalization_is_exact_and_canonical(value, expected):
    assert normalize_https_origin(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "api.example.com",
        "http://api.example.com",
        "https://user@api.example.com",
        "https://api.example.com/v1",
        "https://api.example.com?tenant=one",
        "https://api.example.com#fragment",
        "https://api.example.com:not-a-port",
    ],
)
def test_https_origin_normalization_rejects_non_origins(value):
    with pytest.raises(SSRFError, match="origin|invalid|required"):
        normalize_https_origin(value)


@pytest.fixture(autouse=True)
def private_targets_blocked(monkeypatch):
    monkeypatch.delenv("OUTBOUND_ALLOW_PRIVATE_IPS", raising=False)
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "::1"])
async def test_host_guard_blocks_private_literals(host):
    with pytest.raises(SSRFError, match="non-public address"):
        await assert_host_allowed(host, 443)


async def test_host_guard_blocks_hostname_if_any_answer_is_private(monkeypatch):
    loop = asyncio.get_running_loop()

    async def fake_getaddrinfo(*_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 443)),
        ]

    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(SSRFError, match="resolves to non-public address"):
        await assert_host_allowed("mixed.example", 443)


async def test_host_guard_fails_closed_on_resolution_error(monkeypatch):
    loop = asyncio.get_running_loop()

    async def fake_getaddrinfo(*_args, **_kwargs):
        raise socket.gaierror("not found")

    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(SSRFError, match="Could not resolve host"):
        await assert_host_allowed("missing.example", 443)


async def test_url_guard_rejects_invalid_port():
    with pytest.raises(SSRFError, match="invalid port"):
        await assert_url_allowed("https://example.com:not-a-port/path")


async def test_url_guard_fails_closed_on_malformed_ipv6_url():
    with pytest.raises(SSRFError, match="URL is invalid"):
        await assert_url_allowed("http://[::1")


@pytest.mark.parametrize("port", [0, -1, 65536, "443", True])
async def test_host_guard_rejects_out_of_range_ports(port):
    with pytest.raises(SSRFError, match="invalid port"):
        await assert_host_allowed("example.com", port)


@pytest.mark.parametrize(
    "name",
    ["OUTBOUND_ALLOW_PRIVATE_IPS", "HTTP_NODE_ALLOW_PRIVATE_IPS"],
)
async def test_private_target_opt_out_names_are_explicit(monkeypatch, name):
    monkeypatch.setenv(name, "true")
    assert allow_private_hosts() is True
    await assert_url_allowed("http://127.0.0.1:8080")
    await assert_host_allowed("127.0.0.1", 5432)


def test_current_opt_out_can_disable_stale_legacy_setting(monkeypatch):
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "false")
    monkeypatch.setenv("HTTP_NODE_ALLOW_PRIVATE_IPS", "true")
    assert allow_private_hosts() is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("acme", "acme"),
        ("ACME.myshopify.com", "acme"),
        ("https://acme.myshopify.com/admin", "acme"),
    ],
)
def test_provider_subdomain_normalization_keeps_host_under_provider(value, expected):
    assert normalize_provider_subdomain(value, "myshopify.com") == expected


@pytest.mark.parametrize(
    "value",
    [
        "127.0.0.1#",
        "evil.example",
        "bad_label",
        "https://user@acme.myshopify.com",
        "https://acme.myshopify.com:8443",
    ],
)
def test_provider_subdomain_normalization_rejects_host_delimiters(value):
    with pytest.raises(SSRFError):
        normalize_provider_subdomain(value, "myshopify.com")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("acme", "https://acme.salesforce.com"),
        ("ACME.salesforce.com", "https://acme.salesforce.com"),
        (
            "https://team.sandbox.my.salesforce.com/",
            "https://team.sandbox.my.salesforce.com",
        ),
    ],
)
def test_provider_https_origin_is_canonical(value, expected):
    assert (
        normalize_provider_https_origin(
            value,
            "salesforce.com",
            allow_nested_labels=True,
        )
        == expected
    )


@pytest.mark.parametrize(
    "value",
    [
        "http://acme.salesforce.com",
        "https://acme.salesforce.com:443",
        "https://user@acme.salesforce.com",
        "https://acme.salesforce.com/services/data",
        "https://acme.salesforce.com/?next=evil",
        "https://acme.salesforce.com/#fragment",
        "https://salesforce.com",
        "https://acme.salesforce.com.evil.example",
    ],
)
def test_provider_https_origin_rejects_non_origin_or_suffix_escape(value):
    with pytest.raises(SSRFError):
        normalize_provider_https_origin(
            value,
            "salesforce.com",
            allow_nested_labels=True,
        )


async def test_guarded_client_preserves_hooks_and_guards_redirect_hops():
    observed = []

    async def existing_hook(request):
        observed.append(str(request.url))

    client = guarded_async_client(event_hooks={"request": [existing_hook]})
    try:
        hooks = client.event_hooks["request"]
        assert len(hooks) == 2
        request = httpx.Request("GET", "http://169.254.169.254/latest/meta-data")
        with pytest.raises(SSRFError, match="non-public address"):
            await hooks[0](request)
        assert observed == []
    finally:
        await client.aclose()


async def test_guarded_client_stops_redirect_before_private_request(monkeypatch):
    loop = asyncio.get_running_loop()

    async def public_dns(*_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]

    monkeypatch.setattr(loop, "getaddrinfo", public_dns)
    visited = []

    def handler(request):
        visited.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://169.254.169.254/latest/meta-data"},
        )

    async with guarded_async_client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        with pytest.raises(SSRFError, match="non-public address"):
            await client.get("https://public.example/start")

    assert visited == ["https://public.example/start"]


async def test_pinned_backend_dials_the_validated_ip_not_the_hostname(monkeypatch):
    loop = asyncio.get_running_loop()

    async def public_dns(*_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]

    monkeypatch.setattr(loop, "getaddrinfo", public_dns)
    stream = object()
    network = MagicMock()
    network.connect_tcp = AsyncMock(return_value=stream)
    backend = _PinnedNetworkBackend(backend=network)

    assert await backend.connect_tcp("public.example", 443) is stream
    network.connect_tcp.assert_awaited_once_with(
        "93.184.216.34",
        443,
        timeout=None,
        local_address=None,
        socket_options=None,
    )


async def test_pinned_backend_closes_double_dns_rebinding(monkeypatch):
    loop = asyncio.get_running_loop()
    answers = iter(
        [
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))],
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))],
        ]
    )

    async def rebinding_dns(*_args, **_kwargs):
        return next(answers)

    monkeypatch.setattr(loop, "getaddrinfo", rebinding_dns)
    network = MagicMock()
    network.connect_tcp = AsyncMock()
    backend = _PinnedNetworkBackend(backend=network)

    # The request hook sees the first, public answer. The socket backend checks
    # again, rejects the changed answer, and never asks the OS to dial a host.
    await assert_host_allowed("rebind.example", 80)
    with pytest.raises(SSRFError, match="non-public address"):
        await backend.connect_tcp("rebind.example", 80)
    network.connect_tcp.assert_not_awaited()


async def test_pinned_backend_allows_only_owned_private_storage_host(monkeypatch):
    loop = asyncio.get_running_loop()

    async def private_dns(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 9000))]

    monkeypatch.setattr(loop, "getaddrinfo", private_dns)
    stream = object()
    network = MagicMock()
    network.connect_tcp = AsyncMock(return_value=stream)
    trusted_dial_context = ContextVar("test_trusted_dial", default=None)
    trusted_dial_context.set(("storage.localhost", 9000))
    backend = _PinnedNetworkBackend(
        trusted_dial_context=trusted_dial_context,
        backend=network,
    )

    assert await backend.connect_tcp("storage.localhost", 9000) is stream
    network.connect_tcp.assert_awaited_once_with(
        "10.0.0.8",
        9000,
        timeout=None,
        local_address=None,
        socket_options=None,
    )


async def test_exact_url_trust_does_not_leak_to_same_host_redirect():
    owned_url = "https://storage.example:9000/presigned?signature=owned"
    redirected_url = "https://storage.example:9000/other"
    visited = []

    def handler(request):
        visited.append(str(request.url))
        return httpx.Response(302, headers={"location": redirected_url})

    async with guarded_async_client(
        trusted_exact_urls=[owned_url],
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        with pytest.raises(SSRFError, match="non-exact"):
            await client.get(owned_url)

    # The second path never reaches the transport, even if HTTP Core could
    # otherwise reuse the private connection opened by the exact first URL.
    assert visited == [owned_url]


async def test_guarded_client_trusts_only_an_exact_owned_url():
    owned_url = "http://storage.localhost:9000/presigned?signature=owned"
    metadata_url = "http://169.254.169.254/latest/meta-data"
    visited = []

    def handler(request):
        visited.append(str(request.url))
        return httpx.Response(302, headers={"location": metadata_url})

    async with guarded_async_client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        trusted_exact_urls=[owned_url],
    ) as client:
        with pytest.raises(SSRFError, match="non-public address"):
            await client.get(owned_url)

    assert visited == [owned_url]


async def test_postgres_connector_blocks_before_asyncpg_connect():
    from nodes.postgres_node import PostgresConnectionStringCredential, PostgresNode

    credential = PostgresConnectionStringCredential(
        connection_string="postgresql://user:password@127.0.0.1:5432/app"
    )
    with patch("nodes.postgres_node.asyncpg.connect", new_callable=AsyncMock) as connect:
        with pytest.raises(SSRFError, match="non-public address"):
            await PostgresNode._get_connection(None, credential)
    connect.assert_not_awaited()


async def test_mongodb_connector_blocks_private_seed():
    from nodes.mongodb_node import MongoDBNode

    with pytest.raises(SSRFError, match="non-public address"):
        await MongoDBNode._assert_connection_allowed(
            "mongodb://user:password@127.0.0.1:27017/app?tls=true"
        )


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://db.public.example:27017/app?replicaSet=rs0&tls=true",
        "mongodb://db1.public.example:27017,db2.public.example:27017/app?tls=true",
        "mongodb://db.public.example:27017/app?directConnection=false&tls=true",
        "mongodb+srv://cluster.customer.example/app",
        "mongodb+srv://cluster.abc.mongodb.net/app?srvMaxHosts=1",
        "mongodb+srv://cluster.abc.mongodb.net/app?tls=true;srvServiceName=custom",
        "mongodb+srv://cluster.abc.mongodb.net/app?tls=false",
        "mongodb+srv://cluster.abc.mongodb.net/app?tlsAllowInvalidCertificates=true",
        "mongodb+srv://cluster.abc.mongodb.net/app?tlsAllowInvalidHostnames=true",
    ],
)
async def test_mongodb_connector_rejects_unbounded_topology_modes(uri):
    from nodes.mongodb_node import MongoDBNode

    with pytest.raises(SSRFError):
        await MongoDBNode._assert_connection_allowed(uri)


async def test_mongodb_atlas_srv_requires_every_resolved_host_to_stay_in_domain():
    from nodes.mongodb_node import MongoDBNode

    parsed = {
        "nodelist": [("shard.mongodb.net", 27017), ("steered.example", 27017)],
        "options": {"tls": True},
    }
    with patch("pymongo.uri_parser.parse_uri", return_value=parsed):
        with pytest.raises(SSRFError, match="left the trusted"):
            await MongoDBNode._assert_connection_allowed(
                "mongodb+srv://cluster.abc.mongodb.net/app"
            )


async def test_mongodb_atlas_srv_accepts_tls_verified_provider_topology():
    from nodes.mongodb_node import MongoDBNode

    parsed = {
        "nodelist": [
            ("shard-00-00.abc.mongodb.net", 27017),
            ("shard-00-01.abc.mongodb.net", 27017),
        ],
        "options": {"tls": True},
    }
    with (
        patch("pymongo.uri_parser.parse_uri", return_value=parsed),
        patch("nodes.mongodb_node.assert_host_allowed", new_callable=AsyncMock) as guard,
    ):
        await MongoDBNode._assert_connection_allowed(
            "mongodb+srv://cluster.abc.mongodb.net/app"
        )

    assert guard.await_count == 2


@pytest.mark.parametrize(
    "options",
    [
        {"tls": True, "replicaSet": "rs0"},
        {"tls": True, "loadBalanced": True},
        {"tls": True, "directConnection": False},
    ],
)
async def test_mongodb_plain_topology_checks_real_pymongo_option_casing(options):
    from nodes.mongodb_node import MongoDBNode

    parsed = {
        "nodelist": [("db.public.example", 27017)],
        "options": options,
    }
    with (
        patch("pymongo.uri_parser.parse_uri", return_value=parsed),
        patch("nodes.mongodb_node.assert_host_allowed", new_callable=AsyncMock) as guard,
        pytest.raises(SSRFError, match="direct"),
    ):
        await MongoDBNode._assert_connection_allowed(
            "mongodb://db.public.example:27017/app?tls=true"
        )

    guard.assert_not_awaited()


def test_mongodb_plain_client_is_forced_into_direct_mode(monkeypatch):
    from nodes.mongodb_node import MongoDBNode

    client = object()
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr("motor.motor_asyncio.AsyncIOMotorClient", constructor)

    assert (
        MongoDBNode._get_client(
            {"connection_string": "mongodb://db.public.example:27017/app?tls=true"}
        )
        is client
    )
    constructor.assert_called_once_with(
        "mongodb://db.public.example:27017/app?tls=true",
        serverSelectionTimeoutMS=10000,
        directConnection=True,
    )


def test_mongodb_plain_atlas_topology_is_not_forced_direct(monkeypatch):
    from nodes.mongodb_node import MongoDBNode

    constructor = MagicMock(return_value=object())
    monkeypatch.setattr("motor.motor_asyncio.AsyncIOMotorClient", constructor)
    uri = (
        "mongodb://shard-00-00.abc.mongodb.net:27017,"
        "shard-00-01.abc.mongodb.net:27017/app?replicaSet=atlas-rs&tls=true"
    )

    MongoDBNode._get_client({"connection_string": uri})

    constructor.assert_called_once_with(uri, serverSelectionTimeoutMS=10000)


async def test_mongodb_plain_atlas_multi_seed_passes_policy():
    from nodes.mongodb_node import MongoDBNode

    uri = (
        "mongodb://shard-00-00.abc.mongodb.net:27017,"
        "shard-00-01.abc.mongodb.net:27017/app?replicaSet=atlas-rs&tls=true"
    )
    with patch(
        "nodes.mongodb_node.assert_host_allowed", new_callable=AsyncMock
    ) as guard:
        await MongoDBNode._assert_connection_allowed(uri)

    assert guard.await_count == 2


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("cluster.abc.mongodb.net", True),
        ("CLUSTER.ABC.MONGODB.NET.", True),
        ("mongodb.net", False),
        ("evil-mongodb.net", False),
        ("mongodb.net.evil.example", False),
    ],
)
def test_mongodb_atlas_suffix_uses_a_dns_label_boundary(host, expected):
    from nodes.mongodb_node import _is_atlas_host

    assert _is_atlas_host(host) is expected


def test_mongodb_private_network_opt_out_preserves_replica_mode(monkeypatch):
    from nodes.mongodb_node import MongoDBNode

    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "true")
    constructor = MagicMock(return_value=object())
    monkeypatch.setattr("motor.motor_asyncio.AsyncIOMotorClient", constructor)
    uri = "mongodb://db1.local:27017,db2.local:27017/app?replicaSet=rs0"

    MongoDBNode._get_client({"connection_string": uri})

    constructor.assert_called_once_with(uri, serverSelectionTimeoutMS=10000)


async def test_mcp_oauth_token_endpoint_is_guarded():
    from nodes.oauth.mcp_oauth import exchange_code_for_tokens

    with pytest.raises(SSRFError, match="non-public address"):
        await exchange_code_for_tokens(
            code="code",
            code_verifier="verifier",
            token_endpoint="http://169.254.169.254/token",
            client_id="client",
            redirect_uri="https://app.example/callback",
        )
