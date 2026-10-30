"""Signals that wake the account coordinator from elsewhere in the account:
a workflow run failed, or an agent node messaged it (``message_coordinator``).

Flood control lives here, not in the callers. Failures of one workflow within
``FAILURE_WINDOW`` fold into one signal (``repeats``), and so does the same
error again after the coordinator has looked at it, for ``KNOWN_FAILURE_DAYS``
unless the workflow is edited (a repeat of a known issue is not news); at most
``DAILY_FAILURE_WAKEUPS`` failure signals a day wake the coordinator, and an
agent can message it ``AGENT_MESSAGES_PER_NODE_DAILY`` times a day, within an
account-wide cap. Capped run failures remain recorded; capped agent messages
are explicitly refused before admission.
Credit exhaustion is never a coordinator job: the credits alert owns it, and
a coordinator turn would need the credits that ran out.

Each signal is also an account event (``ACCOUNT_EVENTS``) any subscriber may
be woken by: ``workflow.run.failed`` once per signal (repeats fold into it as
they do for the coordinator, whatever its daily cap), and
``agent.asked_owner`` for each message an agent's caps admit. An account whose
owner an agent answers in the coordinator's place (``ACCOUNT_AGENT``) hears
them through that agent's own event triggers: the coordinator isn't woken too.
The agent is made before the event is published, so an account meant to have
one that hasn't yet (its owner never opened the chat) hears its first signal.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from typing import Any, Dict, Optional

from utils.prompts import PromptPack

logger = logging.getLogger(__name__)

PROMPTS = PromptPack("coordinator")

FAILURE_WINDOW_HOURS = 6
KNOWN_FAILURE_DAYS = 7
DAILY_FAILURE_WAKEUPS = 6
AGENT_MESSAGES_PER_NODE_DAILY = 24
AGENT_MESSAGES_DAILY = 100
_MESSAGE_MAX = 2000
_ERROR_MAX = 1500
_DIAGNOSTICS_MAX = 3000
# Ids, dates, times and long numbers; a status code or a timeout's seconds still tell two failures apart.
_VOLATILE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|\d{4}-\d\d-\d\d(?:[t ][\d:.]+)?"
                       r"|\b\d{1,2}:\d\d(?::\d\d)?\b|\b[0-9a-f]{12,}\b|\d{4,}")


def failure_fingerprint(error: Optional[str]) -> str:
    """The same failure again: its error with ids, numbers and spacing ignored."""
    text = " ".join(_VOLATILE.sub("#", (error or "").lower()).split())
    return hashlib.sha256(text[:200].encode()).hexdigest()[:16]


def signal_ref(kind: str, workflow_id: str, workflow_name: Optional[str]) -> Dict[str, Any]:
    """What a wake-up and every note its turn leaves are about, so the chat can keep them together."""
    return {"kind": kind, "workflow_id": workflow_id, "workflow_name": workflow_name or "Untitled"}


def app_agent_id(workflow_id: str, node_id: str) -> str:
    """The id an agent node of a workflow has among the account's agents."""
    return f"node:{workflow_id}:{node_id}"


async def _publish(pool, type: str, data: Dict[str, Any], *, account_user_id: str,
                   dedupe_key: Optional[str]) -> None:
    from utils.capabilities import ACCOUNT_EVENTS, capability

    publish = capability(ACCOUNT_EVENTS)
    if publish is None:
        return
    try:
        await publish(pool, type, data, account_user_id=account_user_id, dedupe_key=dedupe_key)
    except Exception:
        logger.exception("publishing %s for account %s failed", type, account_user_id)


async def _wake(pool, signal: Dict[str, Any], *, request: str) -> None:
    from repositories.coordinator_wakeups import CoordinatorWakeupRepo

    repo = CoordinatorWakeupRepo(pool)
    user_id = str(signal["user_id"])
    context = {"epoch": await repo.epoch(user_id), "depth": 0, "request": request, "channel": "web",
               "turn_id": str(uuid.uuid4()),
               "signal": signal_ref(signal["kind"], str(signal["workflow_id"]), signal["payload"].get("workflow_name"))}
    await repo.enqueue_signal(signal=signal, context=context, payload={"kind": signal["kind"], **signal["payload"]})


async def record_run_failure(
    pool, *, workflow_id: str, execution_id: Optional[str], error: Optional[str],
    trigger_source: Optional[str], user_id: Optional[str] = None, node_id: Optional[str] = None,
    node_label: Optional[str] = None, diagnostics: Optional[str] = None,
) -> Optional[str]:
    """Record a failed run and wake the coordinator when the flood rules
    allow; returns what happened (for logs and tests). ``error`` is what the
    person was shown and the only text anything quotes back to them;
    ``diagnostics`` (a harness's redacted log) is context for the coordinator
    to diagnose with."""
    from billing.exceptions import match_insufficient_credits, match_spend_cap
    from utils.capabilities import AGENT_WORKFLOW, capability

    if error and match_insufficient_credits(error):
        return "credits"
    if error and match_spend_cap(error):
        return "spend cap"
    agent_workflow = capability(AGENT_WORKFLOW)
    if agent_workflow and await agent_workflow(pool, workflow_id):
        return "agent turn"
    fingerprint = failure_fingerprint(error)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"signal:{workflow_id}")
            wf = await conn.fetchrow(
                "SELECT owner_id, name, updated_at FROM workflows WHERE id = $1::uuid AND deleted_at IS NULL",
                workflow_id)
            if wf is None:
                return "no workflow"
            owner = user_id or str(wf["owner_id"])
            folded = await conn.fetchval(
                f"""UPDATE coordinator_signals SET repeats = repeats + 1, last_seen_at = now(),
                      payload = payload || jsonb_build_object('last_error', $2::text, 'last_execution_id', $3::text)
                    WHERE id = (SELECT id FROM coordinator_signals WHERE workflow_id = $1::uuid AND kind = 'run_failure'
                                AND (created_at > now() - interval '{FAILURE_WINDOW_HOURS} hours'
                                     OR (woke AND payload->>'fingerprint' = $4 AND created_at >= $5
                                         AND created_at > now() - interval '{KNOWN_FAILURE_DAYS} days'))
                                ORDER BY created_at DESC LIMIT 1)
                    RETURNING id""",
                workflow_id, (error or "")[:_ERROR_MAX], execution_id, fingerprint, wf["updated_at"],
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
                 **({"diagnostics": diagnostics[:_DIAGNOSTICS_MAX]} if diagnostics else {}),
                 "failed_runs_last_24h": failures_24h, "fingerprint": fingerprint},
                wake,
            )
    from coder.coordinator.handover import agent_answers

    answered = await agent_answers(pool, owner)
    await _publish(pool, "workflow.run.failed", {
        "object": "workflow_run", "workflow_id": workflow_id, "workflow_name": wf["name"], "run_id": execution_id,
        "status": "failed", "error": (error or "")[:_ERROR_MAX], "step": node_label, "node_id": node_id,
        "trigger_source": trigger_source, "failed_runs_last_24h": failures_24h,
    }, account_user_id=owner, dedupe_key=f"workflow.run.failed:{signal['id']}")
    if not wake:
        return "capped"
    if answered:
        await pool.execute("UPDATE coordinator_signals SET woke = false WHERE id = $1", signal["id"])
        return "agent"
    await _wake(pool, dict(signal), request=f"Triage the failed workflow “{wf['name']}”")
    return "woke"


async def record_agent_message(
    pool, *, user_id: Optional[str], workflow_id: Optional[str], node_id: Optional[str],
    message: str, conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Wake the coordinator with an agent's free-form message."""
    from coder.coordinator.handover import agent_answers
    from repositories.coordinator_signals import CoordinatorSignalRepo
    from utils.coordinator_dispatch import dispatch_event

    message = (message or "").strip()[:_MESSAGE_MAX]
    if not message:
        return {"success": False, "error": "message is required"}
    if not user_id or not workflow_id or not node_id:
        return {"success": False, "error": "no workflow context for this run"}
    to_coordinator = not await agent_answers(pool, user_id)
    try:
        event = await CoordinatorSignalRepo(pool).agent_message(
            user_id=user_id, workflow_id=workflow_id, node_id=node_id,
            payload={"conversation_id": conversation_id, "message": message},
            node_cap=AGENT_MESSAGES_PER_NODE_DAILY, account_cap=AGENT_MESSAGES_DAILY, wake=to_coordinator,
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    if to_coordinator:
        await dispatch_event(pool, event)
    await _publish(pool, "agent.asked_owner", {
        "object": "agent_message", "agent_id": app_agent_id(workflow_id, node_id), "workflow_id": workflow_id,
        "node_id": node_id, "conversation": conversation_id, "message": message,
    }, account_user_id=user_id, dedupe_key=f"agent.asked_owner:{event['id']}" if event else None)
    return {"success": True, "status": "queued",
            "note": "Queued for the coordinator to review; the requested action is not yet confirmed."}


def describe(event: Dict[str, Any]) -> str:
    """The developer message a signal wakeup opens the coordinator's turn with."""
    if event["payload"].get("kind") == "agent_message":
        return PROMPTS.AGENT_MESSAGE_WAKEUP
    return PROMPTS.run_failure_wakeup(known_failure_days=KNOWN_FAILURE_DAYS)
