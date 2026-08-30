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
  undo re-add, post-swap self-heal. Registers ONLY inactive rows carrying the
  marker whose CURRENT operation still requires a webhook; the row re-activates
  only via the post-success persist, so a failed provider call leaves the next
  config-panel open (or restore) to retry.

Rows are hard-deleted only on permanent workflow deletion
(``delete_webhooks_for_workflow``) and by the orphaned-webhook self-heal.

Schema markers:
- Field-level: json_schema_extra={"ui:widget": "webhook"} marks a field as a webhook URL
- Operation-level: model_config=ConfigDict(json_schema_extra={"x-requires-webhook": True})
"""

import logging
from functools import lru_cache
from typing import Dict, Any, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


def _extract_node_config(node: Dict[str, Any]) -> Dict[str, Any]:
    """A node's config lives at ``node['config']`` (backend save format) or
    ``node['data']['config']`` (canvas format). Return whichever is present."""
    cfg = node.get("config") or {}
    if not cfg and isinstance(node.get("data"), dict):
        cfg = node["data"].get("config") or {}
    return cfg


def _usable_credential_ids(node: Dict[str, Any], node_config: Dict[str, Any]) -> List[str]:
    """All usable credential ids configured on a node (config blob or
    ``node.data.credentialIds``), with ``pick_credential_id``'s semantics:
    the credential_type metadata key, empties, and unresolved ``{{...}}``
    references are not credential ids."""
    from utils.credentials import extract_credential_ids

    cred_ids = extract_credential_ids(node_config)
    if not cred_ids and isinstance(node.get("data"), dict):
        cred_ids = extract_credential_ids(node["data"])
    return [
        v for k, v in (cred_ids or {}).items()
        if k != "credential_type"
        and isinstance(v, str)
        and v.strip() != ""
        and "{{" not in v
    ]


def _extract_node_credential_id(node: Dict[str, Any], node_config: Dict[str, Any]) -> Optional[str]:
    """The single credential id configured on a node (trigger nodes carry one)."""
    ids = _usable_credential_ids(node, node_config)
    return ids[0] if ids else None


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


def _app_event_class_for_provider(provider: str):
    """Resolve an app-event provider slug (a webhook_subscriptions row's
    ``provider``) back to its node class — for orphan-row teardown where the
    node has already left the graph."""
    from nodes.core.registry import NODE_REGISTRY
    from nodes.core.webhook_subscriptions import AppEventTriggerMixin

    for node_class in NODE_REGISTRY.values():
        if (
            isinstance(node_class, type)
            and issubclass(node_class, AppEventTriggerMixin)
            and node_class._app_provider == provider
        ):
            return node_class
    return None


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
        from utils.webhook_tunnel import get_webhook_url

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
            # Self-hosted deliveries reach this process directly. Preserve the
            # legacy status fields for node-schema compatibility.
            is_production = True
            relay_connected = True

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
    async def provision_node_webhook(
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
        from utils.webhook_tunnel import unregister_webhook

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
        schedule_class = _schedule_trigger_class(node_type)
        return bool(schedule_class and schedule_class._is_schedule_operation(operation))

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
                "SELECT node_id, external_webhook_id, registered_operation, "
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
        re-registration choke point — trash restore, checkpoint restore, canvas
        undo re-add, and the post-credential-swap self-heal route here.

        Registers ONLY nodes whose webhooks row is INACTIVE and carries the
        ``registered_operation`` marker (a previously-registered trigger that
        ``deregister_node_webhooks`` tore down) and whose CURRENT operation
        still requires a webhook. Action nodes and never-registered triggers
        are never touched — a restored Stripe ``create_customer`` node must not
        grow a wildcard endpoint. The existing row (same UUID/URL) is reused;
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

            if _app_event_trigger_class(node_type) or _schedule_trigger_class(node_type):
                # App-event + cron-schedule families: desired state recomputes
                # from the saved graph and registration is zero-provider-cost
                # (idempotent upserts), so restores route straight through the
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
        canvas save repaired it).
        """
        import json as _json

        async with pool.acquire() as conn:
            await conn.execute(
                """
                WITH target AS (
                    SELECT (idx - 1)::int AS pos
                    FROM jsonb_array_elements(
                        (SELECT workflow->'nodes' FROM workflows WHERE id = $1)
                    ) WITH ORDINALITY AS n(node, idx)
                    WHERE node->>'id' = $2
                    LIMIT 1
                )
                UPDATE workflows
                SET workflow = jsonb_set(
                    workflow,
                    ARRAY['nodes', target.pos::text, 'config'],
                    COALESCE(workflow->'nodes'->target.pos->'config', '{}'::jsonb) || ($3::text)::jsonb
                ),
                updated_at = now()
                FROM target
                WHERE workflows.id = $1
                """,
                wf_uuid,
                node_id,
                _json.dumps(patch),
            )

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
            # so replace-stale-endpoint nodes can drop the previous endpoint.
            register_config = dict(node_config)
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
            logger.warning(
                f"[WEBHOOK] Failed to register external webhook for "
                f"{node_type}:{node_id}: {e}"
            )
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
    ) -> Dict[str, Any]:
        """THE level-triggered converger for a trigger node's external
        registration. Compares DESIRED state (computed purely from the node's
        CURRENT saved config: does its operation require a webhook, and the
        registration fingerprint of operation + credential + node-declared
        fields) against OBSERVED state (the webhooks row) and converges:

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

        Returns ``{"state": ..., "fingerprint": ...?}``; states: no_workflow,
        noop, live, deregistered, registered, unregistered (no credential),
        failed.
        """
        from nodes.core.registry import NODE_REGISTRY
        from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
        from utils.credentials import extract_credential_ids

        wf_uuid = UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id

        lock_key = f"nc:wh_reconcile:{workflow_id}:{node_id}"
        redis = None
        have_lock = False
        try:
            from utils.redis_client import get_shared_redis

            redis = get_shared_redis()
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
                    node_config=node_config, current_op=current_op,
                )

            # Family dispatch: cron-schedule triggers (poll mixin, cron node,
            # bespoke schedule pollers) converge cron schedules + the arm-time
            # baseline against the webhooks row's fingerprint.
            if _schedule_trigger_class(node_type):
                return await WebhookManager._reconcile_schedule_node(
                    pool, wf_uuid, node_id,
                    owner_id=owner_id, user_id=user_id, node=node,
                    node_class=node_class, node_config=node_config,
                    current_op=current_op,
                )

            # Node gone from the saved graph: clear any orphaned app-event
            # subscription rows (dead rows would fan out to a missing node
            # forever, and Discord's provider union would keep stale event
            # types), and best-effort prune any cron schedules still ticking
            # at the missing node (a deactivated row 410s deliveries forever
            # without ever hitting the tick-time orphan cleanup). The external
            # family's row handling follows below.
            orphan_cleaned = False
            if node is None:
                orphan_cleaned = (
                    await WebhookManager._cleanup_orphaned_app_event_rows(
                        pool, wf_uuid, node_id
                    )
                )
                try:
                    from utils.cron_scheduler_client import delete_schedules_for_nodes

                    await delete_schedules_for_nodes(str(wf_uuid), [node_id])
                except Exception:
                    logger.debug(
                        f"[WEBHOOK] Orphan schedule prune failed for {node_id}",
                        exc_info=True,
                    )

            desired = bool(
                node and is_mixin
                and WebhookManager.operation_requires_webhook(node_type, current_op)
            )

            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, is_active, external_webhook_id, registered_operation, "
                    "registered_credential_id, registered_fingerprint "
                    "FROM webhooks WHERE workflow_id = $1 AND node_id = $2",
                    wf_uuid, node_id,
                )

            if not desired:
                # Teardown when the row is live, or when a failed teardown left
                # a recorded provider endpoint behind (retry until clean).
                if row and (
                    (row["is_active"] and row["registered_operation"])
                    or (row["registered_operation"] and row["external_webhook_id"])
                ):
                    await WebhookManager.deregister_node_webhooks(
                        pool, str(workflow_id), [node_id],
                        node_overrides=[node] if node else None,
                        requesting_user_id=user_id or owner_id,
                        org_id=org_id,
                    )
                    return {"state": "deregistered"}
                return {"state": "deregistered" if orphan_cleaned else "noop"}

            credential_id = _extract_node_credential_id(node, node_config)
            desired_fp = registration_fingerprint(
                node_class, current_op, credential_id, node_config
            )
            if row and row["is_active"] and row["registered_fingerprint"] == desired_fp:
                return {"state": "live", "fingerprint": desired_fp}

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
                and not node_class.webhook_registration_stale(node_config, dict(row))
            ):
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE webhooks SET registered_fingerprint = $1, updated_at = now() "
                        "WHERE id = $2",
                        desired_fp, row["id"],
                    )
                return {"state": "live", "fingerprint": desired_fp, "adopted": True}

            # Converge: drop a live-but-stale registration first (the row's
            # registered_credential_id backs provider teardown even after a
            # credential swap), then register the desired state.
            if row and row["registered_operation"] and (
                row["is_active"] or row["external_webhook_id"]
            ):
                await WebhookManager.deregister_node_webhooks(
                    pool, str(workflow_id), [node_id],
                    requesting_user_id=user_id or owner_id,
                    org_id=org_id,
                )

            cred_ids = extract_credential_ids(node_config)
            if not cred_ids and isinstance(node.get("data"), dict):
                cred_ids = extract_credential_ids(node["data"])
            credential = await node_class._resolve_trigger_credential(
                pool, owner_id, cred_ids
            )
            if not credential:
                return {"state": "unregistered", "error": "credential unavailable"}

            ok = await WebhookManager._register_single_node(
                pool, wf_uuid=wf_uuid, user_id=user_id or owner_id,
                node_class=node_class, node_type=node_type, node_id=node_id,
                node_config=node_config, credential=credential,
                credential_id=credential_id, current_op=current_op,
            )
            return {
                "state": "registered" if ok else "failed",
                "fingerprint": desired_fp,
            }
        finally:
            if have_lock and redis is not None:
                try:
                    await redis.delete(lock_key)
                except Exception:
                    pass

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
        from nodes.core.webhook_subscriptions import (
            get_node_subscriptions,
            subscription_rows_match,
        )
        from utils.credentials import extract_credential_ids

        desired_events = (
            node_class._trigger_event_map.get(current_op or "", []) if node else []
        )
        rows = await get_node_subscriptions(pool, str(wf_uuid), node_id)

        if not desired_events:
            # Definitive: the saved graph says no trigger op here (node gone
            # or operation changed away) — tear down via the node class so
            # provider-side state (Discord's event union) converges too.
            if rows:
                await node_class.cleanup_external_webhook(
                    pool, str(wf_uuid), node_id, node_config, None
                )
                return {"state": "deregistered"}
            return {"state": "noop"}

        cred_ids = extract_credential_ids(node_config)
        if not cred_ids and node and isinstance(node.get("data"), dict):
            cred_ids = extract_credential_ids(node["data"])
        credential_id = node_class._pick_trigger_credential_id(cred_ids)

        if subscription_rows_match(
            rows,
            event_types=desired_events,
            credential_id=credential_id,
            user_id=owner_id,
        ):
            return {"state": "live"}

        if not credential_id:
            return {"state": "unregistered", "error": "credential unavailable"}

        _, credential = await node_class._resolve_trigger_credential(
            pool, owner_id, cred_ids
        )
        if not credential:
            return {"state": "unregistered", "error": "credential unavailable"}

        try:
            status = await node_class.register_node_subscriptions(
                pool,
                user_id=owner_id,
                workflow_id=str(wf_uuid),
                node_id=node_id,
                operation=current_op,
                credential_id=credential_id,
                credential=credential,
                config=node_config,
            )
        except Exception as e:
            logger.warning(
                f"[WEBHOOK] App-event registration failed for "
                f"{node_class.__name__}:{node_id}: {e}"
            )
            await WebhookManager.merge_node_config_patch(
                pool, wf_uuid, node_id,
                {"trigger_registered": False, "trigger_error": str(e),
                 "subscription_status": f"⚠ Not registered: {e}"},
            )
            return {"state": "failed", "error": str(e)}
        # Mirror the outcome into the config blob so panels/builder snapshots
        # that read the stored graph don't show a stale failure after a heal.
        await WebhookManager.merge_node_config_patch(
            pool, wf_uuid, node_id,
            {"trigger_registered": True, "trigger_error": None,
             "subscription_status": status},
        )
        return {"state": "registered"}

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
    ) -> Dict[str, Any]:
        """Cron-schedule family arm of ``reconcile_node`` (same contract).

        DESIRED: the node's ``cron_schedule_spec`` — expressions derived from
        the saved config, empty when the config can't run yet (validity gate).
        OBSERVED: the webhooks row's ``registered_fingerprint`` (stamped by
        this arm on success), so the live fast path is one SELECT with zero
        Cloudflare calls. Convergence goes through the
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
            delete_schedules_for_nodes,
            is_cron_scheduler_enabled,
            register_node_schedules,
        )

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
                return {"state": "failed", "error": "schedule spec unavailable"}

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, is_active, registered_operation, registered_fingerprint "
                "FROM webhooks WHERE workflow_id = $1 AND node_id = $2",
                wf_uuid, node_id,
            )

        if not (spec and spec.expressions):
            # NOT desired: node gone, operation changed away, or config not
            # runnable yet. Scheduler-disabled is different — we can't judge,
            # so never tear down (local dev without the CF scheduler).
            if spec is not None and not is_cron_scheduler_enabled():
                return {"state": "noop"}
            # Prune only when something suggests schedules may exist —
            # a family-registered row or legacy config mirrors — so sweep
            # passes over converged nodes stay Cloudflare-free.
            may_have_schedules = bool(
                (row and row["registered_operation"])
                or node_config.get("schedule_id")
                or node_config.get("next_run")
                or node_config.get("trigger_registered")
            )
            if not may_have_schedules:
                return {"state": "noop"}
            try:
                await delete_schedules_for_nodes(str(wf_uuid), [node_id])
            except Exception as e:
                logger.warning(
                    f"[WEBHOOK] Schedule prune failed for {node_id}: {e}"
                )
                return {"state": "failed", "error": str(e)}
            if row and row["registered_operation"]:
                await WebhookManager.deactivate_webhook(
                    pool, str(wf_uuid), node_id, clear_registration=False,
                )
            teardown_values = {
                "schedule_id": None, "next_run": None,
                "trigger_registered": False,
                "trigger_error": (
                    f"Schedule not registered: {spec.config_error}"
                    if spec and spec.config_error else None
                ),
            }
            if node is not None:
                await WebhookManager.merge_node_config_patch(
                    pool, wf_uuid, node_id, teardown_values
                )
            return {"state": "deregistered", "values": teardown_values}

        scope = node_class.schedule_poll_scope(node_config)
        credential_id = _extract_node_credential_id(node, node_config)
        desired_fp = _schedule_registration_fingerprint(
            current_op, spec, scope, credential_id
        )
        if row and row["is_active"] and row["registered_fingerprint"] == desired_fp:
            # Converged — but "next run" moves on every tick, and the config
            # mirror only captured it at registration. The panel refetches
            # through here when its countdown expires; with nothing fresh it
            # showed "Running…" forever after the first tick.
            refreshed = await WebhookManager._refresh_schedule_next_run(
                pool, wf_uuid, node_id, node_config, persist=node is not None,
            )
            result: Dict[str, Any] = {"state": "live", "fingerprint": desired_fp}
            if refreshed:
                result["values"] = refreshed
            return result

        webhook = await WebhookManager.get_or_create_webhook(
            pool, user_id or owner_id, wf_uuid, node_id
        )
        webhook_url = webhook.get("webhook_url")
        if not (is_cron_scheduler_enabled() and webhook_url):
            return {"state": "noop"}

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
            **spec.extra_values,
        }
        if not reg["is_active"]:
            values["trigger_registered"] = False
            values["trigger_error"] = "Failed to create schedule"
            await WebhookManager.merge_node_config_patch(
                pool, wf_uuid, node_id, values
            )
            return {"state": "failed", "values": values}

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
        return {"state": "registered", "fingerprint": desired_fp, "values": values}

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
        if not is_schedule_family and not (
            node_class and isinstance(node_class, type)
            and issubclass(node_class, ExternalWebhookTriggerMixin)
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
    async def resync_trigger_registrations(pool, limit: int = 500) -> Dict[str, int]:
        """Level-triggered backstop (rides daily_maintenance) — GRAPH-driven.

        Walks every live workflow whose saved graph contains a
        registration-capable trigger node (external-webhook mixin or
        app-event trigger op), PLUS workflows holding active registered
        ``webhooks`` rows or any ``webhook_subscriptions`` rows (catches
        orphans whose node left the graph), and reconciles each candidate
        node. Because desired state comes from the GRAPH, a registration
        that NEVER happened — a write surface that missed provisioning —
        is healed within a day, not just drift on rows that already exist
        (the pre-2026-07-30 row-driven sweep could never revive a
        builder-built Slack trigger that shipped unregistered).

        NULL-fingerprint rows are adopted (stamped), not rotated. The
        fingerprint / row-match fast paths make a full pass cheap. Bounded
        per run (``limit`` workflows, least-recently-updated first, overflow
        logged — never silently truncated); failures are counted and logged,
        never raised (one bad workflow must not stall the sweep)."""
        from nodes.core.registry import NODE_REGISTRY
        from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
        from nodes.core.webhook_subscriptions import AppEventTriggerMixin
        from nodes.core.schedule_registration import CronScheduleTriggerMixin

        registerable_types = sorted(
            t for t, c in NODE_REGISTRY.items()
            if isinstance(c, type)
            and issubclass(
                c,
                (
                    ExternalWebhookTriggerMixin,
                    AppEventTriggerMixin,
                    CronScheduleTriggerMixin,
                ),
            )
        )

        stats = {"workflows": 0, "checked": 0, "converged": 0, "adopted": 0, "failed": 0}
        async with pool.acquire() as conn:
            wf_rows = await conn.fetch(
                """
                WITH candidates AS (
                    SELECT wf.id, wf.updated_at
                    FROM workflows wf
                    WHERE wf.deleted_at IS NULL
                      AND jsonb_typeof(wf.workflow->'nodes') = 'array'
                      AND EXISTS (
                          SELECT 1
                          FROM jsonb_array_elements(wf.workflow->'nodes') AS n
                          WHERE n->>'type' = ANY($1::text[])
                      )
                    UNION
                    SELECT wf.id, wf.updated_at
                    FROM webhooks w
                    JOIN workflows wf ON wf.id = w.workflow_id
                    WHERE w.is_active AND w.registered_operation IS NOT NULL
                      AND wf.deleted_at IS NULL
                    UNION
                    SELECT wf.id, wf.updated_at
                    FROM webhook_subscriptions s
                    JOIN workflows wf ON wf.id = s.workflow_id
                    WHERE wf.deleted_at IS NULL
                )
                SELECT id FROM candidates c
                ORDER BY updated_at ASC
                LIMIT $2
                """,
                registerable_types,
                limit + 1,
            )
        if len(wf_rows) > limit:
            wf_rows = wf_rows[:limit]
            logger.warning(
                f"[WEBHOOK] Resync candidate set exceeds limit={limit} — "
                f"remainder picked up next run (least-recently-updated first)"
            )

        for wf_row in wf_rows:
            wf_id = wf_row["id"]
            try:
                owner_id, nodes = await _load_workflow_owner_and_nodes(pool, wf_id)
                if owner_id is None:
                    continue
                graph_candidates = {
                    n["id"]
                    for n in nodes
                    if n.get("id") and n.get("type") in registerable_types
                    and WebhookManager.operation_requires_registration(
                        n.get("type"), _extract_node_config(n).get("operation")
                    )
                }
                async with pool.acquire() as conn:
                    row_nodes = await conn.fetch(
                        "SELECT node_id FROM webhooks WHERE workflow_id = $1 "
                        "AND is_active AND registered_operation IS NOT NULL",
                        wf_id,
                    )
                    sub_nodes = await conn.fetch(
                        "SELECT DISTINCT node_id FROM webhook_subscriptions "
                        "WHERE workflow_id = $1",
                        wf_id,
                    )
                node_ids = graph_candidates | {r["node_id"] for r in row_nodes} | {
                    r["node_id"] for r in sub_nodes
                }
            except Exception:
                stats["failed"] += 1
                logger.warning(
                    f"[WEBHOOK] Resync candidate scan failed for {wf_id}",
                    exc_info=True,
                )
                continue
            if not node_ids:
                continue

            stats["workflows"] += 1
            for node_id in sorted(node_ids):
                stats["checked"] += 1
                try:
                    result = await WebhookManager.reconcile_node(
                        pool, str(wf_id), node_id
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
                    elif state == "failed":
                        stats["failed"] += 1
                except Exception:
                    stats["failed"] += 1
                    logger.warning(
                        f"[WEBHOOK] Resync reconcile failed for {wf_id}:{node_id}",
                        exc_info=True,
                    )
        return stats

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
        Deregister provider-side webhooks against the OLD credential's resource
        when a node's ``credentialIds`` change between saves, then self-heal by
        re-registering under the new credential.

        Without the teardown, swapping credentials on a trigger node leaves an
        active provider-side webhook attached to the previous credential's
        connection — the next event on the OLD connection still fans out to the
        orphan and produces duplicate runs (WhatsApp group-message incident,
        2026-06-25).

        Row semantics fix the swap race: if the config panel already
        re-registered under the NEW credential (row's registered_credential_id
        no longer matches any swapped-away id), the row is the live new
        registration and is left alone — only the old provider endpoint is torn
        down. Otherwise the row is deactivated and ``register_node_webhooks``
        re-registers it under the new credential (also covers headless swaps
        via MCP set_credentials, where no config panel will ever fire).

        Returns the number of credential entries that triggered a teardown.
        """
        old_creds = (old_config or {}).get("credentialIds") or {}
        new_creds = (new_config or {}).get("credentialIds") or {}

        removed_or_swapped: list[tuple[str, str]] = []
        for cred_type, old_cid in old_creds.items():
            if not old_cid:
                continue
            new_cid = new_creds.get(cred_type)
            if old_cid != new_cid:
                removed_or_swapped.append((cred_type, old_cid))

        if not removed_or_swapped:
            return 0

        from nodes.core.registry import NODE_REGISTRY

        if NODE_REGISTRY.get(node_type) is None:
            return 0

        logger.info(
            f"[WEBHOOK] Credential change on {node_type}:{node_id} "
            f"({[cid for _, cid in removed_or_swapped]}) — reconciling registration"
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
                f"[WEBHOOK] Post-credential-swap reconcile failed for "
                f"{node_type}:{node_id}: {e}"
            )
            return supplemental
        acted = supplemental or result.get("state") not in ("noop", "live", "no_workflow")
        return len(removed_or_swapped) if acted else 0

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
        from utils.webhook_tunnel import unregister_webhook

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
