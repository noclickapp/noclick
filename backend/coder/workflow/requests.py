"""Build jobs: build/edit, ask/resume, and requested publication.

Callers submit an outcome and consume one request's state. The builder owns
phase transitions; the publisher remains the authority for published apps.
A request whose origin names a registered reporter (``register_reporter``)
hands it the request after every attempt (asking, finished, failed), so its
caller follows it without polling; the rest are posted to their conversation.
"""

import asyncio
import logging

from billing.usage_tracker import attributed
from repositories.builder_requests import BuilderRequestRepo
from utils.builder_request import PublicationOptions
from utils.capabilities import INTERFACE_PUBLISH, capability
from utils.database_pool import get_native_pool
from utils.socket_singleton import get_sio
from utils.task_notifications import deliver_phone, emit_notification, notification_event

logger = logging.getLogger(__name__)

# Passed as ``organization_id``: the new workflow lands in the user's current workspace, as the app's own builds do.
CURRENT_ORG = object()
# How often a running attempt renews its lease and looks for a cancel.
HEARTBEAT_S = 10

_REPORTERS = {}


def register_reporter(source, report):
    """``report(pool, request_row)`` runs after each attempt of a request whose ``origin.source`` is ``source``."""
    _REPORTERS[source] = report


async def report(pool, request_id):
    row = await pool.fetchrow("SELECT * FROM coordinator_jobs WHERE id=$1::uuid AND kind='build'", request_id)
    reporter = row and _REPORTERS.get((row["origin"] or {}).get("source"))
    if reporter is None:
        return
    try:
        await reporter(pool, dict(row))
    except Exception:
        logger.exception("reporting builder request %s failed", request_id)


def build_view(row):
    publish = row["spec"].get("publish")
    return {
        "job_id": str(row["id"]), "kind": "build", "workflow_id": str(row["workflow_id"]),
        "builder_conversation_id": row["conversation_key"], "status": row["status"], "phase": row["phase"],
        "pending_ask": row["pending_ask"], "result": row["result"], "error": row["error"],
        "publication_requested": publish,
        "publication_status": ((row["result"] or {}).get("publication", {}).get("state", "published")
                               if row["status"] == "completed" and (row["result"] or {}).get("publication")
                               else (row["status"] if publish is not None else "not_requested")),
        "deployment_note": ("This request only saves changes. It does not update the public site."
                            if publish is None else None),
        "delivery": {"send_to_phone": row["send_to_phone"], "phone_state": row["phone_state"],
                     "error": row["delivery_error"]},
    }


def request_context(row):
    return {**row["origin"], "workflow_id": str(row["workflow_id"]),
            "builder_request_id": str(row["id"]), "builder_attempt_id": str(row["attempt_id"]),
            "coordinator_channel": (row.get("continuation") or {}).get("channel"),
            "publication_requested": row["spec"].get("publish")}


async def submit_request(pool, *, user_id, workflow_id=None, instructions=None, name=None, publish=None,
                         origin=None, continuation=None, reply_conversation_id=None, reply_node_id=None,
                         send_to_phone=False, organization_id=CURRENT_ORG):
    instructions = (instructions or "").strip() or None
    if instructions and len(instructions) > 16000:
        raise ValueError("Instructions must contain at most 16000 characters.")
    publication = PublicationOptions.model_validate(publish).model_dump() if publish is not None else None
    if publication and publication["action"] != "publish" and (instructions or not workflow_id):
        raise ValueError("Rename and unpublish operate on an existing deployment; provide workflow_id and omit instructions.")
    if not instructions and not (workflow_id and publication is not None):
        raise ValueError("Provide build instructions, or an existing workflow and publish options.")
    if publication is not None and capability(INTERFACE_PUBLISH) is None:
        raise ValueError("Interface publishing is unavailable on this instance.")
    created_id = None
    if not workflow_id:
        from wss.handlers.workflow_handler import create_workflow_as_user

        placed = {} if organization_id is CURRENT_ORG else {"organization_id": organization_id}
        from repositories.workflow import NEW_WORKFLOW_NAME

        created = await create_workflow_as_user(
            pool, user_id, name=(name or NEW_WORKFLOW_NAME).strip()[:120], description=instructions[:300], **placed,
        )
        if created.get("error"):
            raise ValueError(created["error"])
        workflow_id = created_id = created["workflow_id"]
    try:
        return await BuilderRequestRepo(pool).enqueue(
            user_id=user_id, workflow_id=workflow_id, instructions=instructions, publish=publication,
            origin=origin, continuation=continuation, reply_conversation_id=reply_conversation_id,
            reply_node_id=reply_node_id, send_to_phone=send_to_phone,
        )
    except ValueError:
        if created_id:
            # Refused before anything was built: no empty workflow left behind.
            from wss.handlers.workflow_handler import trash_workflow_as_owner

            await trash_workflow_as_owner(pool, created_id, user_id)
        raise


async def _run_attempt(pool, request, build):
    # What the build spends is attributed as its submitter asked (``origin.attribution``, ``usage_attribution()``).
    with attributed((request["origin"] or {}).get("attribution")):
        await _attempt(pool, request, build)


async def _attempt(pool, request, build):
    repo = BuilderRequestRepo(pool)
    request_id, attempt_id = str(request["id"]), str(request["attempt_id"])

    async def heartbeat():
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            if await repo.heartbeat(request_id, attempt_id) == "cancelled":
                # Cancelled while it builds (from anywhere): stop the builder working on it here.
                from utils.cancellation import get_builder_scope

                scope = get_builder_scope(request["conversation_key"])
                if scope is not None:
                    scope.cancel("user")
                return

    lease = asyncio.create_task(heartbeat())
    try:
        # Recheck access at execution time, including after an answer/reconnect.
        workflow = await repo.accessible_workflow(str(request["user_id"]), str(request["workflow_id"]),
                                                  publishing="publish" in request["spec"])
        if request["phase"] == "building":
            from billing.plan_limits import ai_builder_limit_error

            # Refused here, the request says why (the builder's own refusal reaches only a socket), on the pool
            # the build bills to: its workflow's organization's owner, as the builder gates it.
            organization_id = workflow["organization_id"]
            limit_error = await ai_builder_limit_error(pool, str(request["user_id"]),
                                                       str(organization_id) if organization_id else None)
            if limit_error:
                raise ValueError(limit_error)
            await build(workflow["workflow"])
            # A finish or question changes the request in the builder callback.
            await repo.finish(request_id, attempt_id, error="The build ended without a completed result. Check it before retrying.")
        else:
            publish = capability(INTERFACE_PUBLISH)
            if publish is None:
                raise ValueError("Interface publishing is unavailable on this instance.")
            published = await publish(pool, user_id=str(request["user_id"]), workflow_id=str(request["workflow_id"]),
                                      **request["spec"]["publish"])
            action = request["spec"]["publish"].get("action", "publish")
            expected_state = {"publish": "published", "rename": "renamed", "unpublish": "unpublished"}[action]
            confirmed = (published.get("state") == expected_state if action != "publish"
                         else bool(published.get("url")))
            if published.get("error") or not confirmed or (action == "rename" and not published.get("url")):
                raise ValueError(published.get("error") or "The publisher did not confirm the requested outcome.")
            await repo.finish(request_id, attempt_id, result={**(request["result"] or {}), "publication": published})
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("builder request failed: %s", request_id)
        await repo.finish(request_id, attempt_id, error=str(exc))
    finally:
        lease.cancel()
        await asyncio.gather(lease, return_exceptions=True)
        await report(pool, request_id)


async def run_request(pool, request):
    async def build(graph):
        from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler
        from wss.receiver.client_events import WorkflowBuilderEditRequest

        message = WorkflowBuilderEditRequest(
            request_id=str(request["id"]), conversation_id=request["conversation_key"],
            current_graph=graph, edit_prompt=request["spec"]["instructions"], user_context=request_context(request),
        )
        await WorkflowBuilderHandler(get_sio()).edit_workflow("", message, caller_user_id=str(request["user_id"]))

    await _run_attempt(pool, request, build)


async def resume_request(handler, sid, data, user_id, *, taken=None):
    """Build on the answer to a request's question. ``taken()`` runs once the answer is claimed, before the build:
    the build runs until the builder next stops, far longer than anyone waiting on the answer should."""
    pool = await handler.get_pool()
    request = await BuilderRequestRepo(pool).claim_resume(user_id, data["conversation_id"], data.get("ask_id"))
    await report(pool, str(request["id"]))
    if taken is not None:
        await taken()

    async def build(_graph):
        await handler._handle_input_response_impl(sid, data, caller_user_id=user_id)

    await _run_attempt(pool, request, build)


async def record_question(pool, user_id, context, pending_ask):
    return await BuilderRequestRepo(pool).waiting(user_id, context["builder_request_id"], context["builder_attempt_id"], pending_ask)


async def record_result(pool, user_id, context, *, success, summary, error):
    await BuilderRequestRepo(pool).build_finished(
        user_id, context["builder_request_id"], context["builder_attempt_id"], success=success, summary=summary, error=error,
    )


async def notify_result(pool, request):
    if request["continuation"]:
        from repositories.coordinator_wakeups import CoordinatorWakeupRepo
        from utils.previews import bounded

        await CoordinatorWakeupRepo(pool).enqueue(
            job=request, context=request["continuation"],
            payload=bounded(build_view(request), max_chars=16000, max_items=30),
        )
        return
    repo = BuilderRequestRepo(pool)
    request_id, user_id = str(request["id"]), str(request["user_id"])
    result = request["result"] or {}
    url = (result.get("publication") or {}).get("url") if request["status"] == "completed" else None
    if request["status"] == "cancelled":
        text = "Your builder request was cancelled. A build already running may finish, but no further steps will run."
    elif request["status"] == "failed":
        text = f"I couldn't finish your builder request: {request['error']}"
    else:
        publication = result.get("publication") or {}
        if publication.get("state") == "unpublished":
            text = "Your interface is unpublished. Its public URL is no longer available."
        elif publication.get("state") == "renamed":
            text = ("Your interface is already published at the requested URL." if publication.get("changed") is False
                    else "Your published URL has changed. The previous URL is no longer available.")
        elif url:
            text = "Your interface is published."
        else:
            # Builder prose can describe the edit but cannot attest to deployment.
            text = "Your changes are saved. This request did not publish or update a public site."
    phone_state, delivery_error = request["phone_state"], request["delivery_error"]
    if phone_state == "sending":
        phone_state, delivery_error = await deliver_phone(pool, user_id, text, link=url)
    if url:
        text += f"\n\n{url}"
    if delivery_error:
        text += f"\n\n{delivery_error}"
    event = notification_event(text, f"builder-request:{request_id}", builder_request_id=request_id)
    if await repo.complete_notification(request, event, phone_state=phone_state, delivery_error=delivery_error):
        try:
            await emit_notification(get_sio(), user_id, request["reply_conversation_id"], event)
        except Exception:
            logger.exception("builder result live notification failed: %s", request_id)


async def request_worker():
    active = set()
    try:
        while True:
            try:
                pool = get_native_pool()
                repo = BuilderRequestRepo(pool)
                await repo.reap_stalled()
                notification = await repo.claim_notification()
                if notification:
                    await notify_result(pool, notification)
                for done in tuple(active):
                    if done.done():
                        active.remove(done)
                        if not done.cancelled() and done.exception():
                            logger.error("builder request worker failed", exc_info=done.exception())
                while len(active) < 2:
                    request = await repo.claim()
                    if request is None:
                        break
                    active.add(asyncio.create_task(run_request(pool, request)))
            except Exception:
                logger.exception("builder request poll failed")
            await asyncio.sleep(5)
    finally:
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)


def build_summary(payload) -> str:
    """The one line the owner hears about a finished build when the model
    cannot resume: its status, its error, and the live URL when one exists."""
    text = f"Build {payload.get('status', 'finished')}."
    if payload.get("error"):
        text += " " + payload["error"][:500]
    url = ((payload.get("result") or {}).get("publication") or {}).get("url")
    return text + ("\n" + url if url else "")
