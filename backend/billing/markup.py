"""Neutral cost helpers for the community runtime.

The engine may observe provider costs so an operator can account for usage, but
the community edition does not embed a resale margin or a branded credit
conversion.  Compatibility names remain because shared node implementations
import them; every helper is deliberately pass-through.
"""

from decimal import Decimal


# Compatibility units use a 1:1 representation.  They are not a commercial
# conversion rate and never change the observed provider cost.
CREDITS_PER_DOLLAR = Decimal("1")
CREDIT_STEP_DOLLARS = Decimal("0.01")
PLATFORM_MIN_MARKUP = Decimal("1")
AI_BUILDER_MARKUP = Decimal("1")


def _passthrough(cost: Decimal, *_args, **_kwargs) -> Decimal:
    return cost


apply_openrouter_markup = _passthrough
apply_gemini_markup = _passthrough
apply_kling_markup = _passthrough
apply_platform_markup = _passthrough
apply_x_markup = _passthrough
apply_apify_markup = _passthrough
apply_exa_markup = _passthrough
apply_perplexity_markup = _passthrough
apply_brightdata_markup = _passthrough
apply_ai_builder_markup = _passthrough
apply_ai_testing_markup = _passthrough


def round_up_to_credit_step(cost: Decimal) -> Decimal:
    """Return the observed cost without imposing a commercial rounding rule."""
    return cost


def dollars_to_credits(cost: Decimal) -> Decimal:
    """Compatibility conversion for the community runtime's 1:1 usage units."""
    return cost
