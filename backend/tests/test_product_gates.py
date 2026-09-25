"""billing/gates.py: the one place a product is judged against an account's
plan and credits. An instance with no plan system passes plan checks; a
projected cost is compared with the paying account's remaining credits. A
refusal carries the way past it (the plans page, the credit CTA) and a plan
cap is reported as a sales signal."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from billing import gates, plan_limits
from billing.gates import GateDenied, check_product
from tests.mocks.mock_asyncpg import MockNativePool
from utils import capabilities

pytestmark = pytest.mark.asyncio
USER = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def account(monkeypatch):
    state = {"tier": "free", "remaining": 50.0}
    monkeypatch.setattr(plan_limits, "registered_plan_limits", lambda: object())
    monkeypatch.setattr(plan_limits, "upgrade_url", lambda tier: f"https://app.example.test/upgrade?plan={tier}")
    monkeypatch.setattr(plan_limits, "get_user_tier_from_db", AsyncMock(side_effect=lambda conn, uid: state["tier"]))
    monkeypatch.setattr(plan_limits, "get_effective_tier", AsyncMock(side_effect=lambda conn, uid, tier: tier))
    monkeypatch.setattr(gates.usage_tracker, "resolve_billing_user_id", AsyncMock(return_value="owner"))
    monkeypatch.setattr(gates.usage_tracker, "fetch_credit_remaining",
                        AsyncMock(side_effect=lambda uid: state["remaining"]))
    monkeypatch.setattr(gates, "get_user_profile",
                        AsyncMock(return_value={"email": None, "name": None, "label": "sam"}))
    return state


@pytest.fixture
def platform(monkeypatch):
    """What a platform that sells plans registers: a plan-cap listener and a credit CTA."""
    provided = {capabilities.PLAN_GATE_ALERT: MagicMock(),
                capabilities.CREDIT_CTA: AsyncMock(return_value=("See Plans", "https://app.example.test/pricing"))}
    monkeypatch.setattr(gates, "capability", provided.get)
    return provided


async def test_a_plan_product_admits_paid_plans_only(account, platform):
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER)
    assert exc.value.kind == "plan" and "Plus and Pro" in str(exc.value)
    # The refusal carries one-tap checkout for the lowest plan that includes the
    # product, and the platform hears about the cap hit.
    assert exc.value.next_step == "Upgrade to Plus: https://app.example.test/upgrade?plan=plus"
    platform[capabilities.PLAN_GATE_ALERT].assert_called_once_with(
        {"email": "", "user_metadata": {"name": "sam"}}, "Video generation Gate Hit", {"Tier": "free"})
    for tier in ("plus", "pro", "enterprise"):
        account["tier"] = tier
        await check_product(MockNativePool(), "video_generation", user_id=USER)
    # The session's own tier stands in for the database read when the caller has it.
    account["tier"] = "free"
    await check_product(MockNativePool(), "video_generation", user_id=USER, personal_tier="pro")
    platform[capabilities.PLAN_GATE_ALERT].assert_called_once()


async def test_a_plan_denial_without_a_listener_still_refuses(account, monkeypatch):
    monkeypatch.setattr(gates, "capability", lambda name: None)
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER)
    assert exc.value.kind == "plan" and exc.value.next_step == "Upgrade to Plus: https://app.example.test/upgrade?plan=plus"


async def test_the_projected_cost_is_checked_on_the_paying_account(account, platform):
    account["tier"] = "pro"
    await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=49.5)
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=80)
    assert exc.value.kind == "credits" and "80 credits" in str(exc.value) and "50.0" in str(exc.value)
    assert exc.value.next_step == "See Plans: https://app.example.test/pricing"
    gates.usage_tracker.fetch_credit_remaining.assert_awaited_with("owner")
    platform[capabilities.CREDIT_CTA].assert_awaited_once()
    assert platform[capabilities.CREDIT_CTA].await_args.args == ("owner",)
    platform[capabilities.PLAN_GATE_ALERT].assert_not_called()
    account["remaining"] = None  # an unlimited balance
    await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=10_000)


async def test_a_credit_denial_without_a_cta_has_no_next_step(account, monkeypatch):
    monkeypatch.setattr(gates, "capability", lambda name: None)
    account["tier"] = "pro"
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=80)
    assert exc.value.kind == "credits" and exc.value.next_step == ""


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
