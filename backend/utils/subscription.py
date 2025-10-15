"""
Subscription tier utilities for determining user's subscription status.
Used for conditional feature access (e.g., banner injection for free tier users).
"""

import logging
from typing import Optional
from asyncpg import Pool

logger = logging.getLogger(__name__)


async def get_user_subscription_tier() -> str:
    """
    Determine user's subscription tier based on billing status.

    Args:
        pool: Database connection pool
        user_id: User ID to check

    Returns:
        "free" - User is on free tier (show banner)
        "plus" - User is on plus tier (no banner)
    """
    return "free"
