"""billing/gates.py: the one place a product is judged against an account's
plan and credits. An instance with no plan system passes plan checks; a
projected cost is compared with the paying account's remaining credits, a
purchase (and its balance floor) with the funds it added alone. A refusal
carries what would lift it (``Offer``:
the plans that include the product, or the dollars of funds that cover a
shortfall; on the old plans a monthly top-up, or a plan for a free account)
and a plan cap is reported as a sales signal."""

from decimal import Decimal
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from billing import gates, plan_limits
from billing.gates import PURCHASE_FLOOR_USD, GateDenied, Offer, check_product
from billing.markup import CREDITS_PER_DOLLAR
from tests.mocks.mock_asyncpg import MockNativePool
from utils import capabilities

pytestmark = pytest.mark.asyncio
USER = "11111111-1111-1111-1111-111111111111"
CPD = float(CREDITS_PER_DOLLAR)
PLAN = "plan_thing"


def usd(dollars: float) -> float:
    """Dollars in the credits the gate reads."""
    return dollars * CPD


@pytest.fixture
def account(monkeypatch):
    # ``remaining``: credits the account can use (included usage too); ``funds``: dollars it added;
    # ``old_plans``: whether it still bills on the old plans (Plus/Pro) rather than Free/Member.
    state = {"tier": "free", "remaining": usd(12.5), "funds": 12.5, "old_plans": False}
    monkeypatch.setattr(plan_limits, "registered_plan_limits", lambda: object())
    monkeypatch.setattr(plan_limits, "on_old_plans", AsyncMock(side_effect=lambda conn, uid: state["old_plans"]))

    def plans_including(conn, uid, min_tier):
        """What the account's plans sell (cloud/billing/plan_limits.py): Member on Free/Member, Plus and Pro
        on the old plans, those at or above ``min_tier``."""
        sold = ("plus", "pro") if state["old_plans"] else ("member",)
        return tuple(plan for plan in sold if plan_limits.TIER_RANK[plan] >= plan_limits.TIER_RANK[min_tier])

    monkeypatch.setattr(plan_limits, "plans_including", AsyncMock(side_effect=plans_including))
    monkeypatch.setattr(plan_limits, "get_user_tier_from_db", AsyncMock(side_effect=lambda conn, uid: state["tier"]))
    monkeypatch.setattr(plan_limits, "get_effective_tier", AsyncMock(side_effect=lambda conn, uid, tier: tier))
    monkeypatch.setattr(gates.usage_tracker, "resolve_billing_user_id", AsyncMock(return_value="owner"))
    monkeypatch.setattr(gates.usage_tracker, "fetch_credit_remaining",
                        AsyncMock(side_effect=lambda uid: state["remaining"]))
    # ``capped``: the refusal the account's monthly spending cap makes (None: no cap, or under it).
    state["capped"] = None
    monkeypatch.setattr(gates.usage_tracker, "spend_cap_refusal",
                        AsyncMock(side_effect=lambda uid, price_usd=None: state["capped"]))
    monkeypatch.setattr(gates, "funds_usd", AsyncMock(
        side_effect=lambda conn, uid: None if state["funds"] is None else Decimal(str(state["funds"]))))
    monkeypatch.setattr(gates, "get_user_profile",
                        AsyncMock(return_value={"email": None, "name": None, "label": "sam"}))
    # A product only a plan includes (as a platform registers one: cloud/platform/projects/badge.py's unbranded pages).
    monkeypatch.setitem(gates.PRODUCTS, PLAN, gates.Product("Plan thing", min_tier="member"))
    return state


@pytest.fixture
def plan_cap_listener(monkeypatch):
    """The sales signal a platform that sells plans registers."""
    listener = MagicMock()
    monkeypatch.setattr(gates, "capability", {capabilities.PLAN_GATE_ALERT: listener}.get)
    return listener


async def test_a_plan_product_admits_paid_plans_only(account, plan_cap_listener):
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), PLAN, user_id=USER)
    assert exc.value.kind == "plan" and str(exc.value) == "Plan thing is available on the Member plan."
    # The refusal names the plans that include it, and the platform hears about the cap hit.
    assert exc.value.offer == Offer(plans=("member",)) and exc.value.offer
    plan_cap_listener.assert_called_once_with(
        {"email": "", "user_metadata": {"name": "sam"}}, "Plan thing Gate Hit", {"Tier": "free"})
    for tier in ("member", "plus", "pro", "enterprise"):
        account["tier"] = tier
        await check_product(MockNativePool(), PLAN, user_id=USER)
    # The session's own tier stands in for the database read when the caller has it.
    account["tier"] = "free"
    await check_product(MockNativePool(), PLAN, user_id=USER, personal_tier="pro")
    plan_cap_listener.assert_called_once()
    # On the old plans the same refusal names Plus and Pro, lowest first.
    account["old_plans"] = True
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), PLAN, user_id=USER)
    assert str(exc.value) == "Plan thing is available on the Plus and Pro plans."
    assert exc.value.offer == Offer(plans=("plus", "pro"))


async def test_a_plan_denial_without_a_listener_still_refuses(account, monkeypatch):
    monkeypatch.setattr(gates, "capability", lambda name: None)
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), PLAN, user_id=USER)
    assert exc.value.kind == "plan" and exc.value.offer.plans == ("member",)


async def test_numbers_domains_and_video_need_no_plan(account, plan_cap_listener):
    account["remaining"], account["funds"] = usd(PURCHASE_FLOOR_USD), PURCHASE_FLOOR_USD
    for product in ("phone_numbers", "domains", "video_generation"):
        await check_product(MockNativePool(), product, user_id=USER)
    plan_limits.get_effective_tier.assert_not_awaited()
    plan_cap_listener.assert_not_called()


@pytest.mark.parametrize("product, label", [("phone_numbers", "phone numbers"), ("domains", "domains")])
async def test_a_purchase_needs_five_dollars_in_the_balance_on_any_plan(account, plan_cap_listener, product, label):
    # A dollar short of nothing: $4.99 on Free is refused, in dollars, with funds to add and never a plan.
    account["funds"] = 4.99
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), product, user_id=USER)
    assert exc.value.kind == "credits"
    assert str(exc.value) == (f"Buying {label} needs at least $5 of funds the account added (included usage doesn't "
                              "count); it has $4.99.")
    assert exc.value.offer == Offer(funds_usd=0.01) and not exc.value.offer.plans
    gates.funds_usd.assert_awaited_with(ANY, "owner")
    # $5.00 is enough, on Free.
    account["funds"] = 5
    await check_product(MockNativePool(), product, user_id=USER)
    # Member is no way past it, and Free with the funds needs nothing more.
    account["tier"], account["funds"] = "member", 4.99
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), product, user_id=USER, personal_tier="member")
    assert exc.value.kind == "credits" and exc.value.offer == Offer(funds_usd=0.01)
    plan_cap_listener.assert_not_called()


async def test_a_purchase_above_the_floor_needs_its_own_price(account):
    # A $1.15 number with $5 in the balance is bought; a $7 one with $6 is refused for its price, not the floor.
    account["funds"] = 5
    await check_product(MockNativePool(), "phone_numbers", user_id=USER, projected_credits=usd(1.15))
    account["funds"] = 6
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "phone_numbers", user_id=USER, projected_credits=usd(7))
    assert str(exc.value) == ("Buying phone numbers needs $7 of funds the account added (included usage doesn't "
                              "count); it has $6.")
    assert exc.value.offer == Offer(funds_usd=1.0)


@pytest.mark.parametrize("product", ["phone_numbers", "domains"])
async def test_a_purchase_counts_only_funds_the_account_added(account, product):
    # $400 of included usage left and $2 of funds: the plan's own usage never pays for a purchase.
    account["remaining"], account["funds"] = usd(400), 2
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), product, user_id=USER, projected_credits=usd(1.15))
    assert exc.value.kind == "credits" and str(exc.value).endswith("it has $2.")
    assert exc.value.offer == Offer(funds_usd=3.0)
    gates.usage_tracker.fetch_credit_remaining.assert_not_awaited()
    # Usage that isn't a purchase still draws on everything left.
    await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=usd(300))


async def test_a_shortfall_never_reads_as_enough(account):
    # What's there rounds down and what's needed rounds up, so a refusal never shows two equal amounts.
    account["funds"] = 4.999
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "domains", user_id=USER)
    assert str(exc.value).endswith("it has $4.99.")
    account["funds"] = -1.2  # a debt
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "domains", user_id=USER)
    assert str(exc.value).endswith("it has -$1.20.") and exc.value.offer == Offer(funds_usd=6.2)


async def test_video_runs_on_free_when_the_clip_fits_the_balance(account, plan_cap_listener):
    account["remaining"] = usd(3)
    await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=usd(2.4))
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=usd(4))
    # No floor: only the clip's own cost is needed.
    assert exc.value.kind == "credits" and exc.value.offer == Offer(funds_usd=1.0)
    assert str(exc.value) == "The account needs $4 in its balance for video generation; it has $3."
    plan_cap_listener.assert_not_called()


async def test_the_projected_cost_is_checked_on_the_paying_account(account, plan_cap_listener):
    account["tier"] = "pro"
    await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=usd(12.375))
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=usd(20))
    assert exc.value.kind == "credits" and "$20" in str(exc.value) and "$12.50" in str(exc.value)
    gates.usage_tracker.fetch_credit_remaining.assert_awaited_with("owner")
    # The payer is resolved through the org the work runs in (Owner Pays).
    await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=1, organization_id="org")
    gates.usage_tracker.resolve_billing_user_id.assert_awaited_with(USER, "org")
    # Short of credits: the offer is the dollars of funds that cover the $7.50 shortfall.
    assert exc.value.offer == Offer(funds_usd=7.5)
    plan_cap_listener.assert_not_called()
    account["remaining"] = account["funds"] = None  # an unlimited balance
    await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=10_000)
    await check_product(MockNativePool(), "phone_numbers", user_id=USER)


async def test_the_paying_accounts_monthly_cap_refuses_before_credits_with_nothing_to_buy(account):
    from billing.exceptions import SpendCapReached

    account["capped"] = SpendCapReached("You've hit your $40 monthly cap, ...")
    account["remaining"] = 0  # short of credits too: the cap is what's said
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=usd(3),
                            organization_id="org")
    assert exc.value.kind == "cap" and str(exc.value).startswith("You've hit your $40 monthly cap")
    assert not exc.value.offer  # funds or a plan don't lift it: the owner raises it
    # Asked on the account that pays, with the price in dollars.
    gates.usage_tracker.spend_cap_refusal.assert_awaited_with("owner", price_usd=Decimal(3))
    gates.usage_tracker.fetch_credit_remaining.assert_not_awaited()


async def test_a_free_account_short_of_credits_is_offered_funds(account):
    # Funds lift a free account's limit too (its daily cap holds back only the allowance), so it gets the same offer.
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "image_generation", user_id=USER, projected_credits=usd(20))
    assert exc.value.kind == "credits" and exc.value.offer == Offer(funds_usd=7.5)
    assert exc.value.offer


async def test_an_instance_without_plans_passes_plan_checks_and_offers_nothing(account, monkeypatch):
    monkeypatch.setattr(plan_limits, "registered_plan_limits", lambda: None)
    await check_product(MockNativePool(), PLAN, user_id=USER)
    plan_limits.get_effective_tier.assert_not_awaited()
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "video_generation", user_id=USER, projected_credits=usd(20))
    assert exc.value.kind == "credits" and exc.value.offer == Offer() and not exc.value.offer


async def test_a_rollout_product_needs_its_rollout(account, monkeypatch):
    monkeypatch.setitem(gates.PRODUCTS, "beta", gates.Product("Beta thing", rollout="coordinator"))
    monkeypatch.setattr(gates, "is_feature_enabled", lambda feature, email: email == "staff@example.com")
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "beta", user_id=USER, email="someone@example.com")
    assert exc.value.kind == "gated" and not exc.value.offer
    await check_product(MockNativePool(), "beta", user_id=USER, email="staff@example.com")


async def test_what_a_plan_includes_is_read_on_the_paying_account_without_refusing_or_signalling(
        account, plan_cap_listener, monkeypatch):
    from billing.gates import plan_includes

    tiers = {"owner": "free", USER: "pro"}
    plan_limits.get_user_tier_from_db.side_effect = lambda conn, uid: tiers[uid]
    # Owner Pays: the organization's owner pays, so its plan is the one read.
    assert not await plan_includes(MockNativePool(), PLAN, user_id=USER, organization_id="org-1")
    gates.usage_tracker.resolve_billing_user_id.assert_awaited_with(USER, "org-1")
    tiers["owner"] = "member"
    assert await plan_includes(MockNativePool(), PLAN, user_id=USER, organization_id="org-1")
    plan_cap_listener.assert_not_called()
    tiers["owner"] = "free"
    for no_plan_floor in ("image_generation", "video_generation", "phone_numbers"):
        assert await plan_includes(MockNativePool(), no_plan_floor, user_id=USER, organization_id="org-1")
    monkeypatch.setattr(plan_limits, "registered_plan_limits", lambda: None)
    assert await plan_includes(MockNativePool(), PLAN, user_id=USER)


async def test_on_the_old_plans_a_credit_shortfall_is_offered_a_topup_or_a_plan(account):
    """Main's offers until the account moves to Free/Member: a paid plan tops up,
    a free one needs a plan first (the old plans sell it no funds), and for a
    purchase a top-up on it too, since a plan's included credits aren't funds.
    Judged on the account that pays."""
    account["old_plans"] = True
    account["tier"] = "pro"
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "image_generation", user_id=USER, projected_credits=usd(20))
    assert exc.value.kind == "credits" and exc.value.offer == Offer(topup_credits=usd(7.5)) and exc.value.offer
    plan_limits.on_old_plans.assert_awaited_with(ANY, "owner")
    # Usage on Free: a plan's included credits lift it.
    account["tier"], account["remaining"] = "free", usd(1)
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "image_generation", user_id=USER, projected_credits=usd(2))
    assert exc.value.offer == Offer(plans=("plus", "pro"))
    # A purchase on Free: a plan alone lifts nothing, so the offer is a plan and a top-up on it...
    account["funds"] = 1
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "phone_numbers", user_id=USER)
    assert exc.value.kind == "credits" and exc.value.offer == Offer(plans=("plus", "pro"), topup_credits=usd(4))
    # ...as taking Plus without the top-up shows: still refused, now offered the top-up alone.
    account["tier"], account["remaining"] = "plus", usd(25)
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "phone_numbers", user_id=USER, personal_tier="plus")
    assert exc.value.offer == Offer(topup_credits=usd(4))
    assert "included usage doesn't count" in str(exc.value)
    # A paid old plan's included credits never buy anything: its shortfall is a top-up's.
    account["tier"], account["remaining"], account["funds"] = "pro", usd(400), 0
    with pytest.raises(GateDenied) as exc:
        await check_product(MockNativePool(), "domains", user_id=USER, projected_credits=usd(12))
    assert str(exc.value) == ("Buying domains needs $12 of funds the account added (included usage doesn't count); "
                              "it has $0.")
    assert exc.value.offer == Offer(topup_credits=usd(12))


async def test_bills_on_old_plans_reads_the_paying_account(account):
    from billing.gates import bills_on_old_plans

    account["old_plans"] = True
    assert await bills_on_old_plans(MockNativePool(), user_id=USER, organization_id="org-1")
    gates.usage_tracker.resolve_billing_user_id.assert_awaited_with(USER, "org-1")
    plan_limits.on_old_plans.assert_awaited_with(ANY, "owner")
    account["old_plans"] = False
    assert not await bills_on_old_plans(MockNativePool(), user_id=USER)


@pytest.mark.asyncio
async def test_funds_read_a_usage_answer_that_names_no_credit_from_friends(monkeypatch):
    """A plan-limits implementation that keeps no friends' credit leaves it out of its usage answer."""
    monkeypatch.setattr(gates.plan_limits, "get_credit_usage", AsyncMock(return_value={
        "total_credits_remaining": 40.0, "topup_credits_remaining": 8.0, "balance_usd": 3.0}))
    assert await gates.funds_usd(object(), "payer") == Decimal("8") / CREDITS_PER_DOLLAR + Decimal("3")
