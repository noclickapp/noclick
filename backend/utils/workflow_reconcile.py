"""What a change to a workflow's graph sets in motion outside the graph,
judged from the steps it touched, for every writer (the graph service's edits
and restores, the canvas's save):

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
- a step that's back (a delete undone) registers again what it registered,
  and claims its inbox's address again.

It makes provider round-trips, so no request waits on it: the write records
it (``enqueue``, a ``workflow_reconcile_jobs`` row, in the write's own
transaction) and, once committed, wakes the workflow's worker (``kick``). The
worker (``run``) holds the workflow's lease (``workflow_reconcile_leases``,
claimed, renewed and given back in short statements, so it holds no
connection or transaction while it works) and runs the workflow's jobs in
order step by step: a job waits only for older ones touching one of its steps.
Each is bounded (``WORK_S``; the lease is never renewed past it). A job that
fails or is cut off is retried with backoff (``MAX_ATTEMPTS``), shown where
people look (a trigger step's ``trigger_error``, an ERROR log, the staff
Reliability view), and once given up on it's kept and retried daily
(``retry_given_up``), never dropped; one left by a worker that died resumes
when the lease lapses, on the next sweep (``sweep``: the hosted edition's
operations tick, the open edition's scheduler). A change that only moved steps
queues nothing. The versions a job's own writes produce (a trigger's
webhook fields) are recorded (``workflow_reconcile_versions``): an edit made
on a version is still made on it when only those came after
(``graph_service._locked``).

Each teardown and registration acts on the graph as stored when it acts (a
removed step torn down only while it's still absent, a step registered only
while it's still there), then checks it again and puts right what a write in
between changed (a step back while it was torn down registers again; one
removed while it was registered is torn down), so two runs that overlap (a
lease that lapsed under a worker) still leave each step as the graph has
it."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Collection, Dict, List, Optional, Tuple

from utils.graph_nodes import graph_nodes, node_config

logger = logging.getLogger(__name__)

# A lease lapses LEASE_S after its last renewal (renewed every third of it while its worker runs).
LEASE_S = 60
# How long one job's work may run before it's stopped (and retried).
WORK_S = 120.0
# A job that keeps failing is given up on (logged) after this many attempts, waiting RETRY_S, doubling, between.
MAX_ATTEMPTS = 6
RETRY_S = 30
RETRY_MAX_S = 1800
# How many workflows one sweep runs the due jobs of, how many at once, and how often (the open edition's scheduler).
SWEEP_LIMIT = 50
SWEEP_CONCURRENCY = 4
SWEEP_EVERY_S = 30
# Finished jobs and recorded reconcile versions are kept this long.
KEEP_DAYS = 30


# What a trigger step whose registration a job couldn't finish shows (its ``trigger_error``) until a run of it does.
UNFINISHED = "NoClick couldn't finish registering this trigger and is retrying:"
# Where a step sits and how big it's drawn: moving it sets nothing in motion.
_LAYOUT_KEYS = frozenset({"position", "positionAbsolute", "width", "height", "measured", "style", "selected",
                          "dragging", "zIndex"})


class ReconcileIncomplete(Exception):
    """Part of a job's work failed; the job is retried."""


def _nodes(graph: Any) -> Dict[str, Any]:
    return {n.get("id"): n for n in graph_nodes(graph) if n.get("id")}


def _unplaced(node: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return None if node is None else {k: v for k, v in node.items() if k not in _LAYOUT_KEYS}


async def enqueue(conn, workflow_id: str, user_id: Optional[str], old_graph: Any, new_graph: Any, *,
                  from_version: int, to_version: int,
                  deleted: Optional[Collection[str]] = None) -> Optional[int]:
    """Record, in the write's transaction (``conn``), what its change sets in motion: the steps it touched (removed,
    added, changed) as they were and as it left them, and the canvas's ``deleted`` steps. None when it touched
    none."""
    old, new = _nodes(old_graph), _nodes(new_graph)
    touched = [node_id for node_id in dict.fromkeys([*old, *new])
               if _unplaced(old.get(node_id)) != _unplaced(new.get(node_id))]
    named = [node_id for node_id in dict.fromkeys(deleted or ()) if node_id]
    if not touched and not named:
        return None
    ids = dict.fromkeys([*touched, *named])
    return await conn.fetchval(
        "INSERT INTO workflow_reconcile_jobs (workflow_id, user_id, old_nodes, new_nodes, deleted, from_version, "
        "to_version) VALUES ($1::uuid, $2::uuid, ($3::text)::jsonb, ($4::text)::jsonb, $5, $6, $7) RETURNING id",
        str(workflow_id), user_id,
        json.dumps({i: old[i] for i in ids if i in old}), json.dumps({i: new[i] for i in ids if i in new}),
        None if deleted is None else named, from_version, to_version)


def kick(pool, workflow_id: str) -> None:
    """Wake the workflow's worker once the write that queued a job has committed; never awaited."""
    from utils.async_helpers import spawn

    spawn(run(pool, str(workflow_id)), name=f"workflow-reconcile:{workflow_id}")


async def reconcile_graph_change(pool, workflow_id: str, user_id: Optional[str], old_graph: Any, new_graph: Any, *,
                                 from_version: int = 0, to_version: int = 0,
                                 deleted: Optional[Collection[str]] = None) -> Optional[int]:
    """Queue a change's reconcile (its own transaction) and run the workflow's due jobs now; the job's id."""
    async with pool.acquire() as conn:
        job = await enqueue(conn, workflow_id, user_id, old_graph, new_graph, from_version=from_version,
                            to_version=to_version, deleted=deleted)
    if job is not None:
        await run(pool, str(workflow_id))
    return job


# ── the worker ──────────────────────────────────────────────────────────────

async def run(pool, workflow_id: str) -> None:
    """Run the workflow's due jobs, oldest first, as its one worker: when another holds the lease it returns (that
    worker looks again before it lets go), and it looks again itself after letting go, so a job queued meanwhile
    is never left waiting for a sweep."""
    workflow_id = str(workflow_id)
    while True:
        holder = uuid.uuid4().hex
        if not await _claim(pool, workflow_id, holder):
            return
        bound = {"until": asyncio.get_running_loop().time() + WORK_S}
        renewing = asyncio.create_task(_renew(pool, workflow_id, holder, bound))
        try:
            while (job := await _next(pool, workflow_id)) is not None:
                bound["until"] = asyncio.get_running_loop().time() + WORK_S
                await _run_job(pool, job)
        finally:
            renewing.cancel()
            try:
                await pool.execute("DELETE FROM workflow_reconcile_leases WHERE workflow_id = $1::uuid AND holder = $2",
                                   workflow_id, holder)
            except Exception:
                logger.warning("[reconcile] giving back %s's lease failed; it lapses", workflow_id, exc_info=True)
        if await _next(pool, workflow_id) is None:
            return


async def sweep(pool) -> int:
    """Run the due jobs of the workflows no live worker holds (a worker that died, a retry that's due); how many
    workflows it ran."""
    rows = await pool.fetch(
        "SELECT DISTINCT j.workflow_id FROM workflow_reconcile_jobs j "
        "LEFT JOIN workflow_reconcile_leases l ON l.workflow_id = j.workflow_id AND l.expires_at > now() "
        "WHERE j.status = 'queued' AND j.retry_at <= now() AND l.workflow_id IS NULL LIMIT $1", SWEEP_LIMIT)
    # A few workflows at once, so one slow provider doesn't hold every other workflow's retries.
    room = asyncio.Semaphore(SWEEP_CONCURRENCY)

    async def one(workflow_id: str) -> None:
        async with room:
            try:
                await run(pool, workflow_id)
            except Exception:
                logger.error("[reconcile] sweeping %s failed", workflow_id, exc_info=True)

    await asyncio.gather(*(one(str(row["workflow_id"])) for row in rows))
    return len(rows)


async def retry_given_up(pool) -> int:
    """Queue again every job given up on (the daily maintenance): what it sets in motion (inboxes, volumes, apps,
    conversations, registrations) is never left undone for good. How many."""
    result = await pool.execute("UPDATE workflow_reconcile_jobs SET status = 'queued', attempts = 0, retry_at = now(), "
                                "done_at = NULL WHERE status = 'failed'")
    requeued = int(result.split()[-1])
    if requeued:
        await sweep(pool)
    return requeued


async def prune(pool, *, days: int = KEEP_DAYS) -> int:
    """Drop done jobs and recorded reconcile versions older than ``days`` (a job given up on stays, retried daily);
    how many jobs went."""
    result = await pool.execute("DELETE FROM workflow_reconcile_jobs WHERE status = 'done' "
                                "AND done_at < now() - make_interval(days => $1)", days)
    await pool.execute("DELETE FROM workflow_reconcile_versions WHERE created_at < now() - make_interval(days => $1)",
                       days)
    return int(result.split()[-1])


async def _claim(pool, workflow_id: str, holder: str) -> bool:
    """Take the workflow's lease when it's free or lapsed. False: a live worker holds it, or the workflow's gone."""
    import asyncpg

    try:
        return await pool.fetchval(
            f"""INSERT INTO workflow_reconcile_leases (workflow_id, holder, expires_at)
                VALUES ($1::uuid, $2, now() + interval '{LEASE_S} seconds')
                ON CONFLICT (workflow_id) DO UPDATE SET holder = EXCLUDED.holder, expires_at = EXCLUDED.expires_at
                WHERE workflow_reconcile_leases.expires_at < now()
                RETURNING holder""", workflow_id, holder) == holder
    except asyncpg.ForeignKeyViolationError:
        return False


async def _renew(pool, workflow_id: str, holder: str, bound: Dict[str, float]) -> None:
    """Keep the lease while a job runs, never past its ``WORK_S``: a worker that can't be stopped lets it lapse."""
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(LEASE_S / 3)
        if loop.time() > bound["until"]:
            return
        try:
            await pool.execute(f"UPDATE workflow_reconcile_leases SET expires_at = now() + interval '{LEASE_S} seconds' "
                               "WHERE workflow_id = $1::uuid AND holder = $2", workflow_id, holder)
        except Exception:
            logger.warning("[reconcile] renewing %s's lease failed", workflow_id, exc_info=True)


def _as_dict(value: Any) -> Dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value or {})


def _steps(job: Dict[str, Any]) -> set:
    """The steps a job touches."""
    return {*_as_dict(job["old_nodes"]), *_as_dict(job["new_nodes"]), *(job["deleted"] or ())}


async def _next(pool, workflow_id: str) -> Optional[Dict[str, Any]]:
    """The workflow's oldest due job that no older queued job shares a step with (one waiting for its retry holds
    only the jobs touching its steps); None when there's none."""
    rows = await pool.fetch(
        "SELECT id, workflow_id, user_id, old_nodes, new_nodes, deleted, from_version, to_version, attempts, "
        "retry_at <= now() AS due FROM workflow_reconcile_jobs WHERE workflow_id = $1::uuid AND status = 'queued' "
        "ORDER BY id", workflow_id)
    held: set = set()
    for row in rows:
        steps = _steps(row)
        if row["due"] and not steps & held:
            return dict(row)
        held |= steps
    return None


async def _run_job(pool, job: Dict[str, Any]) -> bool:
    """Run one job; True when it's done."""
    from utils.webhook_manager import PATCH_MOVES

    workflow_id = str(job["workflow_id"])
    user_id = str(job["user_id"]) if job["user_id"] else None
    old = {"nodes": list(_as_dict(job["old_nodes"]).values())}
    new = {"nodes": list(_as_dict(job["new_nodes"]).values())}
    before = await _row(pool, workflow_id)
    moves: List[Tuple[int, int]] = []
    token = PATCH_MOVES.set(moves)
    try:
        await asyncio.wait_for(_reconcile(pool, workflow_id, user_id, old, new, job["deleted"]), timeout=WORK_S)
    except Exception as e:
        reason = f"ran past {WORK_S:g}s" if isinstance(e, asyncio.TimeoutError) else (str(e) or type(e).__name__)
        attempts = job["attempts"] + 1
        given_up = attempts >= MAX_ATTEMPTS
        await pool.execute(
            "UPDATE workflow_reconcile_jobs SET attempts = $2, status = $3, last_error = $4, "
            "retry_at = now() + make_interval(secs => $5), done_at = CASE WHEN $3 = 'failed' THEN now() END "
            "WHERE id = $1", job["id"], attempts, "failed" if given_up else "queued", reason[:2000],
            float(min(RETRY_S * 2 ** (attempts - 1), RETRY_MAX_S)))
        # Its first failure and its giving up page; the retries between only log.
        log = logger.error if given_up or attempts == 1 else logger.warning
        log("[reconcile] job %s of %s (steps %s) %s (attempt %s): %s", job["id"], workflow_id,
            ", ".join(sorted(_steps(job))), "given up on, retried daily" if given_up else "failed, to be retried",
            attempts, reason)
        return False
    finally:
        PATCH_MOVES.reset(token)
    await pool.execute("UPDATE workflow_reconcile_jobs SET status = 'done', done_at = now() WHERE id = $1", job["id"])
    if moves and before is not None:
        await _tell_own_writes(pool, workflow_id, before)
    return True


async def _row(pool, workflow_id: str) -> Optional[Dict[str, Any]]:
    from repositories.workflow import WorkflowRepo

    async with pool.acquire() as conn:
        return await WorkflowRepo(pool).read_graph(conn, workflow_id)


async def _tell_own_writes(pool, workflow_id: str, before: Dict[str, Any]) -> None:
    """Every canvas open on the workflow applies what the job's own writes changed, when nothing else wrote in
    between (each version since ``before`` is a reconcile's); else a canvas's next save conflicts and rebases."""
    from coder.workflow.graph_service import _of, canvas_events, tell

    after = await _row(pool, workflow_id)
    if after is None or after["graph_version"] <= before["graph_version"]:
        return
    ours = await pool.fetchval(
        "SELECT count(*) FROM workflow_reconcile_versions WHERE workflow_id = $1::uuid AND version > $2 "
        "AND version <= $3", workflow_id, before["graph_version"], after["graph_version"])
    if ours != after["graph_version"] - before["graph_version"]:
        return
    await tell(str(after["owner_id"]), workflow_id, after["graph_version"], canvas_events(_of(before), _of(after)),
               base=before["graph_version"])


# ── the work ────────────────────────────────────────────────────────────────

async def _stored(pool, workflow_id: str) -> Any:
    """The workflow's graph as stored now (None once it's gone)."""
    return await pool.fetchval("SELECT workflow FROM workflows WHERE id = $1::uuid", workflow_id)


def _ids(graph: Any) -> set:
    return {n.get("id") for n in graph_nodes(graph) if n.get("id")}


async def _tear_down(pool, workflow_id: str, user_id: Optional[str], nodes: Dict[str, Any]) -> List[str]:
    """Tear down the steps of ``nodes`` (as they were) that the graph as stored still lacks, and give back their
    inboxes; the ones torn down."""
    from utils.email_reservation_manager import EmailReservationManager
    from utils.workflow_resource_manager import cleanup_nodes_resources

    present = _ids(await _stored(pool, workflow_id))
    removed = [node_id for node_id in nodes if node_id not in present]
    if not removed:
        return []
    await cleanup_nodes_resources(pool=pool, workflow_id=workflow_id, node_ids=removed, background=False,
                                  old_nodes=[nodes[i] for i in removed if nodes[i] is not None],
                                  requesting_user_id=user_id)
    present = _ids(await _stored(pool, workflow_id))
    await EmailReservationManager.release_many(pool, workflow_id, [i for i in removed if i not in present])
    return removed


async def _register(pool, workflow_id: str, user_id: Optional[str], node_ids: List[str]) -> List[str]:
    """Register again what the steps of ``node_ids`` the graph as stored holds registered, and claim their inboxes'
    addresses again; the ones it did."""
    from utils.webhook_manager import WebhookManager

    stored = _nodes(await _stored(pool, workflow_id))
    back = [node_id for node_id in node_ids if node_id in stored]
    if back:
        await WebhookManager.register_node_webhooks(pool, workflow_id, user_id, node_ids=back)
        for node_id in back:
            await _claim_inbox(pool, workflow_id, user_id, stored[node_id])
    return back


async def _claim_inbox(pool, workflow_id: str, user_id: Optional[str], node: Dict[str, Any]) -> None:
    """An inbound-email step that's back holds its address again, unless another step took it meanwhile."""
    from utils.email_reservation_manager import EmailReservationManager, get_inbound_email_domain
    from utils.webhook_manager import WebhookManager

    config = node_config(node)
    if node.get("type") != "trigger-email" or not config.get("local_part") or get_inbound_email_domain() is None:
        return
    if await pool.fetchval("SELECT 1 FROM email_reservations WHERE workflow_id = $1::uuid AND node_id = $2",
                           workflow_id, node["id"]):
        return
    try:
        patch = await EmailReservationManager.reserve_from_config(pool, user_id, workflow_id, node["id"], config)
    except ValueError as e:
        logger.warning("[reconcile] %s:%s is back but its address can't be claimed again: %s",
                       workflow_id, node["id"], e)
        return
    if patch:
        await WebhookManager.merge_node_config_patch(pool, uuid.UUID(workflow_id), node["id"], patch)


async def _flag(pool, workflow_id: str, node_id: str, reason: Optional[str]) -> None:
    """Show on a trigger step that a job couldn't finish its registration (``reason``), or clear what it showed once
    a run of it did: never another error the step's registration recorded."""
    from utils.webhook_manager import WebhookManager

    try:
        node = _nodes(await _stored(pool, workflow_id)).get(node_id)
        if node is None:
            return
        shown = node_config(node).get("trigger_error")
        ours = isinstance(shown, str) and shown.startswith(UNFINISHED)
        if reason is not None and (not shown or ours) and _is_trigger(node):
            await WebhookManager.merge_node_config_patch(pool, workflow_id, node_id,
                                                         {"trigger_error": f"{UNFINISHED} {reason}"[:500]})
        elif reason is None and ours:
            await WebhookManager.merge_node_config_patch(pool, workflow_id, node_id, {"trigger_error": None})
    except Exception:
        logger.warning("[reconcile] showing %s:%s's registration state failed", workflow_id, node_id, exc_info=True)


def _is_trigger(node: Dict[str, Any]) -> bool:
    from utils.webhook_manager import WebhookManager

    config = node_config(node)
    kind = node.get("type") or ""
    return kind.startswith("trigger-") or bool(WebhookManager.node_webhook_field_for(kind, config.get("operation")))


async def _reconcile(pool, workflow_id: str, user_id: Optional[str], old_graph: Any, new_graph: Any,
                     deleted: Optional[Collection[str]]) -> None:
    """A job's work: raises ``ReconcileIncomplete`` when part of it failed (after doing the rest), so it's
    retried; a trigger's provisioning only logs, as the next job's provisions it again."""
    from utils.webhook_manager import WebhookManager
    from utils.workflow_readiness import unbound_issues

    old_nodes, new_nodes = _nodes(old_graph), _nodes(new_graph)
    failed: List[str] = []

    gone = [node_id for node_id in old_nodes if node_id not in new_nodes] if deleted is None else \
        [node_id for node_id in dict.fromkeys(deleted) if node_id and node_id not in new_nodes]
    try:
        torn = await _tear_down(pool, workflow_id, user_id, {node_id: old_nodes.get(node_id) for node_id in gone})
        if torn:
            # A write in between put one back while it was torn down: it registers again.
            await _register(pool, workflow_id, user_id, torn)
    except Exception as e:
        logger.warning("[reconcile] tearing down %s of %s failed", gone, workflow_id, exc_info=True)
        failed.append(f"tearing down {', '.join(gone)}: {str(e) or type(e).__name__}")

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
        except Exception as e:
            logger.warning("[reconcile] change hooks of %s:%s failed", workflow_id, node_id, exc_info=True)
            failed.append(f"reconciling {node_id}'s registration: {str(e) or type(e).__name__}")
            await _flag(pool, workflow_id, node_id, str(e) or type(e).__name__)
        else:
            await _flag(pool, workflow_id, node_id, None)

    # Triggers as they stand now: a later write's own job judges what it changed.
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

    added = [node_id for node_id in new_nodes if node_id not in old_nodes]
    try:
        registered = await _register(pool, workflow_id, user_id, added)
        # A write in between removed one while it was registered: it's torn down.
        stood = _nodes(now_graph)
        await _tear_down(pool, workflow_id, user_id, {node_id: stood.get(node_id) or new_nodes.get(node_id)
                                                      for node_id in dict.fromkeys([*provisioned, *registered])})
    except Exception as e:
        logger.warning("[reconcile] registering %s of %s failed", added, workflow_id, exc_info=True)
        failed.append(f"registering {', '.join(added)}: {str(e) or type(e).__name__}")
        for node_id in added:
            await _flag(pool, workflow_id, node_id, str(e) or type(e).__name__)
    else:
        for node_id in registered:
            await _flag(pool, workflow_id, node_id, None)
    if failed:
        raise ReconcileIncomplete("; ".join(failed))
