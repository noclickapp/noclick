"""Product gating in one place: which account may use a product, judged by
its rollout, its plan and its credits against what the use is projected to
cost. Add a product to PRODUCTS and call ``check_product``; never compare
tier names or balances at a call site.

Rollout names come from ``utils/feature_gates.py``. Plans are the effective
tier (the account's own or a paid org it owns). An instance without a plan
system (the open edition) passes every plan check, as its balances read as
unlimited.

A purchase paid for up front (a phone number, a domain) is judged on the
funds the account added (``funds_usd``: its monthly top-up left and its
balance), never the plan's included usage (which its charge may still draw
first), and needs at least ``PURCHASE_FLOOR_USD`` of them on any plan: it
should come from an account that has shown it can pay. The floor is the
product's ``min_credits``, under the purchase's own price.

A refusal says what would lift it (``GateDenied.offer``): the paid plans that
include the product, or the dollars of funds that would cover the shortfall
(on the old plans, ``bills_on_old_plans``: a monthly top-up; a free account
needs a plan first, and for a purchase a top-up on it too, since a plan's
included credits aren't funds). It names no prices and mints no links — the platform that sells
them does (``PURCHASES`` capability), and whoever relays the refusal to a
person relays the offer. A plan cap is reported as a sales signal (``PLAN_GATE_ALERT``).
What an account's work carries because of its plan (rather than something it
asked for) is read with ``plan_includes``: no refusal, no sales signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Literal, Optional, Tuple

from billing import plan_limits
from billing.markup import CREDITS_PER_DOLLAR
from billing.usage_tracker import usage_tracker
from repositories.users import get_user_profile
from utils.capabilities import PLAN_GATE_ALERT, capability
from utils.feature_gates import is_feature_enabled

# "cap": the monthly spending cap the paying account set (adding funds or a plan doesn't lift it).
GateKind = Literal["gated", "plan", "credits", "cap"]


@dataclass(frozen=True)
class Product:
    label: str
    rollout: Optional[str] = None      # a utils.feature_gates rollout key
    min_tier: Optional[str] = None     # "member" admits member, plus, pro and enterprise
    min_credits: float = 0.0           # a floor under any projected cost
    purchase: bool = False             # paid for up front: only funds the account added count


# The least funds the account added must hold before it may make a purchase paid for up front.
PURCHASE_FLOOR_USD = 5
_PURCHASE_FLOOR = PURCHASE_FLOOR_USD * float(CREDITS_PER_DOLLAR)

PRODUCTS: dict[str, Product] = {
    "image_generation": Product("Image generation"),
    "video_generation": Product("Video generation"),
    # Its rollout is enforced where its requests enter (phone_number_handler).
    "phone_numbers": Product("Phone numbers", min_credits=_PURCHASE_FLOOR, purchase=True),
    "domains": Product("Domains", min_credits=_PURCHASE_FLOOR, purchase=True),
}


async def funds_usd(conn, payer: str) -> Optional[Decimal]:
    """What the paying account added and hasn't spent, in dollars: its monthly top-up left
    and its balance (a debt lowers it). The plan's included usage is never funds, nor is
    balance the platform credited it rather than it paying (``referral_credit_usd``),
    which it spends but didn't add. None where usage is unlimited (no plan system, or an
    uncapped plan)."""
    return funds_in(await plan_limits.get_credit_usage(conn, payer))


def funds_in(usage: dict) -> Optional[Decimal]:
    """``funds_usd`` from a ``plan_limits.get_credit_usage`` reading already in hand."""
    if usage["total_credits_remaining"] is None:
        return None
    return (Decimal(str(usage["topup_credits_remaining"])) / CREDITS_PER_DOLLAR
            + Decimal(str(usage["balance_usd"])) - Decimal(str(usage.get("referral_credit_usd", 0))))


async def _remaining(pool, product: Product, payer: str) -> Optional[float]:
    """The credits ``payer`` can put toward ``product``; None when unlimited."""
    if not product.purchase:
        return await usage_tracker.fetch_credit_remaining(payer)
    async with pool.acquire() as conn:
        funds = await funds_usd(conn, payer)
    return None if funds is None else float(funds * CREDITS_PER_DOLLAR)


@dataclass(frozen=True)
class Offer:
    """What would lift the gate: the paid plans that include the product
    (lowest first), or what would cover a shortfall: the dollars of funds (the
    seller rounds them up to an amount it sells) or, on the old plans, the
    credits a monthly top-up would have to cover. Plans and a top-up together
    mean both: a free account on the old plans buying something takes a plan,
    then the top-up on it. Empty where nothing is for sale."""

    plans: Tuple[str, ...] = ()
    funds_usd: float = 0.0
    topup_credits: float = 0.0

    def __bool__(self) -> bool:
        return bool(self.plans) or self.funds_usd > 0 or self.topup_credits > 0


class GateDenied(PermissionError):
    def __init__(self, kind: GateKind, message: str, offer: Offer = Offer()):
        super().__init__(message)
        self.kind = kind
        self.offer = offer


def _dollars(credits: float, rounding: str) -> str:
    """Credits as a person reads them: $5, $4.99, -$1.20."""
    usd = (Decimal(str(credits)) / CREDITS_PER_DOLLAR).quantize(Decimal("0.01"), rounding=rounding)
    amount = f"{abs(usd):.0f}" if usd == usd.to_integral_value() else f"{abs(usd):.2f}"
    return f"{'-' if usd < 0 else ''}${amount}"


def _shortfall(product: Product, *, needed: float, remaining: float) -> str:
    """In dollars, what's needed rounded up and what's there rounded down, so a refusal never reads as enough;
    "at least" where the product's floor, not its price, is what's needed; a purchase says what counts."""
    floor = "at least " if needed <= product.min_credits else ""
    need, have = _dollars(needed, ROUND_CEILING), _dollars(remaining, ROUND_FLOOR)
    if product.purchase:
        return (f"Buying {product.label.lower()} needs {floor}{need} of funds the account added (included usage "
                f"doesn't count); it has {have}.")
    return f"The account needs {floor}{need} in its balance for {product.label.lower()}; it has {have}."


def _plan_names(plans: Tuple[str, ...]) -> str:
    return " and ".join(t.capitalize() for t in plans)


async def _plan_denied(conn, product: Product, *, user_id: str, tier: str) -> GateDenied:
    """The refusal, plus the sales signal every plan cap sends (the same
    fire-and-forget the workflow/credential caps send from their handlers)."""
    alert_plan_gate = capability(PLAN_GATE_ALERT)
    if alert_plan_gate is not None:
        profile = await get_user_profile(conn, user_id) or {}
        alert_plan_gate(
            {"email": profile.get("email") or "", "user_metadata": {"name": profile.get("label")}},
            f"{product.label} Gate Hit", {"Tier": tier},
        )
    plans = await plan_limits.plans_including(conn, user_id, product.min_tier)
    where = f"the {_plan_names(plans)} plan{'s' if len(plans) > 1 else ''}"
    return GateDenied("plan", f"{product.label} is available on {where}.", offer=Offer(plans=plans))


async def _short_of_plan(conn, min_tier: str, *, user_id: str,
                         personal_tier: Optional[str] = None) -> Optional[str]:
    """The account's effective tier when it's below ``min_tier``, else None."""
    personal = personal_tier or await plan_limits.get_user_tier_from_db(conn, user_id)
    tier = await plan_limits.get_effective_tier(conn, user_id, personal)
    return tier if plan_limits.TIER_RANK.get(tier, 0) < plan_limits.TIER_RANK[min_tier] else None


async def plan_includes(pool, product_key: str, *, user_id: str, organization_id: Optional[str] = None) -> bool:
    """Whether the plan of the account that pays for work (Owner Pays: the
    owner of ``organization_id``) includes a plan product. A read of what the
    work carries, not an attempt to use the product: it refuses nothing and
    sends no sales signal."""
    product = PRODUCTS[product_key]
    if not product.min_tier or plan_limits.registered_plan_limits() is None:
        return True
    payer = await usage_tracker.resolve_billing_user_id(user_id, organization_id)
    async with pool.acquire() as conn:
        return await _short_of_plan(conn, product.min_tier, user_id=payer) is None


async def bills_on_old_plans(db, *, user_id: str, organization_id: Optional[str] = None) -> bool:
    """Whether the account that pays for this work (Owner Pays: the owner of
    ``organization_id``) still bills on the platform's old plans, in credits:
    its offers, prices and wording stay the old ones until it moves. ``db`` is
    a pool or a connection."""
    payer = await usage_tracker.resolve_billing_user_id(user_id, organization_id)
    return await plan_limits.on_old_plans(db, payer)


async def credit_offer(pool, payer: str, shortfall_credits: float, *, purchase: bool = False) -> Offer:
    """What lifts ``payer``'s credit shortfall. Funds lift it on any plan,
    Free's daily cap included (it limits only the allowance). On the old plans
    a top-up only adds to a paid plan, so a free account needs a plan first;
    for a ``purchase``, judged on funds alone, the plan's included credits lift
    nothing, so it needs the top-up as well. Where nothing is sold there is
    nothing to offer."""
    if plan_limits.registered_plan_limits() is None:
        return Offer()
    async with pool.acquire() as conn:
        if not await plan_limits.on_old_plans(conn, payer):
            return Offer(funds_usd=round(shortfall_credits / float(CREDITS_PER_DOLLAR), 2))
        if await _short_of_plan(conn, "plus", user_id=payer) is not None:
            return Offer(plans=await plan_limits.plans_including(conn, payer, "plus"),
                         topup_credits=shortfall_credits if purchase else 0.0)
    return Offer(topup_credits=shortfall_credits)


async def check_product(
    pool, product_key: str, *, user_id: str, email: Optional[str] = None,
    projected_credits: Optional[float] = None, personal_tier: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> None:
    """Raise ``GateDenied`` unless the account may use the product now. Credits
    are checked on the account that pays (the owner of ``organization_id``,
    the org the work runs in, under Owner Pays), against the projected cost or
    the product's floor, whichever is more; for a purchase, only its funds.
    Before them, the paying account's monthly spending cap: reached, or crossed
    by the projected cost, it refuses (kind ``cap``) before anything is charged.
    ``personal_tier`` is the session's own tier when the caller has it."""
    product = PRODUCTS[product_key]
    if product.rollout and not is_feature_enabled(product.rollout, email=email):
        raise GateDenied("gated", f"{product.label} isn't available on this account yet.")
    if product.min_tier and plan_limits.registered_plan_limits() is not None:
        async with pool.acquire() as conn:
            short = await _short_of_plan(conn, product.min_tier, user_id=user_id, personal_tier=personal_tier)
            if short is not None:
                raise await _plan_denied(conn, product, user_id=user_id, tier=short)
    payer = await usage_tracker.resolve_billing_user_id(user_id, organization_id)
    price_usd = Decimal(str(projected_credits)) / CREDITS_PER_DOLLAR if projected_credits else None
    capped = await usage_tracker.spend_cap_refusal(payer, price_usd=price_usd)
    if capped is not None:
        raise GateDenied("cap", str(capped))
    needed = max(product.min_credits, projected_credits or 0.0)
    if needed > 0:
        remaining = await _remaining(pool, product, payer)
        if remaining is not None and remaining < needed:
            raise GateDenied("credits", _shortfall(product, needed=needed, remaining=remaining),
                             offer=await credit_offer(pool, payer, needed - remaining, purchase=product.purchase))
