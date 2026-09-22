"""Wake the coordinator on action completion, then deliver its resumed reply."""

import asyncio
import logging

from repositories.coordinator_wakeups import CoordinatorWakeupRepo
from repositories.users import get_user_email
from utils.database_pool import get_native_pool
from utils.socket_singleton import get_sio
from utils.task_notifications import deliver_phone, emit_notification

logger = logging.getLogger(__name__)
MAX_AUTONOMOUS_TURNS = 8


def outcome_summary(event):
    """Keep the source result accessible even if the model cannot resume."""
    payload = event["payload"]
    source = "Builder request" if event["source"] == "builder" else "Agent request"
    text = f"{source} {payload.get('status', 'finished')}."
    if payload.get("error"):
        text += " " + payload["error"][:500]
    url = ((payload.get("result") or {}).get("publication") or {}).get("url") if event["source"] == "builder" else None
    return text + ("\n" + url if url else "")


async def run_wakeup(pool, event):
    from coder.coordinator.agent import COORDINATOR_FEATURE, run_coordinator_turn
    from utils.feature_gates import require_feature
    from wss.handlers.coordinator_handler import plan_allows_turn

    repo = CoordinatorWakeupRepo(pool)
    user_id = str(event["user_id"])
    runner = asyncio.current_task()

    async def heartbeat():
        try:
            while True:
                await asyncio.sleep(30)
                if not await repo.heartbeat(event):
                    runner.cancel()
                    return
        except Exception:
            # An unfenced worker must not keep issuing side effects.
            logger.exception("coordinator wake-up heartbeat failed: %s", event["id"])
            runner.cancel()

    lease = asyncio.create_task(heartbeat())
    try:
        if event["context"]["epoch"] != await repo.epoch(user_id):
            await repo.finish(event, "", skipped=True)
            return
        email = await get_user_email(pool, user_id)
        require_feature(COORDINATOR_FEATURE, email=email)
        allowed, error = await plan_allows_turn(pool, user_id)
        if not allowed:
            await repo.finish(event, outcome_summary(event) + " I couldn't continue: " + str(error))
            return
        if event["context"]["depth"] >= MAX_AUTONOMOUS_TURNS:
            await repo.finish(event, outcome_summary(event) +
                              " I've reached the automatic follow-up limit. Please message me to continue.")
            return
        channel = event["context"]["channel"]
        # A call may have ended hours ago. Its follow-up is delivered as text.
        if channel in ("phone", "whatsapp", "callback", "voice") or (channel == "web" and event["send_to_phone"]):
            channel = "whatsapp_text"
        async with asyncio.timeout(600):
            text = await run_coordinator_turn(
                sio=get_sio(), sid="", user_id=user_id, user_email=email, text="",
                extra={"channel": channel}, completion=event,
            )
        if text is not None:
            await repo.finish(event, text or outcome_summary(event))
    except asyncio.CancelledError:
        # The reaper retries only turns that never started. Started turns may
        # have taken actions, so their uncertain outcome is surfaced instead.
        raise
    except Exception:
        logger.exception("coordinator completion turn failed: %s", event["id"])
        await repo.finish(event, outcome_summary(event) +
                          " I couldn't finish the follow-up. Please check the result before retrying.")
    finally:
        lease.cancel()
        await asyncio.gather(lease, return_exceptions=True)


async def deliver_reply(pool, event):
    user_id = str(event["user_id"])
    error = None
    phone_state = None
    try:
        await emit_notification(get_sio(), user_id, f"coordinator:{user_id}", event["notification"])
    except Exception:
        logger.exception("coordinator follow-up socket delivery failed: %s", event["id"])
    if event["send_to_phone"]:
        phone_state, error = await deliver_phone(pool, user_id, event["response"])
    await CoordinatorWakeupRepo(pool).delivered(event, phone_state, error)


async def wakeup_worker():
    active = set()
    try:
        while True:
            try:
                pool = get_native_pool()
                repo = CoordinatorWakeupRepo(pool)
                await repo.reap_stalled()
                delivery = await repo.claim_delivery()
                if delivery:
                    await deliver_reply(pool, delivery)
                for done in tuple(active):
                    if done.done():
                        active.remove(done)
                        if not done.cancelled() and done.exception():
                            logger.error("coordinator wake-up failed", exc_info=done.exception())
                while len(active) < 4:
                    event = await repo.claim()
                    if event is None:
                        break
                    active.add(asyncio.create_task(run_wakeup(pool, event)))
            except Exception:
                logger.exception("coordinator wake-up poll failed")
            await asyncio.sleep(5)
    finally:
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
