"""Optional instance-policy seam with permissive community defaults.

Shared handlers ask this module whether an operation is allowed.  Without a
registered operator policy every operation is uncapped and no database-backed
commercial tier or allowance is consulted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


_impl: Optional[Any] = None
PLAN_LIMITS: Dict[str, Dict[str, Optional[int]]] = {"community": {}}


def register_plan_limits(impl: Any) -> None:
    global _impl
    _impl = impl


def registered_plan_limits() -> Optional[Any]:
    return _impl


def get_limit(tier: str, limit_key: str) -> Optional[int]:
    if _impl is None:
        return None
    return _impl.get_limit(tier, limit_key)


async def _delegate(name: str, default, *args, **kwargs):
    if _impl is None:
        return default
    return await getattr(_impl, name)(*args, **kwargs)


async def get_user_tier_from_db(conn, user_id: str) -> str:
    if _impl is None:
        return "community"
    return await _impl.get_user_tier_from_db(conn, user_id)


async def get_context_tier(conn, user_id: str) -> str:
    if _impl is None:
        return "community"
    return await _impl.get_context_tier(conn, user_id)


async def get_effective_tier(conn, user_id: str, user_tier: str) -> str:
    if _impl is None:
        return "community"
    return await _impl.get_effective_tier(conn, user_id, user_tier)


async def check_organization_limit(
    conn, user_id: str, *args, **kwargs
) -> Tuple[bool, Optional[str]]:
    return await _delegate(
        "check_organization_limit", (True, None), conn, user_id, *args, **kwargs
    )


async def check_workflow_limit(
    conn, user_id: str, user_tier: str, *args, **kwargs
) -> Tuple[bool, Optional[str]]:
    return await _delegate(
        "check_workflow_limit", (True, None), conn, user_id, user_tier, *args, **kwargs
    )


async def check_credential_limit(
    conn, user_id: str, user_tier: str, *args, **kwargs
) -> Tuple[bool, Optional[str]]:
    return await _delegate(
        "check_credential_limit", (True, None), conn, user_id, user_tier, *args, **kwargs
    )


async def check_checkpoint_limit(
    conn, user_id: str, *args, **kwargs
) -> Tuple[bool, Optional[str]]:
    return await _delegate(
        "check_checkpoint_limit", (True, None), conn, user_id, *args, **kwargs
    )


async def check_saved_output_limit(
    conn, user_id: str, *args, **kwargs
) -> Tuple[bool, Optional[str]]:
    return await _delegate(
        "check_saved_output_limit", (True, None), conn, user_id, *args, **kwargs
    )


async def check_ai_builder_limit(
    conn, user_id: str, *args, **kwargs
) -> Tuple[bool, Optional[str]]:
    return await _delegate(
        "check_ai_builder_limit", (True, None), conn, user_id, *args, **kwargs
    )


async def get_credit_usage(conn, user_id: str) -> Dict[str, Any]:
    if _impl is not None:
        return await _impl.get_credit_usage(conn, user_id)

    # Compatibility response for shared account-usage consumers. Every limit
    # is unbounded and every counter is empty.
    now = datetime.now(timezone.utc).isoformat()
    return {
        "tier": "community",
        "base_credits": None,
        "daily_credits_used": 0.0,
        "daily_credit_cap": None,
        "monthly_credits_used": 0.0,
        "monthly_credit_cap": None,
        "plan_credits_used": 0.0,
        "plan_credits_remaining": None,
        "total_credits_remaining": None,
        "plan_credits_period_end": None,
        "plan_window_start": now,
    }
