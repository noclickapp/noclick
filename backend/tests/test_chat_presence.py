"""
watching_chat: whether the owner is watching their chat this moment, so a
message the chat shows is not also texted. A wrong yes loses the message and a
wrong no only sends it twice, so it answers yes only on a fresh claim from a
tab, and no on anything else (a lapsed claim, a Redis error, no Redis). Claims
arrive as presence:chat beats over the app's socket, one per tab: a tab
withdrawing or disconnecting takes back its own claim and nobody else's.
"""

import pytest
from fakeredis import aioredis

from tests.utils.base_handler_test import BaseHandlerTest
from utils import redis_client, user_presence
from utils.user_presence import CHAT_LIVE_TTL_SECONDS, claim_chat_live, release_chat_live, watching_chat
from wss.receiver.client_events import PresenceChatRequest
from wss.sender import send_event

USER_ID = "uuid-test-user"
TAB_A = "11111111-1111-4111-8111-111111111111"
TAB_B = "22222222-2222-4222-8222-222222222222"


class FakeClock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def time(self):
        return self.now

    def monotonic(self):
        return self.now


class BrokenRedis:
    """A Redis that is down: every command fails."""

    def __getattr__(self, name):
        def fail(*_args, **_kwargs):
            raise ConnectionError("Redis is down")

        return fail


@pytest.fixture
def redis(monkeypatch):
    client = aioredis.FakeRedis()
    monkeypatch.setattr(redis_client, "get_shared_redis", lambda: client)
    return client


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(user_presence, "time", fake)
    return fake


@pytest.mark.asyncio
async def test_a_fresh_claim_is_watching_until_it_lapses(redis, clock):
    assert await watching_chat(USER_ID) is False
    await claim_chat_live(USER_ID, TAB_A)
    assert await watching_chat(USER_ID) is True

    clock.now += CHAT_LIVE_TTL_SECONDS - 1
    assert await watching_chat(USER_ID) is True
    clock.now += 2
    assert await watching_chat(USER_ID) is False
    # Redis lets the whole set go too once no tab renews it.
    assert 0 < await redis.ttl(f"nc:user:chat_live:{USER_ID}") <= CHAT_LIVE_TTL_SECONDS


@pytest.mark.asyncio
async def test_a_beat_renews_the_claim(redis, clock):
    await claim_chat_live(USER_ID, TAB_A)
    for _ in range(4):
        clock.now += 15
        await claim_chat_live(USER_ID, TAB_A)
    clock.now += CHAT_LIVE_TTL_SECONDS - 1
    assert await watching_chat(USER_ID) is True


@pytest.mark.asyncio
async def test_two_tabs_one_leaving_leaves_the_other_watching(redis, clock):
    await claim_chat_live(USER_ID, TAB_A)
    await claim_chat_live(USER_ID, TAB_B)
    await release_chat_live(USER_ID, [TAB_A])
    assert await watching_chat(USER_ID) is True
    await release_chat_live(USER_ID, [TAB_B])
    assert await watching_chat(USER_ID) is False


@pytest.mark.asyncio
async def test_a_tab_that_died_silently_stops_counting_while_another_keeps_beating(redis, clock):
    await claim_chat_live(USER_ID, TAB_A)
    await claim_chat_live(USER_ID, TAB_B)
    # Tab A goes quiet; tab B keeps beating, which keeps the set alive.
    for _ in range(3):
        clock.now += 15
        await claim_chat_live(USER_ID, TAB_B)
    assert await watching_chat(USER_ID) is True
    assert await redis.zrange(f"nc:user:chat_live:{USER_ID}", 0, -1) == [TAB_B.encode()]
    await release_chat_live(USER_ID, [TAB_B])
    assert await watching_chat(USER_ID) is False


@pytest.mark.asyncio
async def test_one_account_watching_says_nothing_of_another(redis, clock):
    await claim_chat_live(USER_ID, TAB_A)
    assert await watching_chat("someone-else") is False


@pytest.mark.asyncio
async def test_a_redis_error_reads_as_not_watching_and_never_raises(monkeypatch, clock):
    monkeypatch.setattr(redis_client, "get_shared_redis", lambda: BrokenRedis())
    await claim_chat_live(USER_ID, TAB_A)
    await release_chat_live(USER_ID, [TAB_A])
    assert await watching_chat(USER_ID) is False


@pytest.mark.asyncio
async def test_no_redis_reads_as_not_watching(monkeypatch):
    monkeypatch.setattr(redis_client, "get_shared_redis", lambda: None)
    await claim_chat_live(USER_ID, TAB_A)
    assert await watching_chat(USER_ID) is False


class TestPresenceHandler(BaseHandlerTest):

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": USER_ID, "user_data": {"email": "someone@example.com"}}

    @pytest.fixture(autouse=True)
    def fake_redis(self, redis):
        return redis

    async def _beat(self, frontend_sio, sid, tab_id, live):
        await send_event(frontend_sio, sid, PresenceChatRequest(tab_id=tab_id, live=live))

    @pytest.mark.asyncio
    async def test_a_tab_claims_and_withdraws_over_the_socket(self, frontend_sio, sid):
        await self._beat(frontend_sio, sid, TAB_A, True)
        assert await watching_chat(USER_ID) is True
        await self._beat(frontend_sio, sid, TAB_A, False)
        assert await watching_chat(USER_ID) is False
        # One-way: the tab is never answered.
        assert self.get_main_api_emitted_events("response") == []

    @pytest.mark.asyncio
    async def test_a_disconnect_withdraws_that_sockets_claims_and_only_those(self, frontend_sio, sid):
        other = f"{sid}-other"
        self.main_api_sio.create_session(sid=other, user_id=USER_ID)
        await self._beat(frontend_sio, sid, TAB_A, True)
        await self._beat(frontend_sio, other, TAB_B, True)

        await self.proxy.cleanup_user(sid)
        assert await watching_chat(USER_ID) is True
        await self.proxy.cleanup_user(other)
        assert await watching_chat(USER_ID) is False

    @pytest.mark.asyncio
    async def test_staff_viewing_the_account_as_its_owner_never_count(self, frontend_sio, sid):
        mimic = f"{sid}-mimic"
        self.main_api_sio.create_session(sid=mimic, user_id=USER_ID, real_user_id="uuid-staff")
        await self._beat(frontend_sio, mimic, TAB_A, True)
        assert await watching_chat(USER_ID) is False

    @pytest.mark.asyncio
    async def test_a_signed_out_socket_claims_nothing(self, frontend_sio, sid):
        anonymous = f"{sid}-anonymous"
        self.main_api_sio.create_session(sid=anonymous)
        await self._beat(frontend_sio, anonymous, TAB_A, True)
        assert await redis_keys() == []

    @pytest.mark.asyncio
    async def test_a_malformed_tab_id_is_refused(self, frontend_sio, sid):
        await send_event(frontend_sio, sid, PresenceChatRequest.model_construct(tab_id="x", live=True))
        assert await watching_chat(USER_ID) is False


async def redis_keys():
    return await redis_client.get_shared_redis().keys("*")
