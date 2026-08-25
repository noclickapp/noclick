"""Stop active workflow executions through the local relay."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import List

from repositories.workflow import WorkflowRepo
from utils.local_relay import get_local_relay_hub

logger = logging.getLogger(__name__)


async def request_execution_stops(
    workflow_id: str,
    user_id: str,
    execution_ids: List[str],
) -> int:
    del workflow_id, user_id
    hub = get_local_relay_hub()
    for execution_id in execution_ids:
        hub.fire_stop(execution_id)
    return len(execution_ids)


async def _running_execution_ids(pool, workflow_id: str) -> List[str]:
    async with pool.acquire() as conn:
        return await WorkflowRepo(pool).list_running_execution_ids(conn, workflow_id)


async def stop_running_workflow_executions(
    pool,
    workflow_id: str,
    user_id: str,
    *,
    timeout_s: float = 8.0,
    poll_interval_s: float = 0.25,
) -> List[str]:
    running = await _running_execution_ids(pool, workflow_id)
    if not running:
        return []

    deadline = time.monotonic() + timeout_s
    while running:
        try:
            await request_execution_stops(workflow_id, user_id, running)
        except Exception as exc:
            logger.warning(
                "Failed to request execution stops for workflow %s: %s",
                workflow_id,
                exc,
            )
        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0:
            return running
        await asyncio.sleep(min(poll_interval_s, remaining_s))
        running = await _running_execution_ids(pool, workflow_id)
    return []
