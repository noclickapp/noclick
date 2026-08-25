"""Cron-schedule registration family — the node-side declaration.

Trigger nodes that fire off a Cloudflare cron schedule (poll triggers, the
cron node, and the bespoke schedule pollers: gmail/firestore/GCS/datadog/
devin) form the FOURTH registration family in ``WebhookManager.reconcile_node``
(after external webhooks, app-event subscriptions, and plain rows). A node
mixes in ``CronScheduleTriggerMixin`` and declares WHAT it wants registered
(``cron_schedule_spec``); the reconciler owns WHEN — desired state derives
from the saved graph, converges through the ``register_node_schedules``
chokepoint, and every lifecycle surface (panel load, builder/MCP provisioning,
operation/credential/config-change hooks, restores, the nightly sweep) simply
calls ``reconcile_node``. Loaders and surfaces never hand-roll registration:
per-surface "which changes matter" lists are exactly where the 2026-08-04
form-trigger incident class lived.
"""

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from pydantic import BaseModel

logger = logging.getLogger(__name__)


@dataclass
class CronScheduleSpec:
    """DESIRED schedule state for one node, derived purely from its config.

    ``expressions`` empty = "this IS a schedule-trigger operation, but the
    config can't run yet" (missing required fields) — the reconciler converges
    to NO schedules and mirrors ``config_error`` so the panel/brain see why.
    """

    expressions: List[str]
    timezone: str = "UTC"
    source: str = "poll_trigger"
    config_error: Optional[str] = None
    # Extra config mirrors the registration should write (e.g. interval_ms).
    extra_values: Dict[str, Any] = field(default_factory=dict)


@lru_cache(maxsize=None)
def operation_config_class(node_cls, operation: Optional[str]):
    """Resolve the config-model union member for ``operation`` (the class
    whose ``operation`` Literal default matches). None when unresolvable.
    Cached — the union walk is static per class."""
    import typing

    model = node_cls.get_config_model()
    if model is None:
        return None
    # Unwrap the NodeConfig {config, credentials} wrapper if present.
    config_field = getattr(model, "model_fields", {}).get("config")
    annotation = config_field.annotation if config_field is not None else model

    # Peel Annotated[Union[...], Discriminator]
    while typing.get_origin(annotation) is not None and typing.get_origin(
        annotation
    ) not in (typing.Union,):
        args = typing.get_args(annotation)
        if not args:
            break
        annotation = args[0]

    members: Tuple[Any, ...]
    if typing.get_origin(annotation) is typing.Union:
        members = typing.get_args(annotation)
    else:
        members = (annotation,)

    for member in members:
        if not (isinstance(member, type) and issubclass(member, BaseModel)):
            continue
        op_field = member.model_fields.get("operation")
        if op_field is None:
            if operation is None:
                return member
            continue
        if op_field.default == operation:
            return member
    return None


class CronScheduleTriggerMixin:
    """Marker + hooks for schedule-registering trigger nodes.

    Default behavior covers the common shape — a single ``schedule`` config
    field (5-min default) registering one cron expression, active when the
    current operation is a schedule-trigger op. Members customize by:

    - ``schedule_trigger_operations``: bespoke nodes (gmail, GCS, …) declare
      their trigger op names; poll-mixin nodes need nothing (detected via
      PollTriggerConfigBase).
    - ``cron_schedule_spec``: full override for exotic shapes (the cron
      node's multi-schedule + timezone + whole-schedule references).
    - ``schedule_poll_scope``: identity of the watched resource — a scope
      change rotates the registration fingerprint so the reconciler re-arms
      (fresh baseline) after a repoint.
    - ``arm_schedule_trigger``: post-registration hook (poll baseline).
    """

    schedule_trigger_operations: ClassVar[Tuple[str, ...]] = ()
    # Informational label stamped into the D1 schedule payload.
    schedule_source: ClassVar[str] = "poll_trigger"

    @classmethod
    def _is_schedule_operation(cls, operation: Optional[str]) -> bool:
        if operation and operation in cls.schedule_trigger_operations:
            return True
        from nodes.core.poll_trigger import PollTriggerConfigBase

        op_class = operation_config_class(cls, operation)
        return bool(op_class and issubclass(op_class, PollTriggerConfigBase))

    @classmethod
    async def cron_schedule_spec(
        cls,
        config: Dict[str, Any],
        operation: Optional[str],
        *,
        workflow_id: Optional[str] = None,
        pool=None,
    ) -> Optional[CronScheduleSpec]:
        """None = not a schedule-trigger op (nothing to register)."""
        from nodes.cron_trigger_node import schedule_to_cron, schedule_to_interval_ms
        from nodes.core.poll_trigger import registration_config_error

        if not cls._is_schedule_operation(operation):
            return None

        ctx = dict(config or {})
        if operation is not None:
            ctx.setdefault("operation", operation)
        config_error = registration_config_error(cls, ctx)
        if config_error:
            return CronScheduleSpec(expressions=[], config_error=config_error)

        schedule = ctx.get("schedule") or {"frequency": "minutes", "interval": 5}
        return CronScheduleSpec(
            expressions=[schedule_to_cron(schedule)],
            source=cls.schedule_source,
            extra_values={"interval_ms": schedule_to_interval_ms(schedule)},
        )

    @classmethod
    def schedule_poll_scope(cls, config: Dict[str, Any]) -> Optional[str]:
        """Watched-resource identity folded into the registration fingerprint.
        Default None (nodes with internal dedup); the poll mixin overrides."""
        return None

    @classmethod
    def registration_fingerprint_fields(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Raw config fields the save-diff hook compares to decide whether a
        config edit is registration-relevant (handle_registration_fields_change).
        Deliberately sync + cheap — the async spec runs only inside reconcile.
        The credential is included because ARMING (the baseline poll) needs it
        even though registration doesn't — a credential attached after
        registration must reconcile so the arm finally runs."""
        from utils.credentials import pick_credential_id

        cfg = config or {}
        return {
            "operation": cfg.get("operation"),
            "schedule": cfg.get("schedule"),
            "schedules": cfg.get("schedules"),
            "timezone": cfg.get("timezone"),
            "scope": cls.schedule_poll_scope(cfg),
            "credential": pick_credential_id(cfg.get("credentialIds") or {}),
        }

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
        """Post-registration arming (poll baseline). Default no-op."""
        return None

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Panel/headless provisioning entry for the whole family: mint the
        webhook row (URL display) and converge registration through THE
        reconciler — never register here. Desired state seeds from the
        caller's context via ``nodes_override`` (the panel edits ahead of its
        autosave); once the save lands, the save-diff hook re-converges from
        the saved graph, so context is a UX head start, not a second truth.
        """
        if field_name != "webhook_url":
            return {"value": None}

        from nodes.core.registry import NODE_REGISTRY
        from utils.webhook_manager import WebhookManager

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool, user_id=user_id, workflow_id=workflow_id, node_id=node_id
        )
        values: Dict[str, Any] = {
            "webhook_id": webhook_data.get("webhook_id"),
            "webhook_url": webhook_data.get("webhook_url"),
            "relay_connected": webhook_data.get("relay_connected"),
            "is_production": webhook_data.get("is_production"),
            "is_active": True,
        }

        node_type = next((k for k, v in NODE_REGISTRY.items() if v is cls), None)
        if node_type is None:
            return {"values": values}

        ctx = dict(context or {})
        if credential_ids:
            # The arm hook (poll baseline) resolves its credential from config.
            ctx.setdefault("credentialIds", dict(credential_ids))
        result = await WebhookManager.reconcile_node(
            pool, str(workflow_id), node_id, user_id=user_id,
            nodes_override=[{"id": node_id, "type": node_type, "config": ctx}],
        )
        reg_values = result.get("values") or {}
        # trigger_error/next_run/schedule_id carry meaningful None (clears);
        # everything else drops None so a no-op reconcile can't blank mirrors.
        values.update({
            k: v for k, v in reg_values.items()
            if v is not None or k in ("trigger_error", "next_run", "schedule_id")
        })
        return {"values": values}

    @classmethod
    async def cleanup_external_webhook(
        cls,
        pool,
        workflow_id: str,
        node_id: str,
        config: Dict[str, Any],
        credentials: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Provider-side teardown = delete the node's cron schedules. Shared
        by the whole family (the bespoke pollers and the cron node previously
        had NO teardown — their schedules outlived operation changes until the
        stale-tick prune fired)."""
        from utils.cron_scheduler_client import delete_schedules_for_nodes

        try:
            await delete_schedules_for_nodes(str(workflow_id), [node_id])
        except Exception as e:
            logger.warning(
                f"[{cls.__name__}] Failed to delete cron schedules for "
                f"node {node_id}: {e}"
            )
