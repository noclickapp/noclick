"""Markup applied to metered costs before they are recorded.

An installation running on its own provider keys adds nothing: costs are
recorded at provider list price, which is what the default below means. A
platform reselling those calls sets `PLATFORM_MARKUP` in its environment — the
margin is a deployment's commercial decision, not a property of the engine, and
it is the one number here that does not belong in source.
"""

import os
from decimal import Decimal, ROUND_CEILING

def _configured_credits_per_dollar() -> Decimal:
    """How many displayed credits a dollar of recorded cost is worth. An
    installation that bills nobody counts dollars (1); a platform selling
    credits sets `CREDITS_PER_DOLLAR` in its environment alongside its markup —
    a deployment's choice, not the engine's."""
    raw = (os.getenv("CREDITS_PER_DOLLAR") or "").strip()
    if not raw:
        return Decimal("1")
    value = Decimal(raw)
    if value <= 0:
        raise ValueError(f"CREDITS_PER_DOLLAR must be positive; got {raw!r}")
    return value


CREDITS_PER_DOLLAR = _configured_credits_per_dollar()

# Smallest displayed credit increment (0.01 credits), in dollars.
CREDIT_STEP_DOLLARS = Decimal("0.01") / CREDITS_PER_DOLLAR

def _configured_markup() -> Decimal:
    """The multiplier applied to platform-keyed costs. 1 = pass-through."""
    raw = (os.getenv("PLATFORM_MARKUP") or "").strip()
    if not raw:
        return Decimal("1")
    value = Decimal(raw)
    if value < 1:
        raise ValueError(
            f"PLATFORM_MARKUP must be >= 1 (pass-through); got {raw!r}. "
            "A multiplier below one would record less than the call cost."
        )
    return value


PLATFORM_MIN_MARKUP = _configured_markup()
AI_BUILDER_MARKUP = PLATFORM_MIN_MARKUP


def _apply_min_markup(cost: Decimal, user_resource: bool) -> Decimal:
    if user_resource or cost <= 0:
        return cost
    return cost * PLATFORM_MIN_MARKUP


def apply_openrouter_markup(cost: Decimal, user_resource: bool, model: str) -> Decimal:
    return _apply_min_markup(cost, user_resource)


def apply_gemini_markup(cost: Decimal, user_resource: bool, model: str) -> Decimal:
    return _apply_min_markup(cost, user_resource)


def apply_kling_markup(cost: Decimal, user_resource: bool, model: str) -> Decimal:
    return _apply_min_markup(cost, user_resource)


def apply_platform_markup(cost: Decimal, user_resource: bool, model: str) -> Decimal:
    return _apply_min_markup(cost, user_resource)


def apply_x_markup(cost: Decimal, user_resource: bool) -> Decimal:
    return _apply_min_markup(cost, user_resource)


def apply_apify_markup(cost: Decimal) -> Decimal:
    return _apply_min_markup(cost, False)


def apply_exa_markup(cost: Decimal) -> Decimal:
    return _apply_min_markup(cost, False)


def apply_perplexity_markup(cost: Decimal) -> Decimal:
    return _apply_min_markup(cost, False)


def apply_brightdata_markup(cost: Decimal) -> Decimal:
    return _apply_min_markup(cost, False)


def apply_modal_compute_markup(cost: Decimal) -> Decimal:
    return _apply_min_markup(cost, False)


def apply_ai_builder_markup(cost: Decimal) -> Decimal:
    if cost > 0:
        return cost * max(AI_BUILDER_MARKUP, PLATFORM_MIN_MARKUP)
    return cost


def apply_ai_testing_markup(cost: Decimal) -> Decimal:
    if cost > 0:
        return cost * PLATFORM_MIN_MARKUP
    return cost


def round_up_to_credit_step(cost: Decimal) -> Decimal:
    """Round a $ cost UP to the nearest 0.01-credit increment so metered charges
    land on clean credit numbers. Non-positive costs pass through unchanged."""
    if cost <= 0:
        return cost
    steps = (cost / CREDIT_STEP_DOLLARS).to_integral_value(rounding=ROUND_CEILING)
    return steps * CREDIT_STEP_DOLLARS


def dollars_to_credits(cost: Decimal) -> Decimal:
    """Convert a stored $ cost to credits (Decimal, may be fractional)."""
    return cost * CREDITS_PER_DOLLAR
