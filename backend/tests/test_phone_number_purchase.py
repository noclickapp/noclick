"""Buying a number: affordable first, bought at the provider, then credential
and recurring charge in one transaction — a credential that cannot be saved
gives the number back."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from billing.usage_tracker import usage_tracker

from tests.mocks.mock_asyncpg import MockNativePool
from utils import capabilities
from utils.capabilities import PHONE_NUMBERS, provide
from wss.handlers import phone_number_handler as h

USER = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def _own_capabilities():
    saved = dict(capabilities._providers)
    capabilities.clear()
    yield
    capabilities.clear()
    capabilities._providers.update(saved)


@pytest.fixture
def seams(monkeypatch):
    numbers = MagicMock()
    numbers.buy = AsyncMock(return_value={"number_sid": "PN1", "phone_number": "+15674833618"})
    numbers.release = AsyncMock()
    numbers.search = AsyncMock(return_value=[{"phone_number": "+15674833618", "locality": "Lucas", "region": "OH", "capabilities": ["voice"]}])
    provide(PHONE_NUMBERS, numbers)
    monkeypatch.setattr("billing.plan_limits.registered_plan_limits", lambda: object())  # plans exist (hosted)
    monkeypatch.setattr("billing.plan_limits.get_effective_tier", AsyncMock(side_effect=lambda conn, uid, tier: tier))
    monkeypatch.setattr(usage_tracker, "resolve_billing_user_id", AsyncMock(return_value=USER))
    monkeypatch.setattr(usage_tracker, "fetch_credit_remaining", AsyncMock(return_value=40.0))
    created = AsyncMock(return_value=({"id": "cred-1"}, None))
    charge = AsyncMock()
    monkeypatch.setattr(h, "create_credential_with_limit_check", created)
    monkeypatch.setattr(h, "start_connection_charge", charge)
    enc = MagicMock(); enc.encrypt_credential = lambda blob: f"enc:{blob['number_sid']}"
    return numbers, created, charge, enc


async def test_buy_mints_credential_and_charge_together(seams):
    numbers, created, charge, enc = seams
    out = await h.buy_number_for_user(MockNativePool(), user_id=USER, user_tier="pro", e164="+15674833618",
                                      credential_name=None, encryption=enc)
    assert out == {"credential_id": "cred-1", "phone_number": "+15674833618"}
    numbers.buy.assert_awaited_once_with("+15674833618", label=f"NoClick {USER[:8]}")
    args = created.await_args.args
    assert args[1:4] == (USER, "pro", "phone_number") and args[4] == "+15674833618" and args[5] == "enc:PN1"
    assert args[6] == {"provider": "twilio", "phone_number": "+15674833618", "number_sid": "PN1", "monthly_credits": 15}
    assert charge.await_args.kwargs == {"user_id": USER, "credential_id": "cred-1", "charge_type": "phone_number"}
    numbers.release.assert_not_awaited()


async def test_the_first_month_must_be_affordable_before_anything_is_bought(seams):
    numbers, created, _, enc = seams
    usage_tracker.fetch_credit_remaining.return_value = 3.0
    with pytest.raises(h.GateDenied) as exc:
        await h.buy_number_for_user(MockNativePool(), user_id=USER, user_tier="plus", e164="+15674833618", credential_name=None, encryption=enc)
    assert exc.value.kind == "credits" and "15 credits" in str(exc.value)
    numbers.buy.assert_not_awaited(); created.assert_not_awaited()


async def test_only_local_numbers_are_bought(seams):
    numbers, created, _, enc = seams
    for number in ("+18005550100", "+18335550100", "+442071234567"):
        with pytest.raises(h.PhoneNumberError) as exc:
            await h.buy_number_for_user(MockNativePool(), user_id=USER, user_tier="pro", e164=number, credential_name=None, encryption=enc)
        assert exc.value.kind == "number"
    numbers.buy.assert_not_awaited()
    assert h.is_local_number("+15674833618") and not h.is_local_number("+18775550100")
async def test_only_paid_plans_may_hold_a_number(seams, monkeypatch):
    numbers, created, _, enc = seams
    with pytest.raises(h.GateDenied) as exc:
        await h.buy_number_for_user(MockNativePool(), user_id=USER, user_tier="free", e164="+15674833618", credential_name=None, encryption=enc)
    assert exc.value.kind == "plan" and "Plus and Pro" in str(exc.value)
    numbers.buy.assert_not_awaited(); created.assert_not_awaited()
    # A free personal tier funded by a paid org it owns counts, like credits do.
    monkeypatch.setattr("billing.plan_limits.get_effective_tier", AsyncMock(return_value="pro"))
    out = await h.buy_number_for_user(MockNativePool(), user_id=USER, user_tier="free", e164="+15674833618", credential_name=None, encryption=enc)
    assert out["credential_id"] == "cred-1"


async def test_a_credential_that_cannot_be_saved_releases_the_number(seams):
    numbers, created, charge, enc = seams
    created.return_value = (None, "Credential limit reached for this plan")
    with pytest.raises(h.PhoneNumberError) as exc:
        await h.buy_number_for_user(MockNativePool(), user_id=USER, user_tier="plus", e164="+15674833618", credential_name="Shop line", encryption=enc)
    assert exc.value.kind == "credential" and "limit" in str(exc.value)
    numbers.release.assert_awaited_once_with("PN1")
    charge.assert_not_awaited()


class FakeSio:
    def __init__(self, session): self._session = session; self.sent = []
    async def get_session(self, sid): return self._session
    async def emit(self, *a, **k): self.sent.append((a, k))


async def test_handler_gates_on_the_rollout_then_the_provider(seams, monkeypatch):
    from utils import feature_gates
    from wss.receiver.client_events import PhoneNumberSearchRequest
    numbers = seams[0]
    sent = []
    monkeypatch.setattr(h, "send_event", AsyncMock(side_effect=lambda sio, sid, ev: sent.append(ev)))
    monkeypatch.setattr(h.PhoneNumberHandler, "get_pool", AsyncMock(return_value=MockNativePool()))  # CI has no live pool
    monkeypatch.setattr(feature_gates, "is_internal_user", lambda email: email.endswith("@noclick.com"))
    monkeypatch.setitem(feature_gates.FEATURE_ROLLOUT, "phone_numbers", feature_gates.INTERNAL)
    handler = h.PhoneNumberHandler(FakeSio({"user_id": USER, "user_data": {"email": "someone@example.com"}}))
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r1", country="US"))
    assert sent[-1].data == {"kind": "gated"}
    handler = h.PhoneNumberHandler(FakeSio({"user_id": USER, "user_data": {"email": "dhruv@noclick.com"}}))
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r1b", country="US"))
    assert sent[-1].data == {"kind": "plan"}  # no tier in the session reads as free
    handler = h.PhoneNumberHandler(FakeSio({"user_id": USER, "user_data": {"email": "dhruv@noclick.com", "subscription_tier": "pro"}}))
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r2", country="US", area_code="567", contains="no click", limit=12))
    assert sent[-1].error is None and sent[-1].data["numbers"][0]["phone_number"] == "+15674833618" and sent[-1].data["monthly_credits"] == 15
    numbers.search.assert_awaited_with("US", "567", 12, contains="NOCLICK")  # spaces dropped, letters kept for the keypad
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r2b", country="US", contains="555-****"))
    assert numbers.search.await_args.kwargs == {"contains": "555****"}
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r2c", country="US", contains="hello world!!"))
    assert sent[-1].data == {"kind": "pattern"}
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r3", country="IN"))
    assert sent[-1].data == {"kind": "country"}
    capabilities.clear()
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r4", country="US"))
    assert sent[-1].data == {"kind": "unavailable"}
