"""Recording what a run cost.

The engine meters work and hands the event here. What happens next is the
platform's business: a ledger row and a balance check if it is charging for the
work, a debug line if it is not. The default does the latter — an installation
running on its own provider keys has nobody to bill.

`usage_tracker` is a proxy rather than the implementation, because forty-eight
call sites do `from billing.usage_tracker import usage_tracker` and bind the
name at import. Registering the real tracker swaps what the proxy forwards to,
so those bindings stay correct however the imports are ordered — which matters,
because the failure mode is silent: a stale binding means a platform records
nothing and charges nobody, and every call still returns cleanly.
"""

import logging
from contextvars import ContextVar
from typing import Any, Optional

from cachetools import TTLCache

from .schema import UsageEventData

logger = logging.getLogger(__name__)

# Minimum credits required to start a metered run. Nothing is metered by
# default; a platform's tracker enforces its own floor.
MIN_CREDITS = 0.0

# Kept for import compatibility with cache-invalidation call sites.
CREDIT_USAGE_CACHE = TTLCache(maxsize=16, ttl=60)
ORG_OWNER_CACHE = TTLCache(maxsize=16, ttl=60)

# Workflow attribution for usage events emitted mid-run.
CURRENT_WORKFLOW_ID: ContextVar[Optional[str]] = ContextVar(
    "billing_workflow_id", default=None
)


def invalidate_credit_cache(user_id: str) -> None:
    CREDIT_USAGE_CACHE.pop(user_id, None)


class UsageTracker:
    """Records nothing, charges nothing, allows everything.

    Balances read as None — "unlimited", which every caller already treats as
    "no reason to stop" — rather than as a large number that would eventually
    run out and surprise someone.
    """

    def __init__(self, usage_dashboard_handler=None):
        self.usage_dashboard_handler = usage_dashboard_handler

    async def resolve_billing_user_id(
        self, user_id: str, organization_id: Optional[str] = None
    ) -> str:
        return user_id

    async def resolve_billing_user_id_strict(
        self, user_id: str, organization_id: Optional[str] = None
    ) -> str:
        return user_id

    async def get_org_owner_id(self, org_id: str) -> Optional[str]:
        """The organization's owner, or None. Nothing is billed here, but the
        builder still attributes an organization's runs to its owner, so this
        is a real lookup rather than a stub answering None for every org."""
        if org_id in ORG_OWNER_CACHE:
            return ORG_OWNER_CACHE[org_id]
        from utils.database_pool import get_native_pool

        owner_id = await get_native_pool().fetchval(
            "SELECT user_id FROM organization_members "
            "WHERE organization_id = $1 AND role = 'owner' LIMIT 1",
            org_id,
        )
        if owner_id is None:
            return None
        ORG_OWNER_CACHE[org_id] = str(owner_id)
        return ORG_OWNER_CACHE[org_id]

    async def track_usage_event(self, usage_event: UsageEventData, sio=None, sid=None):
        logger.debug(
            f"[usage] {usage_event.usage_type}/{usage_event.usage_subtype} "
            f"cost=${usage_event.total_cost} (not recorded — no billing backend)"
        )

    async def track_container_usage_atomic(
        self, usage_event: UsageEventData, event_id: str, sio=None, sid=None
    ):
        await self.track_usage_event(usage_event, sio=sio, sid=sid)

    async def check_credit_balance(self, user_id: str, use_cache: bool = True):
        return None  # None = unlimited; callers treat it as "always ok"

    async def fetch_credit_remaining(self, user_id: str):
        return None  # a definitive read: unlimited

    async def enforce_credit_gate(
        self,
        user_id: str,
        *,
        organization_id: Optional[str] = None,
        sio=None,
        sid: Optional[str] = None,
        caller_user_id: Optional[str] = None,
        user_resource: bool = False,
        surface: str = "agent",
        message: Optional[str] = None,
        min_credits: float = MIN_CREDITS,
    ) -> None:
        return None  # always passes


class _UsageTrackerProxy:
    """Forwards to whatever is registered, resolved per attribute access."""

    def __init__(self, default: UsageTracker):
        self._impl: UsageTracker = default

    def __getattr__(self, name: str) -> Any:
        return getattr(self._impl, name)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics
        return f"<usage_tracker -> {type(self._impl).__name__}>"


usage_tracker = _UsageTrackerProxy(UsageTracker())


def register_usage_tracker(impl: Any) -> None:
    """Point the proxy at a platform's tracker. Call before serving traffic."""
    usage_tracker._impl = impl
    logger.info(f"[usage] Tracker registered: {type(impl).__name__}")


def registered_usage_tracker() -> Any:
    """The implementation currently behind the proxy (tests, diagnostics)."""
    return usage_tracker._impl
