"""
Centralized webhook lifecycle manager — THE owner of trigger registration state.

The ``webhooks`` row is the system of record for a trigger node's external
registration: ``secret``, ``external_webhook_id``, ``registered_operation`` and
``registered_credential_id`` are written synchronously at registration time
(``persist_registration_state``), so signature verification and provider
deregistration never depend on the debounced frontend autosave landing the same
values into the node config blob (the blob only mirrors them for display).

Lifecycle choke points — every mutation surface routes through these two:

- ``deregister_node_webhooks``  — canvas node delete, MCP/agentic remove_node,
  trash, checkpoint restore, operation change, credential swap. Dispatches
  provider teardown via ``node_class.cleanup_external_webhook`` (which is
  provider-side teardown ONLY — the row is managed here), then DEACTIVATES the
  row (``is_active=false``), never deletes it: the UUID/URL survives so a later
  undo/restore re-registers at the same address. ``registered_operation``
  survives deactivation as the "was registered" marker.
- ``register_node_webhooks``    — trash restore, checkpoint restore, canvas
  undo re-add. External-webhook triggers register ONLY from inactive rows
  carrying the marker whose CURRENT operation still requires a webhook (the
  other families converge through ``reconcile_node``); the row re-activates
  only via the post-success persist, so a failed provider call leaves the next
  config-panel open (or restore) to retry.

Rows are hard-deleted only on permanent workflow deletion
(``delete_webhooks_for_workflow``) and by the orphaned-webhook self-heal.

Schema markers:
- Field-level: json_schema_extra={"ui:widget": "webhook"} marks a field as a webhook URL
- Operation-level: model_config=ConfigDict(json_schema_extra={"x-requires-webhook": True})
"""

import asyncio
import logging
import re
from collections import Counter
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from time import monotonic
from typing import Dict, Any, List, Optional, Set, Tuple
from uuid import UUID

from utils.graph_nodes import node_disabled
from utils.runtime_keys import config_without_runtime_keys

logger = logging.getLogger(__name__)

# The versions ``merge_node_config_patch`` moves a workflow through, (before, after) each, while a reconcile job
# runs (``utils.workflow_reconcile``): each such version is recorded as a reconcile's (workflow_reconcile_versions).
PATCH_MOVES: ContextVar[Optional[List[Tuple[int, int]]]] = ContextVar("workflow_patch_moves", default=None)


def _extract_node_config(node: Dict[str, Any]) -> Dict[str, Any]:
    """A node's config lives at ``node['config']`` (backend save format) or
    ``node['data']['config']`` (canvas format). Return whichever is present."""
    cfg = node.get("config") or {}
    if not cfg and isinstance(node.get("data"), dict):
        cfg = node["data"].get("config") or {}
    return cfg


def _usable_credentials(node: Dict[str, Any], node_config: Dict[str, Any]) -> Dict[str, str]:
    """credential type -> id for every usable credential configured on a node
    (config blob or ``node.data.credentialIds``), with ``pick_credential_id``'s
    semantics: the credential_type metadata key, empties, and unresolved
    ``{{...}}`` references are not credential ids."""
    from utils.credentials import extract_credential_ids

    cred_ids = extract_credential_ids(node_config)
    if not cred_ids and isinstance(node.get("data"), dict):
        cred_ids = extract_credential_ids(node["data"])
    return {
        k: v for k, v in (cred_ids or {}).items()
        if k != "credential_type"
        and isinstance(v, str)
        and v.strip() != ""
        and "{{" not in v
    }


def _usable_credential_ids(node: Dict[str, Any], node_config: Dict[str, Any]) -> List[str]:
    """All usable credential ids configured on a node (``_usable_credentials``)."""
    return list(_usable_credentials(node, node_config).values())


def _extract_node_credential_id(node: Dict[str, Any], node_config: Dict[str, Any]) -> Optional[str]:
    """The single credential id configured on a node (trigger nodes carry one)."""
    ids = _usable_credential_ids(node, node_config)
    return ids[0] if ids else None


def _loader_registers(node_type: Optional[str], node: Dict[str, Any], node_config: Dict[str, Any]) -> bool:
    """Whether the node is a trigger its own loader registers (WhatsApp's
    messages on a QR session): it holds a credential its class's
    ``self_registering_triggers`` registers the current operation with."""
    from nodes.core.registry import NODE_REGISTRY

    node_class = NODE_REGISTRY.get(node_type) if node_type else None
    declared = getattr(node_class, "self_registering_triggers", {}).get(
        node_config.get("operation") or "", ()
    )
    return any(t in declared for t in _usable_credentials(node, node_config))


class Holder(str):
    """The workflow holding a one-address resource, as a refusal names it, with
    ``webhook_id``: its registration's row, which a refusal waits on."""

    webhook_id: str

    def __new__(cls, label: str, webhook_id: str):
        holder = super().__new__(cls, label)
        holder.webhook_id = webhook_id
        return holder


async def _live_holder(where: str, *args) -> Optional[Holder]:
    """The workflow of an active webhooks row matching ``where`` (its name, for a refusal), or None."""
    from utils.database_pool import get_native_pool

    row = await get_native_pool().fetchrow(
        "SELECT w.id, w.workflow_id, wf.name FROM webhooks w LEFT JOIN workflows wf ON wf.id = w.workflow_id "
        f"WHERE w.is_active AND {where} LIMIT 1",
        *args,
    )
    if row is None:
        return None
    label = f'"{row["name"]}"' if row["name"] else f"workflow {row['workflow_id']}"
    return Holder(label, str(row["id"]))


async def registration_holder(
    external_webhook_id: str, operations: Tuple[str, ...], *, except_webhook_id: str
) -> Optional[Holder]:
    """The workflow whose live registration on one of ``operations`` already
    holds ``external_webhook_id``, or None. For a provider resource that points
    at ONE address (a phone number's voice webhook, a Telegram bot's webhook):
    a second registration would silently take it from the first, which would
    still read "registered"."""
    return await _live_holder(
        "w.external_webhook_id = $1 AND w.registered_operation = ANY($2::text[]) AND w.id::text <> $3",
        external_webhook_id, list(operations), except_webhook_id,
    )


_WEBHOOK_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def webhook_id_for_url(url: str) -> Optional[str]:
    """The webhooks row id ``url`` addresses when it is one of this instance's webhook addresses, else None."""
    from utils.webhook_delivery import get_webhook_url

    match = _WEBHOOK_ID_RE.search(url or "")
    if match is None or get_webhook_url(match.group(0)) != url:
        return None
    return match.group(0).lower()


async def address_holder(url: str, *, except_webhook_id: str) -> Optional[Holder]:
    """The workflow whose live webhook ``url`` is, when it is one of this
    instance's webhook addresses, or None. Where a provider says a one-address
    resource points now: that outlasts any record of ours (a registration made
    before the record was kept)."""
    webhook_id = webhook_id_for_url(url)
    if webhook_id is None:
        return None
    return await _live_holder("w.id::text = $1 AND w.id::text <> $2", webhook_id, except_webhook_id)


def registration_fingerprint(
    node_class,
    operation: Optional[str],
    credential_id: Optional[str],
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """Hash of everything the provider-side registration depends on. The
    reconciler (and the config panel's idempotency guard) compares the row's
    stored fingerprint against the fingerprint of the node's CURRENT saved
    config: equal = live, different = converge. Node classes declare extra
    registration-relevant config fields via
    ``registration_fingerprint_fields`` (GitHub's repository); they never
    sequence transitions."""
    import hashlib
    import json

    fields: Dict[str, Any] = {}
    if node_class is not None and hasattr(node_class, "registration_fingerprint_fields"):
        try:
            fields = node_class.registration_fingerprint_fields(config or {}) or {}
        except Exception:
            logger.warning(
                "[WEBHOOK] registration_fingerprint_fields failed for "
                f"{getattr(node_class, '__name__', node_class)}",
                exc_info=True,
            )
    basis = json.dumps(
        {"op": operation, "cred": credential_id, "fields": fields},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


async def _load_workflow_owner_and_nodes(
    pool, wf_uuid, include_nodes: bool = True
) -> tuple:
    """Fetch ``(owner_id, nodes)`` from a workflow, tolerating a str-encoded
    jsonb blob (pools without a jsonb codec). Returns ``(None, [])`` if missing.
    ``include_nodes=False`` skips shipping the (potentially large) blob when the
    caller only needs the owner."""
    async with pool.acquire() as conn:
        if include_nodes:
            row = await conn.fetchrow(
                "SELECT owner_id, workflow FROM workflows WHERE id = $1", wf_uuid
            )
        else:
            row = await conn.fetchrow(
                "SELECT owner_id FROM workflows WHERE id = $1", wf_uuid
            )
    if not row:
        return None, []
    if not include_nodes:
        return str(row["owner_id"]), []
    wf = row["workflow"] or {}
    if isinstance(wf, str):
        import json as _json
        wf = _json.loads(wf) if wf else {}
    return str(row["owner_id"]), wf.get("nodes", [])


async def _resolve_node_credential(
    pool,
    credential_id: str,
    *,
    owner_id: str,
    requesting_user_id: Optional[str] = None,
    org_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Decrypt a node's credential, preferring the requesting user's access
    (a collaborator may own the credential on a shared workflow), falling back
    to the workflow owner's."""
    from utils.credential_loader import load_credential

    if requesting_user_id:
        from utils.credentials import get_credential
        data = await get_credential(credential_id, requesting_user_id, pool, org_id)
        if data:
            return data
    return await load_credential(pool, owner_id, credential_id)


# Config fields injected by poll-trigger / webhook provisioning that should be
# stripped when a node's operation no longer requires them.
_WEBHOOK_CONFIG_FIELDS = {
    "webhook_id", "webhook_url", "schedule_id", "next_run",
    "interval_ms", "is_active", "relay_connected", "is_production",
    "trigger_registered", "trigger_error", "signing_secret", "external_webhook_id",
}


@lru_cache(maxsize=None)
def _webhook_field_for_cached(node_type: str, operation: Optional[str]) -> Optional[str]:
    """Impl for WebhookManager.node_webhook_field_for — cached because it
    generates the node's full JSON schema (~40ms on large unions) and runs as
    a per-candidate pre-filter; schemas are static per process."""
    from coder.workflow.operation_catalog import get_operation_schema
    from coder.workflow.workflow_schema import resolve_schema_refs
    from nodes.core.registry import NODE_REGISTRY

    node_class = NODE_REGISTRY.get(node_type)
    if node_class is None:
        return None

    if operation:
        op_schema = get_operation_schema(node_type, operation)
    else:
        # Non-discriminated nodes (trigger-webhook etc.): the webhook field
        # lives on the single config schema; resolve $refs first or the
        # ui:widget marker hides inside a $def.
        full_schema = node_class.get_config_schema()
        if full_schema:
            full_schema = resolve_schema_refs(full_schema)
        op_schema = (
            full_schema.get("properties", {}).get("config", full_schema)
            if full_schema else None
        )
    if not op_schema:
        return None
    webhook_field = WebhookManager.get_webhook_field(op_schema)
    if not webhook_field:
        # Poll/cron triggers mark webhook_url as a hidden ui:loadValue field
        # (no webhook widget) — their loaders mint the row and register the
        # schedule; the same panel-equivalent load applies.
        f = op_schema.get("properties", {}).get("webhook_url")
        if isinstance(f, dict) and f.get("ui:loadValue"):
            webhook_field = "webhook_url"
    if not webhook_field:
        # App-event fan-out triggers (Slack/HubSpot/Discord) register via the
        # subscription_status ui:loadValue field — the third registration
        # family. Missing this gate leaves programmatically-created triggers
        # inactive until somebody opens their configuration panel.
        f = op_schema.get("properties", {}).get("subscription_status")
        if isinstance(f, dict) and f.get("ui:loadValue"):
            webhook_field = "subscription_status"
    return webhook_field


def _schedule_trigger_class(node_type: Optional[str]):
    """The node class when ``node_type`` belongs to the cron-schedule
    registration family (poll mixin, cron node, bespoke schedule pollers)."""
    from nodes.core.registry import NODE_REGISTRY
    from nodes.core.schedule_registration import CronScheduleTriggerMixin

    node_class = NODE_REGISTRY.get(node_type) if node_type else None
    if (
        node_class
        and isinstance(node_class, type)
        and issubclass(node_class, CronScheduleTriggerMixin)
    ):
        return node_class
    return None


def fires_on_schedule(node_type: Optional[str], operation: Optional[str]) -> bool:
    """Whether a node on ``operation`` is a trigger NoClick's scheduler fires
    (the cron node, a poll trigger), which can also be fired at any moment."""
    schedule_class = _schedule_trigger_class(node_type)
    return bool(schedule_class and schedule_class._is_schedule_operation(operation))


def _schedule_registration_fingerprint(
    operation: Optional[str], spec, scope: Optional[str],
    credential_id: Optional[str],
) -> str:
    """Hash of everything the schedule registration OR its arming depends on:
    the cron expressions + timezone (WHEN it fires), the poll scope (WHAT it
    watches — a repoint must rotate so the reconciler re-arms a fresh
    baseline), and the credential id. Registration itself is credential-free,
    but the ARM (baseline poll) is not: without the credential in the hash, a
    credential attached AFTER registration hit the live fast path and the
    baseline never established until the first tick — the arm-timing gap all
    over again. Re-registering on a credential change is a harmless
    deterministic-id upsert, and re-arming no-ops when a valid baseline for
    the scope already exists."""
    import hashlib
    import json

    basis = json.dumps(
        {
            "op": operation,
            "exprs": list(spec.expressions),
            "tz": spec.timezone,
            "scope": scope,
            "cred": credential_id,
        },
        sort_keys=True, default=str,
    )
    return "sched:" + hashlib.sha256(basis.encode()).hexdigest()[:16]


def _app_event_trigger_class(node_type: Optional[str]):
    """The node class when ``node_type`` belongs to the app-event fan-out
    trigger family (AppEventTriggerMixin — Slack/HubSpot/Discord), else None."""
    from nodes.core.registry import NODE_REGISTRY
    from nodes.core.webhook_subscriptions import AppEventTriggerMixin

    node_class = NODE_REGISTRY.get(node_type) if node_type else None
    if (
        node_class
        and isinstance(node_class, type)
        and issubclass(node_class, AppEventTriggerMixin)
    ):
        return node_class
    return None


def _failure_on_record(node_config: Dict[str, Any]) -> bool:
    """Whether an app-event trigger's mirrors still record a failed registration
    (both failure paths write one), which rows saved by an earlier success don't
    contradict: its last attempt must be judged again, not taken as converged."""
    return node_config.get("trigger_registered") is False or str(
        node_config.get("trigger_error") or ""
    ).startswith("Not registered:")


async def _activation_refusal(pool, wf_uuid, node_id: str):
    """The refusal registering the step would meet for unfinished setup, or None. A failed read raises: it says nothing."""
    from utils.workflow_readiness import WorkflowNotReadyError, require_activation_ready

    try:
        await require_activation_ready(pool, wf_uuid, node_id)
    except WorkflowNotReadyError as refusal:
        return refusal
    return None


_ROW_COLUMNS = (
    "id, is_active, external_webhook_id, registered_operation, registered_credential_id, registered_fingerprint, "
    "refused_fingerprint, refused_kind, refused_holder_id, refused_resource, refused_credential_version, "
    "(secret IS NOT NULL) AS secret_set"
)


async def _webhook_row(pool, wf_uuid, node_id: str) -> Optional[Dict[str, Any]]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_ROW_COLUMNS} FROM webhooks WHERE workflow_id = $1 AND node_id = $2", wf_uuid, node_id)
    return dict(row) if row is not None else None


def _recorded(row: Optional[Dict[str, Any]]) -> bool:
    """Whether the row records a registration a teardown can find: its operation, while live or with its endpoint."""
    return bool(row and row.get("registered_operation") and (row.get("is_active") or row.get("external_webhook_id")))


def _secret_unrecorded(node_class, row: Optional[Dict[str, Any]]) -> bool:
    """Whether the row lacks the signing secret its class keeps there alone (``webhook_secret_on_row``): a
    registration made before NoClick kept it, whose deliveries can't be verified until it's read."""
    return bool(row and getattr(node_class, "webhook_secret_on_row", False) and not row.get("secret_set"))


def _app_event_class_for_provider(provider: str):
    """Resolve an app-event provider slug (a webhook_subscriptions row's
    ``provider``) back to its node class — for orphan-row teardown where the
    node has already left the graph."""
    from nodes.core.catalog import every_node_facts
    from nodes.core.registry import NODE_REGISTRY

    for node_type, facts in every_node_facts().items():
        if facts["app_event_provider"] == provider:
            return NODE_REGISTRY[node_type]
    return None


# How long one nightly resync pass may keep starting steps, and how long one step of
# its dry run may take. A step that acts is never cut off: stopped between a provider's
# registration and its record, the next pass would register a second hook.
RESYNC_BUDGET_S = 600
RESYNC_PLAN_STEP_TIMEOUT_S = 90
# How many workflows the dry run reads at once: each step is a few short reads.
RESYNC_PLAN_CONCURRENCY = 8
# A sweep starts or replaces a registration only for a workflow that ran, was edited by
# a person, or whose owner came back within this window; tearing one down is never held.
RESYNC_ACTIVE_WITHIN = timedelta(days=30)


# Why a reconcile decided what it did, in NoClick's words only: a report shows these.
REASONS = {
    "converged": "registered as its settings ask",
    "nothing_desired": "its step doesn't ask for a registration",
    "step_removed": "its step left the workflow",
    "switched_off": "its step is switched off",
    "not_runnable": "its settings can't run yet",
    "never_registered": "nothing is registered for it",
    "taken_down": "its registration was taken down",
    "settings_changed": "its settings changed since it registered",
    "unrecorded": "it's live, and the record of it predates what's kept now",
    "recorded_in_config": "it's live, and only its settings' copy records it, from before the record was kept",
    "seen_live": "the scheduler or provider holds it as its settings ask, and the record lacks it",
    "seen_other": "the scheduler or provider holds something its settings don't ask for",
    "unsigned": "it's live, and the record lacks the secret its deliveries are signed with",
    "no_credential": "no usable account is attached",
    "setup_unfinished": "the workflow's setup is unfinished",
    "credential_rejected": "the provider rejected its account, which hasn't been saved again since",
    "held_elsewhere": "another workflow still holds the one address this needs",
    "inactive": "the workflow hasn't run, been edited or seen its owner lately",
    "no_scheduler": "the scheduler isn't configured here",
    "unreadable": "its schedule couldn't be worked out",
}

# What a dry run calls an outcome, where the name says what would be done.
PLAN_STATES = {
    "register": "would_register",
    "reregister": "would_reregister",
    "deregister": "would_deregister",
    "adopt": "would_adopt",
}


@dataclass
class Decision:
    """What a reconcile does to one step, read before anything is done: the dry
    run reports it and the reconcile carries it out, so the two can't differ.

    ``outcome``: live, noop, adopt (stamp a live registration the record lacks),
    register, reregister (tear down then register), deregister, refused (setup
    unfinished), unregistered (no usable account), provider_refused (refused
    before at these settings, nothing changed since), inactive (a start or
    replacement a sweep holds back), cannot_judge or failed. ``held``: something
    is live now (a refusal or a missing account tears it down first).
    ``held_back``: the outcome an ``inactive`` one stands for."""

    outcome: str
    reason: str
    fingerprint: Optional[str] = None
    held: bool = False
    stamp: Dict[str, Any] = field(default_factory=dict)
    refusal: Optional[BaseException] = None
    held_back: Optional[str] = None
    error: Optional[str] = None

    def plan(self) -> Dict[str, Any]:
        state = PLAN_STATES.get(self.outcome, self.outcome)
        if self.outcome in ("refused", "unregistered", "provider_refused") and self.held:
            state = "would_deregister"
        result: Dict[str, Any] = {"state": state, "outcome": self.outcome, "reason": REASONS[self.reason]}
        for key in ("fingerprint", "held_back", "error"):
            if getattr(self, key) is not None:
                result[key] = getattr(self, key)
        return result

    def done(self, state: str, *, outcome: Optional[str] = None, reason: Optional[str] = None,
             **extra) -> Dict[str, Any]:
        """A reconcile's answer. Registering finds for itself what a dry run predicts (an
        unusable credential, unfinished setup), and says so as the dry run would have."""
        return {"state": state, "outcome": outcome or self.outcome, "reason": REASONS[reason or self.reason], **extra}


def _held_back(decision: Decision, hold_starts: bool) -> Decision:
    """A start or replacement a sweep keeps from an inactive workflow."""
    if hold_starts and decision.outcome in ("register", "reregister"):
        return Decision("inactive", "inactive", fingerprint=decision.fingerprint, held=decision.held,
                        held_back=decision.outcome)
    return decision


async def _refused_before(pool, row, fingerprint: str, credential_id: Optional[str]) -> Optional[str]:
    """Why a registration refused at ``fingerprint`` would be refused again, or None:
    the refusal stands while the account wasn't saved since (a rejected credential)
    or the holder's registration is still live (a one-address resource)."""
    if not row or not row.get("refused_fingerprint") or row["refused_fingerprint"] != fingerprint:
        return None
    from nodes.core.webhook_trigger import RegistrationRefused

    kind = row["refused_kind"]
    async with pool.acquire() as conn:
        if kind == RegistrationRefused.CREDENTIAL_REJECTED:
            version = await conn.fetchval(
                "SELECT token_version FROM credentials WHERE id::text = $1", str(credential_id or ""))
            return kind if version is not None and version == row["refused_credential_version"] else None
        if kind == RegistrationRefused.HELD_ELSEWHERE:
            # Still held: the holder is live and hasn't moved to another resource, or another live
            # registration has the resource now.
            held = await conn.fetchval(
                """
                SELECT EXISTS (SELECT 1 FROM webhooks WHERE id = $1 AND is_active
                               AND (external_webhook_id IS NULL OR $2::text IS NULL OR external_webhook_id = $2))
                    OR ($2::text IS NOT NULL AND EXISTS (
                        SELECT 1 FROM webhooks WHERE is_active AND external_webhook_id = $2 AND id <> $3))
                """,
                row["refused_holder_id"], row.get("refused_resource"), row["id"])
            return kind if held else None
    return None


async def _record_refusal(pool, webhook_id, refusal, fingerprint: str,
                          credential_id: Optional[str]) -> None:
    """Keep a refused registration's settings, so nothing tries it again until they change."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE webhooks
            SET refused_fingerprint = $2, refused_kind = $3, refused_holder_id = $4::uuid, refused_resource = $6,
                refused_at = now(),
                refused_credential_version = (SELECT token_version FROM credentials WHERE id::text = $5)
            WHERE id = $1
            """,
            UUID(str(webhook_id)), fingerprint, refusal.kind, refusal.holder_webhook_id, str(credential_id or ""),
            refusal.resource_id,
        )


async def _observed_schedules(wf_uuid, node_id: str) -> Optional[List[Dict[str, Any]]]:
    """The scheduler's own enabled schedules for a step, or None when it can't say."""
    from utils.cron_scheduler_client import list_schedules

    listed = await list_schedules(workflow_id=str(wf_uuid), timeout=5.0)
    if not isinstance(listed, list):
        return None
    return [s for s in listed if s.get("node_id") == node_id and s.get("enabled") in (1, True)]


def _may_have_schedules(row: Optional[Dict[str, Any]], node_config: Dict[str, Any]) -> bool:
    """Whether the row or a mirror says a step may hold schedules: a teardown with
    nothing to say so stays a no-op, with no scheduler call and no mirror written."""
    return bool(
        (row and row.get("registered_operation"))
        or node_config.get("schedule_id")
        or node_config.get("next_run")
        or node_config.get("trigger_registered")
    )


def _schedules_match(schedules: List[Dict[str, Any]], spec, row_id) -> bool:
    """Whether the scheduler fires the step exactly as its settings ask, at its row's address."""
    return bool(schedules) and (
        sorted(s.get("cron_expression") for s in schedules) == sorted(spec.expressions)
        and all((s.get("timezone") or "UTC") == spec.timezone for s in schedules)
        and all(str(row_id) in (s.get("webhook_url") or "") for s in schedules)
    )


def _reported_kind(node: Optional[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
    """A step's type and operation as a report may show them: only names NoClick
    defined, never a stored string it can't vouch for."""
    from nodes.core.registry import NODE_REGISTRY

    if node is None:
        return "(step removed)", None
    node_type = node.get("type")
    if not isinstance(node_type, str) or node_type not in NODE_REGISTRY:
        return "(unknown)", None
    operation = _extract_node_config(node).get("operation")
    if operation is None:
        return node_type, None
    known = isinstance(operation, str) and _known_operation(node_type, operation)
    return node_type, operation if known else "(unknown)"


@lru_cache(maxsize=None)
def _known_operation(node_type: str, operation: str) -> bool:
    from coder.workflow.operation_catalog import get_operations_for_node_type

    return any(op.name == operation for op in get_operations_for_node_type(node_type))


def resync_plan_summary(plan: Dict[str, Any]) -> Dict[str, Any]:
    """A plan's counts without its lists, for a log line."""
    return {
        "complete": plan["complete"],
        "workflows": plan["workflows"],
        "checked": plan["checked"],
        "no_graph": plan["no_graph"],
        "states": plan["states"],
        "would_register": plan["counts"].get("would_register", []),
    }


class WebhookManager:
    """Centralized webhook lifecycle management."""

    @staticmethod
    async def get_or_create_webhook(
        pool,
        user_id: str,
        workflow_id: UUID,
        node_id: str,
        background_relay: bool = False,
    ) -> Dict[str, Any]:
        """
        Get existing webhook or create a new one for a workflow node.

        Returns the URL plus the row's registration state (``is_active``,
        ``secret_set``, ``external_webhook_id``, ``registered_operation``,
        ``registered_credential_id``) — the mixin's idempotency guard reads it.
        Does NOT activate an inactive row: activation is the successful
        registration's job (``persist_registration_state``), so a torn-down
        trigger can't present as live just because its config panel was opened.
        """
        from utils.webhook_delivery import get_webhook_url, is_relay_connected, register_webhook, relay_in_use
        from utils.workflow_readiness import require_activation_ready

        await require_activation_ready(pool, workflow_id, node_id)

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, is_active, (secret IS NOT NULL) AS secret_set,
                       external_webhook_id, registered_operation, registered_credential_id,
                       registered_fingerprint
                FROM webhooks
                WHERE workflow_id = $1 AND node_id = $2
                """,
                workflow_id,
                node_id
            )

            if row:
                webhook_id = str(row["id"])
                state = dict(row)
                logger.debug(f"[WEBHOOK] Found existing webhook {webhook_id}")
                # Simple trigger rows (no registered_operation marker — plain
                # webhook/cron/alarm, nothing registered provider-side) can
                # re-activate on touch: deactivation only meant "node was
                # deleted". Rows carrying the marker stay inactive until a
                # successful re-registration activates them.
                if row["is_active"] is False and row["registered_operation"] is None:
                    await conn.execute(
                        "UPDATE webhooks SET is_active = true, updated_at = now() WHERE id = $1",
                        row["id"],
                    )
                    state["is_active"] = True
                    logger.info(f"[WEBHOOK] Re-activated simple webhook {webhook_id}")
            else:
                new_row = await conn.fetchrow(
                    """
                    INSERT INTO webhooks (user_id, workflow_id, node_id)
                    VALUES ($1, $2, $3)
                    RETURNING id, is_active
                    """,
                    user_id,
                    workflow_id,
                    node_id
                )
                webhook_id = str(new_row["id"])
                state = {
                    "is_active": new_row["is_active"],
                    "secret_set": False,
                    "external_webhook_id": None,
                    "registered_operation": None,
                    "registered_credential_id": None,
                }
                logger.info(f"[WEBHOOK] Created new webhook {webhook_id}")

            webhook_url = get_webhook_url(webhook_id)
            # Without a relay, deliveries reach this backend directly; the
            # legacy status fields report that as a live route.
            is_production = not relay_in_use()
            if is_production:
                relay_connected = True
            elif background_relay:
                from utils.async_helpers import spawn
                spawn(register_webhook(webhook_id), name=f"webhook-register:{webhook_id}")
                relay_connected = is_relay_connected()  # Optimistic - assume it will succeed
            else:
                registration_success = await register_webhook(webhook_id)
                relay_connected = is_relay_connected() and registration_success

            return {
                "webhook_id": webhook_id,
                "webhook_url": webhook_url,
                "relay_connected": relay_connected,
                "is_production": is_production,
                "is_active": state["is_active"],
                "secret_set": state["secret_set"],
                "external_webhook_id": state["external_webhook_id"],
                "registered_operation": state["registered_operation"],
                "registered_credential_id": state["registered_credential_id"],
            }

    @staticmethod
    def node_webhook_field_for(node_type: str, operation: Optional[str]) -> Optional[str]:
        """The webhook field name on the node's CURRENT operation schema, or
        None when it carries none. Pure schema introspection (cached) — safe
        to call as a pre-filter before acquiring a DB pool.

        Covers both markers: the ``ui:widget="webhook"`` field, and the hidden
        ``ui:loadValue`` ``webhook_url`` poll/cron triggers use (their loaders
        mint the row and register the schedule).
        """
        return _webhook_field_for_cached(node_type, operation)

    @staticmethod
    async def provision_node_webhook(pool, *, user_id, workflow_id, node_id, node_type, operation, config, workflow_graph=None):
        from utils.workflow_readiness import activation_graph_scope, require_activation_ready

        if not WebhookManager.node_webhook_field_for(node_type, operation):
            return None
        with activation_graph_scope(workflow_id, workflow_graph):
            await require_activation_ready(pool, workflow_id, node_id)
            return await WebhookManager._provision_node_webhook(
                pool, user_id=user_id, workflow_id=workflow_id, node_id=node_id,
                node_type=node_type, operation=operation, config=config,
            )

    @staticmethod
    async def _provision_node_webhook(
        pool,
        *,
        user_id: str,
        workflow_id: Any,
        node_id: str,
        node_type: str,
        operation: Optional[str],
        config: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Headless webhook provisioning for a trigger node — the same work a
        config-panel open performs via its ``ui:loadValue`` webhook field, for
        write paths that have no panel (AI builder, MCP server). Returns config
        updates to merge into the node (webhook url/id, provider registration
        state), or None when the node's current schema carries no webhook field.

        Nodes with a custom ``load_field_value`` (Telegram setWebhook,
        poll-trigger schedule registration, external-webhook mixin providers)
        are always re-invoked — their loaders are idempotent by contract (the
        panel re-runs them on every open) and own provider-side registration,
        which must re-run once a credential lands. The generic row-mint path is
        skipped when the config already carries a webhook.
        """
        from nodes.core.registry import NODE_REGISTRY

        node_class = NODE_REGISTRY.get(node_type)
        if node_class is None:
            return None

        webhook_field = WebhookManager.node_webhook_field_for(node_type, operation)
        if hasattr(node_class, "registration_field_for_config"):
            webhook_field = node_class.registration_field_for_config(operation, config)
        if not webhook_field:
            return None

        workflow_uuid = (
            workflow_id if isinstance(workflow_id, UUID) else UUID(str(workflow_id))
        )

        if hasattr(node_class, "load_field_value"):
            # Panel-equivalence: the panel's context always carries the
            # current operation, while programmatic callers may hold it outside
            # config. Fold the parameter in so registration never receives an
            # accidental operation=None.
            loader_context = dict(config)
            if operation is not None:
                loader_context.setdefault("operation", operation)
            result = await node_class.load_field_value(
                field_name=webhook_field,
                user_id=user_id,
                workflow_id=workflow_uuid,
                node_id=node_id,
                pool=pool,
                context=loader_context,
                credential_ids=config.get("credentialIds"),
            )
            # None values are "no info" — dropping them keeps a re-invocation
            # from clobbering an already-minted webhook_url in the caller's
            # config.update(). Unrecognized shapes are ignored, not stored.
            if isinstance(result, dict) and "values" in result:
                return {k: v for k, v in result["values"].items() if v is not None}
            if isinstance(result, dict) and "value" in result:
                return (
                    {webhook_field: result["value"]}
                    if result["value"] is not None else {}
                )
            if isinstance(result, (str, int)):
                return {webhook_field: result}
            return {}

        if config.get("webhook_url") or config.get("webhook_id"):
            return None
        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_uuid,
            node_id=node_id,
            background_relay=True,
        )
        return {
            "webhook_id": webhook_data.get("webhook_id"),
            webhook_field: webhook_data.get("webhook_url"),
            "relay_connected": webhook_data.get("relay_connected"),
            "is_production": webhook_data.get("is_production"),
        }

    @staticmethod
    async def persist_registration_state(
        pool,
        webhook_id: str,
        *,
        signing_secret: Optional[str] = None,
        external_webhook_id: Optional[Any] = None,
        registered_operation: Optional[str] = None,
        registered_credential_id: Optional[str] = None,
        registered_fingerprint: Optional[str] = None,
    ) -> None:
        """Record a successful external registration on the webhooks row and
        (re-)activate it, in one statement.

        The row is what signature verification and deregistration read, so a
        failure here is a real failure — this RAISES instead of silently
        degrading to autosave-dependent state. ``external_webhook_id`` accepts
        whatever type the provider returned (GitHub/Shopify use ints) and is
        stored as text.
        """
        ext_id = str(external_webhook_id) if external_webhook_id is not None else None
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE webhooks
                SET is_active = true,
                    secret = COALESCE($1, secret),
                    external_webhook_id = COALESCE($2, external_webhook_id),
                    registered_operation = $3,
                    registered_credential_id = $4,
                    registered_fingerprint = $5,
                    refused_fingerprint = NULL, refused_kind = NULL, refused_holder_id = NULL,
                    refused_resource = NULL, refused_credential_version = NULL, refused_at = NULL,
                    updated_at = now()
                WHERE id = $6
                """,
                signing_secret,
                ext_id,
                registered_operation,
                registered_credential_id,
                registered_fingerprint,
                UUID(webhook_id) if isinstance(webhook_id, str) else webhook_id,
            )
        if not result.endswith("1"):
            raise RuntimeError(
                f"webhooks row {webhook_id} vanished while persisting registration state"
            )

    @staticmethod
    async def record_signing_secret(
        pool, webhook_url: str, secret: Optional[str], *,
        workflow_id: Optional[str] = None, node_id: Optional[str] = None,
    ) -> None:
        """Record the secret a provider signs ``webhook_url``'s deliveries with
        on the row that URL addresses, for a webhook made outside a registration
        step (WAHooks mints one per webhook it creates, so a webhook carried to
        another connection is signed anew). With ``workflow_id``/``node_id``,
        only when the row is that step's."""
        webhook_id = webhook_id_for_url(webhook_url)
        if not (webhook_id and secret):
            return
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE webhooks SET secret = $1, updated_at = now() WHERE id = $2 "
                "AND ($3::uuid IS NULL OR (workflow_id = $3 AND node_id = $4))",
                secret, UUID(webhook_id),
                UUID(str(workflow_id)) if workflow_id else None, node_id,
            )

    @staticmethod
    async def deactivate_webhook(
        pool,
        workflow_id,
        node_id: str,
        *,
        clear_registration: bool,
        mark_operation: Optional[str] = None,
    ) -> None:
        """Deactivate (preserve) a node's webhooks row after deregistration.

        ``clear_registration=True`` after a confirmed provider teardown — the
        secret and external id are dead. ``False`` when teardown failed or was
        impossible: the row keeps the record of a possibly-live provider
        endpoint so a later re-register can drop it (the provider hooks delete
        the stale ``external_webhook_id`` before creating a fresh one).

        ``registered_*`` survives either way — it's the re-register marker for
        restore. ``mark_operation`` stamps the marker when the row predates
        registration state (legacy config-era registration): a marked row is
        never auto-activated by ``get_or_create_webhook`` and is picked up by
        ``register_node_webhooks`` on restore. An inactive row 410s any
        straggler deliveries.
        """
        wf_uuid = UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id
        set_clause = (
            "is_active = false, secret = NULL, external_webhook_id = NULL, updated_at = now()"
            if clear_registration
            else "is_active = false, updated_at = now()"
        )
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE webhooks SET {set_clause}, "
                f"registered_operation = COALESCE(registered_operation, $3) "
                f"WHERE workflow_id = $1 AND node_id = $2",
                wf_uuid, node_id, mark_operation,
            )

    @staticmethod
    async def delete_webhook(
        pool,
        workflow_id: str,
        node_id: str,
    ) -> bool:
        """
        Delete a webhook for a workflow node.

        Handles both database deletion and relay unregistration.

        Returns:
            True if webhook was deleted, False if not found
        """
        from utils.webhook_delivery import unregister_webhook

        try:
            async with pool.acquire() as conn:
                # Get webhook ID before deleting
                row = await conn.fetchrow(
                    """
                    SELECT id FROM webhooks
                    WHERE workflow_id = $1 AND node_id = $2
                    """,
                    UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id,
                    node_id
                )

                if not row:
                    logger.debug(f"[WEBHOOK] No webhook found for workflow={workflow_id}, node={node_id}")
                    return False

                webhook_id = str(row['id'])

                # Delete from database
                await conn.execute(
                    """
                    DELETE FROM webhooks WHERE id = $1
                    """,
                    row['id']
                )
                logger.info(f"[WEBHOOK] Deleted webhook {webhook_id} from database")

                # Unregister from relay (for local dev)
                try:
                    await unregister_webhook(webhook_id)
                except Exception as e:
                    # Non-fatal - KV entry will expire via TTL anyway
                    logger.debug(f"[WEBHOOK] Could not unregister from relay: {e}")

                return True

        except Exception as e:
            logger.error(f"[WEBHOOK] Error deleting webhook: {e}", exc_info=True)
            return False

    @staticmethod
    def schema_requires_webhook(schema: Dict[str, Any]) -> bool:
        """
        Check if a schema (or operation schema) requires a webhook.

        Looks for:
        1. x-requires-webhook: true at the schema level
        2. Any field with ui:widget="webhook"

        Args:
            schema: JSON schema dict (can be operation schema from anyOf/oneOf)

        Returns:
            True if this schema requires a webhook
        """
        if not schema:
            return False

        # Check schema-level marker
        if schema.get("x-requires-webhook"):
            return True

        # Check field-level markers
        properties = schema.get("properties", {})
        for field_name, field_schema in properties.items():
            if field_schema.get("ui:widget") == "webhook":
                return True

        return False

    @staticmethod
    def operation_requires_webhook(node_type: str, operation: Optional[str]) -> bool:
        """Whether a node type's specific operation requires a webhook."""
        if not operation:
            return False
        from coder.workflow.operation_catalog import get_operation_schema
        schema = get_operation_schema(node_type, operation)
        return WebhookManager.schema_requires_webhook(schema) if schema else False

    @staticmethod
    def operation_requires_registration(
        node_type: str, operation: Optional[str]
    ) -> bool:
        """Whether the operation carries ANY registration a lifecycle surface
        must reconcile: a webhooks-row registration (webhook widget / hidden
        webhook_url loader) or an app-event subscription (Slack/HubSpot/
        Discord trigger op). Mutation hooks gate on THIS, never on
        ``operation_requires_webhook`` alone — the narrower gate is what left
        app-event triggers outside every lifecycle surface (2026-07-30)."""
        if WebhookManager.operation_requires_webhook(node_type, operation):
            return True
        node_class = _app_event_trigger_class(node_type)
        if node_class and node_class._trigger_event_map.get(operation or ""):
            return True
        # Cron-schedule family: covers members invisible to the schema-marker
        # gate (bespoke pollers without x-requires-webhook, the operation-less
        # cron node) so their op/config changes reach the reconciler.
        return fires_on_schedule(node_type, operation)

    @staticmethod
    def registers_itself(node_type: str, operation: Optional[str], credential_type: Optional[str]) -> bool:
        """Whether NoClick registers a trigger on ``operation`` with its provider,
        given a credential of ``credential_type``, with no URL for anyone to
        paste: a node of the external-webhook, app-event or schedule families
        always does; any other only for what it declares in
        ``self_registering_triggers`` (its loader registers it)."""
        from nodes.core.registry import NODE_REGISTRY
        from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

        node_class = NODE_REGISTRY.get(node_type)
        if node_class is None:
            return False
        if (
            (isinstance(node_class, type) and issubclass(node_class, ExternalWebhookTriggerMixin))
            or _app_event_trigger_class(node_type)
            or _schedule_trigger_class(node_type)
        ):
            return True
        return credential_type in node_class.self_registering_triggers.get(operation or "", ())

    @staticmethod
    def get_webhook_field(schema: Dict[str, Any]) -> Optional[str]:
        """
        Get the field name that should contain the webhook URL.

        Args:
            schema: JSON schema dict

        Returns:
            Field name with ui:widget="webhook", or None
        """
        properties = schema.get("properties", {})
        for field_name, field_schema in properties.items():
            if field_schema.get("ui:widget") == "webhook":
                return field_name
        return None

    @staticmethod
    def get_operation_schema(
        root_schema: Dict[str, Any],
        operation_value: Optional[str],
        discriminator_field: str = "operation"
    ) -> Optional[Dict[str, Any]]:
        """
        Get the schema for a specific operation from a discriminated union.

        For nodes with anyOf/oneOf (discriminated by "operation" field),
        returns the schema that matches the given operation value.

        Args:
            root_schema: Full node schema
            operation_value: Value of the discriminator field (e.g., "read", "receive_message")
            discriminator_field: Name of the discriminator field (default: "operation")

        Returns:
            Schema dict for the matching operation, or None
        """
        if not root_schema or not operation_value:
            return None

        # Get config schema
        config_schema = root_schema.get("properties", {}).get("config", root_schema)

        # Check for anyOf/oneOf
        options = config_schema.get("anyOf") or config_schema.get("oneOf") or []
        if not options:
            return config_schema

        # Find matching option by discriminator value
        defs = root_schema.get("$defs", {})

        for option in options:
            # Resolve $ref if present
            if "$ref" in option:
                ref_path = option["$ref"].replace("#/$defs/", "")
                resolved = defs.get(ref_path, option)
            else:
                resolved = option

            # Check if this option's discriminator matches
            props = resolved.get("properties", {})
            disc_prop = props.get(discriminator_field, {})
            if disc_prop.get("const") == operation_value:
                return resolved

        return None

    @staticmethod
    async def deregister_node_webhooks(
        pool,
        workflow_id: str,
        node_ids: Optional[list] = None,
        *,
        node_overrides: Optional[list] = None,
        requesting_user_id: Optional[str] = None,
        org_id: Optional[str] = None,
        manage_rows: bool = True,
        on_trash: bool = False,
    ) -> Dict[str, int]:
        """Tear down provider-side registrations for the given nodes and
        deactivate their webhooks rows. THE deregistration choke point — see
        the module docstring for which surfaces route here.

        ``on_trash=True`` (soft delete) skips node classes with
        ``preserve_registration_on_trash`` — teardown that surrenders a scarce
        user-claimed resource (inbound-email address reservation) would make
        trash irreversible.

        Dispatches through ``node_class.cleanup_external_webhook`` (provider
        teardown only), so every provider participates: mixin nodes by
        ``external_webhook_id``, Typeform by form tag, WhatsApp/Telegram bots,
        watch channels, poll-trigger cron schedules, event subscriptions.

        ``node_ids=None`` means all nodes in the workflow. ``node_overrides``
        carries the pre-removal node dicts when the caller already persisted
        the node-less workflow (the canvas delete saves first). The row's
        ``external_webhook_id`` (written synchronously at registration) backs
        up configs the autosave never reached. Credentials resolve preferring
        the requesting user (collaborator-owned credentials on shared
        workflows), then the workflow owner; each distinct credential is
        decrypted and freshened once per call.

        A teardown failure — including a registered mixin node whose credential
        no longer resolves (the provider hooks would silently no-op) — counts
        as ``failed``: the row is deactivated WITHOUT clearing its secret or
        external id, preserving the record of the possibly-live provider
        endpoint for a later re-register to drop. ``manage_rows=False`` skips
        row updates for callers about to hard-delete the rows wholesale
        (permanent workflow deletion).

        Returns ``{"deregistered": n, "failed": m}``.
        """
        from nodes.core.registry import NODE_REGISTRY
        from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

        results = {"deregistered": 0, "failed": 0}
        wf_uuid = UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id

        owner_id, blob_nodes = await _load_workflow_owner_and_nodes(
            pool, wf_uuid, include_nodes=node_overrides is None
        )
        if owner_id is None:
            return results
        nodes = list(node_overrides) if node_overrides is not None else blob_nodes
        if node_ids is not None:
            target = set(node_ids)
            nodes = [n for n in nodes if n.get("id") in target]
        if not nodes:
            return results

        # Row state for the target nodes. Registration persists the provider
        # endpoint id here synchronously, so deregistration works even when the
        # config blob never got it (register-then-delete race). A DB error here
        # must not read as "nothing was registered" — let it raise.
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, node_id, external_webhook_id, registered_operation, "
                "registered_credential_id "
                "FROM webhooks WHERE workflow_id = $1",
                wf_uuid,
            )
        row_by_node: Dict[str, Any] = {r["node_id"]: r for r in rows}

        cred_cache: Dict[str, Optional[Dict[str, Any]]] = {}

        async def _credential_for(node_class, credential_id: str) -> Optional[Dict[str, Any]]:
            if credential_id in cred_cache:
                return cred_cache[credential_id]
            credential = await _resolve_node_credential(
                pool, credential_id,
                owner_id=owner_id,
                requesting_user_id=requesting_user_id,
                org_id=org_id,
            )
            if credential is not None and hasattr(node_class, "freshen_credential"):
                # Refresh expiring OAuth tokens before deregistering so a stale
                # token doesn't 401 and orphan the provider-side endpoint
                # (no-op for API-key providers like Stripe/Linear).
                try:
                    from nodes.core.oauth_audit import caller_path_scope
                    with caller_path_scope("webhook_cleanup"):
                        credential = await node_class.freshen_credential(
                            credential, pool=pool, user_id=owner_id, credential_id=credential_id
                        )
                except Exception as fe:
                    logger.warning(f"[WEBHOOK] freshen_credential failed for {credential_id}: {fe}")
            cred_cache[credential_id] = credential
            return credential

        for node in nodes:
            node_type = node.get("type")
            node_id = node.get("id")
            if not node_type or not node_id:
                continue

            row = row_by_node.get(node_id)
            node_class = NODE_REGISTRY.get(node_type)
            if not node_class:
                # Unknown type: nothing to tear down, but don't leave a live URL
                # pointing at a removed node.
                if manage_rows and row is not None:
                    await WebhookManager.deactivate_webhook(
                        pool, wf_uuid, node_id, clear_registration=False
                    )
                continue

            if on_trash and getattr(node_class, "preserve_registration_on_trash", False):
                continue

            node_config = _extract_node_config(node)
            # The row's id is written synchronously at registration, so it's at
            # least as fresh as the config blob's copy (which lags behind the
            # debounced autosave) — prefer it when present.
            row_ext = row["external_webhook_id"] if row else None
            if row_ext:
                node_config = {**node_config, "external_webhook_id": row_ext}
            if row is not None and row.get("id") is not None:
                # Which address is this node's, for a provider whose one webhook may since point elsewhere.
                node_config = {**node_config, "webhook_id": str(row["id"])}

            credential_ids = _usable_credential_ids(node, node_config)
            # The row remembers WHICH credential registered the endpoint. After
            # a credential swap the current config no longer carries it, but
            # provider teardown may need the ORIGINAL auth (per-account state) —
            # prefer it first so teardown never depends on stale old_config
            # plumbing from the mutation surface.
            row_cred = row["registered_credential_id"] if row else None
            if row_cred and row_cred not in credential_ids:
                credential_ids = [row_cred] + credential_ids
            credentials = [
                c for c in [await _credential_for(node_class, cid) for cid in credential_ids]
                if c is not None
            ]

            # A registered mixin node whose credential no longer resolves can't
            # tear down — the provider hooks no-op silently. Fail it instead of
            # counting a no-op as success and erasing the endpoint record.
            was_registered = bool(
                (row and row["registered_operation"])
                or node_config.get("external_webhook_id")
                or node_config.get("trigger_registered") is True
            )
            is_mixin = isinstance(node_class, type) and issubclass(node_class, ExternalWebhookTriggerMixin)
            success = False
            if is_mixin and was_registered and not credentials:
                logger.warning(
                    f"[WEBHOOK] No resolvable credential to deregister {node_type}:{node_id} — "
                    f"provider endpoint may remain registered"
                )
            else:
                # Provider state can be per-connection (WhatsApp via WAHooks),
                # so tear down against each configured credential; most nodes
                # carry exactly one.
                success = True
                for credential in (credentials or [None]):
                    try:
                        await node_class.cleanup_external_webhook(
                            pool, str(workflow_id), node_id, node_config, credential
                        )
                    except Exception as e:
                        success = False
                        logger.warning(
                            f"[WEBHOOK] Provider teardown failed for {node_type}:{node_id}: {e}"
                        )
                if success:
                    logger.info(f"[WEBHOOK] Deregistered external webhook for {node_type}:{node_id}")

            results["deregistered" if success else "failed"] += 1

            if manage_rows and row is not None:
                try:
                    # Stamp the marker for registered mixin rows that predate
                    # registration state, so restore knows to re-register them
                    # (and get_or_create_webhook won't auto-activate).
                    mark = (
                        node_config.get("operation")
                        if is_mixin and was_registered
                        else None
                    )
                    await WebhookManager.deactivate_webhook(
                        pool, wf_uuid, node_id,
                        clear_registration=success,
                        mark_operation=mark,
                    )
                except Exception as de:
                    logger.warning(
                        f"[WEBHOOK] Could not deactivate webhook row for {node_type}:{node_id}: {de}"
                    )

        return results

    @staticmethod
    async def register_node_webhooks(
        pool,
        workflow_id: str,
        user_id: str,
        nodes: Optional[list] = None,
        node_ids: Optional[list] = None,
    ) -> int:
        """Re-register external webhooks for restored trigger nodes. THE
        re-registration choke point — trash restore, checkpoint restore and
        canvas undo re-add route here.

        App-event, cron-schedule and loader-registered triggers (WhatsApp on a
        QR session) converge through ``reconcile_node``. External-webhook
        triggers register ONLY when their webhooks row is INACTIVE and carries
        the ``registered_operation`` marker (a previously-registered trigger
        that ``deregister_node_webhooks`` tore down) and their CURRENT
        operation still requires a webhook. Their action nodes and
        never-registered triggers are never touched — a restored Stripe
        ``create_customer`` node must not grow a wildcard endpoint (the
        reconciler's desired state excludes action operations the same way).
        The existing row (same UUID/URL) is reused;
        it re-activates only via the post-success persist, so a failed provider
        call leaves the row inactive (deliveries 410) and the next config-panel
        open retries with the error surfaced.

        ``nodes`` overrides reading the workflow blob (checkpoint restore runs
        before the blob update). Node configs in the blob are patched with the
        fresh registration values so delivery verification and the FE see them
        without waiting for any autosave.

        Returns the count of successfully re-registered endpoints.
        """
        from nodes.core.registry import NODE_REGISTRY
        from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
        from utils.credentials import extract_credential_ids

        registered = 0
        wf_uuid = UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id

        owner_id, blob_nodes = await _load_workflow_owner_and_nodes(
            pool, wf_uuid, include_nodes=nodes is None
        )
        if owner_id is None:
            return 0
        candidates = list(nodes) if nodes is not None else blob_nodes
        if node_ids is not None:
            target = set(node_ids)
            candidates = [n for n in candidates if n.get("id") in target]
        if not candidates:
            return 0

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT node_id, id, is_active, registered_operation "
                "FROM webhooks WHERE workflow_id = $1",
                wf_uuid,
            )
        row_by_node: Dict[str, Any] = {r["node_id"]: r for r in rows}

        for node in candidates:
            node_type = node.get("type")
            node_id = node.get("id")
            if not node_type or not node_id:
                continue

            if (
                _app_event_trigger_class(node_type)
                or _schedule_trigger_class(node_type)
                or _loader_registers(node_type, node, _extract_node_config(node))
            ):
                # App-event + cron-schedule families, and triggers their own
                # loader registers (WhatsApp on a QR session): desired state
                # recomputes from the saved graph and registration is
                # idempotent, so restores route straight through the
                # reconciler — no inactive-row marker gating needed.
                try:
                    result = await WebhookManager.reconcile_node(
                        pool, str(wf_uuid), node_id
                    )
                    if result.get("state") == "registered":
                        registered += 1
                except Exception:
                    logger.warning(
                        f"[WEBHOOK] Family re-register failed for "
                        f"{node_type}:{node_id}",
                        exc_info=True,
                    )
                continue

            node_class = NODE_REGISTRY.get(node_type)
            if not (
                node_class
                and isinstance(node_class, type)
                and issubclass(node_class, ExternalWebhookTriggerMixin)
            ):
                continue

            row = row_by_node.get(node_id)
            if not row or row["is_active"] or not row["registered_operation"]:
                continue  # never registered, or already live — nothing to restore

            node_config = _extract_node_config(node)
            current_op = node_config.get("operation")
            if not WebhookManager.operation_requires_webhook(node_type, current_op):
                continue  # node no longer runs a webhook-trigger operation

            cred_ids = extract_credential_ids(node_config)
            if not cred_ids and isinstance(node.get("data"), dict):
                cred_ids = extract_credential_ids(node["data"])
            credential_id = _extract_node_credential_id(node, node_config)
            credential = await node_class._resolve_trigger_credential(pool, owner_id, cred_ids)
            if not credential:
                logger.warning(
                    f"[WEBHOOK] Credential unavailable — cannot re-register {node_type}:{node_id} "
                    f"(row stays inactive; the config panel will surface the error)"
                )
                continue

            if await WebhookManager._register_single_node(
                pool, wf_uuid=wf_uuid, user_id=user_id,
                node_class=node_class, node_type=node_type, node_id=node_id,
                node_config=node_config, credential=credential,
                credential_id=credential_id, current_op=current_op,
            ):
                registered += 1

        return registered

    @staticmethod
    async def merge_node_config_patch(
        pool, wf_uuid, node_id: str, patch: Dict[str, Any]
    ) -> None:
        """Merge a dict into one node's config blob via atomic CTE (no
        read-modify-write race).

        ($3::text)::jsonb, NOT $3::jsonb: this runs on codec'd runtime pools
        AND plain cron pools. A bare jsonb param double-encodes the dumped
        string on codec pools, and `object || string-scalar` is jsonb ARRAY
        concatenation — it silently turned the node's config into a list
        (2026-07-20: broke every hook reading the blob until the next full
        canvas save repaired it). Inside a reconcile job (``PATCH_MOVES``), the
        version it moves the workflow to is recorded as a reconcile's, in the
        same statement, and the move goes to the job.
        """
        import json as _json

        moves = PATCH_MOVES.get()
        async with pool.acquire() as conn:
            moved = await conn.fetchrow(
                """
                WITH locked AS (
                    SELECT graph_version FROM workflows WHERE id = $1 FOR UPDATE
                ), target AS (
                    SELECT (idx - 1)::int AS pos
                    FROM jsonb_array_elements(
                        (SELECT workflow->'nodes' FROM workflows WHERE id = $1)
                    ) WITH ORDINALITY AS n(node, idx)
                    WHERE node->>'id' = $2
                    LIMIT 1
                ), moved AS (
                    UPDATE workflows
                    SET workflow = jsonb_set(
                        workflow,
                        ARRAY['nodes', target.pos::text, 'config'],
                        COALESCE(workflow->'nodes'->target.pos->'config', '{}'::jsonb) || ($3::text)::jsonb
                    ),
                    updated_at = now()
                    FROM target, locked
                    WHERE workflows.id = $1
                    RETURNING locked.graph_version AS before, workflows.graph_version AS after
                ), noted AS (
                    INSERT INTO workflow_reconcile_versions (workflow_id, version)
                    SELECT $1, after FROM moved WHERE $4 AND after <> before
                    ON CONFLICT DO NOTHING
                )
                SELECT before, after FROM moved
                """,
                wf_uuid,
                node_id,
                _json.dumps(config_without_runtime_keys(patch)),
                moves is not None,
            )
        if moves is not None and moved is not None and moved["after"] != moved["before"]:
            moves.append((moved["before"], moved["after"]))

    @staticmethod
    async def _register_single_node(
        pool,
        *,
        wf_uuid,
        user_id: str,
        node_class,
        node_type: str,
        node_id: str,
        node_config: Dict[str, Any],
        credential: Dict[str, Any],
        credential_id: Optional[str],
        current_op: Optional[str],
    ) -> bool:
        """Provider-register ONE node against its existing/new row and persist
        the registration (fingerprint included) + config mirror. The single
        register implementation ``register_node_webhooks`` and
        ``reconcile_node`` share. Returns success."""
        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=wf_uuid,
            node_id=node_id,
            background_relay=True,
        )
        webhook_url = webhook_data["webhook_url"]
        webhook_id = webhook_data["webhook_id"]

        try:
            # The row's endpoint id backs up the (possibly stale) config mirror
            # so replace-stale-endpoint nodes can drop the previous endpoint;
            # its own id tells a one-address resource's hook which row is its own.
            register_config = {**node_config, "webhook_id": webhook_id}
            if not register_config.get("external_webhook_id") and webhook_data.get("external_webhook_id"):
                register_config["external_webhook_id"] = webhook_data.get("external_webhook_id")
            extra = await node_class._register_external_webhook(
                webhook_url=webhook_url,
                credential=credential,
                config=register_config,
                node_id=node_id,
            )
            await WebhookManager.persist_registration_state(
                pool, webhook_id,
                signing_secret=(extra or {}).get("signing_secret"),
                external_webhook_id=(extra or {}).get("external_webhook_id"),
                registered_operation=current_op,
                registered_credential_id=credential_id,
                registered_fingerprint=registration_fingerprint(
                    node_class, current_op, credential_id, node_config
                ),
            )

            config_patch: Dict[str, Any] = {
                "trigger_registered": True,
                "trigger_error": None,
                "webhook_id": webhook_id,
                "webhook_url": webhook_url,
            }
            if extra:
                config_patch.update(extra)

            await WebhookManager.merge_node_config_patch(
                pool, wf_uuid, node_id, config_patch
            )

            logger.info(f"[WEBHOOK] Registered external webhook for {node_type}:{node_id}")
            return True

        except Exception as e:
            from nodes.core.webhook_trigger import RegistrationRefused

            logger.warning(
                f"[WEBHOOK] Failed to register external webhook for "
                f"{node_type}:{node_id}: {e}"
            )
            if isinstance(e, RegistrationRefused):
                try:
                    await _record_refusal(
                        pool, webhook_id, e,
                        registration_fingerprint(node_class, current_op, credential_id, node_config), credential_id,
                    )
                except Exception:
                    logger.warning(f"[WEBHOOK] Could not record the refusal on {node_type}:{node_id}", exc_info=True)
            # The step says why, as a panel open would: a headless caller (the
            # platform's triggers, a restore) reads it back as the reason.
            try:
                await WebhookManager.merge_node_config_patch(
                    pool, wf_uuid, node_id, {"trigger_registered": False, "trigger_error": str(e)}
                )
            except Exception:
                logger.warning(f"[WEBHOOK] Could not record the failure on {node_type}:{node_id}", exc_info=True)
            return False

    @staticmethod
    async def reconcile_node(
        pool,
        workflow_id: str,
        node_id: str,
        *,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
        nodes_override: Optional[List[Dict[str, Any]]] = None,
        plan_only: bool = False,
        refresh_next_run: bool = True,
        hold_starts: bool = False,
        observe: bool = False,
    ) -> Dict[str, Any]:
        """THE level-triggered converger for a trigger node's external
        registration. Compares DESIRED state (computed purely from the node's
        CURRENT saved config: does its operation require a webhook, or for a
        node registered by its own loader its ``self_registering_triggers``,
        and the registration fingerprint of operation + credential +
        node-declared fields) against OBSERVED state (the webhooks row) and
        converges:

        - desired None,  row live      → teardown (deregister + deactivate)
        - desired None,  row inactive  → retry a previously-failed teardown if
                                         the row still records a provider
                                         endpoint, else no-op
        - fingerprints equal, row live → no-op ("live")
        - anything else                → teardown stale registration (row
                                         context drives provider cleanup),
                                         then register the desired one

        Idempotent and safe to call from ANY mutation surface — surfaces never
        pass old-vs-new state, which is where every duplicate-registration bug
        lived (the old state raced the debounced config mirror). A best-effort
        Redis lock serializes concurrent reconciles per node; convergence does
        NOT depend on it (each reconcile reads current state, and
        replace-stale/sweep-by-URL registration is itself convergent).

        Each family first DECIDES (``Decision``: reads only) and then APPLIES
        that decision, so ``plan_only``, which stops after deciding, reports
        exactly what a reconcile does: no write, no customer's provider called,
        no credential decrypted or refreshed, no lock. ``observe`` (the sweep
        and its dry run) also reads NoClick's own sources beside the row: the
        scheduler's schedules for a step, and a class's
        ``observe_registration`` (WhatsApp's webhooks on NoClick's WAHooks
        account), so a live registration the row doesn't record is adopted
        (the row stamped), never taken for none. A mutation surface's
        reconcile judges by the row, as its change rotates the fingerprint
        anyway. A registration a
        provider refused for good (``RegistrationRefused``) isn't tried again
        at the same settings until its account is saved again or the holder
        lets go (``provider_refused``).

        Returns ``{"state", "outcome", "reason", "fingerprint"?}``; states:
        no_workflow, noop, live (``adopted`` when stamped), deregistered,
        registered, unregistered (no credential), refused, provider_refused,
        inactive, failed. A plan answers ``would_register``,
        ``would_reregister``, ``would_deregister`` or ``would_adopt`` where a
        reconcile would act, and the rest as they are; ``outcome`` is the same
        word in both. ``hold_starts`` (a sweep over an inactive workflow) turns
        a start or replacement into ``inactive``; a teardown is never held.
        ``refresh_next_run=False`` leaves a converged schedule's mirror as it
        is (a sweep: that write reads as an edit of the workflow).
        """
        from nodes.core.registry import NODE_REGISTRY
        from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

        wf_uuid = UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id

        lock_key = f"nc:wh_reconcile:{workflow_id}:{node_id}"
        redis = None
        have_lock = False
        try:
            from utils.redis_client import get_shared_redis

            redis = None if plan_only else get_shared_redis()
            if redis is not None:
                # Spin briefly for the lock, then proceed regardless — a
                # wrongly-skipped reconcile is worse than provider churn.
                for _ in range(16):
                    if await redis.set(lock_key, "1", nx=True, ex=60):
                        have_lock = True
                        break
                    import asyncio as _asyncio

                    await _asyncio.sleep(0.5)
        except Exception:
            logger.debug("[WEBHOOK] reconcile lock unavailable", exc_info=True)

        try:
            # Desired truth defaults to the SAVED graph; callers holding the
            # authoritative in-memory graph BEFORE their save (the agentic
            # builder's self-heal) pass nodes_override so the reconcile
            # doesn't read a stale blob.
            owner_id, blob_nodes = await _load_workflow_owner_and_nodes(
                pool, wf_uuid, include_nodes=nodes_override is None
            )
            if owner_id is None:
                return {"state": "no_workflow"}
            if nodes_override is not None:
                blob_nodes = nodes_override

            node = next((n for n in blob_nodes if n.get("id") == node_id), None)
            node_type = node.get("type") if node else None
            node_class = NODE_REGISTRY.get(node_type) if node_type else None
            is_mixin = bool(
                node_class
                and isinstance(node_class, type)
                and issubclass(node_class, ExternalWebhookTriggerMixin)
            )
            node_config = _extract_node_config(node) if node else {}
            current_op = node_config.get("operation")

            # Family dispatch: app-event fan-out triggers (Slack/HubSpot/
            # Discord) converge against webhook_subscriptions, not the
            # webhooks table.
            if _app_event_trigger_class(node_type):
                return await WebhookManager._reconcile_app_event_node(
                    pool, wf_uuid, node_id,
                    owner_id=owner_id, node=node, node_class=node_class,
                    node_config=node_config, current_op=current_op, plan_only=plan_only,
                    hold_starts=hold_starts,
                )

            # Family dispatch: cron-schedule triggers (poll mixin, cron node,
            # bespoke schedule pollers) converge cron schedules + the arm-time
            # baseline against the webhooks row's fingerprint.
            if _schedule_trigger_class(node_type):
                return await WebhookManager._reconcile_schedule_node(
                    pool, wf_uuid, node_id,
                    owner_id=owner_id, user_id=user_id, node=node,
                    node_class=node_class, node_config=node_config,
                    current_op=current_op, plan_only=plan_only,
                    refresh_next_run=refresh_next_run, hold_starts=hold_starts, observe=observe,
                )

            row = await _webhook_row(pool, wf_uuid, node_id)
            decision = await WebhookManager._decide_push(
                pool, wf_uuid, node_id, owner_id=owner_id, node=node, node_class=node_class,
                node_type=node_type, node_config=node_config, current_op=current_op, row=row,
                is_mixin=is_mixin, hold_starts=hold_starts, observe=observe, predict=plan_only,
            )
            if plan_only:
                return decision.plan()
            return await WebhookManager._apply_push(
                pool, decision, workflow_id=workflow_id, wf_uuid=wf_uuid, node_id=node_id,
                user_id=user_id, org_id=org_id, owner_id=owner_id, node=node, node_class=node_class,
                node_type=node_type, node_config=node_config, current_op=current_op, row=row, is_mixin=is_mixin,
            )
        finally:
            if have_lock and redis is not None:
                try:
                    await redis.delete(lock_key)
                except Exception:
                    pass

    @staticmethod
    async def _decide_push(
        pool, wf_uuid, node_id: str, *, owner_id: str, node: Optional[Dict[str, Any]], node_class,
        node_type: Optional[str], node_config: Dict[str, Any], current_op: Optional[str],
        row: Optional[Dict[str, Any]], is_mixin: bool, hold_starts: bool, observe: bool = False,
        predict: bool = False,
    ) -> Decision:
        """The push family's decision (a provider endpoint per step, or a
        trigger its own loader registers). DESIRED: the step's operation needs
        a webhook, or its loader registers it. OBSERVED: the row, and where the
        class can see it (``observe_registration``), the registration itself.
        ``predict`` (a dry run) also reads what registering would find for
        itself: whether the credential is usable and the setup finished."""
        from nodes.core.webhook_subscriptions import get_node_subscriptions
        from utils.credential_loader import credential_usable
        from utils.webhook_delivery import get_webhook_url

        recorded = _recorded(row)
        if node is None:
            # Subscription rows a removed step left would fan out to it forever.
            orphaned = bool(await get_node_subscriptions(pool, str(wf_uuid), node_id))
            return Decision("deregister" if recorded or orphaned else "noop", "step_removed", held=recorded)

        # A trigger its own loader registers (WhatsApp's messages on a QR
        # session) is desired while the node holds a credential the loader
        # registers its operation with, and converges through that loader.
        loader_registered = not is_mixin and _loader_registers(node_type, node, node_config)
        desired = loader_registered or bool(
            is_mixin and WebhookManager.operation_requires_webhook(node_type, current_op)
        )
        if not desired:
            return Decision("deregister" if recorded else "noop", "nothing_desired", held=recorded)

        credential_id = _extract_node_credential_id(node, node_config)
        fingerprint = registration_fingerprint(node_class, current_op, credential_id, node_config)
        converged = bool(row and row["is_active"] and row["registered_fingerprint"] == fingerprint)
        # A sweep reads the signing secret a live registration's record lacks; anything else takes it as it is.
        if converged and not (observe and _secret_unrecorded(node_class, row)):
            return Decision("live", "converged", fingerprint=fingerprint, held=True)

        # Pre-migration adoption: a NULL-fingerprint row whose operation +
        # credential still match IS the live registration under the old
        # liveness definition — stamp the fingerprint instead of rotating
        # the provider endpoint (the first resync would otherwise churn
        # every pre-existing trigger). A node-declared staleness signal
        # (webhook_registration_stale, e.g. PostHog's registered_event_name
        # mirror) vetoes adoption: it means the provider registration
        # predates the current config, so stamping would bless the drift.
        if (
            row and row["is_active"]
            and row["registered_fingerprint"] is None
            and row["registered_operation"] == current_op
            and (row["registered_credential_id"] or None) == (credential_id or None)
            and not (is_mixin and node_class.webhook_registration_stale(node_config, dict(row)))
        ):
            return Decision("adopt", "unrecorded", fingerprint=fingerprint, held=True)
        # Older still: a row from before registrations were recorded at all, which only the config's mirrors
        # describe. Registering would add a second provider endpoint beside the live one.
        legacy = is_mixin and row is not None and node_class.legacy_registration(
            node_config, row, get_webhook_url(str(row["id"])))
        if legacy:
            return Decision("adopt", "recorded_in_config", fingerprint=fingerprint, held=True, stamp={
                "registered_operation": current_op, "registered_credential_id": credential_id, **legacy,
            })

        refused = None if converged else await _refused_before(pool, row, fingerprint, credential_id)
        if refused:
            return Decision("provider_refused", refused, fingerprint=fingerprint, held=recorded)

        # What the provider holds, where the class can see it without the
        # customer's credential: live as asked, the row is only stamped.
        observed = None
        observer = getattr(node_class, "observe_registration", None) if observe else None
        if observer is not None and row is not None:
            observed = await observer(
                pool, webhook_url=get_webhook_url(str(row["id"])), credential_id=credential_id, config=node_config,
            )
        if observed and row["is_active"]:
            return Decision("adopt", "unsigned" if converged else "seen_live", fingerprint=fingerprint, held=True,
                            stamp={"registered_operation": current_op, "registered_credential_id": credential_id,
                                   **observed})
        if converged and observed is None:
            return Decision("live", "converged", fingerprint=fingerprint, held=True)
        held = recorded

        # A sweep holding back an inactive workflow does nothing here, whatever registering would find.
        if predict and not hold_starts:
            if not await credential_usable(pool, owner_id, credential_id):
                return Decision("unregistered", "no_credential", fingerprint=fingerprint, held=held)
            refusal = await _activation_refusal(pool, wf_uuid, node_id)
            if refusal is not None:
                return Decision("refused", "setup_unfinished", fingerprint=fingerprint, held=held, refusal=refusal)
        if held and not converged:
            reason = "settings_changed"
        elif observed is False and row and row["is_active"]:
            reason = "taken_down"
        else:
            reason = "taken_down" if row and row["registered_operation"] else "never_registered"
        return _held_back(Decision(
            "reregister" if held else "register", reason, fingerprint=fingerprint, held=held,
        ), hold_starts)

    @staticmethod
    async def _apply_push(
        pool, decision: Decision, *, workflow_id, wf_uuid, node_id: str, user_id: Optional[str],
        org_id: Optional[str], owner_id: str, node: Optional[Dict[str, Any]], node_class,
        node_type: Optional[str], node_config: Dict[str, Any], current_op: Optional[str],
        row: Optional[Dict[str, Any]], is_mixin: bool,
    ) -> Dict[str, Any]:
        """Carry out ``_decide_push``'s decision."""
        from utils.credentials import extract_credential_ids
        from utils.workflow_readiness import WorkflowNotReadyError

        outcome = decision.outcome
        if node is None:
            # Node gone from the saved graph: clear any orphaned app-event
            # subscription rows (dead rows would fan out to a missing node
            # forever, and Discord's provider union would keep stale event
            # types), and best-effort prune any cron schedules still ticking
            # at the missing node (a deactivated row 410s deliveries forever
            # without ever hitting the tick-time orphan cleanup).
            orphaned = await WebhookManager._cleanup_orphaned_app_event_rows(pool, wf_uuid, node_id)
            try:
                from utils.cron_scheduler_client import delete_schedules_for_nodes

                await delete_schedules_for_nodes(str(wf_uuid), [node_id])
            except Exception:
                logger.debug(f"[WEBHOOK] Orphan schedule prune failed for {node_id}", exc_info=True)
            if _recorded(row):
                await WebhookManager.deregister_node_webhooks(
                    pool, str(workflow_id), [node_id], requesting_user_id=user_id or owner_id, org_id=org_id,
                )
                return decision.done("deregistered")
            return decision.done("deregistered" if orphaned else "noop")

        if outcome in ("noop", "inactive"):
            return decision.done(outcome)
        if outcome == "live":
            return decision.done("live", fingerprint=decision.fingerprint)
        if outcome == "adopt":
            await WebhookManager._stamp_row(pool, row["id"], decision)
            return decision.done("live", fingerprint=decision.fingerprint, adopted=True)
        if outcome == "deregister":
            # Teardown when the row is live, or when a failed teardown left
            # a recorded provider endpoint behind (retry until clean).
            await WebhookManager.deregister_node_webhooks(
                pool, str(workflow_id), [node_id],
                node_overrides=[node], requesting_user_id=user_id or owner_id, org_id=org_id,
            )
            return decision.done("deregistered")

        # Converge: drop a live-but-stale registration first (the row's
        # registered_credential_id backs provider teardown even after a
        # credential swap), whatever comes of the new one.
        if _recorded(row):
            await WebhookManager.deregister_node_webhooks(
                pool, str(workflow_id), [node_id], requesting_user_id=user_id or owner_id, org_id=org_id,
            )
        if outcome == "unregistered":
            return decision.done("unregistered", error="credential unavailable")
        if outcome == "provider_refused":
            return decision.done("provider_refused", error=REASONS[decision.reason])
        if outcome == "refused":
            # The saved config can't activate: the registration an earlier
            # config made was torn down above, and the step says why.
            if row and row["registered_operation"]:
                await WebhookManager.merge_node_config_patch(
                    pool, wf_uuid, node_id,
                    {"trigger_registered": False, "trigger_error": str(decision.refusal)},
                )
            raise decision.refusal

        try:
            if not is_mixin and _loader_registers(node_type, node, node_config):
                values = await WebhookManager._provision_node_webhook(
                    pool, user_id=user_id or owner_id, workflow_id=wf_uuid, node_id=node_id,
                    node_type=node_type, operation=current_op, config=node_config,
                ) or {}
                await WebhookManager.merge_node_config_patch(pool, wf_uuid, node_id, values)
                return decision.done(
                    "registered" if values.get("trigger_registered") is True else "failed",
                    fingerprint=decision.fingerprint,
                )

            cred_ids = extract_credential_ids(node_config)
            if not cred_ids and isinstance(node.get("data"), dict):
                cred_ids = extract_credential_ids(node["data"])
            credential = await node_class._resolve_trigger_credential(pool, owner_id, cred_ids)
            if not credential:
                return decision.done("unregistered", outcome="unregistered", reason="no_credential",
                                     error="credential unavailable")

            ok = await WebhookManager._register_single_node(
                pool, wf_uuid=wf_uuid, user_id=user_id or owner_id,
                node_class=node_class, node_type=node_type, node_id=node_id,
                node_config=node_config, credential=credential,
                credential_id=_extract_node_credential_id(node, node_config), current_op=current_op,
            )
            return decision.done("registered" if ok else "failed", fingerprint=decision.fingerprint)
        except WorkflowNotReadyError as refused:
            # Refused between deciding and registering: as above.
            if row and row["registered_operation"]:
                await WebhookManager.merge_node_config_patch(
                    pool, wf_uuid, node_id,
                    {"trigger_registered": False, "trigger_error": str(refused)},
                )
            raise

    @staticmethod
    async def _stamp_row(pool, webhook_id, decision: Decision) -> None:
        """Adopt a live registration: the row records it, and nothing else is touched (the workflow isn't edited)."""
        stamp = {"registered_fingerprint": decision.fingerprint, **decision.stamp}
        columns = ["registered_fingerprint"] + sorted(c for c in stamp if c != "registered_fingerprint")
        assignments = ", ".join(f"{column} = ${index + 1}" for index, column in enumerate(columns))
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE webhooks SET {assignments}, updated_at = now() WHERE id = ${len(columns) + 1}",
                *(None if stamp[c] is None else str(stamp[c]) for c in columns), webhook_id,
            )

    @staticmethod
    async def _reconcile_app_event_node(
        pool,
        wf_uuid,
        node_id: str,
        *,
        owner_id: str,
        node: Optional[Dict[str, Any]],
        node_class,
        node_config: Dict[str, Any],
        current_op: Optional[str],
        plan_only: bool = False,
        hold_starts: bool = False,
    ) -> Dict[str, Any]:
        """App-event family arm of ``reconcile_node`` (same contract/states).

        DESIRED: the node's current operation is one of the class's trigger
        ops → its event types, registered under the node's credential AS THE
        WORKFLOW OWNER (the identity fan-out fires and bills as). OBSERVED:
        the node's ``webhook_subscriptions`` rows.

        The row-match fast path needs no credential load and no provider
        call, so sweeps over live registrations are one SELECT per node.
        Convergence never deletes on a non-definitive signal: an unresolvable
        credential keeps the observed rows — fan-out doesn't need the
        credential, so a live registration keeps working through provider
        blips and credential detaches.
        """
        from nodes.core.webhook_subscriptions import get_node_subscriptions
        from utils.credential_loader import credential_usable
        from utils.credentials import extract_credential_ids
        from utils.workflow_readiness import WorkflowNotReadyError, require_activation_ready

        desired_events = (
            node_class.subscription_events_for_config(current_op, node_config) if node else []
        )
        rows = await get_node_subscriptions(pool, str(wf_uuid), node_id)
        cred_ids = extract_credential_ids(node_config)
        if not cred_ids and node and isinstance(node.get("data"), dict):
            cred_ids = extract_credential_ids(node["data"])
        credential_id = node_class._pick_trigger_credential_id(cred_ids) if desired_events else None

        # ── decide ──
        if not desired_events:
            # Definitive: the saved graph says no trigger op here (node gone
            # or operation changed away).
            decision = Decision("deregister" if rows else "noop",
                                "step_removed" if node is None else "nothing_desired", held=bool(rows))
        elif node_class.rows_are_registration(
            rows,
            event_types=desired_events,
            credential_id=credential_id,
            user_id=owner_id,
            config=node_config,
        ) and not _failure_on_record(node_config):
            decision = Decision("live", "converged", held=True)
        elif not credential_id or (plan_only and not hold_starts
                                   and not await credential_usable(pool, owner_id, credential_id)):
            # Fan-out doesn't need the credential, so a live registration keeps
            # working through provider blips and credential detaches: never torn down for this.
            decision = Decision("unregistered", "no_credential")
        elif plan_only and not hold_starts and (refusal := await _activation_refusal(pool, wf_uuid, node_id)) is not None:
            # Registering checks the setup itself (below); a dry run reads ahead.
            decision = Decision("refused", "setup_unfinished", held=bool(rows), refusal=refusal)
        else:
            decision = _held_back(Decision(
                "reregister" if rows else "register",
                "settings_changed" if rows else "never_registered", held=bool(rows),
            ), hold_starts)
        if plan_only:
            return decision.plan()

        # ── apply ──
        outcome = decision.outcome
        if outcome in ("noop", "live", "inactive"):
            return decision.done(outcome)
        if outcome == "unregistered":
            return decision.done("unregistered", error="credential unavailable")
        if outcome == "deregister":
            # Through the node class, so provider-side state (Discord's event union) converges too.
            await node_class.cleanup_external_webhook(pool, str(wf_uuid), node_id, node_config, None)
            return decision.done("deregistered")

        async def unregistrable(refused: BaseException) -> Dict[str, Any]:
            # The saved config can't activate (a restore or an edit made it
            # unrunnable): the subscriptions an earlier config registered stop
            # fanning out to it, and the step says why.
            if rows:
                await node_class.cleanup_external_webhook(
                    pool, str(wf_uuid), node_id, node_config, None
                )
            await WebhookManager.merge_node_config_patch(
                pool, wf_uuid, node_id,
                {"trigger_registered": False, "trigger_error": str(refused),
                 "subscription_status": f"⚠ Not registered: {refused}",
                 "trigger_action": None},
            )
            return decision.done("deregistered" if rows else "refused", outcome="refused", reason="setup_unfinished",
                                 error=str(refused))

        if outcome == "refused":
            return await unregistrable(decision.refusal)

        _, credential = await node_class._resolve_trigger_credential(
            pool, owner_id, cred_ids
        )
        if not credential:
            return decision.done("unregistered", outcome="unregistered", reason="no_credential",
                                 error="credential unavailable")

        try:
            await require_activation_ready(pool, wf_uuid, node_id)
            mirrors = await node_class.register_and_describe(
                pool,
                user_id=owner_id,
                workflow_id=str(wf_uuid),
                node_id=node_id,
                operation=current_op,
                credential_id=credential_id,
                credential=credential,
                config=node_config,
            )
        except WorkflowNotReadyError as refused:
            return await unregistrable(refused)
        except Exception as e:
            logger.warning(
                f"[WEBHOOK] App-event registration failed for "
                f"{node_class.__name__}:{node_id}: {e}"
            )
            await WebhookManager.merge_node_config_patch(
                pool, wf_uuid, node_id,
                {"trigger_registered": False, "trigger_error": str(e),
                 "subscription_status": f"⚠ Not registered: {e}",
                 "trigger_action": None},
            )
            return decision.done("failed", error=str(e))
        # Mirror the outcome into the config blob so panels/builder snapshots
        # that read the stored graph don't show a stale failure after a heal.
        await WebhookManager.merge_node_config_patch(pool, wf_uuid, node_id, mirrors)
        return decision.done("registered")

    @staticmethod
    async def _refresh_schedule_next_run(
        pool, wf_uuid, node_id: str, node_config: Dict[str, Any], *, persist: bool,
    ) -> Optional[Dict[str, Any]]:
        """The scheduler's current next_run for a converged node, as a config
        patch when it differs from the mirror — else None. Never disturbs the
        fast path: any scheduler error means "keep what the mirror says"."""
        from utils.cron_scheduler_client import get_schedule

        ids = [i for i in (node_config.get("schedule_ids") or [node_config.get("schedule_id")]) if i]
        if not ids:
            return None
        upcoming = []
        for schedule_id in ids[:8]:
            try:
                info = await get_schedule(str(schedule_id), timeout=3.0)
            except Exception:
                return None
            if info.get("error") or not isinstance(info.get("next_run"), str):
                return None
            upcoming.append(info["next_run"])
        earliest = min(upcoming)
        if earliest == node_config.get("next_run"):
            return None
        if persist:
            await WebhookManager.merge_node_config_patch(
                pool, wf_uuid, node_id, {"next_run": earliest}
            )
        return {"next_run": earliest}

    @staticmethod
    async def _reconcile_schedule_node(
        pool,
        wf_uuid,
        node_id: str,
        *,
        owner_id: str,
        user_id: Optional[str],
        node: Optional[Dict[str, Any]],
        node_class,
        node_config: Dict[str, Any],
        current_op: Optional[str],
        plan_only: bool = False,
        refresh_next_run: bool = True,
        hold_starts: bool = False,
        observe: bool = False,
    ) -> Dict[str, Any]:
        """Cron-schedule family arm of ``reconcile_node`` (same contract).

        DESIRED: the node's ``cron_schedule_spec`` — expressions derived from
        the saved config, empty when the config can't run yet (validity gate).
        OBSERVED: the webhooks row's ``registered_fingerprint`` (stamped by
        this arm on success), so the live fast path is one SELECT with zero
        Cloudflare calls; past it, the scheduler's own schedules for the step
        (``_decide_schedule``), so a schedule the row never recorded is adopted
        or replaced, never taken for none. Convergence goes through the
        ``register_node_schedules`` chokepoint (deterministic ids + upsert +
        prune — inherently idempotent, so there is no adoption subtlety:
        legacy NULL-fingerprint registrations converge via one harmless
        upsert and are stamped).

        Registration mirrors (webhook_url, schedule_id, next_run,
        trigger_registered/…_error) are merged into the saved config blob so
        panels and brain snapshots read fresh state from any surface. On
        success the family's ``arm_schedule_trigger`` hook spawns (poll
        baseline: "new" is measured from arming).
        """
        from utils.async_helpers import spawn
        from utils.cron_scheduler_client import (
            is_cron_scheduler_enabled,
            register_node_schedules,
        )
        from utils.workflow_readiness import WorkflowNotReadyError

        spec = None
        if node is not None:
            try:
                spec = await node_class.cron_schedule_spec(
                    node_config, current_op, workflow_id=str(wf_uuid), pool=pool
                )
            except Exception:
                logger.warning(
                    f"[WEBHOOK] cron_schedule_spec failed for "
                    f"{node_class.__name__}:{node_id}",
                    exc_info=True,
                )
                return Decision("failed", "unreadable", error="schedule spec unavailable").done(
                    "failed", error="schedule spec unavailable")

        row = await _webhook_row(pool, wf_uuid, node_id)
        scheduler = is_cron_scheduler_enabled()
        decision = await WebhookManager._decide_schedule(
            pool, wf_uuid, node_id, node=node, node_class=node_class, node_config=node_config,
            current_op=current_op, spec=spec, row=row, scheduler=scheduler, observe=observe,
            hold_starts=hold_starts, predict=plan_only,
        )
        if plan_only:
            return decision.plan()

        # ── apply ──
        outcome = decision.outcome
        unschedule_error = f"Schedule not registered: {spec.config_error}" if spec and spec.config_error else None
        # Can't judge a step that isn't desired: never torn down. One that is still gets its row below.
        if outcome == "noop" or (outcome == "cannot_judge" and decision.fingerprint is None):
            return decision.done("noop")
        if outcome == "inactive":
            return decision.done("inactive")
        if outcome == "deregister":
            paused = node is not None and node_disabled(node)
            return await WebhookManager._unschedule(
                pool, wf_uuid, node_id, node=node, node_config=node_config, row=row, paused=paused,
                error=unschedule_error, decision=decision,
            )
        if outcome == "live":
            # Converged — but "next run" moves on every tick, and the config
            # mirror only captured it at registration. The panel refetches
            # through here when its countdown expires; with nothing fresh it
            # showed "Running…" forever after the first tick.
            result = decision.done("live", fingerprint=decision.fingerprint)
            if not refresh_next_run:
                return result
            refreshed = await WebhookManager._refresh_schedule_next_run(
                pool, wf_uuid, node_id, node_config, persist=node is not None,
            )
            if refreshed:
                result["values"] = refreshed
            return result
        if outcome == "adopt":
            await WebhookManager._stamp_row(pool, row["id"], decision)
            return decision.done("live", fingerprint=decision.fingerprint, adopted=True)
        if outcome == "refused":
            # The saved config can't activate (a restore or an edit made it
            # unrunnable): a schedule an earlier config registered doesn't stay
            # live, and the step says why. The refusal still reaches the caller.
            if decision.held and scheduler:
                await WebhookManager._unschedule(
                    pool, wf_uuid, node_id, node=node, node_config=node_config, row=row, paused=False,
                    error=str(decision.refusal), decision=decision,
                )
            raise decision.refusal

        desired_fp = decision.fingerprint
        try:
            webhook = await WebhookManager.get_or_create_webhook(
                pool, user_id or owner_id, wf_uuid, node_id
            )
        except WorkflowNotReadyError as refused:
            # Refused between deciding and registering: as above, only where a schedule may exist (a trigger
            # never registered gets no prune and no mirror).
            if scheduler and (decision.held or _may_have_schedules(row, node_config)):
                await WebhookManager._unschedule(
                    pool, wf_uuid, node_id, node=node, node_config=node_config, row=row, paused=False,
                    error=str(refused), decision=decision,
                )
            raise
        webhook_url = webhook.get("webhook_url")
        if not (scheduler and webhook_url):
            return decision.done("noop")

        reg = await register_node_schedules(
            user_id=owner_id,
            workflow_id=str(wf_uuid),
            node_id=node_id,
            webhook_url=webhook_url,
            cron_expressions=spec.expressions,
            timezone=spec.timezone,
            source=spec.source,
        )
        values: Dict[str, Any] = {
            "webhook_id": webhook.get("webhook_id"),
            "webhook_url": webhook_url,
            "relay_connected": webhook.get("relay_connected"),
            "is_production": webhook.get("is_production"),
            "is_active": True,
            "schedule_id": reg["schedule_id"],
            "schedule_ids": reg["schedule_ids"],
            "next_run": reg["next_run"],
            # Re-registering is how a breaker pause ends (the node was
            # re-enabled), so the pause reason goes with it.
            "paused_reason": None,
            **spec.extra_values,
        }
        if not reg["is_active"]:
            values["trigger_registered"] = False
            values["trigger_error"] = "Failed to create schedule"
            await WebhookManager.merge_node_config_patch(
                pool, wf_uuid, node_id, values
            )
            return decision.done("failed", values=values)

        await WebhookManager.persist_registration_state(
            pool, webhook["webhook_id"],
            registered_operation=current_op or "__schedule__",
            registered_fingerprint=desired_fp,
        )
        values["trigger_registered"] = True
        values["trigger_error"] = None
        await WebhookManager.merge_node_config_patch(pool, wf_uuid, node_id, values)
        spawn(
            node_class.arm_schedule_trigger(
                user_id=owner_id, workflow_id=str(wf_uuid), node_id=node_id,
                config=node_config, pool=pool,
            ),
            name=f"schedule-arm:{node_id}",
        )
        return decision.done("registered", fingerprint=desired_fp, values=values)

    @staticmethod
    async def _decide_schedule(
        pool, wf_uuid, node_id: str, *, node: Optional[Dict[str, Any]], node_class,
        node_config: Dict[str, Any], current_op: Optional[str], spec, row: Optional[Dict[str, Any]],
        scheduler: bool, hold_starts: bool, observe: bool = False, predict: bool = False,
    ) -> Decision:
        """The schedule family's decision. DESIRED: the step's
        ``cron_schedule_spec``. OBSERVED: the row's fingerprint (the fast path:
        no scheduler call), else, with ``observe``, the scheduler's own
        schedules for the step, which settle what the row can't (a schedule
        registered before the row recorded one, or one the row says it holds)."""
        # A node of both families on a push operation (Atlas's, Cloudflare's):
        # the row is its webhook's, which a lack of schedule says nothing about.
        if spec is None and node is not None and current_op and row and row["registered_operation"] == current_op:
            return Decision("noop", "nothing_desired")

        # A disabled trigger is not desired either: the disabled flag IS the
        # pause primitive (the panel toggle, the builder's <disable_node>, the
        # failure breaker in webhook_routes), and this is the one place that
        # turns it into a pruned schedule.
        paused = node is not None and node_disabled(node)
        if paused or not (spec and spec.expressions):
            reason = ("step_removed" if node is None else "switched_off" if paused
                      else "not_runnable" if spec and spec.config_error else "nothing_desired")
            # Scheduler-disabled is different — we can't judge, so never tear
            # down (local dev without the CF scheduler).
            if spec is not None and not scheduler:
                return Decision("cannot_judge", "no_scheduler")
            # Only when something says schedules may exist, so sweeps over
            # converged steps stay cheap: the row, a mirror, or, for a step with
            # a row (an address a schedule could fire at), the scheduler.
            may_have = _may_have_schedules(row, node_config) or (
                scheduler and observe and row is not None and bool(await _observed_schedules(wf_uuid, node_id)))
            return Decision("deregister" if may_have else "noop", reason, held=may_have)

        scope = node_class.schedule_poll_scope(node_config)
        credential_id = _extract_node_credential_id(node, node_config)
        fingerprint = _schedule_registration_fingerprint(current_op, spec, scope, credential_id)
        if row and row["is_active"] and row["registered_fingerprint"] == fingerprint:
            return Decision("live", "converged", fingerprint=fingerprint, held=True)
        if not scheduler:
            return Decision("cannot_judge", "no_scheduler", fingerprint=fingerprint)

        schedules = await _observed_schedules(wf_uuid, node_id) if observe else None
        if row and row["is_active"] and schedules is not None and _schedules_match(schedules, spec, row["id"]):
            return Decision("adopt", "seen_live", fingerprint=fingerprint, held=True,
                            stamp={"registered_operation": current_op or "__schedule__"})
        if schedules is None:
            held = bool(row and row["is_active"] and row["registered_operation"])
        else:
            held = bool(schedules)

        # Registering checks the setup itself (get_or_create_webhook); a dry run reads ahead.
        refusal = await _activation_refusal(pool, wf_uuid, node_id) if predict and not hold_starts else None
        if refusal is not None:
            may_have = held or _may_have_schedules(row, node_config)
            return Decision("refused", "setup_unfinished", fingerprint=fingerprint, held=may_have, refusal=refusal)
        if schedules:
            reason = "seen_other"
        elif row and row["registered_operation"]:
            reason = "settings_changed" if held else "taken_down"
        else:
            reason = "never_registered"
        return _held_back(Decision(
            "reregister" if held else "register", reason, fingerprint=fingerprint, held=held,
        ), hold_starts)

    @staticmethod
    async def _unschedule(
        pool, wf_uuid, node_id: str, *, node: Optional[Dict[str, Any]], node_config: Dict[str, Any],
        row, paused: bool, error: Optional[str], decision: Decision,
    ) -> Dict[str, Any]:
        """The schedule arm's teardown: prune the node's schedules and mirror
        that it has none, with ``error`` (why it can't run) as its
        ``trigger_error``."""
        from utils.cron_scheduler_client import delete_schedules_for_nodes

        try:
            await delete_schedules_for_nodes(str(wf_uuid), [node_id])
        except Exception as e:
            logger.warning(
                f"[WEBHOOK] Schedule prune failed for {node_id}: {e}"
            )
            return decision.done("failed", error=str(e))
        if row and row["registered_operation"]:
            await WebhookManager.deactivate_webhook(
                pool, str(wf_uuid), node_id, clear_registration=False,
            )
        teardown_values = {
            "schedule_id": None, "next_run": None,
            "trigger_registered": False,
            "trigger_error": error,
        }
        if node is not None:
            await WebhookManager.merge_node_config_patch(
                pool, wf_uuid, node_id, teardown_values
            )
        return decision.done("deregistered", paused=paused, values=teardown_values)

    @staticmethod
    async def _cleanup_orphaned_app_event_rows(pool, wf_uuid, node_id: str) -> bool:
        """Delete ``webhook_subscriptions`` rows whose node left the saved
        graph, dispatching through the provider's node class so provider-side
        state converges (Discord recomputes its event union). Returns True
        when rows were cleaned."""
        from nodes.core.webhook_subscriptions import (
            delete_subscriptions,
            get_node_subscriptions,
        )

        rows = await get_node_subscriptions(pool, str(wf_uuid), node_id)
        if not rows:
            return False
        node_class = _app_event_class_for_provider(rows[0]["provider"])
        if node_class is None:
            await delete_subscriptions(pool, str(wf_uuid), node_id)
        else:
            await node_class.cleanup_external_webhook(
                pool, str(wf_uuid), node_id, {}, None
            )
        logger.info(
            f"[WEBHOOK] Cleared orphaned app-event subscription rows for "
            f"{wf_uuid}:{node_id}"
        )
        return True

    @staticmethod
    async def handle_registration_fields_change(
        pool,
        node_type: str,
        workflow_id: str,
        node_id: str,
        old_config: Optional[Dict[str, Any]],
        new_config: Optional[Dict[str, Any]],
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
        nodes_override: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Reconcile when a registration-RELEVANT config field changed while
        operation and credentials stayed put (those have their own hooks).
        The fields a node declares via ``registration_fingerprint_fields``
        feed the provider-side registration (PostHog's event_name, GitHub's
        repository) — before this hook, editing one silently kept the STALE
        provider registration until the config panel happened to reopen
        (PostHog stuck filtering the old event while the config showed the
        new one, 2026-07-20). Returns True when a reconcile acted."""
        from nodes.core.registry import NODE_REGISTRY
        from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

        node_class = NODE_REGISTRY.get(node_type)
        is_schedule_family = _schedule_trigger_class(node_type) is not None
        # A trigger its own loader registers (WhatsApp's own-chat setting) converges through the reconciler too.
        loader_registered = bool(node_class and getattr(node_class, "self_registering_triggers", {}).get(
            (new_config or {}).get("operation") or ""))
        if not is_schedule_family and not (
            node_class and isinstance(node_class, type)
            and (loader_registered or issubclass(node_class, ExternalWebhookTriggerMixin))
            and hasattr(node_class, "registration_fingerprint_fields")
        ):
            return False
        try:
            old_fields = node_class.registration_fingerprint_fields(old_config or {}) or {}
            new_fields = node_class.registration_fingerprint_fields(new_config or {}) or {}
        except Exception:
            logger.warning(
                f"[WEBHOOK] fingerprint fields unreadable for {node_type}:{node_id}",
                exc_info=True,
            )
            return False
        if old_fields == new_fields:
            return False
        # Schedule-family membership is judged by the wider registration gate
        # (bespoke pollers carry no schema webhook marker; the cron node has
        # no operation at all).
        gate = (
            WebhookManager.operation_requires_registration
            if is_schedule_family
            else WebhookManager.operation_requires_webhook
        )
        if not gate(node_type, (new_config or {}).get("operation")):
            return False

        changed_keys = sorted(
            k for k in {**old_fields, **new_fields}
            if old_fields.get(k) != new_fields.get(k)
        )
        logger.info(
            f"[WEBHOOK] Registration fields {changed_keys} changed on "
            f"{node_type}:{node_id} — reconciling"
        )
        # A pre-fingerprint (NULL) row would be ADOPTED by the reconcile —
        # stamped with the NEW config's fingerprint, provider untouched. Here
        # we KNOW the fields just changed, so the provider registration was
        # built from the OLD config: stamp the historical fingerprint first so
        # the reconcile sees the drift and rotates (first post-migration edit
        # of a pre-existing PostHog trigger kept filtering the old event_name
        # until a panel reopen, 2026-07-20). Schedule-family rows skip this:
        # their registration is an idempotent upsert with no rotation hazard,
        # so the reconcile converges regardless of the stored fingerprint.
        if not is_schedule_family:
            try:
                old_fp = registration_fingerprint(
                    node_class, (old_config or {}).get("operation"),
                    _extract_node_credential_id({}, old_config or {}),
                    old_config or {},
                )
                wf_uuid = UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE webhooks SET registered_fingerprint = $1, updated_at = now() "
                        "WHERE workflow_id = $2 AND node_id = $3 "
                        "AND is_active AND registered_fingerprint IS NULL",
                        old_fp, wf_uuid, node_id,
                    )
            except Exception:
                logger.warning(
                    f"[WEBHOOK] pre-reconcile fingerprint stamp failed for "
                    f"{node_type}:{node_id}", exc_info=True,
                )
        try:
            result = await WebhookManager.reconcile_node(
                pool, workflow_id, node_id, user_id=user_id, org_id=org_id,
                nodes_override=nodes_override,
            )
        except Exception as e:
            logger.warning(
                f"[WEBHOOK] Registration-fields reconcile failed for "
                f"{node_type}:{node_id}: {e}"
            )
            return False
        return result.get("state") not in ("noop", "live", "no_workflow")

    @staticmethod
    def _registerable_types() -> List[str]:
        """The node types a step of which can hold a registration."""
        from nodes.core.catalog import every_node_facts

        return sorted(t for t, facts in every_node_facts().items() if facts["registers"])

    @staticmethod
    async def _resync_steps(
        pool, wf_id: UUID, registerable_types: List[str]
    ) -> Tuple[Dict[str, Dict[str, Any]], Set[str]]:
        """A workflow's steps by id, and those a resync reconciles: the triggers
        its graph holds and whatever its rows say is registered, in the graph or not."""
        from repositories import trigger_resync

        owner_id, nodes = await _load_workflow_owner_and_nodes(pool, wf_id)
        if owner_id is None:
            return {}, set()
        graph_candidates = {
            n["id"]
            for n in nodes
            if n.get("id") and n.get("type") in registerable_types
            and WebhookManager.operation_requires_registration(
                n.get("type"), _extract_node_config(n).get("operation")
            )
        }
        steps = {n["id"]: n for n in nodes if n.get("id")}
        return steps, graph_candidates | await trigger_resync.registered_nodes(pool, wf_id)

    @staticmethod
    async def resync_trigger_registrations(
        pool, limit: int = 500, budget_s: float = RESYNC_BUDGET_S
    ) -> Dict[str, Any]:
        """Level-triggered backstop (rides daily_maintenance) — GRAPH-driven.

        Walks every live workflow whose saved graph contains a
        registration-capable trigger node (external-webhook mixin or
        app-event trigger op), PLUS workflows holding active registered
        ``webhooks`` rows or any ``webhook_subscriptions`` rows (catches
        orphans whose node left the graph), and reconciles each candidate
        node. Because desired state comes from the GRAPH, a registration
        that NEVER happened — a write surface that missed provisioning —
        is healed by the next lap, not just drift on rows that already exist
        (the pre-2026-07-30 row-driven sweep could never revive a
        builder-built Slack trigger that shipped unregistered).

        Healing a trigger can start a schedule or a bot nobody has looked at
        in months, spending its owner's money, so until a person has read
        ``plan_trigger_resync`` and thrown the switch
        (``trigger_resync.set_registers``) a pass only reports it: no write, no
        provider call, and the lap stays where it is. Switched on, it still
        starts or replaces a registration only for a workflow in use within
        ``RESYNC_ACTIVE_WITHIN`` (a run, a person's edit, its owner back:
        ``trigger_resync.is_active``), and holds the rest as ``inactive``;
        teardowns, adoptions and refusals aren't held.

        A pass visits at most ``limit`` workflows, in id order, from where the
        last one reached (``trigger_resync_state``), and stops starting them
        past ``budget_s``, judged before each step and never by cutting one off;
        the next picks up there, and the lap wraps at the end. The lap moves
        before each visit: a workflow that kills the pass can't stop the
        rotation, and the next lap reaches it. A workflow time stopped partway
        is where the next pass starts, unless it was this pass's first. Turning the
        switch off stops a pass at its next workflow, and of two passes at once
        the one that finds the lap moved stops.

        NULL-fingerprint rows are adopted (stamped), not rotated. The
        fingerprint / row-match fast paths make a full pass cheap. Failures are
        counted and logged, never raised (one bad workflow must not stall the
        sweep), and a workflow whose blob holds no list of steps says nothing
        about them, so it's counted and nothing of it is torn down."""
        from repositories import trigger_resync

        state = await trigger_resync.read_state(pool)
        if not state.registers:
            plan = await WebhookManager.plan_trigger_resync(pool, budget_s=budget_s)
            return {"registers": False, **resync_plan_summary(plan)}

        deadline = monotonic() + budget_s
        registerable_types = WebhookManager._registerable_types()
        after = state.after_workflow_id
        rows = await trigger_resync.candidates(pool, registerable_types, after=after, limit=limit + 1)
        stats: Dict[str, Any] = {
            "registers": True, "workflows": 0, "checked": 0, "converged": 0, "adopted": 0, "refused": 0,
            "provider_refused": 0, "inactive": 0, "failed": 0, "no_graph": 0, "lap_finished": False, "stopped": None,
        }
        for index, wf_row in enumerate(rows[:limit]):
            if monotonic() >= deadline:
                stats["stopped"] = "out of time"
                break
            if not await trigger_resync.advance(pool, expected=after, to=wf_row["id"]):
                stats["stopped"] = "turned off, or another pass took the lap over"
                break
            before, after = after, wf_row["id"]
            checked = stats["checked"]
            if not await WebhookManager._resync_workflow(pool, wf_row, registerable_types, stats, deadline):
                stats["stopped"] = "out of time"
                # The next pass starts with it, unless it was this one's first and got a step done:
                # one too long for any pass can't hold the lap.
                if (index or stats["checked"] == checked) and await trigger_resync.advance(
                    pool, expected=after, to=before
                ):
                    after = before
                break
        else:
            if len(rows) <= limit:
                stats["lap_finished"] = await trigger_resync.advance(
                    pool, expected=after, to=None, lap_finished=True
                )
        if stats["stopped"]:
            logger.warning(f"[WEBHOOK] Resync pass stopped early ({stats['stopped']}); the next one picks up there")
        return stats

    @staticmethod
    async def _resync_workflow(
        pool, wf_row, registerable_types: List[str], stats: Dict[str, Any], deadline: float
    ) -> bool:
        """One workflow of a pass that acts. False when ``deadline`` came before its last step."""
        from utils.workflow_readiness import WorkflowNotReadyError

        from repositories import trigger_resync

        wf_id = wf_row["id"]
        if not wf_row["has_graph"]:
            stats["no_graph"] += 1
            return True
        hold_starts = not trigger_resync.is_active(wf_row, datetime.now(timezone.utc), RESYNC_ACTIVE_WITHIN)
        try:
            _, node_ids = await WebhookManager._resync_steps(pool, wf_id, registerable_types)
        except Exception:
            stats["failed"] += 1
            logger.warning(
                f"[WEBHOOK] Resync candidate scan failed for {wf_id}",
                exc_info=True,
            )
            return True
        if not node_ids:
            return True

        stats["workflows"] += 1
        for node_id in sorted(node_ids):
            if monotonic() >= deadline:
                return False
            stats["checked"] += 1
            try:
                result = await WebhookManager.reconcile_node(
                    pool, str(wf_id), node_id, refresh_next_run=False, hold_starts=hold_starts, observe=True,
                )
                state = result.get("state")
                if result.get("adopted"):
                    stats["adopted"] += 1
                elif state in ("registered", "deregistered"):
                    stats["converged"] += 1
                    logger.info(
                        f"[WEBHOOK] Resync converged {wf_id}:{node_id} "
                        f"({state}) — a mutation surface missed a reconcile"
                    )
                elif state in ("failed", "provider_refused", "inactive", "refused"):
                    stats[state] += 1
            except WorkflowNotReadyError:
                stats["refused"] += 1
            except Exception:
                stats["failed"] += 1
                logger.warning(
                    f"[WEBHOOK] Resync reconcile failed for {wf_id}:{node_id}",
                    exc_info=True,
                )
        return True

    @staticmethod
    async def plan_trigger_resync(pool, *, budget_s: Optional[float] = None) -> Dict[str, Any]:
        """What a pass that acts would do to every workflow it may visit: the
        same decisions ``reconcile_node`` acts on, read with ``plan_only``, so
        nothing is written, no customer's provider is called, and the lap
        doesn't move. Workflows are read ``RESYNC_PLAN_CONCURRENCY`` at a time.

        It's read by people, so it holds no customer content: workflow ids,
        days since each was last in use (run, edited by a person, its owner
        back), node types and operation names NoClick defined, and each
        decision's reason in NoClick's words. ``listed`` has one entry per step
        for every outcome but the two that do nothing, ``counts`` the same by
        type and operation, and ``complete`` says whether ``budget_s`` let it
        reach them all."""
        from repositories import trigger_resync

        deadline = None if budget_s is None else monotonic() + budget_s
        registerable_types = WebhookManager._registerable_types()
        rows = await trigger_resync.candidates(pool, registerable_types)
        now = datetime.now(timezone.utc)
        states: Counter = Counter()
        listed: Dict[str, List[Dict[str, Any]]] = {}
        plan: Dict[str, Any] = {"complete": True, "workflows": 0, "checked": 0, "no_graph": 0,
                                "active_within_days": RESYNC_ACTIVE_WITHIN.days}

        def days(at) -> Optional[int]:
            return (now - at).days if at is not None else None

        def note(state: str, wf_row, node: Optional[Dict[str, Any]], result: Optional[Dict[str, Any]] = None,
                 error: Optional[BaseException] = None) -> None:
            states[state] += 1
            if state in ("live", "noop", "no_workflow"):
                return
            kind, operation = _reported_kind(node)
            entry = {
                "workflow_id": str(wf_row["id"]),
                "type": kind,
                "operation": operation,
                "reason": (result or {}).get("reason"),
                "last_active_days_ago": days(trigger_resync.last_active(wf_row)),
                "last_run_days_ago": days(wf_row["last_run_at"]),
                "owner_seen_days_ago": days(wf_row["owner_seen_at"]),
            }
            if (result or {}).get("held_back"):
                entry["held_back"] = PLAN_STATES.get(result["held_back"], result["held_back"])
            if error is not None:
                entry["error"] = type(error).__name__
            listed.setdefault(state, []).append(entry)

        def out_of_time() -> bool:
            if deadline is not None and monotonic() >= deadline:
                plan["complete"] = False
            return not plan["complete"]

        async def read(wf_row) -> None:
            if out_of_time():
                return
            if not wf_row["has_graph"]:
                plan["no_graph"] += 1
                return
            try:
                steps, node_ids = await WebhookManager._resync_steps(pool, wf_row["id"], registerable_types)
            except Exception as e:
                note("failed", wf_row, None, error=e)
                return
            if not node_ids:
                return
            plan["workflows"] += 1
            hold_starts = not trigger_resync.is_active(wf_row, now, RESYNC_ACTIVE_WITHIN)
            for node_id in sorted(node_ids):
                if out_of_time():
                    return
                plan["checked"] += 1
                node = steps.get(node_id)
                try:
                    result = await asyncio.wait_for(
                        WebhookManager.reconcile_node(
                            pool, str(wf_row["id"]), node_id, nodes_override=list(steps.values()), plan_only=True,
                            hold_starts=hold_starts, observe=True,
                        ),
                        RESYNC_PLAN_STEP_TIMEOUT_S,
                    )
                except Exception as e:
                    logger.warning(f"[WEBHOOK] Resync plan failed for {wf_row['id']}:{node_id}", exc_info=True)
                    note("failed", wf_row, node, error=e)
                else:
                    note(result["state"], wf_row, node, result)

        gate = asyncio.Semaphore(RESYNC_PLAN_CONCURRENCY)

        async def bounded(wf_row) -> None:
            async with gate:
                await read(wf_row)

        await asyncio.gather(*(bounded(wf_row) for wf_row in rows))

        for entries in listed.values():
            entries.sort(key=lambda e: (e["workflow_id"], e["type"], str(e["operation"])))
        plan["states"] = dict(states)
        plan["listed"] = listed
        plan["counts"] = {
            state: [
                {"type": kind, "operation": operation, "count": count}
                for (kind, operation), count in Counter(
                    (entry["type"], entry["operation"]) for entry in entries
                ).most_common()
            ]
            for state, entries in listed.items()
        }
        return plan

    @staticmethod
    async def handle_operation_change(
        pool,
        node_type: str,
        workflow_id: str,
        node_id: str,
        old_operation: Optional[str],
        new_operation: Optional[str],
        old_config: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
        nodes_override: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Deregister the OLD operation's provider webhook when a node's operation
        changes away from one that required it.

        Two cases act; both route through the choke points:
        - webhook op → non-webhook op: provider teardown + row deactivation.
        - webhook op → DIFFERENT webhook op: teardown the old registration,
          then self-heal by re-registering for the new operation (covers
          headless changes — MCP/agentic set_operation — where no config panel
          will fire ``load_field_value``; when the panel already re-registered,
          ``register_node_webhooks``' inactive-row gate makes this a no-op).

        Returns True if cleanup was performed.
        """
        if old_operation == new_operation:
            return False

        old_requires = WebhookManager.operation_requires_registration(node_type, old_operation)
        new_requires = WebhookManager.operation_requires_registration(node_type, new_operation)

        if not (old_requires or new_requires):
            return False

        logger.info(
            f"[WEBHOOK] Operation changed from {old_operation} to {new_operation} "
            f"on {node_type}:{node_id} — reconciling registration"
        )

        # Level-triggered: no old-vs-new transition plumbing (the old state
        # raced the debounced config mirror and orphaned one provider hook per
        # rapid operation flip, 2026-07-19). The reconciler reads the SAVED
        # graph as desired truth and the row as observed truth and converges;
        # the fingerprint makes it a no-op when the panel already converged.
        try:
            result = await WebhookManager.reconcile_node(
                pool, workflow_id, node_id, user_id=user_id, org_id=org_id,
                nodes_override=nodes_override,
            )
        except Exception as e:
            logger.warning(
                f"[WEBHOOK] Post-operation-change reconcile failed for "
                f"{node_type}:{node_id}: {e}"
            )
            return False
        return result.get("state") not in ("noop", "live", "no_workflow")

    @staticmethod
    async def handle_credential_change(
        pool,
        node_type: str,
        workflow_id: str,
        node_id: str,
        old_config: Dict[str, Any],
        new_config: Dict[str, Any],
        user_id: str,
        org_id: Optional[str] = None,
        nodes_override: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """
        Reconcile a node's registration when its ``credentialIds`` change
        between saves: a swap or removal (the OLD credential's provider
        endpoint must go, or every event on the old connection fans out to an
        orphan — WhatsApp group-message incident, 2026-06-25), or an attach to
        a node whose current operation registers something. An attach is a
        change like any other: the fingerprint covers the credential, and a
        trigger whose row was torn down (or never registered) converges only
        through this reconcile, whatever its config mirror still says.

        Row semantics fix the swap race: if the config panel already
        re-registered under the NEW credential, the reconcile is a fingerprint
        no-op and only the old provider endpoint is torn down. Headless swaps
        (MCP set_credentials) converge the same way.

        Returns the number of changed credential entries when the reconcile
        acted, else 0.
        """
        old_creds = _usable_credentials({}, old_config or {})
        new_creds = _usable_credentials({}, new_config or {})
        removed_or_swapped = [
            (cred_type, old_cid) for cred_type, old_cid in old_creds.items()
            if new_creds.get(cred_type) != old_cid
        ]
        attached = [cid for cred_type, cid in new_creds.items() if cred_type not in old_creds]
        # A pure attach has nothing to tear down: only a node that registers on
        # its current operation can need converging.
        if not removed_or_swapped and not (
            attached and (
                WebhookManager.operation_requires_registration(
                    node_type, (new_config or {}).get("operation")
                )
                or _loader_registers(node_type, {}, new_config or {})
            )
        ):
            return 0

        from nodes.core.registry import NODE_REGISTRY

        if NODE_REGISTRY.get(node_type) is None:
            return 0

        logger.info(
            f"[WEBHOOK] Credential change on {node_type}:{node_id} "
            f"(replaced {[cid for _, cid in removed_or_swapped]}, attached {attached}) "
            f"— reconciling registration"
        )

        # Panel-won race supplement: when the config panel already
        # re-registered under the NEW credential, the reconcile below is a
        # fingerprint no-op — correct for OUR state, but the OLD credential's
        # provider endpoint (created before the panel's re-register) may still
        # exist for providers without replace-stale/sweep idempotency. If the
        # row's endpoint id has MOVED past old_config's, drop the old endpoint
        # with the old credential. Best-effort and 404-tolerant: a stale id is
        # convergence, never a failure.
        supplemental = 0
        old_ext = (old_config or {}).get("external_webhook_id")
        if old_ext:
            try:
                wf_uuid = UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT external_webhook_id FROM webhooks "
                        "WHERE workflow_id = $1 AND node_id = $2",
                        wf_uuid, node_id,
                    )
                row_ext = row["external_webhook_id"] if row else None
                if row_ext and str(row_ext) != str(old_ext):
                    from utils.credentials import get_credential

                    node_class = NODE_REGISTRY.get(node_type)
                    for _, old_cid in removed_or_swapped:
                        old_cred = await get_credential(old_cid, user_id, pool, org_id)
                        if old_cred:
                            await node_class.cleanup_external_webhook(
                                pool, workflow_id, node_id, old_config, old_cred
                            )
                            supplemental += 1
                            logger.info(
                                f"[WEBHOOK] Dropped pre-swap endpoint {old_ext} for "
                                f"{node_type}:{node_id} (panel already re-registered)"
                            )
                            break
            except Exception as e:
                logger.warning(
                    f"[WEBHOOK] Pre-swap endpoint cleanup failed for "
                    f"{node_type}:{node_id}: {e}"
                )

        # Level-triggered: the fingerprint covers the credential, so a swap is
        # just a mismatch for the reconciler to converge. Provider teardown of
        # the OLD registration resolves the row's registered_credential_id
        # (deregister prefers it), so no old-credential plumbing rides here —
        # the old_config-driven teardown raced the panel's own re-register and
        # the debounced mirror.
        try:
            result = await WebhookManager.reconcile_node(
                pool, workflow_id, node_id, user_id=user_id, org_id=org_id,
                nodes_override=nodes_override,
            )
        except Exception as e:
            logger.warning(
                f"[WEBHOOK] Post-credential-change reconcile failed for "
                f"{node_type}:{node_id}: {e}"
            )
            return supplemental
        acted = supplemental or result.get("state") not in ("noop", "live", "no_workflow")
        return len(removed_or_swapped) + len(attached) if acted else 0

    @staticmethod
    async def delete_webhooks_for_workflow(
        pool,
        workflow_id: str,
    ) -> int:
        """
        Delete all webhooks for a workflow.

        Used when a workflow is deleted.

        Args:
            pool: Database connection pool
            workflow_id: Workflow UUID string

        Returns:
            Number of webhooks deleted
        """
        from utils.webhook_delivery import unregister_webhook

        deleted_count = 0

        try:
            async with pool.acquire() as conn:
                # Get all webhook IDs for this workflow
                rows = await conn.fetch(
                    """
                    SELECT id FROM webhooks WHERE workflow_id = $1
                    """,
                    UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id
                )

                if not rows:
                    logger.debug(f"[WEBHOOK] No webhooks found for workflow={workflow_id}")
                    return 0

                webhook_ids = [row['id'] for row in rows]

                # Delete from database
                await conn.execute(
                    """
                    DELETE FROM webhooks WHERE workflow_id = $1
                    """,
                    UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id
                )
                deleted_count = len(webhook_ids)
                logger.info(f"[WEBHOOK] Deleted {deleted_count} webhooks for workflow={workflow_id}")

                # Unregister from relay (for local dev) - best effort
                for webhook_id in webhook_ids:
                    try:
                        await unregister_webhook(str(webhook_id))
                    except Exception as e:
                        logger.debug(f"[WEBHOOK] Could not unregister {webhook_id} from relay: {e}")

        except Exception as e:
            logger.error(f"[WEBHOOK] Error deleting webhooks for workflow: {e}", exc_info=True)

        return deleted_count
