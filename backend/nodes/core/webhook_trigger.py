"""Shared plumbing for push (webhook) trigger nodes.

A webhook-trigger node fires its workflow when an external service POSTs to a
NoClick-minted webhook URL. Two pieces of per-node work recur for every such
integration:

  1. Provision the internal webhook URL and register it with the external
     service (so the service knows where to send events).
  2. Deregister it with the external service when the node is removed.

``ExternalWebhookTriggerMixin`` implements both — the generic ``load_field_value``
and ``cleanup_external_webhook`` flows — and delegates the provider-specific
HTTP calls to two hooks each node implements: ``_register_external_webhook`` and
``_unregister_external_webhook``.

Registration state lives on the WEBHOOKS ROW (see ``utils.webhook_manager``),
written synchronously via ``WebhookManager.persist_registration_state`` — the
idempotency guard here reads the row, so it works for every trigger node
regardless of which fields its Pydantic config model declares, and detects
operation/credential changes server-side. The node config only mirrors the
values for display (and as the pre-row-era legacy source, adopted into the row
once via the backfill below).

Usage::

    class TypeformNode(ExternalWebhookTriggerMixin, WorkflowNode):
        @classmethod
        async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
            ...  # call the provider's "create webhook" API
            return {"signing_secret": ...}

        @classmethod
        async def _unregister_external_webhook(cls, *, credential, config, node_id):
            ...  # call the provider's "delete webhook" API
"""

import logging
from typing import Any, Dict, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from utils.credential_loader import load_credential

logger = logging.getLogger(__name__)


class WebhookTriggerConfigBase(BaseModel):
    """Shared hidden config fields for every external-webhook trigger node.

    Inherit a trigger's config model from this so the webhook lifecycle fields
    PERSIST (round-trip through Pydantic validation, which drops undeclared
    keys). These are display mirrors — the webhooks row is the system of record
    for registration state — but the mirrors keep the FE and delivery fallbacks
    working without extra reads.

    Contains ONLY the hidden, never-rendered lifecycle fields — deliberately NOT
    the visible ``webhook_url`` field. That keeps the visible config (webhook_url
    + any node-specific fields like team_id/domain) declared on the node itself,
    so inheriting this base never reorders or alters a node's rendered UI; it only
    adds hidden state. ``x-requires-webhook`` is declared here so subclasses don't
    repeat it; Pydantic merges ConfigDict across the MRO, so a subclass adding its
    own model_config keeps the marker.

    ``external_webhook_id`` accepts int (GitHub/Shopify) or str provider ids.
    Subscription-style triggers (Slack/HubSpot/Discord events) don't register a
    per-node external webhook and should not use this base at all.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[Union[str, int]] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class ExternalWebhookTriggerMixin:
    """Mixin providing webhook provisioning + registration for trigger nodes.

    Mix in *before* ``WorkflowNode`` so its ``cleanup_external_webhook`` and
    ``load_field_value`` take precedence in the MRO.
    """

    @classmethod
    async def _register_external_webhook(
        cls,
        *,
        webhook_url: str,
        credential: Dict[str, Any],
        config: Dict[str, Any],
        node_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Register *webhook_url* with the external service.

        Called once the internal webhook URL is provisioned and a credential is
        available. Return a dict of extra values to persist into node config
        (e.g. an external webhook id), or ``None``. Raise on failure — the
        mixin converts the exception into a ``trigger_error`` shown to the user.
        """
        raise NotImplementedError(
            f"{cls.__name__} must implement _register_external_webhook"
        )

    @classmethod
    async def _unregister_external_webhook(
        cls,
        *,
        credential: Optional[Dict[str, Any]],
        config: Dict[str, Any],
        node_id: str,
    ) -> None:
        """Deregister this node's webhook from the external service."""
        raise NotImplementedError(
            f"{cls.__name__} must implement _unregister_external_webhook"
        )

    @classmethod
    def registration_fingerprint_fields(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Config fields (beyond operation + credential) the provider-side
        registration DEPENDS on — they feed the registration fingerprint the
        reconciler compares to decide live vs re-register. Override when a
        user-editable field changes WHAT gets registered (GitHub's
        ``repository``, PostHog's ``event_name``); default: nothing extra.
        Declarative only — a node never sequences teardown/re-register."""
        return {}

    @classmethod
    def webhook_registration_stale(
        cls, config: Dict[str, Any], webhook_data: Dict[str, Any]
    ) -> bool:
        """Return True when the existing registration no longer matches the
        node's config and must be redone.

        The row guard in ``load_field_value`` only detects operation/credential
        changes — override this when the provider-side registration ALSO depends
        on a user-editable config field (e.g. PostHog's ``event_name``), typically
        by comparing the field against a mirror the node returned from
        ``_register_external_webhook``. Default: registration never goes stale
        from config edits.
        """
        return False

    @classmethod
    async def _resolve_trigger_credential(
        cls, pool, user_id: str, credential_ids: Optional[Dict[str, str]]
    ) -> Optional[Dict[str, Any]]:
        """Resolve the single credential configured on a trigger node.

        Trigger nodes carry exactly one auth credential; pick whichever id is
        present in the ``credential_ids`` map and decrypt it.
        """
        from utils.credentials import pick_credential_id

        credential_id = pick_credential_id(credential_ids or {})
        if not credential_id:
            return None
        credential = await load_credential(pool, user_id, credential_id)
        if credential is not None:
            # Refresh expiring OAuth tokens at load so external-webhook
            # registration never uses a stale token (no-op when the node
            # doesn't override freshen_credential).
            from nodes.core.oauth_audit import caller_path_scope
            with caller_path_scope("trigger_register"):
                credential = await cls.freshen_credential(
                    credential, pool=pool, user_id=user_id, credential_id=credential_id
                )
        return credential

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provision the internal webhook URL and register it externally.

        Triggered when the trigger node's config UI loads the ``webhook_url``
        field (``ui:widget="webhook"``, ``ui:loadValue=True``).
        """
        if field_name != "webhook_url":
            return {"value": None}

        from utils.credentials import pick_credential_id
        from utils.webhook_manager import WebhookManager

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )
        values: Dict[str, Any] = {
            "webhook_id": webhook_data.get("webhook_id"),
            "webhook_url": webhook_data.get("webhook_url"),
            "relay_connected": webhook_data.get("relay_connected"),
            "is_production": webhook_data.get("is_production"),
        }

        credential_id = pick_credential_id(credential_ids or {})
        credential = await cls._resolve_trigger_credential(
            pool, user_id, credential_ids
        )
        if credential is None:
            values["trigger_registered"] = False
            values["trigger_error"] = "Connect credentials to activate this trigger"
            return {"values": values}

        ctx = context or {}
        current_op = ctx.get("operation")
        # Some providers (e.g. Asana) deliver the signing secret asynchronously
        # via a separate handshake request, not as part of the registration
        # response — ``webhook_signing_secret_is_async`` signals it's stored
        # later. Others (PostHog, Tableau) never issue one at all (the
        # unguessable webhook URL is the capability) — ``webhook_signing_
        # secret_not_issued``. Either way the guards must not require a secret:
        # demanding one from a secret-less provider makes the idempotency guard
        # NEVER hold, so every config-panel open re-registers a fresh provider
        # endpoint and orphans the previous one.
        secret_required = not (
            getattr(cls, "webhook_signing_secret_is_async", False)
            or getattr(cls, "webhook_signing_secret_not_issued", False)
        )
        # A config carrying a DIFFERENT url than the row derives (legacy url
        # format, or a config restored against a re-minted row) is stale — its
        # registration points elsewhere and must be redone.
        url_changed = bool(ctx.get("webhook_url")) and ctx.get("webhook_url") != values["webhook_url"]

        from utils.webhook_manager import registration_fingerprint

        desired_fp = registration_fingerprint(cls, current_op, credential_id, ctx)

        # Idempotency guard — reads the ROW, not the config, so it holds for
        # every trigger node and breaks on operation/credential changes.
        # Re-registering on every config open would race the workflow save:
        # the new signing_secret reaches the frontend before the debounced
        # autosave lands, and a re-register also rotates the provider secret.
        # The fingerprint (op + credential + node-declared fields) is the
        # canonical "live" definition shared with the reconciler; pre-migration
        # rows (NULL fingerprint) fall back to the field-equality checks.
        row_fp = webhook_data.get("registered_fingerprint")
        row_registered = (
            webhook_data.get("is_active")
            and webhook_data.get("registered_operation") is not None
            and webhook_data.get("registered_operation") == current_op
            and (webhook_data.get("registered_credential_id") or None) == (credential_id or None)
            and (row_fp is None or row_fp == desired_fp)
            and (webhook_data.get("secret_set") or not secret_required)
            and not url_changed
            and not cls.webhook_registration_stale(ctx, webhook_data)
        )
        if row_registered:
            values["trigger_registered"] = True
            values["trigger_error"] = None
            values["signing_secret"] = ctx.get("signing_secret")
            # Mirror the row's id when the autosave never landed it in config.
            values["external_webhook_id"] = (
                ctx.get("external_webhook_id") or webhook_data.get("external_webhook_id")
            )
            return {"values": values}

        # Legacy backfill: the row predates registration state but the config
        # claims a live registration (pre-row-era). Adopt it into the row once
        # instead of re-registering (which would needlessly rotate the provider
        # secret for every pre-existing trigger).
        legacy_registered = (
            webhook_data.get("is_active")
            and webhook_data.get("registered_operation") is None
            and ctx.get("trigger_registered") is True
            and (ctx.get("signing_secret") or not secret_required)
            and ctx.get("external_webhook_id")
            and not url_changed
        )
        if legacy_registered:
            try:
                await WebhookManager.persist_registration_state(
                    pool, values["webhook_id"],
                    signing_secret=ctx.get("signing_secret"),
                    external_webhook_id=ctx.get("external_webhook_id"),
                    registered_operation=current_op,
                    registered_credential_id=credential_id,
                    registered_fingerprint=desired_fp,
                )
            except Exception as db_exc:
                # Config remains the operative source for this legacy node; the
                # backfill retries on the next panel open.
                logger.warning(
                    f"[{cls.__name__}] Legacy registration backfill failed for "
                    f"{node_id}: {db_exc}"
                )
            values["trigger_registered"] = True
            values["trigger_error"] = None
            values["signing_secret"] = ctx.get("signing_secret")
            values["external_webhook_id"] = ctx.get("external_webhook_id")
            return {"values": values}

        extra: Optional[Dict[str, Any]] = None
        try:
            # The row's external_webhook_id is written synchronously at
            # registration, so it's at least as fresh as the config mirror
            # (which lags behind the debounced autosave) — merge it into the
            # ctx so stale-endpoint replacement can find the previous provider
            # endpoint instead of minting a duplicate.
            register_ctx = dict(ctx)
            if not register_ctx.get("external_webhook_id") and webhook_data.get("external_webhook_id"):
                register_ctx["external_webhook_id"] = webhook_data.get("external_webhook_id")
            # Opt-in lifecycle behavior (webhook_replace_stale_endpoint): a
            # re-registration (operation/credential/fingerprint change) REPLACES
            # the previous provider endpoint via the node's own unregister hook,
            # so every re-register is create-after-delete rather than a leak.
            # The config mirror and the row can point at DIFFERENT stale
            # endpoints (a headless re-register raced by a panel edit before the
            # autosave landed) — tear down every distinct candidate, or the one
            # not chosen leaks provider-side. Best-effort: an already-gone
            # endpoint is convergence, and registration proceeds regardless.
            if getattr(cls, "webhook_replace_stale_endpoint", False):
                stale_ids = {ctx.get("external_webhook_id"), webhook_data.get("external_webhook_id")}
                stale_ids.discard(None)
                stale_ids.discard("")
                for stale_id in stale_ids:
                    try:
                        await cls._unregister_external_webhook(
                            credential=credential,
                            config={**register_ctx, "external_webhook_id": stale_id},
                            node_id=node_id,
                        )
                    except Exception as drop_exc:
                        logger.warning(
                            f"[{cls.__name__}] Stale-endpoint teardown ({stale_id}) before "
                            f"re-register failed for {node_id}: {drop_exc}"
                        )
            extra = await cls._register_external_webhook(
                webhook_url=values["webhook_url"],
                credential=credential,
                config=register_ctx,
                node_id=node_id,
            )
            # Persist to the row FIRST — verification and deregistration read
            # it, and it's what activates the row. A failure here is a real
            # failure (handled below), never a silent warning.
            await WebhookManager.persist_registration_state(
                pool, values["webhook_id"],
                signing_secret=(extra or {}).get("signing_secret"),
                external_webhook_id=(extra or {}).get("external_webhook_id"),
                registered_operation=current_op,
                registered_credential_id=credential_id,
                registered_fingerprint=desired_fp,
            )
            values["trigger_registered"] = True
            values["trigger_error"] = None
            if extra:
                values.update(extra)
        except Exception as e:
            logger.error(
                f"[{cls.__name__}] Failed to register external webhook for "
                f"node {node_id}: {e}"
            )
            values["trigger_registered"] = False
            values["trigger_error"] = str(e)
            if extra:
                # Registration succeeded but the persist failed: keep the
                # provider's ids in config so the retry's stale-endpoint drop
                # can find (and replace) this endpoint instead of orphaning it.
                values.update(extra)

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
        """Provider-side teardown ONLY — deregister the external webhook.

        The webhooks row is owned by the caller
        (``WebhookManager.deregister_node_webhooks`` deactivates or deletes
        it based on the surface); raising here tells it the endpoint may still
        be live so the row keeps that record.
        """
        await cls._unregister_external_webhook(
            credential=credentials,
            config=config or {},
            node_id=node_id,
        )
