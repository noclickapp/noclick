"""Plan limits — self-hosted edition: everything is unlimited.

Keeps the hosted edition's import surface (limit checks, tier helpers, window
math) so shared engine code runs unchanged; every gate passes and every cap
reads as unlimited (None). The window helpers are real date math — the usage
dashboard uses them for display even when nothing is capped.
"""

from datetime import datetime, timedelta
import logging
from typing import Any, Dict, Optional, Tuple

from .clock import billing_now, billing_month_start_utc

# Caps are None = unlimited across the board.
logger = logging.getLogger(__name__)

# Set by register_plan_limits() below.
_impl = None

PLAN_LIMITS: Dict[str, Dict[str, Optional[int]]] = {
    "free": {},
    "plus": {},
    "pro": {},
    "enterprise": {},
}

TIER_RANK = {"free": 0, "plus": 1, "pro": 2, "enterprise": 3}

# Org tiers owned by a user (paid, non-personal orgs). Used by credit-tier
# resolution; functional so org-aware call sites behave.
OWNED_ORG_TIERS_SQL = """
    SELECT o.subscription_tier
      FROM organization_members om
      JOIN organizations o ON o.id = om.organization_id
     WHERE om.user_id = $1
       AND om.role = 'owner'
       AND o.is_personal_workspace = false
       AND o.subscription_tier <> 'free'
"""


def get_limit(tier: str, limit_key: str) -> Optional[int]:
    """The cap for a tier, or None for uncapped.

    The table below is the uncapped one an installation without billing runs
    on. A platform's own limits arrive with its registration — and this has to
    ask for them rather than read PLAN_LIMITS directly, or every caller silently
    reads the free tier.
    """
    if _impl is not None:
        return _impl.get_limit(tier, limit_key)
    return PLAN_LIMITS.get(tier, {}).get(limit_key)


def resolve_credit_tier(personal_tier: Optional[str], owned_org_tiers) -> str:
    best = personal_tier or "free"
    for tier in owned_org_tiers or []:
        t = tier["subscription_tier"] if isinstance(tier, dict) else tier
        if TIER_RANK.get(t, 0) > TIER_RANK.get(best, 0):
            best = t
    return best


def _add_months(dt, months: int):
    """Add `months` calendar months to a datetime, clamping the day to the
    target month's length (so Jan 31 + 1 month = Feb 28/29, matching how Stripe
    anchors monthly billing on short months)."""
    import calendar
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def monthly_window_start(anchor, now):
    """Start of the CURRENT monthly credit window, given the plan's billing-cycle
    anchor (Stripe current_period_start) and the current time.

    Plan credits are granted PER MONTH regardless of the billing interval. For a
    monthly subscription the Stripe period already advances ~monthly so this is a
    no-op. For an ANNUAL subscription the Stripe period spans a full year — using
    it directly as the SUM lower bound caps the user at one month's allowance for
    the whole year. Rolling the anchor forward in whole-month steps to the latest
    anniversary <= now gives the user a fresh monthly allowance on their billing
    day-of-month. Returns None when anchor is None (caller falls back to UTC
    calendar month)."""
    if anchor is None:
        return None
    if now < anchor:
        # Clock skew / not-yet-started cycle — the anchor is the safe lower bound.
        return anchor
    months = (now.year - anchor.year) * 12 + (now.month - anchor.month)
    candidate = _add_months(anchor, months)
    if candidate > now:
        candidate = _add_months(anchor, months - 1)
    return candidate


def topup_window_start(period_end, now):
    """Start of the CURRENT monthly topup window, derived by rolling the topup
    coverage `period_end` BACKWARD in whole months to the latest boundary <= now.

    A topup grants its quota PER MONTH regardless of billing interval. For a
    monthly topup the boundaries are one month apart so this is the prior billing
    day; for a YEARLY topup (period_end a year out) the same backward roll still
    lands on the current month's billing day — so a yearly topup resets monthly
    within its prepaid year instead of only on the annual invoice. Mirror of
    monthly_window_start (which rolls a past anchor forward); here the anchor is
    the future coverage end, so we roll back. Caller invokes this only while
    within coverage (period_end > now). Returns None when period_end is None."""
    if period_end is None:
        return None
    months = (period_end.year - now.year) * 12 + (period_end.month - now.month)
    candidate = _add_months(period_end, -months)
    if candidate > now:
        candidate = _add_months(period_end, -(months + 1))
    return candidate


def topup_window_end(period_end, now):
    """End of the CURRENT monthly topup window — i.e. the topup's next monthly
    quota reset. Computed directly off `period_end` (one ladder step above
    topup_window_start's result) so day-clamping matches the window math:
    stepping the clamped start forward with _add_months would drift on 29-31
    anchors (Feb 28 + 1mo = Mar 28, but the true boundary is Mar 31). Caller
    invokes this only while within coverage (period_end > now). Returns None
    when period_end is None (pre-ledger rollout; caller falls back to the UTC
    calendar month)."""
    if period_end is None:
        return None
    months = (period_end.year - now.year) * 12 + (period_end.month - now.month)
    candidate = _add_months(period_end, -months)
    if candidate > now:
        months += 1
    return _add_months(period_end, -(months - 1))


def _format_tier_name(tier: str) -> str:
    return (tier or "free").capitalize()


# ── The gates ────────────────────────────────────────────────────────────────
# Whether an account may create another workflow, spend another builder credit,
# keep another checkpoint. An installation that bills nobody has no reason to
# refuse, so the default answers yes to all of them; a platform registers its
# own limits. Each returns (allowed, reason) — a refusal carries the sentence
# shown to the user.


def register_plan_limits(impl) -> None:
    """Install a platform's limit enforcement. Call before serving traffic."""
    global _impl
    _impl = impl
    logger.info(f"[plan_limits] Registered: {type(impl).__name__}")


def registered_plan_limits():
    return _impl


async def _delegate(name: str, default, *args, **kwargs):
    if _impl is None:
        return default
    return await getattr(_impl, name)(*args, **kwargs)


async def get_user_tier_from_db(conn, user_id: str) -> str:
    if _impl is not None:
        return await _impl.get_user_tier_from_db(conn, user_id)
    row = await conn.fetchrow(
        "SELECT subscription_tier FROM user_billing WHERE id = $1", user_id,
    )
    return (row["subscription_tier"] if row else None) or "free"


async def get_context_tier(conn, user_id) -> str:
    if _impl is not None:
        return await _impl.get_context_tier(conn, user_id)
    return await get_user_tier_from_db(conn, user_id)


async def get_effective_tier(conn, user_id: str, user_tier: str) -> str:
    if _impl is not None:
        return await _impl.get_effective_tier(conn, user_id, user_tier)
    return user_tier or "free"


async def check_organization_limit(conn, user_id: str, *args, **kwargs) -> Tuple[bool, Optional[str]]:
    return await _delegate("check_organization_limit", (True, None), conn, user_id, *args, **kwargs)


async def check_workflow_limit(conn, user_id: str, user_tier: str, *args, **kwargs) -> Tuple[bool, Optional[str]]:
    return await _delegate("check_workflow_limit", (True, None), conn, user_id, user_tier, *args, **kwargs)


async def check_credential_limit(conn, user_id: str, user_tier: str, *args, **kwargs) -> Tuple[bool, Optional[str]]:
    return await _delegate("check_credential_limit", (True, None), conn, user_id, user_tier, *args, **kwargs)


async def check_checkpoint_limit(conn, user_id: str, *args, **kwargs) -> Tuple[bool, Optional[str]]:
    return await _delegate("check_checkpoint_limit", (True, None), conn, user_id, *args, **kwargs)


async def check_saved_output_limit(conn, user_id: str, *args, **kwargs) -> Tuple[bool, Optional[str]]:
    return await _delegate("check_saved_output_limit", (True, None), conn, user_id, *args, **kwargs)


async def check_ai_builder_limit(conn, user_id: str, *args, **kwargs) -> Tuple[bool, Optional[str]]:
    return await _delegate("check_ai_builder_limit", (True, None), conn, user_id, *args, **kwargs)


async def get_credit_usage(conn, user_id: str) -> Dict[str, Any]:
    """Unlimited pools: caps and remaining read as None (the UI renders a None
    cap as uncapped) and the counters are zero."""
    if _impl is not None:
        return await _impl.get_credit_usage(conn, user_id)
    now = billing_now()
    return {
        "tier": await get_user_tier_from_db(conn, user_id),
        "base_credits": None,
        "topup_credits": 0,
        "daily_credits_used": 0.0,
        "daily_credit_cap": None,
        "monthly_credits_used": 0.0,
        "monthly_credit_cap": None,
        "plan_credits_used": 0.0,
        "plan_credits_remaining": None,
        "topup_credits_remaining": 0.0,
        "topup_credits_period_end": None,
        "topup_active": False,
        "total_credits_remaining": None,
        "plan_credits_period_end": None,
        "plan_window_start": billing_month_start_utc(now).isoformat(),
        "topup_next_reset_at": None,
    }
