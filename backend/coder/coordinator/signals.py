"""Signals that wake the account coordinator from elsewhere in the account:
a workflow run failed, or an agent node messaged it (``message_coordinator``).

Flood control lives here, not in the callers. Failures of one workflow within
``FAILURE_WINDOW`` fold into one signal (``repeats``); at most
``DAILY_FAILURE_WAKEUPS`` failure signals a day wake the coordinator, and an
agent can message it ``AGENT_MESSAGES_PER_NODE_DAILY`` times a day. A signal
that doesn't wake the coordinator is still recorded, so it can see it later.
Credit exhaustion is never a coordinator job: the credits alert owns it, and
a coordinator turn would need the credits that ran out.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

FAILURE_WINDOW_HOURS = 6
DAILY_FAILURE_WAKEUPS = 6
AGENT_MESSAGES_PER_NODE_DAILY = 3
AGENT_MESSAGES_DAILY = 10
_MESSAGE_MAX = 2000
_ERROR_MAX = 1500


async def _wake(pool, signal: Dict[str, Any], *, request: str) -> None:
    from repositories.coordinator_wakeups import CoordinatorWakeupRepo

    repo = CoordinatorWakeupRepo(pool)
    user_id = str(signal["user_id"])
    context = {"epoch": await repo.epoch(user_id), "depth": 0, "request": request, "channel": "web",
               "turn_id": str(uuid.uuid4())}
    await repo.enqueue_signal(signal=signal, context=context, payload={"kind": signal["kind"], **signal["payload"]})


async def record_run_failure(
    pool, *, workflow_id: str, execution_id: Optional[str], error: Optional[str],
    trigger_source: Optional[str], user_id: Optional[str] = None, node_id: Optional[str] = None,
    node_label: Optional[str] = None,
) -> Optional[str]:
    """Record a failed run and wake the coordinator when the flood rules
    allow; returns what happened (for logs and tests)."""
    from billing.exceptions import match_insufficient_credits

    if error and match_insufficient_credits(error):
        return "credits"
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"signal:{workflow_id}")
            wf = await conn.fetchrow(
                "SELECT owner_id, name FROM workflows WHERE id = $1::uuid AND deleted_at IS NULL", workflow_id)
            if wf is None:
                return "no workflow"
            owner = user_id or str(wf["owner_id"])
            folded = await conn.fetchval(
                f"""UPDATE coordinator_signals SET repeats = repeats + 1, last_seen_at = now(),
                      payload = payload || jsonb_build_object('last_error', $2::text, 'last_execution_id', $3::text)
                    WHERE id = (SELECT id FROM coordinator_signals WHERE workflow_id = $1::uuid AND kind = 'run_failure'
                                AND created_at > now() - interval '{FAILURE_WINDOW_HOURS} hours'
                                ORDER BY created_at DESC LIMIT 1)
                    RETURNING id""",
                workflow_id, (error or "")[:_ERROR_MAX], execution_id,
            )
            if folded:
                return "folded"
            woke_today = await conn.fetchval(
                "SELECT count(*) FROM coordinator_signals WHERE user_id = $1::uuid AND kind = 'run_failure' "
                "AND woke AND created_at > now() - interval '24 hours'", owner)
            failures_24h = await conn.fetchval(
                "SELECT count(*) FROM workflow_executions WHERE workflow_id = $1::uuid AND status = 'error' "
                "AND started_at > now() - interval '24 hours'", workflow_id)
            wake = woke_today < DAILY_FAILURE_WAKEUPS
            signal = await conn.fetchrow(
                """INSERT INTO coordinator_signals (user_id, kind, workflow_id, node_id, execution_id, payload, woke)
                   VALUES ($1::uuid, 'run_failure', $2::uuid, $3, $4::uuid, $5, $6) RETURNING *""",
                owner, workflow_id, node_id, execution_id,
                {"workflow_id": workflow_id, "workflow_name": wf["name"], "execution_id": execution_id,
                 "trigger_source": trigger_source, "node_label": node_label, "error": (error or "")[:_ERROR_MAX],
                 "failed_runs_last_24h": failures_24h},
                wake,
            )
    if not wake:
        return "capped"
    await _wake(pool, dict(signal), request=f"Triage the failed workflow “{wf['name']}”")
    return "woke"


async def record_agent_message(
    pool, *, user_id: Optional[str], workflow_id: Optional[str], node_id: Optional[str],
    message: str, conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """An agent node asks the coordinator for help or tells it something."""
    message = (message or "").strip()[:_MESSAGE_MAX]
    if not message:
        return {"success": False, "error": "message is required"}
    if not user_id or not workflow_id:
        return {"success": False, "error": "no workflow context for this run"}
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"agent-msg:{user_id}")
            counts = await conn.fetchrow(
                """SELECT count(*) FILTER (WHERE workflow_id = $2::uuid AND node_id = $3) AS node,
                          count(*) AS account
                   FROM coordinator_signals WHERE user_id = $1::uuid AND kind = 'agent_message'
                   AND created_at > now() - interval '24 hours'""", user_id, workflow_id, node_id)
            if counts["node"] >= AGENT_MESSAGES_PER_NODE_DAILY or counts["account"] >= AGENT_MESSAGES_DAILY:
                return {"success": False, "error": "You've messaged the coordinator as often as allowed today. "
                                                   "Carry on without it, or use submit_feedback for a platform bug."}
            name = await conn.fetchval("SELECT name FROM workflows WHERE id = $1::uuid", workflow_id)
            signal = await conn.fetchrow(
                """INSERT INTO coordinator_signals (user_id, kind, workflow_id, node_id, payload, woke)
                   VALUES ($1::uuid, 'agent_message', $2::uuid, $3, $4, true) RETURNING *""",
                user_id, workflow_id, node_id,
                {"workflow_id": workflow_id, "workflow_name": name, "node_id": node_id,
                 "conversation_id": conversation_id, "message": message},
            )
    await _wake(pool, dict(signal), request=f"An agent in “{name}” messaged you")
    return {"success": True, "delivered": "The coordinator will look at this; carry on with your task."}


def describe(event: Dict[str, Any]) -> str:
    """The developer message a signal wakeup opens the coordinator's turn with."""
    payload = event["payload"]
    if payload.get("kind") == "agent_message":
        return ("An agent in the account sent you a message. Read it, do what helps (fix or adjust its workflow "
                "through request_build, answer it with message_agent, or reach the owner with message_owner "
                "when only they can help), and keep your note here short.")
    return (
        "A workflow in the account failed. If your memory says the owner doesn't want failures triaged (for this "
        "workflow or at all), leave it at a one-line note here. Otherwise triage it without the owner unless "
        "they're needed:\n"
        "1. Find out why. Prefer asking the builder (request_build on that workflow: diagnose, then fix); "
        "get_run or list_runs give you a quick look yourself.\n"
        "2. If the workflow is clearly useless (an abandoned test, a duplicate, nothing uses it), pause it with "
        "pause_workflow and say why.\n"
        "3. If it's broken and fixable, have the builder fix it.\n"
        "4. If it can't be fixed, or it's a NoClick platform problem, submit_feedback.\n"
        "5. If it keeps failing (failed_runs_last_24h, repeats) or needs the owner (a credential, a decision), "
        "tell them with message_owner. Otherwise don't bother them: a short note here is enough."
    )
