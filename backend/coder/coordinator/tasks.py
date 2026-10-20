"""Dispatch durable coordinator requests through the existing agent runtime.
Immediate and deferred replies settle the same task; a persisted notification
returns the result to the account even when the original container is gone.

Another surface may ask an agent for turns on this same path, on a
conversation of its own (``register_agent_job_source``, then
``CoordinatorTaskRepo.enqueue_turn``): each finished job's outcome goes back to
that surface the moment it settles, never to the coordinator.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from billing.usage_tracker import attribute_usage
from coder.coordinator.jobs import outcome_for, register_job_source
from repositories.coordinator_tasks import COORDINATOR_KEY_PREFIX, COORDINATOR_SOURCE, CoordinatorTaskRepo
from utils.access_control import Permission, check_resource_access
from utils.async_helpers import spawn
from utils.database_pool import get_native_pool
from utils.graph_nodes import node_disabled, node_label
from utils.socket_singleton import get_sio
from utils.task_notifications import deliver_phone, emit_notification, notification_event

logger = logging.getLogger(__name__)
POLL_SECONDS = 5
MAX_CONCURRENT = 4
# Every usage event a job's turn records names the job.
JOB_ATTRIBUTION_KEY = "coordinator_job_id"


# A surface's agent turns run on conversation keys that start with its prefix.
_KEY_PREFIXES: Dict[str, str] = {}


def register_agent_job_source(source: str, *, key_prefix: str,
                              deliver: Callable[[Any, Dict[str, Any]], Awaitable[None]]) -> None:
    """A surface that asks agents for turns: its conversation keys start with
    ``key_prefix``, and ``deliver(pool, job)`` takes each finished job back
    (it may get one twice, at once and from the worker's backstop)."""
    _KEY_PREFIXES[source] = key_prefix
    register_job_source(source, deliver)


def _source(job: Dict[str, Any]) -> str:
    return (job.get("origin") or {}).get("source") or COORDINATOR_SOURCE


def agent_view(row: dict, *, include_result: bool = True) -> dict:
    from utils.previews import bounded

    result = {
        "job_id": str(row["id"]), "kind": "agent", "workflow_id": str(row["workflow_id"]),
        "node_id": row["node_id"], "agent_name": row["spec"]["agent_name"], "status": row["status"],
        "message": row["spec"]["message"],
        "reply_to_job_id": str(row["parent_job_id"]) if row.get("parent_job_id") else None,
        "execution_id": str(row["execution_id"]) if row.get("execution_id") else None,
        "created_at": row["created_at"].isoformat(), "error": row.get("error"),
    }
    if include_result:
        result["result"] = bounded(row.get("result"), max_chars=16000, max_items=20)
        result["delivery_error"] = row.get("delivery_error")
    return result


async def account_agents(pool, user_id: str, organization_id: Optional[str]) -> List[Dict[str, Any]]:
    """Every agent node in the workflows of the user's workspace (``organization_id``,
    else its own), the most recently edited workflow first."""
    from repositories.dashboard import DashboardRepo
    from utils.graph_nodes import graph_nodes, node_config, node_model

    rows = await DashboardRepo(pool).list_workflows(user_id, uuid.UUID(organization_id) if organization_id else None)
    return [{"workflow_id": str(row["id"]), "workflow_name": row["name"], "node_id": node["id"],
             "name": node_label(node) or "Agent",
             "purpose": str(node_config(node).get("goal") or (node.get("data") or {}).get("goal") or "")[:500],
             "model": node_model(node), "disabled": node_disabled(node)}
            for row in rows for node in graph_nodes(row["workflow"]) if node.get("type") == "agent"]


async def agent_target(pool, sio, *, user_id: str, workflow_id: str, node_id: str) -> dict:
    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

    async with pool.acquire() as conn:
        access = await check_resource_access(conn, user_id, "workflow", workflow_id)
    # The owner of a workflow NoClick runs itself only views it, and still talks to its agent.
    if not access.has_access or (access.permission not in (Permission.OWNER, Permission.EDIT)
                                 and access.via != "owner"):
        raise ValueError("You need edit access to message this workflow's agent.")
    fetched = await WorkflowExecutionHandler(sio)._fetch_workflow(workflow_id, user_id)
    if not fetched:
        raise ValueError("Workflow not found.")
    target = next((n for n in fetched[0] if n.get("id") == node_id and n.get("type") == "agent"), None)
    if not target or node_disabled(target):
        raise ValueError("Choose an enabled agent node in this workflow.")
    return target


async def request_agent_message(pool, sio, *, user_id: str, workflow_id: str, node_id: str,
                                message: str, send_to_phone: bool, reply_to_job_id: Optional[str] = None,
                                continuation=None) -> dict:
    message = message.strip()
    if not message or len(message) > 16000:
        raise ValueError("An agent message must contain between 1 and 16000 characters.")
    target = await agent_target(pool, sio, user_id=user_id, workflow_id=workflow_id, node_id=node_id)
    task = await CoordinatorTaskRepo(pool).enqueue(
        user_id=user_id, workflow_id=workflow_id, node_id=node_id, agent_name=node_label(target) or "Agent",
        message=message, send_to_phone=send_to_phone, parent_job_id=reply_to_job_id, continuation=continuation,
    )
    return {"success": True, "job": agent_view(task),
            "note": "Queued. The reply will arrive in this coordinator conversation. Pass this job_id as "
                    "reply_to_job_id to continue the same agent conversation; job_status checks progress."}


def reply_text(output: Any) -> str:
    from nodes.agent.rehearsal_launch import _reply_text

    return _reply_text(output) or ""


def turn_error(output: Any, error: Optional[str] = None, *, silent_ok: bool = False) -> Optional[str]:
    """Why a finished agent turn failed, or None when it replied (or, ``silent_ok``, when a turn nobody waits on
    ended with nothing to say)."""
    if isinstance(output, dict):
        error = error or output.get("error")
        if output.get("status") in ("failed", "error", "turn_lost"):
            error = error or "The agent could not complete the request."
    if not error and not silent_ok and not reply_text(output):
        error = "The agent finished without a reply."
    return str(error) if error else None


async def deliver_outcome(pool, job: Dict[str, Any]) -> None:
    """Hand a surface's finished job back to it, then mark it delivered; one
    that fails stays for the worker's next pass (``notify_results``)."""
    try:
        await outcome_for(job)(pool, job)
    except Exception:
        logger.exception("agent job %s: delivering its outcome to %s failed", job["id"], _source(job))
        return
    await CoordinatorTaskRepo(pool).mark_notified(str(job["id"]))


async def finish(repo: CoordinatorTaskRepo, task_id: str, *, result: Optional[dict] = None,
                 error: Optional[str] = None) -> None:
    """Finish a job once; a surface's goes back to it at once (the coordinator's
    own reach it through ``notify_results``)."""
    row = await repo.finish(task_id, result=result, error=error)
    if row is not None and _source(row) != COORDINATOR_SOURCE:
        await deliver_outcome(repo.pool, row)


async def settle_output(repo: CoordinatorTaskRepo, task_id: str, output: Any, error: Optional[str] = None) -> None:
    from utils.previews import bounded

    if isinstance(output, dict) and output.get("status") == "awaiting_agent_turn":
        await repo.wait_for_reply(task_id)
        return
    await finish(repo, task_id, result=bounded(output, max_chars=32000, max_items=30), error=turn_error(output, error))


async def complete_agent_deliveries(*, workflow_id: str, node_id: str, conversation_id: Optional[str], output: dict) -> None:
    """Match the response package's deliveries, never a conversation's latest message."""
    prefix = f"ck:{workflow_id}:{node_id}:"
    keys = (COORDINATOR_KEY_PREFIX, *_KEY_PREFIXES.values())
    if not conversation_id or not conversation_id.startswith(tuple(prefix + key for key in keys)):
        return
    ids = []
    for value in output.get("input_execution_ids") or []:
        try:
            ids.append(str(uuid.UUID(str(value))))
        except ValueError:
            continue
    if not ids:
        return
    repo = CoordinatorTaskRepo(get_native_pool())
    for task_id in await repo.find_deliveries(
        workflow_id=workflow_id, node_id=node_id, conversation_key=conversation_id[len(prefix):], execution_ids=ids,
    ):
        await settle_output(repo, task_id, output)


async def run_task(pool, task: dict) -> None:
    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
    from wss.receiver.client_events import WorkflowExecuteRequest

    repo = CoordinatorTaskRepo(pool)
    task_id, user_id, workflow_id = str(task["id"]), str(task["user_id"]), str(task["workflow_id"])
    attribute_usage(**{JOB_ATTRIBUTION_KEY: task_id})

    async def heartbeat():
        while True:
            await asyncio.sleep(30)
            await repo.heartbeat(task_id)

    lease = asyncio.create_task(heartbeat())
    try:
        # Access and node state may have changed while this request was queued.
        await agent_target(pool, get_sio(), user_id=user_id, workflow_id=workflow_id, node_id=task["node_id"])
        spec = task["spec"]
        handler = WorkflowExecutionHandler(get_sio())
        request = WorkflowExecuteRequest(
            request_id=f"coordinator-task-{task_id}", workflow_id=workflow_id, start_node_id=task["node_id"],
            trigger_source="coordinator",
            conversation_id=f"ck:{workflow_id}:{task['node_id']}:{task['conversation_key']}",
            config_overrides={task["node_id"]: {
                "message": spec["message"], "conversation_key": task["conversation_key"], "mockedOutput": None,
                **({"message_attachments": spec["attachments"]} if spec.get("attachments") else {}),
                **(spec.get("config") or {}),
            }},
        )
        result = await handler.handle_execute("", request, str(task["execution_id"]), caller_user_id=user_id)
        await settle_output(repo, task_id, result.node_outputs.get(task["node_id"]),
                            error=result.error if not result.success else None)
    except asyncio.CancelledError:
        # A restarted worker reaps the lease; it must not resend a possibly consumed request.
        raise
    except Exception as exc:
        logger.exception("coordinator agent task failed: %s", task_id)
        await finish(repo, task_id, error=str(exc))
    finally:
        lease.cancel()
        await asyncio.gather(lease, return_exceptions=True)


async def start_now(pool, job_id: str) -> None:
    """Run a queued job now instead of at the worker's next poll; when another
    process claims it first, that one runs it."""
    task = await CoordinatorTaskRepo(pool).claim(job_id)
    if task is not None:
        spawn(run_task(pool, task), name=f"coordinator-agent-task:{job_id}")


async def notify_results(pool) -> None:
    repo = CoordinatorTaskRepo(pool)
    for task in await repo.pending_notifications():
        if _source(task) != COORDINATOR_SOURCE:
            # A surface's job its immediate delivery missed (a crash, a reaped lease).
            await deliver_outcome(pool, task)
            continue
        if task["continuation"]:
            from repositories.coordinator_wakeups import CoordinatorWakeupRepo

            await CoordinatorWakeupRepo(pool).enqueue(job=task, context=task["continuation"], payload=agent_view(task))
            continue
        task_id, user_id, agent_name = str(task["id"]), str(task["user_id"]), task["spec"]["agent_name"]
        text = (f"{agent_name} could not complete your request: {task['error']}" if task["status"] == "failed"
                else f"{agent_name} replied:\n\n{reply_text(task.get('result'))}")
        turn_id = f"coordinator-task:{task_id}"
        event = notification_event(text, turn_id, coordinator_task_id=task_id)
        if not await repo.persist_notification(task_id, event):
            continue
        try:
            await emit_notification(get_sio(), user_id, f"coordinator:{user_id}", event)
        except Exception as exc:
            logger.exception("coordinator task live delivery failed: %s", task_id)
            await repo.record_delivery_error(task_id, str(exc))
        if task["send_to_phone"]:
            _, delivery_error = await deliver_phone(pool, user_id, text)
            if delivery_error:
                await repo.record_delivery_error(task_id, delivery_error)


async def task_worker() -> None:
    """Every serving process may poll; database claims distribute work without duplicate dispatch."""
    active: set[asyncio.Task] = set()
    try:
        while True:
            try:
                pool = get_native_pool()
                repo = CoordinatorTaskRepo(pool)
                await repo.reap_stalled()
                await notify_results(pool)
                for done in tuple(active):
                    if done.done():
                        active.remove(done)
                        if not done.cancelled() and done.exception():
                            logger.error("coordinator task worker execution failed", exc_info=done.exception())
                while len(active) < MAX_CONCURRENT:
                    task = await repo.claim()
                    if task is None:
                        break
                    active.add(asyncio.create_task(run_task(pool, task)))
            except Exception:
                logger.exception("coordinator task poll failed")
            await asyncio.sleep(POLL_SECONDS)
    finally:
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)


def agent_summary(payload: dict) -> str:
    """The one line the owner hears about a finished agent request when the
    model cannot resume."""
    text = f"Agent request {payload.get('status', 'finished')}."
    if payload.get("error"):
        text += " " + payload["error"][:500]
    return text
