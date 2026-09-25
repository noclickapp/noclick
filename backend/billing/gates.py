"""Product gating in one place: which account may use a product, judged by
its rollout, its plan and its credits against what the use is projected to
cost. Add a product to PRODUCTS and call ``check_product``; never compare
tier names or balances at a call site.

Rollout names come from ``utils/feature_gates.py``. Plans are the effective
tier (the account's own or a paid org it owns). An instance without a plan
system (the open edition) passes every plan check, as its balances read as
unlimited.

A refusal says what the account can do about it: a plan denial carries the
platform's plans page and is reported as a sales signal (``PLAN_GATE_ALERT``),
a credit denial carries the platform's own top-up or upgrade link
(``CREDIT_CTA``). Whoever relays the refusal to a person relays both.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from billing import plan_limits
from billing.usage_tracker import usage_tracker
from repositories.users import get_user_profile
from utils.capabilities import CREDIT_CTA, PLAN_GATE_ALERT, capability
from utils.feature_gates import is_feature_enabled

GateKind = Literal["gated", "plan", "credits"]


@dataclass(frozen=True)
class Product:
    label: str
    rollout: Optional[str] = None      # a utils.feature_gates rollout key
    min_tier: Optional[str] = None     # "plus" admits plus, pro and enterprise
    min_credits: float = 0.0           # a floor under any projected cost


PRODUCTS: dict[str, Product] = {
    "image_generation": Product("Image generation"),
    "video_generation": Product("Video generation", min_tier="plus"),
    # Its rollout is enforced where its requests enter (phone_number_handler).
    "phone_numbers": Product("Phone numbers", min_tier="plus"),
}


class GateDenied(PermissionError):
    """``next_step`` is the sentence that says what the account can do about
    it (an upgrade or top-up link); "" where the instance sells nothing."""

    def __init__(self, kind: GateKind, message: str, next_step: str = ""):
        super().__init__(message)
        self.kind = kind
        self.next_step = next_step


def _plan_names(min_tier: str) -> str:
    ranked = [t for t, r in sorted(plan_limits.TIER_RANK.items(), key=lambda kv: kv[1])
              if r >= plan_limits.TIER_RANK[min_tier] and t != "enterprise"]
    return " and ".join(t.capitalize() for t in ranked)


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
    return GateDenied(
        "plan", f"{product.label} is available on the {_plan_names(product.min_tier)} plans.",
        next_step=f"Upgrade: {plan_limits.plans_url()}",
    )


async def check_product(
    pool, product_key: str, *, user_id: str, email: Optional[str] = None,
    projected_credits: Optional[float] = None, personal_tier: Optional[str] = None,
) -> None:
    """Raise ``GateDenied`` unless the account may use the product now. Credits
    are checked on the account that pays (the org owner under Owner Pays).
    ``personal_tier`` is the session's own tier when the caller has it."""
    product = PRODUCTS[product_key]
    if product.rollout and not is_feature_enabled(product.rollout, email=email):
        raise GateDenied("gated", f"{product.label} isn't available on this account yet.")
    if product.min_tier and plan_limits.registered_plan_limits() is not None:
        async with pool.acquire() as conn:
            personal = personal_tier or await plan_limits.get_user_tier_from_db(conn, user_id)
            tier = await plan_limits.get_effective_tier(conn, user_id, personal)
            if plan_limits.TIER_RANK.get(tier, 0) < plan_limits.TIER_RANK[product.min_tier]:
                raise await _plan_denied(conn, product, user_id=user_id, tier=tier)
    needed = max(product.min_credits, projected_credits or 0.0)
    if needed > 0:
        payer = await usage_tracker.resolve_billing_user_id(user_id)
        remaining = await usage_tracker.fetch_credit_remaining(payer)
        if remaining is not None and remaining < needed:
            cta = capability(CREDIT_CTA)
            label, url = await cta(payer, pool=pool) if cta is not None else ("", "")
            raise GateDenied(
                "credits",
                f"{product.label} needs {round(needed, 1):g} credits and the account has {remaining:.1f}.",
                next_step=f"{label}: {url}" if url else "",
            )
