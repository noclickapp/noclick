"""App-level event subscriptions and fan-out for Slack / HubSpot triggers.

Slack and HubSpot deliver every event for the whole NoClick app to one
app-level URL, tagged with a tenant id (Slack ``team_id`` / HubSpot
``portalId``). A per-workflow webhook URL therefore can't be used — instead each
trigger node records rows in ``webhook_subscriptions`` keyed by
``(provider, tenant_id, event_type)``, and the app-level receiver fans a single
inbound event out to every workflow that subscribed to it.

``AppEventTriggerMixin`` owns the registration/teardown; the receiver route
calls :func:`find_subscriptions` to do the fan-out lookup.
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


def _as_uuid(value):
    return UUID(value) if isinstance(value, str) else value


async def save_subscriptions(
    pool,
    *,
    provider: str,
    tenant_id: str,
    user_id: str,
    workflow_id: str,
    node_id: str,
    credential_id: Optional[str],
    event_types: List[str],
    verification_key: Optional[str] = None,
) -> None:
    """Replace a trigger node's subscriptions with one row per event type."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM webhook_subscriptions WHERE workflow_id = $1 AND node_id = $2",
                _as_uuid(workflow_id),
                node_id,
            )
            for event_type in event_types:
                await conn.execute(
                    """
                    INSERT INTO webhook_subscriptions (
                        provider, tenant_id, event_type, user_id,
                        workflow_id, node_id, credential_id, verification_key
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    provider,
                    tenant_id,
                    event_type,
                    _as_uuid(user_id),
                    _as_uuid(workflow_id),
                    node_id,
                    _as_uuid(credential_id) if credential_id else None,
                    verification_key,
                )


async def find_subscriptions(
    pool, provider: str, tenant_id: str, event_type: str
) -> List[Dict[str, Any]]:
    """Return every subscription matching an inbound event (the fan-out lookup).

    Per-subscription event filtering (e.g. channel scoping) is applied later, at
    fire time, against the trigger node's live config — see ``_fire_subscription``.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM webhook_subscriptions
            WHERE provider = $1 AND tenant_id = $2 AND event_type = $3
            """,
            provider,
            tenant_id,
            event_type,
        )
        return [dict(r) for r in rows]


async def delete_subscriptions(pool, workflow_id: str, node_id: str) -> None:
    """Delete all subscriptions for a trigger node."""
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM webhook_subscriptions WHERE workflow_id = $1 AND node_id = $2",
            _as_uuid(workflow_id),
            node_id,
        )


async def get_node_subscriptions(
    pool, workflow_id: str, node_id: str
) -> List[Dict[str, Any]]:
    """Return every subscription row owned by a trigger node."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM webhook_subscriptions
            WHERE workflow_id = $1 AND node_id = $2
            """,
            _as_uuid(workflow_id),
            node_id,
        )
        return [dict(r) for r in rows]


async def list_subscriptions_for_tenant(
    pool, provider: str, tenant_id: str
) -> List[Dict[str, Any]]:
    """Return every subscription row for one provider tenant/account."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM webhook_subscriptions
            WHERE provider = $1 AND tenant_id = $2
            """,
            provider,
            tenant_id,
        )
        return [dict(r) for r in rows]


async def get_verification_key(
    pool, provider: str, tenant_id: str
) -> Optional[str]:
    """Return the provider verification key stored for one tenant/account."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT verification_key
            FROM webhook_subscriptions
            WHERE provider = $1 AND tenant_id = $2
              AND verification_key IS NOT NULL
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            provider,
            tenant_id,
        )
        return row["verification_key"] if row else None


def subscription_rows_match(
    rows: List[Dict[str, Any]],
    *,
    event_types: List[str],
    credential_id: Optional[str],
    user_id: str,
    tenant_id: Optional[str] = None,
) -> bool:
    """Whether a node's existing subscription rows already ARE the desired
    registration (the level-triggered no-op fast path). ``tenant_id=None``
    skips the tenant compare — callers without a resolved credential rely on
    the credential_id compare instead (a credential is bound to one tenant)."""
    if not rows or {r["event_type"] for r in rows} != set(event_types):
        return False
    for r in rows:
        if (str(r["credential_id"]) if r["credential_id"] else None) != (
            str(credential_id) if credential_id else None
        ):
            return False
        if str(r["user_id"]) != str(user_id):
            return False
        if tenant_id is not None and str(r["tenant_id"]) != str(tenant_id):
            return False
    return True


class AppEventTriggerMixin:
    """Trigger-node mixin for app-level fan-out triggers (Slack, HubSpot,
    Discord).

    The node has no per-workflow webhook URL — events arrive at a shared
    app-level route. The mixin registers ``webhook_subscriptions`` rows keyed by
    the connected account's tenant id and the chosen event types.

    Nodes set the ``_app_provider`` class attribute, the ``_trigger_event_map``
    (operation -> provider event types), and implement ``_resolve_tenant_id``.
    Each per-event trigger op maps to its event type(s); the user picks the
    specific trigger rather than a generic event field.

    ``register_node_subscriptions`` is THE registration core — the config
    panel's ``load_field_value``, headless provisioning
    (``WebhookManager.provision_node_webhook``), and the registration
    reconciler all converge on it. Nodes needing provider-side work (Discord's
    event-webhook union) override the core, never ``load_field_value``.
    """

    _app_provider: Optional[str] = None
    # operation literal -> the provider event types it subscribes to
    _trigger_event_map: Dict[str, List[str]] = {}
    # Panel / provisioning message when no credential is attached yet.
    _credential_prompt: str = "Connect a credential to activate this trigger"

    @classmethod
    async def _resolve_tenant_id(cls, credential: Dict[str, Any]) -> Optional[str]:
        """Return the connected account's tenant id (Slack team_id / HubSpot
        portalId), looking it up via the provider API if not on the credential."""
        raise NotImplementedError(
            f"{cls.__name__} must implement _resolve_tenant_id"
        )

    @classmethod
    def _pick_trigger_credential_id(
        cls, credential_ids: Optional[Dict[str, str]]
    ) -> Optional[str]:
        """The credential id a registration binds to (trigger nodes carry
        one). The reconciler's row-match fast path MUST pick with the same
        rule registration does, or the two disagree and every reconcile
        churns the rows."""
        return next((cid for cid in (credential_ids or {}).values() if cid), None)

    @classmethod
    async def _resolve_trigger_credential(cls, pool, user_id, credential_ids):
        """Return ``(credential_id, credential_dict)`` for the node's credential."""
        from utils.credential_loader import load_credential

        credential_id = cls._pick_trigger_credential_id(credential_ids)
        if not credential_id:
            return None, None
        credential = await load_credential(pool, user_id, credential_id)
        if credential is not None:
            # Refresh expiring OAuth tokens at load so tenant resolution /
            # subscription calls never use a stale token.
            from nodes.core.oauth_audit import caller_path_scope
            with caller_path_scope("trigger_register"):
                credential = await cls.freshen_credential(
                    credential, pool=pool, user_id=user_id, credential_id=credential_id
                )
        return credential_id, credential

    @classmethod
    def _subscription_status_line(
        cls, event_types: List[str], config: Optional[Dict[str, Any]]
    ) -> str:
        """Human status shown on the panel's Status field after registration.

        A channel-scoped trigger config carries a ``channel`` field; the
        actual filtering happens at fire time against the live config."""
        channel = (config or {}).get("channel")
        scope = "in the selected channel" if channel else "across all channels"
        return f"Active — listening {scope}"

    @classmethod
    async def register_node_subscriptions(
        cls,
        pool,
        *,
        user_id: str,
        workflow_id,
        node_id: str,
        operation: Optional[str],
        credential_id: Optional[str],
        credential: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create/replace the node's subscription rows for ``operation`` and
        return the human status line. Raises on failure — callers own the
        envelope (panel ``_fail`` / reconciler ``failed`` state).

        ``user_id`` is the identity the trigger FIRES as (the workflow owner —
        it lands in the row and drives execution + billing on fan-out).
        Idempotent: rows already matching the desired registration are left
        untouched, so panel re-opens and sweep passes never churn the table.
        """
        event_types = cls._trigger_event_map.get(operation or "", [])
        if not event_types:
            raise ValueError(f"Unknown trigger operation: {operation}")
        tenant_id = await cls._resolve_tenant_id(credential)
        if not tenant_id:
            raise ValueError("Could not determine the connected account")

        existing = await get_node_subscriptions(pool, str(workflow_id), node_id)
        if not subscription_rows_match(
            existing,
            event_types=event_types,
            credential_id=credential_id,
            user_id=user_id,
            tenant_id=str(tenant_id),
        ):
            await save_subscriptions(
                pool,
                provider=cls._app_provider,
                tenant_id=str(tenant_id),
                user_id=user_id,
                workflow_id=str(workflow_id),
                node_id=node_id,
                credential_id=credential_id,
                event_types=event_types,
            )
        return cls._subscription_status_line(event_types, config)

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
        """Register the node's event subscriptions when its config UI loads
        (also invoked headlessly by ``WebhookManager.provision_node_webhook``
        for builder/MCP write paths — same panel-equivalent contract)."""
        if field_name != "subscription_status":
            return {"value": None}

        values: Dict[str, Any] = {}

        def _fail(message: str) -> Dict[str, Any]:
            """Surface a registration failure on the visible status field so the
            user sees why instead of a silently empty field."""
            values["trigger_registered"] = False
            values["trigger_error"] = message
            values["subscription_status"] = f"⚠ {message}"
            return {"values": values}

        credential_id, credential = await cls._resolve_trigger_credential(
            pool, user_id, credential_ids
        )
        if credential is None:
            return _fail(cls._credential_prompt)

        try:
            # Rows are stamped with the workflow OWNER — the identity the
            # trigger fires (and bills) as — regardless of which session
            # (collaborator, MCP caller) performed the registration.
            from utils.webhook_manager import _load_workflow_owner_and_nodes

            owner_id, _ = await _load_workflow_owner_and_nodes(
                pool, _as_uuid(str(workflow_id)), include_nodes=False
            )
            if owner_id is None:
                raise ValueError("Workflow not found")
            status = await cls.register_node_subscriptions(
                pool,
                user_id=owner_id,
                workflow_id=workflow_id,
                node_id=node_id,
                operation=(context or {}).get("operation"),
                credential_id=credential_id,
                credential=credential,
                config=context,
            )
        except Exception as e:
            logger.error(
                f"[{cls.__name__}] Failed to register subscriptions for "
                f"node {node_id}: {e}"
            )
            return _fail(f"Not registered: {e}")

        values["trigger_registered"] = True
        values["trigger_error"] = None
        values["subscription_status"] = status
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
        """Delete the node's event subscriptions."""
        await delete_subscriptions(pool, str(workflow_id), node_id)
