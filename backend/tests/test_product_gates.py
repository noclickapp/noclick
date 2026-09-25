"""billing/gates.py: the one place a product is judged against an account's
plan and credits. An instance with no plan system passes plan checks; a
projected cost is compared with the paying account's remaining credits. A
refusal carries what would lift it (``Offer``: the plans that include the
product, or the credits a top-up must cover) and a plan cap is reported as a
sales signal."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from billing import gates, plan_limits
from billing.gates import GateDenied, Offer, check_product
from tests.mocks.mock_asyncpg import MockNativePool
from utils import capabilities

pytestmark = pytest.mark.asyncio
USER = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def account(monkeypatch):
    state = {"tier": "free", "remaining": 50.0}
    monkeypatch.setattr(plan_limits, "registered_plan_limits", lambda: object())
    monkeypatch.setattr(plan_limits, "get_user_tier_from_db", AsyncMock(side_effect=lambda conn, uid: state["tier"]))
    monkeypatch.setattr(plan_limits, "get_effective_tier", AsyncMock(side_effect=lambda conn, uid, tier: tier))
    monkeypatch.setattr(gates.usage_tracker, "resolve_billing_user_id", AsyncMock(return_value="owner"))
    monkeypatch.setattr(gates.usage_tracker, "fetch_credit_remaining",
                        AsyncMock(side_effect=lambda uid: state["remaining"]))
    monkeypatch.setattr(gates, "get_user_profile",
                        AsyncMock(return_value={"email": None, "name": None, "label": "sam"}))
    return state


@pytest.fixture
def plan_cap_listener(monkeypatch):
    """The sales signal a platform that sells plans registers."""
    listener = MagicMock()
    monkeypatch.setattr(gates, "capability", {capabilities.PLAN_GATE_ALERT: listener}.get)
    return listener


async def test_a_plan_product_admits_paid_plans_only(account, plan_cap_listener):
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER)
    assert exc.value.kind == "plan" and "Plus and Pro" in str(exc.value)
    # The refusal names the plans that include it, lowest first, and the platform hears about the cap hit.
    assert exc.value.offer == Offer(plans=("plus", "pro")) and exc.value.offer
    plan_cap_listener.assert_called_once_with(
        {"email": "", "user_metadata": {"name": "sam"}}, "Video generation Gate Hit", {"Tier": "free"})
    for tier in ("plus", "pro", "enterprise"):
        account["tier"] = tier
        await check_product(MockNativePool(), "video_generation", user_id=USER)
    # The session's own tier stands in for the database read when the caller has it.
    account["tier"] = "free"
    await check_product(MockNativePool(), "video_generation", user_id=USER, personal_tier="pro")
    plan_cap_listener.assert_called_once()


async def test_a_plan_denial_without_a_listener_still_refuses(account, monkeypatch):
    monkeypatch.setattr(gates, "capability", lambda name: None)
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER)
    assert exc.value.kind == "plan" and exc.value.offer.plans == ("plus", "pro")


async def test_the_projected_cost_is_checked_on_the_paying_account(account, plan_cap_listener):
    account["tier"] = "pro"
    await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=49.5)
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=80)
    assert exc.value.kind == "credits" and "80 credits" in str(exc.value) and "50.0" in str(exc.value)
    gates.usage_tracker.fetch_credit_remaining.assert_awaited_with("owner")
    # A paid plan takes a top-up: the offer is the credits it must cover, judged on the PAYER's plan.
    assert exc.value.offer == Offer(topup_credits=30.0)
    assert plan_limits.get_user_tier_from_db.await_args.args[1] == "owner"
    plan_cap_listener.assert_not_called()
    account["remaining"] = None  # an unlimited balance
    await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=10_000)


async def test_a_free_account_short_of_credits_is_offered_a_plan_not_a_topup(account):
    # image_generation has no plan floor, so a free account reaches the credit check.
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "image_generation", user_id=USER, projected_credits=80)
    assert exc.value.kind == "credits" and exc.value.offer == Offer(plans=("plus", "pro"))


async def test_an_instance_without_plans_passes_plan_checks_and_offers_nothing(account, monkeypatch):
    monkeypatch.setattr(plan_limits, "registered_plan_limits", lambda: None)
    await check_product(MockNativePool(), "video_generation", user_id=USER)
    plan_limits.get_effective_tier.assert_not_awaited()
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=80)
    assert exc.value.kind == "credits" and exc.value.offer == Offer() and not exc.value.offer


async def test_a_rollout_product_needs_its_rollout(account, monkeypatch):
    monkeypatch.setitem(gates.PRODUCTS, "beta", gates.Product("Beta thing", rollout="coordinator"))
    monkeypatch.setattr(gates, "is_feature_enabled", lambda feature, email: email == "staff@example.com")
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "beta", user_id=USER, email="someone@example.com")
    assert exc.value.kind == "gated" and not exc.value.offer
    await check_product(MockNativePool(), "beta", user_id=USER, email="staff@example.com")
