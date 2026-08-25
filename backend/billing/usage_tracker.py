"""Optional metering sink with no-op community defaults."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, Optional

from cachetools import TTLCache

from .schema import UsageEventData


logger = logging.getLogger(__name__)
MIN_CREDITS = 0.0
CREDIT_USAGE_CACHE = TTLCache(maxsize=16, ttl=60)
ORG_OWNER_CACHE = TTLCache(maxsize=16, ttl=60)
CURRENT_WORKFLOW_ID: ContextVar[Optional[str]] = ContextVar(
    "metering_workflow_id", default=None
)


def invalidate_credit_cache(user_id: str) -> None:
    CREDIT_USAGE_CACHE.pop(user_id, None)


class UsageTracker:
    """Default sink: record nothing and reject nothing."""

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

    async def track_usage_event(self, usage_event: UsageEventData, sio=None, sid=None):
        logger.debug(
            "[usage] %s/%s quantity=%s",
            usage_event.usage_type,
            usage_event.usage_subtype,
            usage_event.quantity,
        )

    async def track_container_usage_atomic(
        self, usage_event: UsageEventData, event_id: str, sio=None, sid=None
    ):
        await self.track_usage_event(usage_event, sio=sio, sid=sid)

    async def check_credit_balance(self, user_id: str, use_cache: bool = True):
        return None

    async def fetch_credit_remaining(self, user_id: str):
        return None

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
        return None


class _UsageTrackerProxy:
    def __init__(self, default: UsageTracker):
        self._impl: Any = default

    def __getattr__(self, name: str) -> Any:
        return getattr(self._impl, name)


usage_tracker = _UsageTrackerProxy(UsageTracker())


def register_usage_tracker(impl: Any) -> None:
    usage_tracker._impl = impl


def registered_usage_tracker() -> Any:
    return usage_tracker._impl
