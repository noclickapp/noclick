"""What a change to a workflow's graph sets in motion outside the graph,
judged from the graph before and after it, for every writer (the graph
service's edits and restores, the canvas's save):

- a step removed tears down what it registered (schedules, provider webhooks,
  node state, published apps, conversations, volumes; ``cleanup_nodes_resources``,
  given the removed steps as they were) and gives back its inbound-email address.
  The canvas names the steps it deleted (``deleted``), and only those go: a
  closing tab's last save of a graph it loaded before another writer added a
  step must not take that step's resources;
- a step whose operation, connections or registration fields changed has its
  trigger registration reconciled (``WebhookManager``'s change hooks);
- a trigger with no webhook yet, or one whose registration failed, is
  provisioned once nothing it needs is missing, its webhook fields written
  into its config;
- a step that's back (a delete undone) registers again what it registered.

It makes provider round-trips, so writers run it after their write commits.
One workflow's reconciles run one at a time: one per process, then a lease
across processes (``workflow_reconcile_leases``, claimed, renewed and given
back in short statements, so a reconcile holds no connection or transaction
while it works, and one that lapses is anyone's). A reconcile's work is
bounded (``WORK_S``: stopped there, its lease given back, and never renewed
past it). One waits for another's with backoff, at most ``WAIT_S``, then runs
anyway, so two may overlap: each teardown and registration acts on the graph
as stored when it acts (a removed step is torn down only while it's still
absent, a step registered only while it's still there), then checks it again
and puts right what a write in between changed (a step back while it was
torn down registers again; one removed while it was registered is torn
down). Each part runs whatever another part did. Given the version the write
left, it returns the version its own writes (a trigger's webhook fields) left
the workflow at, so a writer hands back a version its caller can edit from;
another writer's change in between ends that chain."""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
import weakref
from contextlib import asynccontextmanager
from typing import Any, Collection, Dict, List, Optional, Tuple

from utils.graph_nodes import graph_nodes, node_config

logger = logging.getLogger(__name__)

# A lease lapses LEASE_S after its last renewal (renewed every third of it while its reconcile runs).
LEASE_S = 60
# How long a reconcile waits for another of the same workflow before it runs anyway.
WAIT_S = 30.0
# How long a reconcile's work may run before it's stopped and its lease given back.
WORK_S = 120.0


async def reconcile_graph_change(pool, workflow_id: str, user_id: str, old_graph: Any, new_graph: Any, *,
                                 version: Optional[int] = None,
                                 deleted: Optional[Collection[str]] = None) -> Optional[int]:
    from utils.webhook_manager import PATCH_MOVES

    workflow_id = str(workflow_id)
    moves: List[Tuple[int, int]] = []
    token = PATCH_MOVES.set(moves)
    try:
        async with _one_at_a_time(pool, workflow_id):
            try:
                await asyncio.wait_for(_reconcile(pool, workflow_id, user_id, old_graph, new_graph, deleted),
                                       timeout=WORK_S)
            except asyncio.TimeoutError:
                logger.error("[reconcile] %s: its work ran past %ss; stopped, its lease given back",
                             workflow_id, WORK_S)
    finally:
        PATCH_MOVES.reset(token)
    if version is None:
        return None
    following = dict(moves)
    while version in following:
        version = following.pop(version)
    return version


_IN_PROCESS: "weakref.WeakValueDictionary[str, asyncio.Lock]" = weakref.WeakValueDictionary()


@asynccontextmanager
async def _one_at_a_time(pool, workflow_id: str):
    """Run the body as the workflow's one reconcile: its in-process lock, then its lease; waited for with backoff,
    at most ``WAIT_S`` in all, after which it runs anyway (logged)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT_S
    lock = _IN_PROCESS.get(workflow_id)
    if lock is None:
        lock = _IN_PROCESS.setdefault(workflow_id, asyncio.Lock())
    try:
        await asyncio.wait_for(lock.acquire(), timeout=WAIT_S)
        locked = True
    except asyncio.TimeoutError:
        locked = False
        logger.warning("[reconcile] %s: another reconcile in this process held it past %ss; running anyway",
                       workflow_id, WAIT_S)
    holder = uuid.uuid4().hex
    leased = False
    renewing = None
    try:
        leased = await _claim(pool, workflow_id, holder, deadline)
        if leased:
            renewing = asyncio.create_task(_renew(pool, workflow_id, holder))
        yield
    finally:
        if renewing is not None:
            renewing.cancel()
        if leased:
            try:
                await pool.execute("DELETE FROM workflow_reconcile_leases WHERE workflow_id = $1::uuid AND holder = $2",
                                   workflow_id, holder)
            except Exception:
                logger.warning("[reconcile] giving back %s's lease failed; it lapses", workflow_id, exc_info=True)
        if locked:
            lock.release()


async def _claim(pool, workflow_id: str, holder: str, deadline: float) -> bool:
    """Take the workflow's lease when it's free or lapsed, retrying with backoff until ``deadline``. False: run
    without it (the wait ran out, or the workflow is gone)."""
    import asyncpg

    loop = asyncio.get_running_loop()
    delay = 0.05
    while True:
        try:
            if await pool.fetchval(
                    f"""INSERT INTO workflow_reconcile_leases (workflow_id, holder, expires_at)
                        VALUES ($1::uuid, $2, now() + interval '{LEASE_S} seconds')
                        ON CONFLICT (workflow_id) DO UPDATE SET holder = EXCLUDED.holder,
                            expires_at = EXCLUDED.expires_at
                        WHERE workflow_reconcile_leases.expires_at < now()
                        RETURNING holder""", workflow_id, holder) == holder:
                return True
        except asyncpg.ForeignKeyViolationError:
            return False  # the workflow is gone: nothing to keep another reconcile of it away from
        if loop.time() + delay > deadline:
            logger.warning("[reconcile] %s: another reconcile held its lease past %ss; running anyway",
                           workflow_id, WAIT_S)
            return False
        await asyncio.sleep(delay * random.uniform(0.8, 1.2))
        delay = min(delay * 2, 1.0)


async def _renew(pool, workflow_id: str, holder: str) -> None:
    """Keep the lease while the work runs, never past ``WORK_S``: a holder that can't be stopped lets it lapse."""
    loop = asyncio.get_running_loop()
    until = loop.time() + WORK_S
    while loop.time() + LEASE_S / 3 < until:
        await asyncio.sleep(LEASE_S / 3)
        try:
            await pool.execute(f"UPDATE workflow_reconcile_leases SET expires_at = now() + interval '{LEASE_S} seconds' "
                               "WHERE workflow_id = $1::uuid AND holder = $2", workflow_id, holder)
        except Exception:
            logger.warning("[reconcile] renewing %s's lease failed", workflow_id, exc_info=True)


async def _stored(pool, workflow_id: str) -> Any:
    """The workflow's graph as stored now (None once it's gone)."""
    return await pool.fetchval("SELECT workflow FROM workflows WHERE id = $1::uuid", workflow_id)


def _ids(graph: Any) -> set:
    return {n.get("id") for n in graph_nodes(graph) if n.get("id")}


async def _tear_down(pool, workflow_id: str, user_id: str, nodes: Dict[str, Any]) -> List[str]:
    """Tear down the steps of ``nodes`` (as they were) that the graph as stored still lacks, and give back their
    inboxes; the ones torn down."""
    from utils.email_reservation_manager import EmailReservationManager
    from utils.workflow_resource_manager import cleanup_nodes_resources

    present = _ids(await _stored(pool, workflow_id))
    removed = [node_id for node_id in nodes if node_id not in present]
    if not removed:
        return []
    try:
        await cleanup_nodes_resources(pool=pool, workflow_id=workflow_id, node_ids=removed, background=False,
                                      old_nodes=[nodes[i] for i in removed if nodes[i] is not None],
                                      requesting_user_id=user_id)
    except Exception:
        logger.warning("[reconcile] cleanup of removed steps %s of %s failed", removed, workflow_id, exc_info=True)
    try:
        await EmailReservationManager.release_many(pool, workflow_id, removed)
    except Exception:
        logger.warning("[reconcile] releasing the inboxes of %s of %s failed", removed, workflow_id, exc_info=True)
    return removed


async def _register(pool, workflow_id: str, user_id: str, node_ids: List[str]) -> List[str]:
    """Register again what the steps of ``node_ids`` the graph as stored holds registered; the ones it did."""
    from utils.webhook_manager import WebhookManager

    present = _ids(await _stored(pool, workflow_id))
    back = [node_id for node_id in node_ids if node_id in present]
    if back:
        try:
            await WebhookManager.register_node_webhooks(pool, workflow_id, user_id, node_ids=back)
        except Exception:
            logger.warning("[reconcile] re-registering %s of %s failed", back, workflow_id, exc_info=True)
    return back


async def _reconcile(pool, workflow_id: str, user_id: str, old_graph: Any, new_graph: Any,
                     deleted: Optional[Collection[str]]) -> None:
    from utils.webhook_manager import WebhookManager
    from utils.workflow_readiness import unbound_issues

    old_nodes = {n.get("id"): n for n in graph_nodes(old_graph) if n.get("id")}
    new_nodes = {n.get("id"): n for n in graph_nodes(new_graph) if n.get("id")}

    gone = [node_id for node_id in old_nodes if node_id not in new_nodes] if deleted is None else \
        [node_id for node_id in dict.fromkeys(deleted) if node_id and node_id not in new_nodes]
    torn = await _tear_down(pool, workflow_id, user_id, {node_id: old_nodes.get(node_id) for node_id in gone})
    if torn:
        # A write in between put one back while it was torn down: it registers again.
        await _register(pool, workflow_id, user_id, torn)

    now_graph = await _stored(pool, workflow_id)
    now_ids = _ids(now_graph)
    for node_id, node in new_nodes.items():
        old = old_nodes.get(node_id)
        if old is None or node_id not in now_ids:
            continue
        node_type = node.get("type", "")
        old_config, new_config = node_config(old), node_config(node)
        try:
            old_op, new_op = old_config.get("operation"), new_config.get("operation")
            if old_op and new_op and old_op != new_op:
                await WebhookManager.handle_operation_change(pool, node_type, workflow_id, node_id, old_op, new_op,
                                                             old_config=old_config, user_id=user_id)
            await WebhookManager.handle_credential_change(pool, node_type, workflow_id, node_id, old_config,
                                                          new_config, user_id)
            # Registration fields (PostHog's event_name, GitHub's repository) under the same operation and
            # connections: else the provider stays registered on the old value until the panel reopens.
            await WebhookManager.handle_registration_fields_change(pool, node_type, workflow_id, node_id,
                                                                   old_config, new_config, user_id=user_id)
        except Exception:
            logger.warning("[reconcile] change hooks of %s:%s failed", workflow_id, node_id, exc_info=True)

    # Triggers as they stand now: a later write's own reconcile judges what it changed.
    provisioned = []
    for trigger in graph_nodes(now_graph):
        config = node_config(trigger)
        kind, node_id = trigger.get("type"), trigger.get("id")
        if not node_id or config.get("disabled") in (True, "true"):
            continue
        if not WebhookManager.node_webhook_field_for(kind, config.get("operation")):
            continue
        if config.get("webhook_url") and not config.get("trigger_error"):
            continue
        try:
            if await unbound_issues(pool, workflow_id, now_graph, node_id):
                continue
            patch = await WebhookManager.provision_node_webhook(
                pool, user_id=user_id, workflow_id=workflow_id, node_id=node_id, node_type=kind,
                operation=config.get("operation"), config=config, workflow_graph=now_graph)
            if patch:
                provisioned.append(node_id)
                await WebhookManager.merge_node_config_patch(pool, workflow_id, node_id, patch)
        except Exception:
            logger.warning("[reconcile] trigger activation of %s:%s failed", workflow_id, node_id, exc_info=True)

    registered = await _register(pool, workflow_id, user_id,
                                 [node_id for node_id in new_nodes if node_id not in old_nodes])
    # A write in between removed one while it was registered: it's torn down.
    stood = {n.get("id"): n for n in graph_nodes(now_graph)}
    await _tear_down(pool, workflow_id, user_id, {node_id: stood.get(node_id) or new_nodes.get(node_id)
                                                  for node_id in dict.fromkeys([*provisioned, *registered])})
