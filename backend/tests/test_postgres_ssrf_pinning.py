"""DNS-rebinding and ambient-credential coverage for PostgreSQL."""

import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg.connect_utils
import pytest

from nodes.postgres_node import (
    _PinnedPostgresLoop,
    _connect_pinned_postgres,
    _parse_safe_postgres_dsn,
    PostgresConnectionStringCredential,
    PostgresNode,
)
from utils.ssrf import SSRFError


async def test_connect_resolves_once_but_keeps_hostname_for_asyncpg_tls():
    connection = object()
    with (
        patch(
            "nodes.postgres_node.resolve_host_addresses",
            new=AsyncMock(return_value=["93.184.216.34"]),
        ) as resolve,
        patch(
            "nodes.postgres_node.asyncpg.connect",
            new=AsyncMock(return_value=connection),
        ) as connect,
    ):
        result = await _connect_pinned_postgres(
            "db.example.com",
            5432,
            user="user",
            password="pass",
            database="app",
            ssl=False,
        )

    assert result is connection
    resolve.assert_awaited_once_with("db.example.com", 5432)
    kwargs = connect.await_args.kwargs
    assert kwargs["host"] == "db.example.com"
    assert kwargs["port"] == 5432
    assert kwargs["loop"]._address == "93.184.216.34"
    assert kwargs["statement_cache_size"] == 0
    assert kwargs["direct_tls"] is False
    assert kwargs["target_session_attrs"] == "any"


async def test_connect_retries_only_prevalidated_addresses_on_network_error():
    connection = object()
    attempted_addresses = []

    async def fake_connect(*_args, **kwargs):
        attempted_addresses.append(kwargs["loop"]._address)
        if len(attempted_addresses) == 1:
            raise OSError("first address unavailable")
        return connection

    with (
        patch(
            "nodes.postgres_node.resolve_host_addresses",
            new=AsyncMock(return_value=["93.184.216.34", "93.184.216.35"]),
        ),
        patch("nodes.postgres_node.asyncpg.connect", side_effect=fake_connect),
    ):
        result = await _connect_pinned_postgres("db.example.com", 5432)

    assert result is connection
    assert attempted_addresses == ["93.184.216.34", "93.184.216.35"]


async def test_pinned_loop_dials_ip_but_preserves_direct_tls_server_name():
    real_loop = MagicMock()
    real_loop.create_connection = AsyncMock(return_value=(object(), object()))
    loop = _PinnedPostgresLoop(
        real_loop,
        "db.example.com",
        5432,
        "93.184.216.34",
    )
    ssl_context = object()
    protocol_factory = object()

    await loop.create_connection(
        protocol_factory,
        "DB.EXAMPLE.COM.",
        5432,
        ssl=ssl_context,
    )

    real_loop.create_connection.assert_awaited_once_with(
        protocol_factory,
        "93.184.216.34",
        5432,
        ssl=ssl_context,
        server_hostname="db.example.com",
    )


async def test_pinned_loop_rejects_driver_target_changes():
    real_loop = MagicMock()
    real_loop.create_connection = AsyncMock()
    loop = _PinnedPostgresLoop(
        real_loop,
        "db.example.com",
        5432,
        "93.184.216.34",
    )

    with pytest.raises(SSRFError, match="unvalidated"):
        await loop.create_connection(object(), "metadata.internal", 5432)

    real_loop.create_connection.assert_not_awaited()


class _FakeTransport:
    def __init__(self):
        self.protocol = None

    def write(self, _data):
        return None

    def close(self):
        return None

    def set_protocol(self, protocol):
        self.protocol = protocol


class _FakeDialLoop:
    def __init__(self, real_loop):
        self.real_loop = real_loop
        self.dials = []
        self.tls_server_names = []

    def __getattr__(self, name):
        return getattr(self.real_loop, name)

    async def create_connection(self, protocol_factory, host, port, **kwargs):
        self.dials.append((host, port, kwargs))
        protocol = protocol_factory()
        transport = _FakeTransport()
        protocol.data_received(b"S")
        return transport, protocol

    async def start_tls(
        self,
        transport,
        protocol,
        ssl_context,
        *,
        server_hostname,
    ):
        self.tls_server_names.append(server_hostname)
        return transport


class _FakePostgresProtocol:
    def __init__(self):
        self.is_ssl = False
        self.connected_transport = None

    def connection_made(self, transport):
        self.connected_transport = transport


async def test_asyncpg_starttls_dials_pinned_ip_with_original_sni():
    import asyncio

    fake_loop = _FakeDialLoop(asyncio.get_running_loop())
    pinned_loop = _PinnedPostgresLoop(
        fake_loop,
        "db.example.com",
        5432,
        "93.184.216.34",
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    _transport, protocol = await asyncpg.connect_utils._create_ssl_connection(
        _FakePostgresProtocol,
        "db.example.com",
        5432,
        loop=pinned_loop,
        ssl_context=context,
    )

    assert fake_loop.dials == [("93.184.216.34", 5432, {})]
    assert fake_loop.tls_server_names == ["db.example.com"]
    assert protocol.is_ssl is True


async def test_connection_string_is_decomposed_before_asyncpg(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "ambient-password-must-not-be-used")
    credential = PostgresConnectionStringCredential(
        connection_string=(
            "postgresql://user%40tenant:p%2Fass@db.example.com:6543/app"
            "?sslmode=require&application_name=noclick"
        )
    )
    connection = object()
    with patch(
        "nodes.postgres_node._connect_pinned_postgres",
        new=AsyncMock(return_value=connection),
    ) as connect:
        result = await PostgresNode._get_connection(None, credential)

    assert result is connection
    args = connect.await_args.args
    kwargs = connect.await_args.kwargs
    assert args == ("db.example.com", 6543)
    assert kwargs["user"] == "user@tenant"
    assert kwargs["password"] == "p/ass"
    assert kwargs["database"] == "app"
    assert kwargs["server_settings"] == {"application_name": "noclick"}
    assert isinstance(kwargs["ssl"], ssl.SSLContext)
    assert kwargs["ssl"].verify_mode == ssl.CERT_NONE


@pytest.mark.parametrize(
    "option",
    [
        "passfile=/tmp/pgpass",
        "sslkey=/tmp/client.key",
        "sslcert=/tmp/client.crt",
        "sslrootcert=/tmp/root.crt",
        "sslcrl=/tmp/root.crl",
        "sslpassword=secret",
        "host=127.0.0.1",
        "options=-c%20search_path%3Dprivate",
    ],
)
def test_connection_string_rejects_file_and_connection_control_options(option):
    with pytest.raises(SSRFError, match="not allowed"):
        _parse_safe_postgres_dsn(
            f"postgresql://user:pass@db.example.com/app?{option}"
        )


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://db.example.com/app",
        "postgresql://user@db.example.com/app",
        "postgresql://user:@db.example.com/app",
    ],
)
async def test_connection_string_never_falls_back_to_ambient_password(monkeypatch, dsn):
    monkeypatch.setenv("PGPASSWORD", "ambient-password-must-not-be-used")
    monkeypatch.setenv("PGPASSFILE", "/tmp/ambient-pgpass")
    credential = PostgresConnectionStringCredential(connection_string=dsn)
    with patch(
        "nodes.postgres_node._connect_pinned_postgres",
        new=AsyncMock(),
    ) as connect:
        with pytest.raises(SSRFError, match="username and password"):
            await PostgresNode._get_connection(None, credential)
    connect.assert_not_awaited()


@pytest.mark.parametrize("mode", ["allow", "prefer", "unexpected"])
def test_ambiguous_or_unknown_ssl_modes_are_rejected(mode):
    with pytest.raises(SSRFError, match="SSL mode"):
        _parse_safe_postgres_dsn(
            f"postgresql://user:pass@db.example.com/app?sslmode={mode}"
        )
