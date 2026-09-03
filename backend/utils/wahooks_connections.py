"""WAHooks connection lifecycle — teardown + orphan reconciliation.

All NoClick users share ONE WAHooks account; each `whatsapp_qr` credential
owns exactly one connection (its id lives in the encrypted blob, and — since
2026-07 — in credential metadata). Deleting the credential must delete the
provider connection or we keep paying for it AND the user's personal WhatsApp
stays linked to our account after they believe it's disconnected.

Teardown failures were silent for months (the callers invoked a nonexistent
`encryption.decrypt`, ate the AttributeError, and deleted the DB row anyway),
so alongside the direct teardown there's a reconciliation sweep that deletes
any non-scannable connection no credential references. scan_qr connections
are the reusable idle pool get_or_create hands out — never swept — and
connections with an active QR reservation are mid-flow, so they're skipped.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


def get_wahooks_api_key() -> Optional[str]:
    return os.environ.get("WAHOOKS_API_KEY") or None


async def delete_wahooks_connection(connection_id: str) -> None:
    """Delete one connection at WAHooks. Raises on failure — callers decide
    whether their surrounding operation may proceed without the teardown."""
    api_key = get_wahooks_api_key()
    if not api_key:
        raise RuntimeError("WAHooks API key not configured")
    from wahooks import WAHooks

    def _delete():
        # wahooks ships only a sync httpx client; keep it off the event loop.
        with WAHooks(api_key=api_key) as client:
            client.delete_connection(connection_id)

    await asyncio.to_thread(_delete)
    logger.info(f"[WAHooks] Deleted connection {connection_id}")


async def migrate_wahooks_webhooks(old_connection_id: str, new_connection_id: str) -> int:
    """Re-create every webhook registered on ``old_connection_id`` on
    ``new_connection_id`` (same url + events; urls the new connection already
    serves are skipped). WAHooks webhooks are per-connection, so a credential
    rebind that deletes the replaced connection unregisters every trigger on
    it unless they are carried over first. Returns the count carried over;
    raises on failure — the caller decides whether teardown may proceed."""
    api_key = get_wahooks_api_key()
    if not api_key:
        raise RuntimeError("WAHooks API key not configured")
    from wahooks import WAHooks

    def _migrate() -> int:
        with WAHooks(api_key=api_key) as client:
            served = {w.get("url") for w in client.list_webhooks(new_connection_id)}
            moved = 0
            for hook in client.list_webhooks(old_connection_id):
                if not hook.get("url") or hook["url"] in served:
                    continue
                client.create_webhook(
                    new_connection_id, url=hook["url"], events=list(hook.get("events") or [])
                )
                moved += 1
            return moved

    moved = await asyncio.to_thread(_migrate)
    logger.info(
        f"[WAHooks] Migrated {moved} webhook(s) from {old_connection_id} to {new_connection_id}"
    )
    return moved


async def live_credential_connection_ids(pool) -> Set[str]:
    """connection_ids referenced by any whatsapp_qr credential. Metadata is
    the fast path; the encrypted blob is decrypted as the source of truth for
    rows minted before connection_id was stamped into metadata."""
    from utils.encryption import get_encryption

    encryption = get_encryption()
    ids: Set[str] = set()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT credential, metadata FROM credentials WHERE credential_type = 'whatsapp_qr'"
        )
    for row in rows:
        meta = row["metadata"] or {}
        if isinstance(meta, str):
            # Pools without the jsonb codec (e.g. the daily_maintenance pool)
            # return jsonb as its JSON text; without this parse the fast path
            # never fires and every blob gets decrypted each sweep.
            meta = json.loads(meta)
        if isinstance(meta, dict) and meta.get("connection_id"):
            ids.add(str(meta["connection_id"]))
            continue
        cred = encryption.decrypt_credential(row["credential"])
        if cred.get("connection_id"):
            ids.add(str(cred["connection_id"]))
    return ids


def pick_orphan_connections(
    connections: List[Dict[str, Any]], live_ids: Set[str]
) -> List[str]:
    """Pure selection: non-scannable connections no credential references.
    scan_qr is the reusable idle pool; everything else without an owner is
    an orphan (still linked to someone's phone, still billed to us)."""
    orphans = []
    for conn in connections:
        cid = conn.get("id")
        if not cid or str(cid) in live_ids:
            continue
        if conn.get("status") == "scan_qr":
            continue
        orphans.append(str(cid))
    return orphans


async def _has_active_reservation(connection_id: str) -> bool:
    """True when a QR flow is mid-scan on this connection (bind imminent)."""
    from utils.redis_client import get_shared_redis

    client = get_shared_redis()
    if client is None:
        return False
    try:
        return await client.get(f"whatsapp:qr:reserved:{connection_id}") is not None
    except Exception as e:
        # Unknown = assume reserved: one extra day of a possibly-orphaned
        # connection beats deleting one a user is about to bind.
        logger.warning(f"[WAHooks] Reservation check failed for {connection_id}: {e}")
        return True


async def backfill_credential_phone_numbers(pool) -> Dict[str, Any]:
    """Stamp ``metadata.phone_number`` on whatsapp_qr credentials missing it,
    from the WAHooks connection list. Finalize's same-phone rebind and the
    disconnect alert both key on it, but finalize often binds before WAHooks
    has resolved the phone. This daily job closes the gap so
    reconnect-not-remint engages for
    existing credentials too."""
    api_key = get_wahooks_api_key()
    if not api_key:
        return {"skipped": "no_api_key"}
    from wahooks import WAHooks

    def _list():
        with WAHooks(api_key=api_key) as client:
            return client.list_connections()

    phones = {
        str(c["id"]): str(c.get("phoneNumber") or c.get("phone_number") or "")
        for c in await asyncio.to_thread(_list)
        if c.get("id")
    }

    from utils.credentials import credential_metadata

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, metadata FROM credentials WHERE credential_type = 'whatsapp_qr'"
        )
    stamped = []
    for row in rows:
        meta = credential_metadata(row)
        if meta.get("phone_number"):
            continue
        phone = phones.get(str(meta.get("connection_id") or ""))
        if not phone:
            continue
        async with pool.acquire() as conn:
            # Metadata-only merge — never touches the encrypted blob (no CAS
            # concern) and builds the jsonb server-side so it works on pools
            # with or without the jsonb codec. The WHERE re-check keeps a
            # concurrent finalize-stamped phone authoritative.
            await conn.execute(
                """UPDATE credentials
                   SET metadata = COALESCE(metadata, '{}'::jsonb)
                       || jsonb_build_object('phone_number', $2::text)
                   WHERE id = $1 AND COALESCE(metadata->>'phone_number', '') = ''""",
                row["id"], phone,
            )
        stamped.append(str(row["id"]))
    summary = {"credentials": len(rows), "stamped": stamped}
    logger.info(f"[WAHooks] Phone-number backfill: {summary}")
    return summary
async def sweep_orphan_connections(pool) -> Dict[str, Any]:
    """Reconcile WAHooks connections against credentials; delete orphans.

    Returns a summary dict for the maintenance log. Raises only on the
    initial listing (nothing to reconcile against); per-connection delete
    failures are counted and retried by the next sweep.
    """
    api_key = get_wahooks_api_key()
    if not api_key:
        logger.info("[WAHooks] Sweep skipped: no API key configured")
        return {"skipped": "no_api_key"}
    from wahooks import WAHooks

    def _list():
        with WAHooks(api_key=api_key) as client:
            return client.list_connections()

    connections = await asyncio.to_thread(_list)
    live_ids = await live_credential_connection_ids(pool)
    orphans = pick_orphan_connections(connections, live_ids)

    deleted, failed, reserved = [], [], []
    for cid in orphans:
        if await _has_active_reservation(cid):
            reserved.append(cid)
            continue
        try:
            await delete_wahooks_connection(cid)
            deleted.append(cid)
        except Exception as e:
            logger.error(f"[WAHooks] Sweep failed to delete orphan {cid}: {e}")
            failed.append(cid)

    summary = {
        "connections": len(connections),
        "credentialed": len(live_ids),
        "deleted": deleted,
        "failed": failed,
        "skipped_reserved": reserved,
    }
    logger.info(f"[WAHooks] Orphan sweep: {summary}")
    return summary
