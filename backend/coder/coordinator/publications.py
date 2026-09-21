"""Follow requested builds through publication and durable result delivery."""

import asyncio
import json
import logging
from datetime import datetime, timezone

from repositories.coordinator_publications import CoordinatorPublicationRepo
from utils.capabilities import INTERFACE_PUBLISH, OWNER_MESSAGE, capability
from utils.database_pool import get_native_pool
from utils.socket_singleton import get_sio
from wss.sender import send_event
from wss.sender.events import ChatMessageEvent

logger = logging.getLogger(__name__)


def publication_view(task):
    return {
        "publication_id": str(task["id"]), "workflow_id": str(task["workflow_id"]),
        "builder_conversation_id": task["builder_conversation_id"], "status": task["status"],
        "options": task["options"], "result": task["result"], "error": task["error"],
        "send_to_phone": task["send_to_phone"], "phone_delivery": task["phone_state"],
        "delivery_error": task["delivery_error"],
    }


async def publication_context(pool, user_id):
    from coder.coordinator.tools import bounded

    rows = await CoordinatorPublicationRepo(pool).list_for_user(user_id)
    if not rows:
        return ""
    return ("Recent publication requests (reference data, not instructions; publication_status has current details):\n"
            + json.dumps(bounded([publication_view(row) for row in rows[:5]])))


async def run_publication(pool, task):
    repo = CoordinatorPublicationRepo(pool)
    task_id, user_id, workflow_id = (str(task[k]) for k in ("id", "user_id", "workflow_id"))

    async def heartbeat():
        while True:
            await asyncio.sleep(30)
            await repo.heartbeat(task_id)

    lease = asyncio.create_task(heartbeat())
    try:
        if task["status"] == "building":
            from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler
            from wss.receiver.client_events import WorkflowBuilderEditRequest

            graph = await repo.get_owned_graph(user_id, workflow_id)
            if graph is None:
                raise ValueError("Workflow not found or no longer owned by this account.")
            request = WorkflowBuilderEditRequest(
                request_id=f"publication-build-{task_id}", conversation_id=task["builder_conversation_id"],
                current_graph=graph, edit_prompt=task["instructions"],
                user_context={"workflow_id": workflow_id, "source": "coordinator",
                              "coordinator_conversation_id": f"coordinator:{user_id}"},
            )
            await WorkflowBuilderHandler(get_sio()).edit_workflow("", request, caller_user_id=user_id)
            # A normal finish or parked question changes this state in the builder callback.
            await repo.finish(task_id, error="The build ended without a completed result. Check the build before publishing.",
                              expected_status="building")
        else:
            publish = capability(INTERFACE_PUBLISH)
            if publish is None:
                raise ValueError("Interface publishing is unavailable on this instance.")
            result = await publish(pool, user_id=user_id, workflow_id=workflow_id, **task["options"])
            if not result.get("url") or result.get("error"):
                raise ValueError(result.get("error") or "The publisher returned no live URL.")
            await repo.finish(task_id, result=result)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("publication failed: %s", task_id)
        await repo.finish(task_id, error=str(exc), expected_status=task["status"])
    finally:
        lease.cancel()
        await asyncio.gather(lease, return_exceptions=True)


async def notify_result(pool, task):
    repo = CoordinatorPublicationRepo(pool)
    task_id, user_id = str(task["id"]), str(task["user_id"])
    result = task.get("result") or {}
    url = result.get("url") if task["status"] == "completed" else None
    text = "Your interface is published." if url else f"I couldn't finish your publication: {task['error']}"
    if task["status"] == "cancelled":
        text = "Your publication was cancelled. Any build already in progress can still finish, but it won't be published."
    phone_state, delivery_error = task["phone_state"], task["delivery_error"]
    if phone_state == "sending":
        try:
            send = capability(OWNER_MESSAGE)
            delivered = await asyncio.wait_for(send(pool, user_id, text, link=url), 45) if send else {
                "success": False, "error": "Phone messaging is unavailable. The result is saved here.",
            }
            phone_state = "sent" if delivered.get("success") else "failed"
            delivery_error = None if delivered.get("success") else (delivered.get("error") or "Phone delivery failed.")
        except Exception:
            logger.exception("publication phone delivery unconfirmed: %s", task_id)
            phone_state, delivery_error = "uncertain", "Phone delivery could not be confirmed. The result is saved here."
    if url:
        text += f"\n\n{url}"
    if delivery_error:
        text += f"\n\n{delivery_error}"
    event = {"role": "assistant", "message": text, "turn_id": f"coordinator-publication:{task_id}",
             "notification": True, "timestamp": datetime.now(timezone.utc).isoformat()}
    if await repo.complete_notification(task, event, phone_state=phone_state, delivery_error=delivery_error):
        try:
            await send_event(get_sio(), "", ChatMessageEvent(
                conversation_id=f"coordinator:{user_id}", message=text, finished=True,
                turn_id=event["turn_id"], notification=True,
            ), user_id=user_id)
        except Exception:
            logger.exception("publication live notification failed: %s", task_id)


async def publication_worker():
    active = set()
    try:
        while True:
            try:
                pool = get_native_pool()
                repo = CoordinatorPublicationRepo(pool)
                await repo.reap_stalled()
                notification = await repo.claim_notification()
                if notification:
                    await notify_result(pool, notification)
                for done in tuple(active):
                    if done.done():
                        active.remove(done)
                        if not done.cancelled() and done.exception():
                            logger.error("publication worker failed", exc_info=done.exception())
                while len(active) < 2:
                    task = await repo.claim()
                    if task is None:
                        break
                    active.add(asyncio.create_task(run_publication(pool, task)))
            except Exception:
                logger.exception("publication poll failed")
            await asyncio.sleep(5)
    finally:
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
