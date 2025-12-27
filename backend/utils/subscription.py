"""
Subscription tier utilities for determining user's subscription status.
Used for conditional feature access (e.g., banner injection for free tier users).
"""

import logging
from typing import Optional
from asyncpg import Pool

logger = logging.getLogger(__name__)


async def get_user_subscription_tier(user_data: dict) -> str:
    """
    Determine user's subscription tier from JWT payload.

    Args:
        user_data: JWT payload containing subscription_tier

    Returns:
        "free" - User is on free tier (show banner)
        "team" - User is on team tier (no banner)
    """
    return user_data.get("subscription_tier", "free")
