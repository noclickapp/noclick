"""Shared plumbing for poll-based triggers.

Some integrations have no usable push API (Google Sheets, Notion databases,
Google Forms), so their triggers run on a schedule: a Cloudflare cron Durable
Object fires on the configured interval and POSTs the node's webhook URL; the
workflow then runs and the node's ``execute()`` polls the external API for new
items.

``ScheduledPollTriggerMixin`` owns the generic wiring — provisioning the webhook
URL, creating/updating the cron schedule, teardown, and ``seen``-set dedup.
``PollTriggerConfigBase`` carries the config fields every poll trigger needs;
node trigger configs subclass it and add ``operation`` plus node-specific fields.

A poll node implements only its ``execute()`` poll logic and calls
``_filter_unseen`` to emit just the items it hasn't seen before.
"""

import hashlib
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from nodes.cron_trigger_node import ScheduleConfig
from nodes.core.schedule_registration import CronScheduleTriggerMixin

logger = logging.getLogger(__name__)

# Bound the per-node seen-id set so it cannot grow without limit.
_MAX_SEEN_IDS = 10000


def bounded_seen_ids(
    prev_ids: List[str], current_ids: List[str], cap: int = _MAX_SEEN_IDS
) -> List[str]:
    """Merge a persisted seen-set with this poll's ids, order-preserving, and
    cap the size — keeping the MOST-RECENTLY-active ids.

    This poll's ids move to the end, so when the set overflows ``cap`` the ids
    dropped are the ones that haven't appeared in recent polls (already scrolled
    off the source), never ids still in the current window. Slicing a plain
    ``set`` instead would drop arbitrary ids and re-fire ones still present.
    """
    current_dedup = list(dict.fromkeys(current_ids))
    current_set = set(current_dedup)
    merged = [i for i in prev_ids if i not in current_set] + current_dedup
    return merged[-cap:]


class PollTriggerConfigBase(BaseModel):
    """Config fields shared by every poll-trigger operation.

    Subclasses declare ``operation`` (the discriminator) and any node-specific
    fields (e.g. a spreadsheet id).
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    schedule: Optional[ScheduleConfig] = Field(
        default_factory=lambda: ScheduleConfig(frequency="minutes", interval=5),
        title="Schedule",
        json_schema_extra={
            "ui:widget": "schedule",
            "x-exclude-frequencies": ["seconds"],
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True, "ui:loadValue": True},
    )
    schedule_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    next_run: Optional[str] = Field(
        default=None, json_schema_extra={"ui:widget": "nextRun"}
    )
    interval_ms: Optional[int] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_active: Optional[bool] = Field(
        default=True, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


def _scope_of_op_config(op_config: BaseModel) -> str:
    """Hash of a PARSED operation config minus the shared infra fields
    (schedule/webhook mirrors) — i.e. exactly the operation + node-specific
    fields the poll reads."""
    identity = {
        k: v for k, v in op_config.model_dump(mode="json").items()
        if k not in PollTriggerConfigBase.model_fields
    }
    canon = json.dumps(identity, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def poll_scope(node_cls, flat_config: Optional[Dict[str, Any]]) -> Optional[str]:
    """Identity hash of WHAT a poll trigger watches. A seen-set baseline is
    only valid for the scope it was recorded under: point the trigger at a
    different resource (new form_id) and the next poll re-baselines instead
    of blasting the new resource's entire history through the workflow.

    The identity is an ALLOWLIST — the operation's DECLARED config fields,
    taken from the parsed model (the same typed view ``execute()`` reads) —
    never the raw flat dict: the flat config also carries canvas/builder
    metadata (``goal``, ``label``, ``operationReason``, ``userFields``, …),
    and hashing those made every cosmetic write look like a repoint, so
    routine builder churn re-baselined per poll and swallowed real events
    (2026-08-04). Returns ``None`` when the config doesn't parse — callers
    treat that as "cannot judge", never as a mismatch.
    """
    try:
        parsed = node_cls.parse_config({"config": dict(flat_config or {})})
    except Exception:
        return None
    op_config = getattr(parsed, "config", None)
    if not isinstance(op_config, BaseModel):
        return None
    return _scope_of_op_config(op_config)


def registration_config_error(node_cls, context: Optional[Dict[str, Any]]) -> Optional[str]:
    """Blocker for schedule registration: the trigger config in ``context``
    fails validation (missing required fields), so a registered schedule would
    just mint a failing tick every interval. Judged only when the context
    carries an ``operation`` — contexts without one (the FE schedule-update
    path merges none) can't be judged against the discriminated union and
    register as before. ``{{ref}}`` values count as valid-pending-runtime.
    """
    ctx = context or {}
    if not ctx.get("operation"):
        return None
    verdict = node_cls.validate_saved_config(ctx)
    if verdict["valid"]:
        return None
    return "; ".join(verdict["errors"]) or "config failed validation"


class ScheduledPollTriggerMixin(CronScheduleTriggerMixin):
    """Trigger-node mixin for schedule-driven polling.

    Mix in *before* ``WorkflowNode``. A member of the cron-schedule
    registration family (``CronScheduleTriggerMixin``): registration,
    teardown and the shared ``load_field_value`` all converge through
    ``WebhookManager.reconcile_node`` — this mixin adds only what polling
    needs on top: the ``_filter_unseen`` dedup helper, the poll-scope
    identity, the arm-time baseline, and ``resolve_trigger_payload`` (the
    cron POST is a wake-up signal).
    """

    @classmethod
    def schedule_poll_scope(cls, config: Dict[str, Any]) -> Optional[str]:
        """A repoint (new form_id) rotates the registration fingerprint so
        the reconciler re-arms a fresh baseline for the new resource."""
        return poll_scope(cls, config)

    @classmethod
    async def arm_schedule_trigger(
        cls,
        *,
        user_id: str,
        workflow_id: str,
        node_id: str,
        config: Dict[str, Any],
        pool,
    ) -> None:
        # Arm-time baseline: snapshot the watched resource NOW, so "new" is
        # measured from arming — not from the first scheduled tick, which
        # used to swallow anything submitted in between (the user's own test
        # submission, typically).
        await cls._establish_poll_baseline(
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
            context=config,
            credential_ids=(config or {}).get("credentialIds"),
            pool=pool,
        )

    @classmethod
    async def _establish_poll_baseline(
        cls,
        *,
        user_id: str,
        workflow_id,
        node_id: str,
        context: Optional[Dict[str, Any]],
        credential_ids: Optional[Dict[str, str]],
        pool,
    ) -> None:
        """Run the trigger's poll once, headlessly, right after schedule
        registration. The poll IS the baseline mechanism (``_filter_unseen``
        first-poll semantics), so there is no second snapshot implementation
        to drift from the real poll. ``_poll_baseline_only`` makes it
        write-a-baseline-or-nothing: when a valid baseline for the current
        scope already exists (panel reopen, schedule edit, race with a live
        tick) it cannot consume unseen items. Every failure is non-fatal —
        no state is written and the first scheduled tick baselines as before.
        """
        from nodes.core.registry import NODE_REGISTRY, NodeFactory
        from nodes.core.run_op import resolve_operation_credential
        from utils.credentials import pick_credential_id
        from utils.database_pool import get_native_pool

        try:
            # Cheap pre-check: an existing baseline whose scope matches (or
            # predates scoping — adopted, never rotated) needs no provider
            # call. Only a missing or scope-mismatched baseline polls.
            row = await get_native_pool().fetchrow(
                "SELECT state FROM workflow_node_state WHERE workflow_id = $1 AND node_id = $2",
                workflow_id, node_id,
            )
            if row is not None:
                state = row["state"]
                if isinstance(state, str):
                    state = json.loads(state)
                state = state or {}
                stored_scope = state.get("scope")
                ctx_scope = poll_scope(cls, context)
                # A baseline exists and nothing says it's for a different
                # resource (unscoped legacy state and an unjudgeable context
                # both count as "no mismatch") → no provider call.
                if "seen_ids" in state and (
                    stored_scope is None
                    or ctx_scope is None
                    or stored_scope == ctx_scope
                ):
                    return

            node_type = next((k for k, v in NODE_REGISTRY.items() if v is cls), None)
            if node_type is None:
                return

            credential_id = pick_credential_id(credential_ids or {})
            node_data: Dict[str, Any] = {"config": dict(context or {})}
            if credential_id:
                node_data["credentials"] = await resolve_operation_credential(
                    credential_id, user_id, pool, workflow_id=str(workflow_id)
                )
                node_data["credential_id"] = credential_id

            instance = NodeFactory.create_node(
                node_id=node_id,
                node_type=node_type,
                node_data=node_data,
                sio=None,
                sid=None,
                workflow_id=str(workflow_id),
                user_id=user_id,
            )
            instance._poll_baseline_only = True
            await instance.run({})
            logger.info(f"[{cls.__name__}] Arm-time baseline established for node {node_id}")
        except Exception as e:
            logger.warning(
                f"[{cls.__name__}] Arm-time baseline for node {node_id} skipped: {e}"
            )

    # cleanup_external_webhook (schedule deletion) is inherited from
    # CronScheduleTriggerMixin — one teardown for the whole family.

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        """The cron POST is a wake-up signal — run execute() to do the poll."""
        return None

    async def _filter_unseen(
        self, items: List[Any], id_fn: Callable[[Any], Optional[str]]
    ) -> List[Any]:
        """Return only items whose id has not been seen on a previous poll.

        The first poll for a given poll scope (see ``poll_scope``) *baselines*
        — it records the current items as seen and emits nothing, so the
        trigger only fires for items that appear afterwards. A stored baseline
        whose scope no longer matches (the watched resource changed) is
        re-baselined the same way. Legacy state without a scope is adopted:
        dedup runs as before and the scope is stamped on the next write.

        With ``_poll_baseline_only`` set (the arm-time baseline runner), the
        poll only ever WRITES a baseline — when a valid one for this scope
        already exists it neither consumes unseen items nor writes: this is a
        headless run, and anything it marked seen would never reach the
        workflow.

        The seen-set write is a compare-and-swap (``_update_node_state``): an
        overlapping poll on another container that already emitted these items
        wins, and this poll re-reads and yields nothing instead of
        double-firing.
        """
        # Prefer the parsed config on this instance — the exact typed view
        # execute() ran with; fall back to parsing the raw node_data config.
        op_config = getattr(getattr(self, "_config", None), "config", None)
        scope = (
            _scope_of_op_config(op_config) if isinstance(op_config, BaseModel)
            else poll_scope(type(self), (getattr(self, "node_data", None) or {}).get("config"))
        )
        baseline_only = getattr(self, "_poll_baseline_only", False)

        def mutator(state):
            seen_list = state.get("seen_ids", [])  # ordered, least-recent first
            stored_scope = state.get("scope")
            is_first_poll = "seen_ids" not in state
            # An unjudgeable scope (None) is never a mismatch — rebaselining on
            # a non-signal would swallow real events.
            rebaseline = (
                scope is not None and stored_scope is not None and stored_scope != scope
            )
            seen = set(seen_list)

            current_ids = []
            fresh: List[Any] = []
            for item in items:
                item_id = id_fn(item)
                if item_id is None:
                    continue
                current_ids.append(item_id)
                if not is_first_poll and not rebaseline and item_id not in seen:
                    fresh.append(item)

            scope_to_store = scope if scope is not None else stored_scope
            if is_first_poll or rebaseline:
                new_state = {"seen_ids": bounded_seen_ids([], current_ids)}
                if scope_to_store is not None:
                    new_state["scope"] = scope_to_store
                return new_state, ([], "rebaseline" if rebaseline else "baseline")
            if baseline_only:
                return None, ([], None)  # valid baseline exists → hands off
            if fresh:
                new_state = {"seen_ids": bounded_seen_ids(seen_list, current_ids)}
                if scope_to_store is not None:
                    new_state["scope"] = scope_to_store
                return new_state, (fresh, None)
            return None, ([], None)  # nothing new → no write

        # skip_result: on a transient state blip / lost contention, emit nothing
        # this tick (state untouched) instead of failing the scheduled run.
        fresh, baseline_event = await self._update_node_state(
            mutator, skip_result=([], None)
        )
        if baseline_event:
            # A baseline swallow is invisible in outputs (emits nothing) — the
            # 2026-08-04 scope-flap diagnosis had to be reconstructed from
            # state-version arithmetic. Make it a queryable event instead.
            logger.info(
                f"[{type(self).__name__}] node {self.node_id}: poll {baseline_event} "
                f"(scope={scope}) — existing items recorded as seen, nothing emitted"
            )
        self._poll_emitted_count = 0 if baseline_event else len(fresh)
        return fresh

    def trigger_produced_no_event(self, output: Dict[str, Any]) -> bool:
        """Poll found nothing new (``_filter_unseen`` emitted no fresh items)
        → executor skips downstream. Returns False when the node never
        polled, so it can never wrongly halt. See ``WorkflowNode`` for the seam.
        """
        return getattr(self, "_poll_emitted_count", None) == 0

    def trigger_emitted_event(self, output: Dict[str, Any]) -> bool:
        """Poll ran this run and emitted fresh items → the executor stamps
        ``_pollFired`` so a wired agent receives them as its trigger event on
        any run source. See ``WorkflowNode`` for the seam."""
        return (getattr(self, "_poll_emitted_count", None) or 0) > 0
