"""Tests for the WhatsApp QR connection bind guards.

Idle provider connections may be reused, so concurrent owners must never receive
or bind the same connection. Guard 1: Redis reservation per (connection_id →
user). Guard 2: partial unique index on credentials.metadata->>'connection_id'.
Guard 3: start never shows the QR of a connection another owner's credential
already binds. Provider-side device linking happens at scan time, before
finalize can refuse the bind.
"""
import sys
import types
import uuid

import asyncpg
import pytest


from utils.whatsapp_qr import (
    QR_RESERVATION_TTL_S,
    _bound_to_other_owner,
    _reservation_status,
    _try_reserve_connection,
    get_connection_statuses,
    start_qr_connection,
)


class FakeRedis:
    """Byte-faithful subset of redis.asyncio used by the reservation helpers."""

    def __init__(self):
        self.store = {}
        self.ttls = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value.encode() if isinstance(value, str) else value
        if ex:
            self.ttls[key] = ex
        return True

    async def get(self, key):
        return self.store.get(key)


class BrokenRedis:
    def __getattr__(self, name):
        async def _fail(*a, **k):
            raise ConnectionError("redis down")
        return _fail


@pytest.fixture
def fake_redis(monkeypatch):
    from utils import redis_client
    fake = FakeRedis()
    monkeypatch.setattr(redis_client, "_client", fake)
    return fake


@pytest.fixture
def broken_redis(monkeypatch):
    from utils import redis_client
    monkeypatch.setattr(redis_client, "_client", BrokenRedis())


@pytest.fixture
def no_redis(monkeypatch):
    from utils import redis_client
    monkeypatch.setattr(redis_client, "_client", None)
    monkeypatch.delenv("REDIS_URL", raising=False)


@pytest.mark.asyncio
class TestReservation:
    async def test_first_claim_wins(self, fake_redis):
        assert await _try_reserve_connection("conn-1", "user-a") is True
        assert fake_redis.ttls["whatsapp:qr:reserved:conn-1"] == QR_RESERVATION_TTL_S

    async def test_second_user_rejected(self, fake_redis):
        await _try_reserve_connection("conn-1", "user-a")
        assert await _try_reserve_connection("conn-1", "user-b") is False

    async def test_same_user_reclaim_refreshes(self, fake_redis):
        await _try_reserve_connection("conn-1", "user-a")
        assert await _try_reserve_connection("conn-1", "user-a") is True

    async def test_redis_unavailable_fails_open(self, no_redis):
        # Best-effort guard: the unique index is the hard guarantee.
        assert await _try_reserve_connection("conn-1", "user-a") is True

    async def test_redis_error_fails_open(self, broken_redis):
        assert await _try_reserve_connection("conn-1", "user-a") is True

    async def test_status_held(self, fake_redis):
        await _try_reserve_connection("conn-1", "user-a")
        assert await _reservation_status("conn-1", "user-a") == "held"

    async def test_status_other_user(self, fake_redis):
        await _try_reserve_connection("conn-1", "user-a")
        assert await _reservation_status("conn-1", "user-b") == "other"

    async def test_status_expired_when_key_missing(self, fake_redis):
        # A vanished reservation must NOT be claimable at bind time: a stale
        # polling loop from an earlier flow could otherwise bind a phone
        # someone else just scanned.
        assert await _reservation_status("conn-1", "user-a") == "expired"

    async def test_status_unavailable_on_redis_error(self, broken_redis):
        assert await _reservation_status("conn-1", "user-a") == "unavailable"


@pytest.mark.asyncio
class TestConnectionUniqueIndex:
    async def test_double_bind_rejected(self, postgres_db):
        conn = postgres_db
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uniq_whatsapp_qr_connection_id
            ON credentials ((metadata->>'connection_id'))
            WHERE credential_type = 'whatsapp_qr' AND metadata->>'connection_id' IS NOT NULL
        """)
        user_a, user_b = uuid.uuid4(), uuid.uuid4()
        for uid in (user_a, user_b):
            await conn.execute(
                "INSERT INTO auth.users (id, email, role) VALUES ($1, $2, 'authenticated') ON CONFLICT DO NOTHING",
                uid, f"test-{uid}@example.com",
            )

        async def insert(owner, connection_id):
            await conn.execute(
                """INSERT INTO credentials (id, owner_id, credential_type, name, credential, metadata)
                   VALUES ($1, $2, 'whatsapp_qr', 'test', 'enc', $3)""",
                uuid.uuid4(), owner, {"provider": "wahooks", "connection_id": connection_id},
            )

        await insert(user_a, "conn-shared")
        with pytest.raises(asyncpg.UniqueViolationError):
            async with conn.transaction():  # savepoint: contain the abort
                await insert(user_b, "conn-shared")
        # Different connections and metadata without the key stay unaffected.
        await insert(user_b, "conn-other")
        await conn.execute(
            """INSERT INTO credentials (id, owner_id, credential_type, name, credential, metadata)
               VALUES ($1, $2, 'whatsapp_qr', 'legacy', 'enc', $3)""",
            uuid.uuid4(), user_b, {"provider": "wahooks"},
        )
        await conn.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")


class _PoolShim:
    """pool.acquire() context manager over the test's single connection."""

    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *args):
                return False

        return _Ctx()


async def _seed_binding(conn, connection_id):
    """Insert an auth user + a whatsapp_qr credential bound to connection_id."""
    owner = uuid.uuid4()
    await conn.execute(
        "INSERT INTO auth.users (id, email, role) VALUES ($1, $2, 'authenticated')",
        owner, f"test-{owner}@example.com",
    )
    await conn.execute(
        """INSERT INTO credentials (id, owner_id, credential_type, name, credential, metadata)
           VALUES ($1, $2, 'whatsapp_qr', 'test', 'enc', $3)""",
        uuid.uuid4(), owner, {"provider": "wahooks", "connection_id": connection_id},
    )
    return owner


@pytest.fixture
def stub_wahooks(monkeypatch):
    """Stub the wahooks SDK: get-or-create recycles 'conn-recycled'; create
    mints 'conn-fresh'. Returns the call counter."""
    calls = {"created": 0, "virgin_only": None}

    class StubClient:
        def __init__(self, api_key):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_or_create_scannable_connection(self, virgin_only=False):
            calls["virgin_only"] = virgin_only
            return {"id": "conn-recycled", "qr": "QR-RECYCLED"}

        def create_connection(self):
            calls["created"] += 1
            return {"id": "conn-fresh", "qr": "QR-FRESH"}

    mod = types.ModuleType("wahooks")
    mod.WAHooks = StubClient
    mod.WAHooksError = type("WAHooksError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "wahooks", mod)
    monkeypatch.setenv("WAHOOKS_API_KEY", "test-key")
    return calls


@pytest.mark.asyncio
class TestRecycledConnectionGuard:
    """Guard 3: a recycled connection bound to another owner's credential is
    never handed out — a fresh one is minted instead. The owner's own binding
    stays reusable (reconnect-your-own-session)."""

    async def test_bound_to_other_owner_detected(self, postgres_db):
        await _seed_binding(postgres_db, "conn-bound")
        pool = _PoolShim(postgres_db)
        assert await _bound_to_other_owner(pool, "conn-bound", str(uuid.uuid4())) is True
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")

    async def test_own_binding_not_flagged(self, postgres_db):
        owner = await _seed_binding(postgres_db, "conn-bound")
        pool = _PoolShim(postgres_db)
        assert await _bound_to_other_owner(pool, "conn-bound", str(owner)) is False
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")

    async def test_unbound_not_flagged(self, postgres_db):
        assert await _bound_to_other_owner(_PoolShim(postgres_db), "conn-nobody", str(uuid.uuid4())) is False

    async def test_start_mints_fresh_when_recycled_is_bound(
        self, postgres_db, fake_redis, stub_wahooks
    ):
        await _seed_binding(postgres_db, "conn-recycled")
        result = await start_qr_connection(_PoolShim(postgres_db), owner_id=str(uuid.uuid4()))
        assert result["success"] is True
        assert result["connection_id"] == "conn-fresh"
        assert stub_wahooks["created"] == 1
        assert stub_wahooks["virgin_only"] is True
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")

    async def test_start_reuses_own_bound_connection(self, postgres_db, fake_redis, stub_wahooks):
        owner = await _seed_binding(postgres_db, "conn-recycled")
        result = await start_qr_connection(_PoolShim(postgres_db), owner_id=str(owner))
        assert result["success"] is True
        assert result["connection_id"] == "conn-recycled"
        assert stub_wahooks["created"] == 0
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")


def _stub_wahooks_list(monkeypatch, list_impl):
    """Stub the wahooks SDK with a custom list_connections implementation."""

    class StubClient:
        def __init__(self, api_key):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def list_connections(self):
            return list_impl()

    mod = types.ModuleType("wahooks")
    mod.WAHooks = StubClient
    mod.WAHooksError = type("WAHooksError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "wahooks", mod)
    monkeypatch.setenv("WAHOOKS_API_KEY", "test-key")


@pytest.mark.asyncio
class TestConnectionStatuses:
    """get_connection_statuses feeds the credential picker's dead-session flag:
    id→status map on success, None (= unknown, never dead) on any failure."""

    @pytest.fixture(autouse=True)
    def _fresh_cache(self, monkeypatch):
        import utils.whatsapp_qr as wq
        monkeypatch.setattr(wq, "_status_cache", None)

    async def test_maps_ids_to_statuses(self, monkeypatch):
        _stub_wahooks_list(monkeypatch, lambda: [
            {"id": "c1", "status": "connected"},
            {"id": "c2", "status": "scan_qr"},
            {"status": "orphan-without-id"},
        ])
        assert await get_connection_statuses() == {"c1": "connected", "c2": "scan_qr"}

    async def test_unreachable_returns_none(self, monkeypatch):
        def _boom():
            raise ConnectionError("wahooks down")
        _stub_wahooks_list(monkeypatch, _boom)
        assert await get_connection_statuses() is None

    async def test_missing_api_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("WAHOOKS_API_KEY", raising=False)
        assert await get_connection_statuses() is None

    async def test_cached_within_ttl(self, monkeypatch):
        calls = {"n": 0}

        def _list():
            calls["n"] += 1
            return [{"id": "c1", "status": "connected"}]

        _stub_wahooks_list(monkeypatch, _list)
        assert await get_connection_statuses() == {"c1": "connected"}
        assert await get_connection_statuses() == {"c1": "connected"}
        assert calls["n"] == 1


class TestIdempotentFinalize:
    """A duplicate finalize poll of an already-bound connection must resolve by
    OWNER: the binding user's own retry returns the existing credential as
    success, while another user's attempt stays a hard conflict."""

    def test_same_owner_is_idempotent_success(self):
        from utils.whatsapp_qr import is_own_binding
        uid = uuid.uuid4()
        assert is_own_binding(uid, str(uid)) is True

    def test_other_owner_is_conflict(self):
        from utils.whatsapp_qr import is_own_binding
        assert is_own_binding(uuid.uuid4(), str(uuid.uuid4())) is False
