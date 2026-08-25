"""Persistence and renewal dispatch for expiring push-notification channels.

Google Drive/Calendar watch channels and Jira dynamic webhooks expire (hours to
30 days) and must be renewed before they lapse. Each trigger node's subscription
is tracked as a row in ``webhook_channels``; a scheduled renewal worker
scans for rows nearing expiry and calls :func:`renew_channel`, which
dispatches to the owning node's ``renew_watch_channel`` classmethod.

The receiver finds the trigger node by ``config.webhook_id`` as usual — this
table only adds the expiry metadata that plain webhook triggers don't need.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Stop renewing a channel after this many consecutive failures (a permanently
# broken credential, say) so the renewal job doesn't hammer the API forever.
# Re-saving the workflow resets the counter and revives the trigger.
_MAX_RENEWAL_ATTEMPTS = 20


def renew_after_for(expires_at: datetime) -> datetime:
    """Return when a channel should be renewed: the midpoint of its remaining
    life. This adapts to whatever TTL the provider grants — a short-lived
    channel is renewed proportionally sooner — instead of assuming a fixed
    safety window.
    """
    now = datetime.now(timezone.utc)
    if expires_at <= now:
        return now
    return now + (expires_at - now) / 2


async def save_watch_channel(
    pool,
    *,
    webhook_id: str,
    user_id: str,
    workflow_id: str,
    node_id: str,
    provider: str,
    credential_id: Optional[str],
    channel_id: str,
    resource_id: Optional[str],
    channel_token: str,
    expires_at,
    watched_resource: Optional[str] = None,
) -> None:
    """Upsert a watch-channel record, keyed by ``(workflow_id, node_id)``.

    Re-registration resets the renewal failure state, so re-saving a workflow
    revives a trigger whose channel had been given up on.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO webhook_channels (
                webhook_id, user_id, workflow_id, node_id, provider,
                credential_id, channel_id, resource_id, watched_resource,
                channel_token, expires_at, renew_after
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (workflow_id, node_id) DO UPDATE SET
                webhook_id = EXCLUDED.webhook_id,
                provider = EXCLUDED.provider,
                credential_id = EXCLUDED.credential_id,
                channel_id = EXCLUDED.channel_id,
                resource_id = EXCLUDED.resource_id,
                watched_resource = EXCLUDED.watched_resource,
                channel_token = EXCLUDED.channel_token,
                expires_at = EXCLUDED.expires_at,
                renew_after = EXCLUDED.renew_after,
                renewal_attempts = 0,
                last_renewal_error = NULL,
                claimed_at = NULL,
                updated_at = NOW()
            """,
            UUID(webhook_id) if isinstance(webhook_id, str) else webhook_id,
            UUID(user_id) if isinstance(user_id, str) else user_id,
            UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id,
            node_id,
            provider,
            UUID(credential_id) if isinstance(credential_id, str) else credential_id,
            channel_id,
            resource_id,
            watched_resource,
            channel_token,
            expires_at,
            renew_after_for(expires_at),
        )


async def get_watch_channel(
    pool, workflow_id: str, node_id: str
) -> Optional[Dict[str, Any]]:
    """Return the watch-channel row for a trigger node, or ``None``."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM webhook_channels WHERE workflow_id = $1 AND node_id = $2",
            UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id,
            node_id,
        )
        return dict(row) if row else None


async def delete_watch_channel(pool, workflow_id: str, node_id: str) -> None:
    """Delete a watch-channel record (the external channel must be stopped
    separately by the node's ``_unregister_external_webhook``)."""
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM webhook_channels WHERE workflow_id = $1 AND node_id = $2",
            UUID(workflow_id) if isinstance(workflow_id, str) else workflow_id,
            node_id,
        )


async def claim_due_channels(pool, limit: int = 100) -> List[Dict[str, Any]]:
    """Atomically claim a batch of channels due for renewal.

    Marks each returned row with ``claimed_at`` so overlapping renewal runs
    don't process the same channel twice (``FOR UPDATE SKIP LOCKED`` plus a
    15-minute claim staleness window). Channels that have failed renewal
    ``_MAX_RENEWAL_ATTEMPTS`` times are skipped — they need the workflow
    re-saved to recover.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            UPDATE webhook_channels SET claimed_at = NOW()
            WHERE id IN (
                SELECT id FROM webhook_channels
                WHERE renew_after < NOW()
                  AND renewal_attempts < $2
                  AND (claimed_at IS NULL OR claimed_at < NOW() - INTERVAL '15 minutes')
                ORDER BY renew_after
                LIMIT $1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """,
            limit,
            _MAX_RENEWAL_ATTEMPTS,
        )
        return [dict(r) for r in rows]


async def update_channel_subscription(
    pool, channel_row_id, *, channel_id: str, resource_id: Optional[str], expires_at
) -> None:
    """Update a channel row after a successful renewal, clearing failure state."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE webhook_channels
            SET channel_id = $2, resource_id = $3, expires_at = $4,
                renew_after = $5, last_renewed_at = NOW(),
                renewal_attempts = 0, last_renewal_error = NULL,
                claimed_at = NULL, updated_at = NOW()
            WHERE id = $1
            """,
            channel_row_id,
            channel_id,
            resource_id,
            expires_at,
            renew_after_for(expires_at),
        )


async def record_renewal_failure(
    pool, channel_row_id, error: str
) -> Optional[Dict[str, Any]]:
    """Record a failed renewal attempt; returns the updated attempt count."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE webhook_channels
            SET renewal_attempts = renewal_attempts + 1,
                last_renewal_error = $2,
                claimed_at = NULL,
                updated_at = NOW()
            WHERE id = $1
            RETURNING renewal_attempts, expires_at
            """,
            channel_row_id,
            error[:1000],
        )
        return dict(row) if row else None


# Maps a channel's provider to the node type whose `renew_watch_channel`
# classmethod knows how to re-subscribe it.
_PROVIDER_NODE_TYPES = {
    "google_drive": "automation-google-drive",
    "google_calendar": "automation-google-calendar",
    "jira": "automation-jira",
}


async def renew_channel(pool, channel_row: Dict[str, Any]) -> None:
    """Renew one channel by dispatching to its node class.

    A failed renewal is recorded on the row (attempt count + error) rather than
    raised, so the renewal job continues with the rest of the batch. An expired
    channel that keeps failing is escalated to an ERROR log.
    """
    from nodes.core.registry import NODE_REGISTRY

    provider = channel_row.get("provider")
    node_type = _PROVIDER_NODE_TYPES.get(provider)
    node_cls = NODE_REGISTRY.get(node_type) if node_type else None
    if node_cls is None or not hasattr(node_cls, "renew_watch_channel"):
        logger.warning(
            f"[watch_channels] No renewal handler for provider '{provider}'"
        )
        return

    # Tag credential refreshes that the renew_watch_channel implementation triggers
    # as 'trigger_renew' so the hourly cron path is distinguishable from
    # save-time 'trigger_register' in the oauth.refresh audit.
    from nodes.core.oauth_audit import caller_path_scope
    try:
        with caller_path_scope("trigger_renew"):
            await node_cls.renew_watch_channel(pool, channel_row)
    except Exception as e:
        result = await record_renewal_failure(pool, channel_row["id"], str(e))
        attempts = (result or {}).get("renewal_attempts", 0)
        expires_at = (result or {}).get("expires_at")
        now = datetime.now(timezone.utc)
        already_dead = expires_at is not None and expires_at <= now
        if attempts >= _MAX_RENEWAL_ATTEMPTS or already_dead:
            logger.error(
                f"[watch_channels] Channel {channel_row.get('id')} ({provider}) "
                f"renewal failed (attempt {attempts}, "
                f"{'channel expired' if already_dead else 'giving up soon'}): {e}"
            )
        else:
            logger.warning(
                f"[watch_channels] Channel {channel_row.get('id')} ({provider}) "
                f"renewal attempt {attempts} failed: {e}"
            )


class WatchChannelTriggerMixin:
    """Trigger-node mixin for expiring push-notification subscriptions.

    Like ``ExternalWebhookTriggerMixin`` it provisions the internal webhook URL
    and registers an external subscription, but it threads the extra context a
    watch channel needs (pool, workflow/user ids, webhook id, credential id) so
    the node can persist a ``webhook_channels`` row for the renewal job.

    Nodes implement three classmethods: ``_register_watch_channel``,
    ``_stop_watch_channel`` and ``renew_watch_channel``.
    """

    @classmethod
    async def _register_watch_channel(
        cls,
        *,
        pool,
        user_id: str,
        workflow_id: str,
        node_id: str,
        webhook_id: str,
        webhook_url: str,
        credential: Dict[str, Any],
        credential_id: Optional[str],
        config: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Create the external watch channel and persist a ``webhook_channels``
        row. Return a dict of values to merge into node config (e.g. the
        verification token, an initial cursor). Raise on failure."""
        raise NotImplementedError(
            f"{cls.__name__} must implement _register_watch_channel"
        )

    @classmethod
    async def _stop_watch_channel(
        cls,
        *,
        pool,
        workflow_id: str,
        node_id: str,
        credential: Optional[Dict[str, Any]],
        config: Dict[str, Any],
        channel_row: Dict[str, Any],
    ) -> None:
        """Stop the external watch channel (the row is deleted by the mixin)."""
        raise NotImplementedError(
            f"{cls.__name__} must implement _stop_watch_channel"
        )

    @classmethod
    async def _resolve_trigger_credential(cls, pool, user_id, credential_ids):
        """Return ``(credential_id, credential_dict)`` for the node's credential."""
        from utils.credential_loader import load_credential

        if not credential_ids:
            return None, None
        credential_id = next((cid for cid in credential_ids.values() if cid), None)
        credential = await load_credential(pool, user_id, credential_id)
        if credential is not None:
            # Refresh expiring OAuth tokens at load so watch-channel registration
            # never uses a stale token (no-op when the node doesn't override).
            from nodes.core.oauth_audit import caller_path_scope
            with caller_path_scope("trigger_register"):
                credential = await cls.freshen_credential(
                    credential, pool=pool, user_id=user_id, credential_id=credential_id
                )
        return credential_id, credential

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
        """Provision the internal webhook URL and register the watch channel."""
        if field_name != "webhook_url":
            return {"value": None}

        from utils.webhook_manager import WebhookManager

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool, user_id=user_id, workflow_id=workflow_id, node_id=node_id
        )
        values: Dict[str, Any] = {
            "webhook_id": webhook_data.get("webhook_id"),
            "webhook_url": webhook_data.get("webhook_url"),
            "relay_connected": webhook_data.get("relay_connected"),
            "is_production": webhook_data.get("is_production"),
        }

        credential_id, credential = await cls._resolve_trigger_credential(
            pool, user_id, credential_ids
        )
        if credential is None:
            values["trigger_registered"] = False
            values["trigger_error"] = "Connect credentials to activate this trigger"
            return {"values": values}

        try:
            extra = await cls._register_watch_channel(
                pool=pool,
                user_id=user_id,
                workflow_id=str(workflow_id),
                node_id=node_id,
                webhook_id=values["webhook_id"],
                webhook_url=values["webhook_url"],
                credential=credential,
                credential_id=credential_id,
                config=context or {},
            )
            values["trigger_registered"] = True
            values["trigger_error"] = None
            if extra:
                values.update(extra)
        except Exception as e:
            logger.error(
                f"[{cls.__name__}] Failed to register watch channel for "
                f"node {node_id}: {e}"
            )
            values["trigger_registered"] = False
            values["trigger_error"] = str(e)

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
        """Stop the watch channel and delete its row (provider-side teardown
        only — the webhooks row is owned by the WebhookManager choke point).
        A stop failure is non-fatal: expired channels are routine."""
        try:
            channel_row = await get_watch_channel(pool, str(workflow_id), node_id)
            if channel_row:
                await cls._stop_watch_channel(
                    pool=pool,
                    workflow_id=str(workflow_id),
                    node_id=node_id,
                    credential=credentials,
                    config=config or {},
                    channel_row=channel_row,
                )
        except Exception as e:
            logger.warning(
                f"[{cls.__name__}] Failed to stop watch channel for "
                f"node {node_id}: {e}"
            )

        await delete_watch_channel(pool, str(workflow_id), node_id)
