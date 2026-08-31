"""Blast-radius bound for app-webhook trigger fires.

The self-echo guard (utils/slack_self_echo.py) catches NoClick-authored
echoes exactly, but no authorship/fingerprint check can see a TWO-PARTY loop:
NoClick posts, some external bot in the channel auto-replies, and that
genuinely foreign message re-triggers the workflow. This bounds every such
topology: a trigger node firing more than FIRE_BUDGET_MAX times per window
per channel is suppressed — loudly — until the window rolls.

Slack analogue of the email reply cap (nodes/agent/email_reply.py). Redis
errors fail open (an unbounded-but-credit-gated loop beats suppressing a
legitimately busy channel on a Redis blip).
"""

import logging
from typing import Optional

from utils.redis_client import get_shared_redis

logger = logging.getLogger(__name__)

# Tuning: a suppressed fire is a silently missed message for a legitimate
# channel agent, so the cap errs generous — 20 agent runs / 5 min is above any
# human-driven channel burst, while a runaway loop (agent turn ≈ 15-60s → a
# 2-party echo fires ~5-20×/window) is damped to 20 per window instead of
# running unbounded to the credit wall.
FIRE_BUDGET_MAX = 20
FIRE_BUDGET_WINDOW_SECONDS = 300


async def over_fire_budget(
    workflow_id: str, node_id: str, channel: Optional[str]
) -> bool:
    """Count this prospective fire against the (node, channel) window;
    True = over budget, caller must suppress the run."""
    client = get_shared_redis()
    if client is None:
        return False
    key = f"appwebhook:firebudget:{workflow_id}:{node_id}:{channel or 'any'}"
    try:
        # SET NX EX (not INCR+EXPIRE): creates the window key WITH its TTL
        # atomically, so a crash can't orphan a TTL-less counter — and unlike
        # EXPIRE NX it doesn't require Redis 7 (a 6.x server would error into
        # the fail-open path and silently disable the budget).
        await client.set(key, 0, ex=FIRE_BUDGET_WINDOW_SECONDS, nx=True)
        count = await client.incr(key)
        if count == 1:
            # The window can expire in the gap between SET NX (which saw the
            # key alive and no-op'd) and INCR, which then recreates it with
            # NO TTL — a counter that never rolls and, once past the cap,
            # suppresses the channel forever (2026-08-31 incident).
            # count == 1 marks every key INCR could have created; re-stamping
            # a legitimately fresh window's TTL is a harmless no-op.
            await client.expire(key, FIRE_BUDGET_WINDOW_SECONDS)
        if count <= FIRE_BUDGET_MAX:
            return False
        if await client.ttl(key) == -1:
            # Orphaned TTL-less counter (minted by the race above before the
            # heal existed): reset it into a fresh window instead of
            # suppressing the channel permanently.
            await client.set(key, 1, ex=FIRE_BUDGET_WINDOW_SECONDS)
            return False
        return True
    except Exception as e:
        logger.warning(f"[FireBudget] Check failed for {key}: {e}")
        return False
