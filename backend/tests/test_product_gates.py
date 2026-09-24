"""billing/gates.py: the one place a product is judged against an account's
plan and credits. An instance with no plan system passes plan checks; a
projected cost is compared with the paying account's remaining credits."""

from unittest.mock import AsyncMock

import pytest

from billing import gates, plan_limits
from billing.gates import GateDenied, check_product
from tests.mocks.mock_asyncpg import MockNativePool

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
    return state


async def test_a_plan_product_admits_paid_plans_only(account):
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER)
    assert exc.value.kind == "plan" and "Plus and Pro" in str(exc.value)
    for tier in ("plus", "pro", "enterprise"):
        account["tier"] = tier
        await check_product(MockNativePool(), "video_generation", user_id=USER)
    # The session's own tier stands in for the database read when the caller has it.
    account["tier"] = "free"
    await check_product(MockNativePool(), "video_generation", user_id=USER, personal_tier="pro")


async def test_the_projected_cost_is_checked_on_the_paying_account(account):
    account["tier"] = "pro"
    await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=49.5)
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=80)
    assert exc.value.kind == "credits" and "80 credits" in str(exc.value) and "50.0" in str(exc.value)
    gates.usage_tracker.fetch_credit_remaining.assert_awaited_with("owner")
    account["remaining"] = None  # an unlimited balance
    await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=10_000)


async def test_an_instance_without_plans_passes_plan_checks(account, monkeypatch):
    monkeypatch.setattr(plan_limits, "registered_plan_limits", lambda: None)
    await check_product(MockNativePool(), "video_generation", user_id=USER)
    plan_limits.get_effective_tier.assert_not_awaited()


async def test_a_rollout_product_needs_its_rollout(account, monkeypatch):
    monkeypatch.setitem(gates.PRODUCTS, "beta", gates.Product("Beta thing", rollout="coordinator"))
    monkeypatch.setattr(gates, "is_feature_enabled", lambda feature, email: email == "staff@example.com")
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "beta", user_id=USER, email="someone@example.com")
    assert exc.value.kind == "gated"
    await check_product(MockNativePool(), "beta", user_id=USER, email="staff@example.com")
