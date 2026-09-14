"""Durable, replaceable deadlines for missing-update monitoring.

An on-time update replaces a watch before scheduling its next deadline. Old
or duplicate timer deliveries are discarded atomically, across containers.
"""
from datetime import datetime, timezone
import logging
import uuid

from nodes.alarm_node import AlarmNode

logger = logging.getLogger(__name__)


def _state_node(workflow_id, alarm_node_id):
    return AlarmNode(
        node_id=alarm_node_id,
        node_type="alarm",
        node_data={},
        config=None,
        workflow_id=workflow_id,
        sio=None,
        sid=None,
    )


def _timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(
            "A reporting deadline must include its timezone (ISO 8601 offset)."
        )
    return parsed.astimezone(timezone.utc)


def _now():
    return datetime.now(timezone.utc)


def _identity(agent_node_id, watch_key):
    if not isinstance(watch_key, str) or not watch_key.strip() or len(watch_key) > 200:
        raise ValueError(
            "watch_key must identify the monitored site (1–200 characters)."
        )
    return f"{agent_node_id}:{watch_key}"


async def schedule_watch(
    *, node, alarm_node_id, watch_key, observed_at, run_at, webhook_url, payload
):
    """Reserve the latest observed update, schedule once, then publish its ID.

    Scheduler failure is explicit and leaves the watch unarmed. It must not
    resurrect the previous deadline and alert about an update already received.
    """
    from utils.cron_scheduler_client import create_alarm, delete_schedule

    deadline = _timestamp(run_at)
    now = _now()
    observed = _timestamp(observed_at) if observed_at else None
    if deadline <= now:
        raise ValueError("The next reporting deadline must be in the future.")
    if observed and (observed > now or observed >= deadline):
        raise ValueError(
            "observed_at must be the real update timestamp, no later than now and before the deadline."
        )
    identity = _identity(node.node_id, watch_key)
    state_node = _state_node(node.workflow_id, alarm_node_id)
    token = str(uuid.uuid4())

    def reserve(state):
        watches = dict(state.get("deadline_watches") or {})
        previous = watches.get(identity) or {}
        last_seen = previous.get("last_seen_at")
        # Replayed/out-of-order inbound messages cannot postpone a deadline.
        # A failed scheduling attempt may be explicitly retried with the same
        # observation, but a preparing/armed/fired watch is not re-created.
        if (
            observed
            and last_seen
            and (
                observed < _timestamp(last_seen)
                or (
                    observed == _timestamp(last_seen)
                    and previous.get("status") not in ("error", "cancelled", "paused")
                )
            )
        ):
            return None, {"reserved": False, "watch": previous}
        if (
            not observed
            and previous
            and previous.get("status") not in ("error", "cancelled", "paused")
        ):
            return None, {"reserved": False, "watch": previous}
        if len(watches) >= 1000 and identity not in watches:
            raise ValueError(
                "This Alarm node already tracks 1,000 sites; use a separate Alarm node."
            )
        watch = {
            "token": token,
            "status": "preparing",
            "deadline": deadline.isoformat(),
            "agent_node_id": node.node_id,
            "watch_key": watch_key,
            "last_seen_at": observed.isoformat() if observed else last_seen,
            "armed_at": now.isoformat(),
        }
        watches[identity] = watch
        return {**state, "deadline_watches": watches}, {
            "reserved": True,
            "previous": previous,
            "watch": watch,
        }

    reserved = await state_node._update_node_state(reserve)
    if not reserved["reserved"]:
        watch = reserved["watch"]
        return {
            "success": watch["status"] in ("armed", "fired"),
            "status": watch["status"],
            "schedule_id": watch.get("schedule_id"),
            "next_run": watch["deadline"],
            "message": "This update is already recorded; the existing deadline was preserved.",
        }

    async def finish(status, **extra):
        def mutate(state):
            watches = dict(state.get("deadline_watches") or {})
            current = watches.get(identity) or {}
            if current.get("token") != token:
                return None, False
            watches[identity] = {**current, "status": status, **extra}
            return {**state, "deadline_watches": watches}, True

        return await state_node._update_node_state(mutate)

    watch_payload = {**payload, "deadline_watch": {"key": watch_key, "token": token}}
    try:
        result = await create_alarm(
            user_id=node.user_id,
            workflow_id=str(node.workflow_id),
            node_id=alarm_node_id,
            run_at=deadline.isoformat(),
            webhook_url=webhook_url,
            payload=watch_payload,
        )
        if result.get("error") or not result.get("id"):
            raise RuntimeError(result.get("error") or "Scheduler returned no alarm ID.")
    except Exception as error:
        await finish("error", error=str(error))
        return {
            "success": False,
            "error": f"Missing-update check is not armed: {error}",
        }

    current = await finish("armed", schedule_id=result["id"])
    stale_id = (
        (reserved.get("previous") or {}).get("schedule_id") if current else result["id"]
    )
    if stale_id:
        try:
            removed = await delete_schedule(schedule_id=stale_id)
            if removed.get("error"):
                logger.warning("Stale watch timer cleanup failed: %s", removed["error"])
        except Exception:
            # State is authoritative: even if cleanup fails, this old token
            # can never wake the agent. Keep the new successfully armed timer.
            logger.warning("Stale watch timer cleanup failed", exc_info=True)
    return {
        "success": True,
        "status": "armed" if current else "superseded",
        "schedule_id": result["id"],
        "next_run": deadline.isoformat(),
        "watch_key": watch_key,
        "last_seen_at": reserved["watch"]["last_seen_at"],
        "message": "Missing-update deadline armed."
        if current
        else "A newer update replaced this deadline.",
    }


async def claim_watch_delivery(workflow_id, alarm_node_id, agent_node_id, payload):
    """Ordinary alarms pass through; a current due watch dispatches once.

    Runs after webhook authentication and graph lookup. The agent identity
    comes from the saved edge, never from an untrusted payload's agent ID.
    """
    data = payload.get("payload") or payload
    watch_ref = data.get("deadline_watch")
    if watch_ref is None:
        return True
    if not agent_node_id or not isinstance(watch_ref, dict):
        return False
    identity = _identity(agent_node_id, watch_ref.get("key"))
    state_node = _state_node(workflow_id, alarm_node_id)
    now = _now()

    def claim(state):
        watches = dict(state.get("deadline_watches") or {})
        watch = watches.get(identity) or {}
        if watch.get("token") != watch_ref.get("token") or watch.get("status") in (
            "fired",
            "error",
            "cancelled",
            "paused",
        ):
            return None, False
        if watch.get("status") != "armed" or now < _timestamp(watch["deadline"]):
            raise RuntimeError(
                "Deadline watch is not due yet; retry this timer delivery."
            )
        watches[identity] = {**watch, "status": "fired", "fired_at": now.isoformat()}
        return {**state, "deadline_watches": watches}, True

    return await state_node._update_node_state(claim)


async def set_watch_schedule_status(node, alarm_node_id, schedule_id, status):
    """Keep queued deliveries consistent with cancel/disable, not just CF state."""
    state_node = _state_node(node.workflow_id, alarm_node_id)

    def update(state):
        watches = dict(state.get("deadline_watches") or {})
        changed = False
        for identity, watch in watches.items():
            if (
                watch.get("schedule_id") != schedule_id
                or watch.get("agent_node_id") != node.node_id
            ):
                continue
            if status == "armed":
                if (
                    watch.get("status") == "fired"
                    or _timestamp(watch["deadline"]) <= _now()
                ):
                    raise ValueError(
                        "This reporting deadline has passed. Arm a new deadline instead of re-enabling it."
                    )
            watches[identity] = {**watch, "status": status}
            changed = True
        return (
            ({**state, "deadline_watches": watches}, None) if changed else (None, None)
        )

    await state_node._update_node_state(update)
