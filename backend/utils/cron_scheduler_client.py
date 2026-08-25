"""
Client for interacting with the configured cron scheduler API.
Used to create, update, and delete cron schedules for workflow cron nodes,
and to create one-time alarms for agent-initiated wake-ups.
"""

import os
import re
import secrets
import uuid
import logging
import httpx
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# A bare ``python backend/server.py`` is a supported community deployment, not
# only the launch scripts which happen to inject these values.  In that edition
# the scheduler is mounted in this same process, so derive its loopback URL and
# an unguessable process-local API secret when the operator did not override
# them.  Hosted deployments remain explicit and fail closed when either value
# is absent.
if os.getenv("NOCLICK_LOCAL") == "1":
    CRON_SCHEDULER_URL = os.getenv("CRON_SCHEDULER_URL") or (
        f"http://127.0.0.1:{os.getenv('PORT', '8000')}/local-cron"
    )
    CRON_SCHEDULER_SECRET = os.getenv("CRON_SCHEDULER_SECRET") or secrets.token_urlsafe(32)
    # local_cron reads the secret from the environment at request time. Assign
    # it even when an env file contained ``CRON_SCHEDULER_SECRET=``; setdefault
    # would preserve that empty value and make every in-process call return 401.
    os.environ["CRON_SCHEDULER_SECRET"] = CRON_SCHEDULER_SECRET
else:
    CRON_SCHEDULER_URL = os.getenv("CRON_SCHEDULER_URL", "")
    CRON_SCHEDULER_SECRET = os.getenv("CRON_SCHEDULER_SECRET", "")


def is_cron_scheduler_enabled() -> bool:
    """Check if cron scheduler is configured."""
    return bool(CRON_SCHEDULER_URL and CRON_SCHEDULER_SECRET)


# Fixed namespace for deriving deterministic schedule ids.
_SCHEDULE_ID_NAMESPACE = uuid.UUID("b1e7a3f0-4c2d-4b6a-9f3e-2d8c1a5b7e90")


def deterministic_schedule_id(workflow_id: str, node_id: str, slot: int = 0) -> str:
    """Stable schedule id for a (workflow, node, slot) triple.

    The same inputs always yield the same id, so re-registering a node's
    schedules upserts the existing rows instead of minting new ones. This is
    what makes concurrent/repeated registration idempotent — N simultaneous
    loads converge to one row per slot rather than N duplicates.
    """
    return str(uuid.uuid5(_SCHEDULE_ID_NAMESPACE, f"{workflow_id}:{node_id}:{slot}"))


async def register_node_schedules(
    *,
    user_id: str,
    workflow_id: str,
    node_id: str,
    webhook_url: str,
    cron_expressions: List[str],
    payload: Optional[Dict[str, Any]] = None,
    timezone: str = "UTC",
    source: str = "trigger",
) -> Dict[str, Any]:
    """Idempotently (re)register a node's cron schedules — the ONE chokepoint
    every trigger node should use. Do not hand-roll create/update/delete.

    Each expression in ``cron_expressions`` is upserted under a DETERMINISTIC id
    keyed by (workflow, node, slot), then every other schedule for the node is
    pruned (keep_ids = the desired set). Stable ids mean concurrent/repeated
    calls converge to one row per slot instead of creating duplicates; a
    shrunk/empty set cleans up its excess. If we intended to register schedules
    but EVERY create failed (transient), the prune is skipped so we never delete
    the node's existing live schedule with nothing to replace it — important
    while migrating legacy random-id rows, whose ids aren't in the desired set
    and would otherwise be pruned on a failed re-create.

    Returns ``{schedule_ids, schedule_id, next_run, is_active}`` where
    ``schedule_id`` is the first id (convenience for single-schedule nodes).
    No-ops (all empty) when the scheduler is unconfigured or webhook_url is falsy.
    """
    if not (is_cron_scheduler_enabled() and webhook_url):
        return {"schedule_ids": [], "schedule_id": None, "next_run": None, "is_active": False}

    schedule_ids: List[str] = []
    desired_ids: List[str] = []
    next_runs: List[str] = []

    for slot, cron_expression in enumerate(cron_expressions):
        sched_id = deterministic_schedule_id(workflow_id, node_id, slot)
        desired_ids.append(sched_id)
        result = await create_schedule(
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
            cron_expression=cron_expression,
            webhook_url=webhook_url,
            payload=payload if payload is not None else {"source": source, "node_id": node_id},
            timezone=timezone,
            schedule_id=sched_id,
        )
        if "id" in result:
            schedule_ids.append(result["id"])
            if result.get("next_run"):
                next_runs.append(result["next_run"])
        elif "error" in result:
            logger.warning(
                f"[register_node_schedules] node={node_id} slot={slot} failed: {result['error']}"
            )

    # Prune stale/duplicate schedules for this node (keep the desired set).
    # Skip ONLY when we wanted schedules but every create failed transiently —
    # pruning then would delete the still-live (possibly legacy-id) row with no
    # replacement. An empty desired set (cron disabled) still prunes everything.
    if schedule_ids or not cron_expressions:
        await delete_schedules_for_nodes(workflow_id, [node_id], keep_ids=desired_ids)

    return {
        "schedule_ids": schedule_ids,
        "schedule_id": schedule_ids[0] if schedule_ids else None,
        "next_run": min(next_runs) if next_runs else None,
        "is_active": bool(schedule_ids),
    }


async def delete_schedules_for_nodes(
    workflow_id: str,
    node_ids: List[str],
    keep_ids: Optional[List[str]] = None,
    timeout: float = 10.0
) -> Dict[str, Any]:
    """
    Delete cron schedules for the specified nodes in a workflow.

    Args:
        workflow_id: The workflow ID
        node_ids: List of node IDs whose schedules should be deleted
        keep_ids: When provided, delete only schedules NOT in this set (prune-by-
            exclusion). Used by idempotent re-registration to drop stale/duplicate
            schedules while preserving the current desired ones. Omit (or empty)
            to delete ALL schedules for the nodes (genuine node/workflow removal).
        timeout: Request timeout in seconds

    Returns:
        Dict with 'deleted' count and 'deleted_schedules' list, or 'error' on failure
    """
    if not is_cron_scheduler_enabled():
        logger.debug("Cron scheduler not configured, skipping schedule deletion")
        return {"deleted": 0, "skipped": True}

    if not node_ids:
        return {"deleted": 0}

    try:
        async with httpx.AsyncClient() as client:
            body: Dict[str, Any] = {"workflow_id": workflow_id, "node_ids": node_ids}
            if keep_ids:
                body["keep_ids"] = keep_ids
            response = await client.post(
                f"{CRON_SCHEDULER_URL}/schedules/bulk-delete-nodes",
                json=body,
                headers={
                    "Authorization": f"Bearer {CRON_SCHEDULER_SECRET}",
                    "Content-Type": "application/json"
                },
                timeout=timeout
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(
                    f"Deleted {result.get('deleted', 0)} cron schedules for "
                    f"workflow {workflow_id}, nodes: {node_ids}"
                )
                return result
            else:
                logger.error(
                    f"Failed to delete cron schedules: {response.status_code} - {response.text}"
                )
                return {"deleted": 0, "error": f"HTTP {response.status_code}"}

    except httpx.TimeoutException:
        logger.error(f"Timeout deleting cron schedules for workflow {workflow_id}")
        return {"deleted": 0, "error": "Timeout"}
    except Exception as e:
        logger.error(f"Error deleting cron schedules: {e}", exc_info=True)
        return {"deleted": 0, "error": str(e)}


async def delete_schedules_for_workflow(
    workflow_id: str,
    timeout: float = 10.0
) -> Dict[str, Any]:
    """
    Delete all cron schedules for a workflow.
    Called when a workflow is deleted.

    Args:
        workflow_id: The workflow ID
        timeout: Request timeout in seconds

    Returns:
        Dict with 'deleted' count, or 'error' on failure
    """
    if not is_cron_scheduler_enabled():
        logger.debug("Cron scheduler not configured, skipping workflow schedule deletion")
        return {"deleted": 0, "skipped": True}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{CRON_SCHEDULER_URL}/schedules/by-workflow/{workflow_id}",
                headers={
                    "Authorization": f"Bearer {CRON_SCHEDULER_SECRET}"
                },
                timeout=timeout
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(
                    f"Deleted {result.get('deleted', 0)} cron schedules for workflow {workflow_id}"
                )
                return result
            else:
                logger.error(
                    f"Failed to delete workflow cron schedules: {response.status_code} - {response.text}"
                )
                return {"deleted": 0, "error": f"HTTP {response.status_code}"}

    except httpx.TimeoutException:
        logger.error(f"Timeout deleting workflow cron schedules for {workflow_id}")
        return {"deleted": 0, "error": "Timeout"}
    except Exception as e:
        logger.error(f"Error deleting workflow cron schedules: {e}", exc_info=True)
        return {"deleted": 0, "error": str(e)}


async def list_schedules(
    workflow_id: str,
    timeout: float = 10.0
) -> Any:
    """
    List all schedules for a workflow.

    Args:
        workflow_id: The workflow ID to filter by
        timeout: Request timeout in seconds

    Returns:
        List of schedule dicts on success, or dict with 'error' on failure
    """
    if not is_cron_scheduler_enabled():
        logger.debug("Cron scheduler not configured, skipping schedule list")
        return {"error": "Cron scheduler not configured", "skipped": True}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{CRON_SCHEDULER_URL}/schedules",
                params={"workflow_id": workflow_id},
                headers={
                    "Authorization": f"Bearer {CRON_SCHEDULER_SECRET}"
                },
                timeout=timeout
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(
                    f"Failed to list schedules: {response.status_code} - {response.text}"
                )
                return {"error": f"HTTP {response.status_code}"}

    except httpx.TimeoutException:
        logger.error(f"Timeout listing schedules for workflow {workflow_id}")
        return {"error": "Timeout"}
    except Exception as e:
        logger.error(f"Error listing schedules: {e}", exc_info=True)
        return {"error": str(e)}


async def delete_schedule(
    schedule_id: str,
    timeout: float = 10.0
) -> Dict[str, Any]:
    """
    Delete a single schedule by ID.

    Args:
        schedule_id: The schedule ID to delete
        timeout: Request timeout in seconds

    Returns:
        Dict with 'deleted' count, or 'error' on failure
    """
    if not is_cron_scheduler_enabled():
        logger.debug("Cron scheduler not configured, skipping schedule delete")
        return {"error": "Cron scheduler not configured", "skipped": True}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{CRON_SCHEDULER_URL}/schedules/{schedule_id}",
                headers={
                    "Authorization": f"Bearer {CRON_SCHEDULER_SECRET}"
                },
                timeout=timeout
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Deleted schedule {schedule_id}: {result}")
                return result
            elif response.status_code == 404:
                return {"error": "Schedule not found"}
            else:
                logger.error(
                    f"Failed to delete schedule: {response.status_code} - {response.text}"
                )
                return {"error": f"HTTP {response.status_code}"}

    except httpx.TimeoutException:
        logger.error(f"Timeout deleting schedule {schedule_id}")
        return {"error": "Timeout"}
    except Exception as e:
        logger.error(f"Error deleting schedule: {e}", exc_info=True)
        return {"error": str(e)}


async def get_schedule(
    schedule_id: str,
    timeout: float = 10.0
) -> Dict[str, Any]:
    """
    Get a schedule by ID.

    Args:
        schedule_id: The schedule ID
        timeout: Request timeout in seconds

    Returns:
        Dict with schedule data, or 'error' on failure
    """
    if not is_cron_scheduler_enabled():
        logger.debug("Cron scheduler not configured, skipping schedule get")
        return {"error": "Cron scheduler not configured", "skipped": True}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{CRON_SCHEDULER_URL}/schedules/{schedule_id}",
                headers={
                    "Authorization": f"Bearer {CRON_SCHEDULER_SECRET}"
                },
                timeout=timeout
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return {"error": "Schedule not found"}
            else:
                logger.error(
                    f"Failed to get cron schedule: {response.status_code} - {response.text}"
                )
                return {"error": f"HTTP {response.status_code}"}

    except httpx.TimeoutException:
        logger.error(f"Timeout getting cron schedule {schedule_id}")
        return {"error": "Timeout"}
    except Exception as e:
        logger.error(f"Error getting cron schedule: {e}", exc_info=True)
        return {"error": str(e)}


async def create_schedule(
    user_id: str,
    workflow_id: str,
    node_id: str,
    cron_expression: str,
    webhook_url: str,
    payload: Optional[Dict[str, Any]] = None,
    max_attempts: int = 3,
    timeout: float = 10.0,
    timezone: str = "UTC",
    schedule_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new cron schedule for a workflow node.

    Args:
        user_id: The user ID
        workflow_id: The workflow ID
        node_id: The node ID
        cron_expression: Cron expression (e.g., "0 * * * *" for hourly)
        webhook_url: URL to call when cron fires
        payload: Optional payload to send with webhook
        max_attempts: Number of retry attempts on failure
        timeout: Request timeout in seconds
        timezone: IANA timezone for the cron schedule (e.g., "US/Eastern")
        schedule_id: Optional caller-supplied stable id. When set, the worker
            upserts this id instead of minting a new row, so repeated/concurrent
            creates of the same logical schedule converge to one row (idempotent).

    Returns:
        Dict with 'id' and 'next_run' on success, or 'error' on failure
    """
    if not is_cron_scheduler_enabled():
        logger.debug("Cron scheduler not configured, skipping schedule creation")
        return {"error": "Cron scheduler not configured", "skipped": True}

    try:
        async with httpx.AsyncClient() as client:
            body: Dict[str, Any] = {
                "user_id": user_id,
                "workflow_id": workflow_id,
                "node_id": node_id,
                "cron_expression": cron_expression,
                "webhook_url": webhook_url,
                "payload": payload,
                "max_attempts": max_attempts,
                "timezone": timezone,
            }
            if schedule_id:
                body["id"] = schedule_id
            response = await client.post(
                f"{CRON_SCHEDULER_URL}/schedules",
                json=body,
                headers={
                    "Authorization": f"Bearer {CRON_SCHEDULER_SECRET}",
                    "Content-Type": "application/json"
                },
                timeout=timeout
            )

            if response.status_code == 201:
                result = response.json()
                logger.info(
                    f"Created cron schedule {result.get('id')} for "
                    f"workflow {workflow_id}, node {node_id}"
                )
                return result
            else:
                logger.error(
                    f"Failed to create cron schedule: {response.status_code} - {response.text}"
                )
                return {"error": f"HTTP {response.status_code}: {response.text}"}

    except httpx.TimeoutException:
        logger.error(f"Timeout creating cron schedule for node {node_id}")
        return {"error": "Timeout"}
    except Exception as e:
        logger.error(f"Error creating cron schedule: {e}", exc_info=True)
        return {"error": str(e)}


async def update_schedule(
    schedule_id: str,
    cron_expression: Optional[str] = None,
    webhook_url: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    enabled: Optional[bool] = None,
    max_attempts: Optional[int] = None,
    timeout: float = 10.0
) -> Dict[str, Any]:
    """
    Update an existing cron schedule.

    Args:
        schedule_id: The schedule ID
        cron_expression: New cron expression (optional)
        webhook_url: New webhook URL (optional)
        payload: New payload (optional)
        enabled: Enable/disable schedule (optional)
        max_attempts: New retry count (optional)
        timeout: Request timeout in seconds

    Returns:
        Dict with 'success' on success, or 'error' on failure
    """
    if not is_cron_scheduler_enabled():
        logger.debug("Cron scheduler not configured, skipping schedule update")
        return {"error": "Cron scheduler not configured", "skipped": True}

    # Build update payload with only provided fields
    update_data: Dict[str, Any] = {}
    if cron_expression is not None:
        update_data["cron_expression"] = cron_expression
    if webhook_url is not None:
        update_data["webhook_url"] = webhook_url
    if payload is not None:
        update_data["payload"] = payload
    if enabled is not None:
        update_data["enabled"] = enabled
    if max_attempts is not None:
        update_data["max_attempts"] = max_attempts

    if not update_data:
        return {"error": "No updates provided"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{CRON_SCHEDULER_URL}/schedules/{schedule_id}",
                json=update_data,
                headers={
                    "Authorization": f"Bearer {CRON_SCHEDULER_SECRET}",
                    "Content-Type": "application/json"
                },
                timeout=timeout
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Updated cron schedule {schedule_id}")
                return {"success": True, "next_run": result.get("next_run")}
            else:
                logger.error(
                    f"Failed to update cron schedule: {response.status_code} - {response.text}"
                )
                return {"error": f"HTTP {response.status_code}"}

    except httpx.TimeoutException:
        logger.error(f"Timeout updating cron schedule {schedule_id}")
        return {"error": "Timeout"}
    except Exception as e:
        logger.error(f"Error updating cron schedule: {e}", exc_info=True)
        return {"error": str(e)}


# ============================================================================
# One-time Alarm Support
# ============================================================================

_COUNTDOWN_PATTERN = re.compile(r'^(\d+)\s*(s|m|h|d)$', re.IGNORECASE)
_COUNTDOWN_MULTIPLIERS = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}


def parse_countdown_to_timestamp(delay: str) -> str:
    """
    Parse a human-readable delay string into an ISO 8601 UTC timestamp.

    Supported formats: '30s', '5m', '2h', '1d' (seconds, minutes, hours, days).

    Args:
        delay: Duration string like '30m', '2h', '1d'

    Returns:
        ISO 8601 UTC timestamp string

    Raises:
        ValueError: If the delay format is invalid or duration is non-positive
    """
    match = _COUNTDOWN_PATTERN.match(delay.strip())
    if not match:
        raise ValueError(
            f"Invalid countdown format: '{delay}'. "
            "Use a number followed by s (seconds), m (minutes), h (hours), or d (days). "
            "Examples: '30s', '5m', '2h', '1d'"
        )

    amount = int(match.group(1))
    unit = match.group(2).lower()

    if amount <= 0:
        raise ValueError(f"Countdown duration must be positive, got {amount}")

    seconds = amount * _COUNTDOWN_MULTIPLIERS[unit]
    run_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return run_at.isoformat()


async def create_alarm(
    user_id: str,
    workflow_id: str,
    node_id: str,
    run_at: str,
    webhook_url: str,
    payload: Optional[Dict[str, Any]] = None,
    max_attempts: int = 3,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """
    Create a one-time alarm that fires at a specific timestamp and auto-deletes.

    Args:
        user_id: The user ID
        workflow_id: The workflow ID
        node_id: The alarm node ID
        run_at: ISO 8601 timestamp for when the alarm should fire
        webhook_url: URL to call when alarm fires
        payload: Payload to include in the webhook (e.g., alarm message)
        max_attempts: Number of delivery retry attempts
        timeout: Request timeout in seconds

    Returns:
        Dict with 'id' and 'next_run' on success, or 'error' on failure
    """
    if not is_cron_scheduler_enabled():
        logger.debug("Cron scheduler not configured, skipping alarm creation")
        return {"error": "Cron scheduler not configured", "skipped": True}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{CRON_SCHEDULER_URL}/schedules",
                json={
                    "user_id": user_id,
                    "workflow_id": workflow_id,
                    "node_id": node_id,
                    "cron_expression": "__run_at__",
                    "webhook_url": webhook_url,
                    "payload": payload,
                    "max_attempts": max_attempts,
                    "run_once": True,
                    "run_at": run_at,
                },
                headers={
                    "Authorization": f"Bearer {CRON_SCHEDULER_SECRET}",
                    "Content-Type": "application/json"
                },
                timeout=timeout
            )

            if response.status_code == 201:
                result = response.json()
                logger.info(
                    f"Created one-time alarm {result.get('id')} for "
                    f"workflow {workflow_id}, node {node_id}, fires at {run_at}"
                )
                return result
            else:
                logger.error(
                    f"Failed to create alarm: {response.status_code} - {response.text}"
                )
                return {"error": f"HTTP {response.status_code}: {response.text}"}

    except httpx.TimeoutException:
        logger.error(f"Timeout creating alarm for node {node_id}")
        return {"error": "Timeout"}
    except Exception as e:
        logger.error(f"Error creating alarm: {e}", exc_info=True)
        return {"error": str(e)}
