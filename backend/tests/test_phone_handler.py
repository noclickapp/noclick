"""
PhoneHandler through the real receiver routing: every phone:* event is gated
on the phone_channel rollout, resolves the actor from the socket session, and
returns the service's verdicts as correlated responses. The repository is
also run once against the native-pool double so its SQL shapes execute.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from repositories.phones import PhoneRepo
from tests.mocks.mock_asyncpg import MockNativePool
from tests.test_phone_identity import PHONE, FakeRepo, FakeVerify
from tests.utils.base_handler_test import BaseHandlerTest
from utils import feature_gates
from utils.phone_identity import PhoneIdentity
from wss.receiver.client_events import (
    PhoneLinkCheckRequest, PhoneLinkStartRequest, PhoneStatusRequest, PhoneUnlinkRequest,
)
from wss.sender import send_event

USER_ID = "uuid-test-user"


class TestPhoneHandler(BaseHandlerTest):

    def get_session_data(self, sid):
        # The real session carries the auth email under user_data; the gate reads it there.
        return {"sid": sid, "user_id": USER_ID, "user_data": {"email": "someone@example.com"}}

    @pytest.fixture(autouse=True)
    def phone_service(self, monkeypatch):
        self.repo, self.verify = FakeRepo(), FakeVerify()
        monkeypatch.setitem(feature_gates.FEATURE_ROLLOUT, "phone_channel", feature_gates.EVERYONE)
        with patch("wss.handlers.phone_handler.default_service",
                   return_value=PhoneIdentity(self.repo, self.verify)):
            yield

    async def _send(self, frontend_sio, sid, request):
        await send_event(frontend_sio, sid, request)
        responses = [e[1] for e in self.get_main_api_emitted_events("response")
                     if e[1]["request_id"] == request.request_id]
        assert len(responses) == 1, responses
        return responses[0]

    @pytest.mark.asyncio
    async def test_link_flow_over_the_socket(self, frontend_sio, sid):
        status = await self._send(frontend_sio, sid, PhoneStatusRequest(request_id="s1"))
        assert status["data"] == {"configured": True, "phone": None, "verified_at": None, "link_version": None}

        started = await self._send(frontend_sio, sid, PhoneLinkStartRequest(request_id="a1", phone="+1 424 242 1064"))
        assert started.get("error") is None and started["data"]["phone"] == PHONE
        challenge_id = started["data"]["challenge_id"]

        wrong = await self._send(frontend_sio, sid, PhoneLinkCheckRequest(request_id="c1", challenge_id=challenge_id, code="000000"))
        assert wrong["data"] == {"kind": "invalid_code"} and wrong["error"]

        linked = await self._send(frontend_sio, sid, PhoneLinkCheckRequest(request_id="c2", challenge_id=challenge_id, code="123456"))
        assert linked.get("error") is None and linked["data"]["phone"] == PHONE and linked["data"]["link_version"] == 1
        assert (await self.repo.get_user_by_phone(PHONE))["user_id"] == USER_ID

        unlinked = await self._send(frontend_sio, sid, PhoneUnlinkRequest(request_id="u1"))
        assert unlinked["data"] == {"unlinked": True}
        assert (await self._send(frontend_sio, sid, PhoneStatusRequest(request_id="s2")))["data"]["phone"] is None

    @pytest.mark.asyncio
    async def test_bad_number_is_a_typed_error_and_never_reaches_the_provider(self, frontend_sio, sid):
        response = await self._send(frontend_sio, sid, PhoneLinkStartRequest(request_id="a2", phone="4242421064"))
        assert response["data"] == {"kind": "invalid_number"} and "country code" in response["error"]
        assert self.verify.started == []

    @pytest.mark.asyncio
    async def test_every_event_is_gated_on_the_rollout(self, frontend_sio, sid, monkeypatch):
        monkeypatch.setitem(feature_gates.FEATURE_ROLLOUT, "phone_channel", feature_gates.INTERNAL)
        monkeypatch.setattr(feature_gates, "is_internal_user", lambda email: email == "staff@example.com")
        for i, request in enumerate((
            PhoneStatusRequest(request_id="g0"),
            PhoneLinkStartRequest(request_id="g1", phone=PHONE),
            PhoneLinkCheckRequest(request_id="g2", challenge_id="ch-1", code="123456"),
            PhoneUnlinkRequest(request_id="g3"),
        )):
            response = await self._send(frontend_sio, sid, request)
            assert response["data"] == {"kind": "gated"} and "available on your account" in response["error"], request
        assert self.verify.started == [] and self.repo.challenges == {}

        monkeypatch.setattr(feature_gates, "is_internal_user", lambda email: email == "someone@example.com")
        response = await self._send(frontend_sio, sid, PhoneStatusRequest(request_id="g4"))
        assert response.get("error") is None and response["data"]["configured"] is True


async def test_repository_sql_executes_against_the_pool_double():
    now = datetime.now(timezone.utc)
    pool = MockNativePool({
        "INSERT INTO public.phone_verification_challenges": {"id": "ch-1", "phone_e164": PHONE, "expires_at": now},
        "FROM public.phone_verification_challenges WHERE id": {
            "id": "ch-1", "user_id": "u1", "phone_e164": PHONE, "provider_sid": "VE1",
            "status": "pending", "attempts": 0, "expires_at": now + timedelta(minutes=5),
        },
        "SELECT COUNT(*)": 2,
        "FROM public.user_phones WHERE user_id": {"phone_e164": PHONE, "verified_at": now, "link_version": 1},
        "FROM public.user_phones WHERE phone_e164": {"user_id": "u1", "verified_at": now, "link_version": 1},
        "INSERT INTO public.user_phones": {"phone_e164": PHONE, "verified_at": now, "link_version": 2},
        "UPDATE public.user_phones SET unlinked_at": "UPDATE 1",
    })
    repo = PhoneRepo(pool)
    assert (await repo.create_challenge(user_id="u1", phone_e164=PHONE, provider_sid="VE1", expires_at=now))["id"] == "ch-1"
    assert (await repo.get_challenge("ch-1", user_id="u1"))["status"] == "pending"
    await repo.record_check("ch-1", status="pending")
    assert await repo.count_starts(user_id="u1", since=now) == 2
    with pytest.raises(ValueError):
        await repo.count_starts(since=now)
    assert (await repo.get_active_phone("u1"))["link_version"] == 1
    assert (await repo.get_user_by_phone(PHONE))["user_id"] == "u1"
    assert (await repo.consume_and_link(user_id="u1", phone_e164=PHONE, challenge_id="ch-1"))["link_version"] == 2
    assert await repo.unlink("u1") is True
    # The supersede + insert and the approve + bind pairs each ran inside one acquired connection.
    statements = [c.args[0] for c in pool.conn.execute.await_args_list]
    assert any("SET status = 'superseded'" in s for s in statements)
    assert any("SET status = 'approved'" in s for s in statements)
