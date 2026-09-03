"""
User-agnostic WhatsApp QR connection core (WAHooks).

The single implementation of "start a scannable connection" and "finalize a
scanned connection into a credential", callable with an explicit ``owner_id``.
Both surfaces bind to that owner and share this one audited copy:
  - the authenticated socket handler (owner = the signed-in user), and
  - the public credential-provide link (owner = the requester who wants it).

Bind safety is required because idle provider connections may be reused, so
concurrent flows must never receive or bind the same connection. It is enforced
identically for both surfaces:
1. A Redis reservation binds the connection_id to ``owner_id``; ``finalize``
   refuses to bind it for anyone else (a conflicting start mints a fresh one).
2. ``credentials.metadata->>'connection_id'`` + a partial unique index make
   double-binding impossible even if the reservation is unavailable.
3. ``start`` never shows the QR of a connection another owner's credential
   already binds. A recycled session retains its credential binding and webhook
   registrations, and provider-side device linking happens at scan time, so a
   finalize-only ownership check is too late.
"""

import asyncio
import logging
import os
import time
from typing import Any, Iterable, Optional

import asyncpg

from utils.redis_client import get_shared_redis

logger = logging.getLogger(__name__)

# Generously covers display → scan → status poll; a stale reservation must
# expire so an abandoned idle connection can be handed out again.
QR_RESERVATION_TTL_S = 15 * 60


# Status enrichment for credential lists: one WAHooks list call covers the
# provider sessions visible to this installation; cache it briefly.
_STATUS_CACHE_TTL_S = 60
_status_cache: Optional[tuple[float, dict[str, str]]] = None


async def get_connection_statuses(
    require: Optional[Iterable[str]] = None,
) -> Optional[dict[str, str]]:
    """connection_id → WAHooks session status ('connected', 'scan_qr',
    'pending', 'failed', 'stopped') for the installation. None = unknown
    (WAHooks unreachable/misconfigured) — callers must treat unknown as
    healthy, never dead (non-definitive-signal doctrine).

    ``require``: the connection ids the caller is about to judge. A cached
    map lacking any of them is a cache MISS, not "gone": every scan mints a
    connection the cache predates, and serving that map would flag a just-
    connected credential "(disconnected)" for up to a minute. Absence from a
    FRESH list is the only definitive "gone"."""
    global _status_cache
    now = time.monotonic()
    if _status_cache and now - _status_cache[0] < _STATUS_CACHE_TTL_S:
        cached = _status_cache[1]
        if all(cid in cached for cid in (require or ())):
            return cached
    try:
        api_key = get_wahooks_api_key()
    except ValueError:
        return None

    from wahooks import WAHooks

    def _list_connections():
        with WAHooks(api_key=api_key) as client:
            return client.list_connections()

    try:
        connections = await asyncio.wait_for(asyncio.to_thread(_list_connections), timeout=5)
    except Exception as e:
        logger.warning(f"[WhatsAppQR] Connection status fetch failed: {e}")
        return None
    statuses = {c["id"]: c.get("status", "") for c in connections if c.get("id")}
    _status_cache = (now, statuses)
    return statuses


def remember_connection_status(connection_id: str, status: str) -> None:
    """Stamp a status observed first-hand (finalize just saw ``connected``)
    into the live cache so the next picker list agrees without a refetch."""
    if _status_cache:
        _status_cache[1][connection_id] = status


def get_wahooks_api_key() -> str:
    """Get the server-side WAHooks API key from environment."""
    key = os.environ.get("WAHOOKS_API_KEY")
    if not key:
        raise ValueError("WAHooks API key not configured")
    return key


async def dead_session_status(connection_id: str) -> Optional[str]:
    """The definitively-dead session status for one connection, or None when
    connected/unknown. Unknown (WAHooks unreachable) is NEVER dead — the
    non-definitive-signal doctrine every consumer of this rule must share."""
    statuses = await get_connection_statuses(require=(connection_id,))
    if statuses is None:
        return None
    status = statuses.get(connection_id, "missing")
    return None if status == "connected" else status


def _poll_qr(client, connection_id: str, qr: str = "", attempts: int = 5) -> str:
    """Blocking QR poll (thread-pool): a just-created/reset session boots its
    QR within seconds; transient fetch errors count as a spent attempt."""
    from wahooks import WAHooksError

    for _ in range(attempts):
        if qr or not connection_id:
            break
        time.sleep(2)
        try:
            qr = client.get_qr(connection_id).get("qr", "")
        except WAHooksError:
            continue
    return qr


async def _reconnect_qr(
    pool, api_key: str, owner_id: str, credential_id: str
) -> Optional[dict[str, Any]]:
    """QR for re-scanning INTO an existing credential's own connection, or
    None to fall through to a fresh scan (finalize's same-phone rebind then
    repairs the credential in place). WAHooks resets a failed/stopped session
    on QR fetch, so the scan relinks the same session and finalize resolves it
    as the idempotent own-binding success — credential id and webhooks survive untouched."""
    from wahooks import WAHooks, WAHooksError
    from utils.credentials import credential_metadata

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT metadata FROM credentials
               WHERE id = $1::uuid AND owner_id = $2::uuid
                 AND credential_type = 'whatsapp_qr'""",
            credential_id, owner_id,
        )
    own_conn_id = credential_metadata(row).get("connection_id") if row else None
    if not own_conn_id or not await _try_reserve_connection(own_conn_id, owner_id):
        return None

    def _get_own_qr():
        with WAHooks(api_key=api_key) as client:
            try:
                qr = client.get_qr(own_conn_id).get("qr", "")
            except WAHooksError:
                return ""  # connection gone at WAHooks — fall back now, don't poll
            return _poll_qr(client, own_conn_id, qr)

    qr_value = await asyncio.to_thread(_get_own_qr)
    if not qr_value:
        logger.warning(
            f"[WhatsAppQR] Reconnect via connection {own_conn_id} yielded no QR — "
            f"falling back to a fresh scan (finalize rebinds by phone)"
        )
        return None
    logger.info(
        f"[WhatsAppQR] Reconnect QR ready for credential {credential_id} "
        f"(connection {own_conn_id})"
    )
    return {
        "success": True,
        "connection_id": own_conn_id,
        "qr_code": qr_value,
        "reconnect": True,
        "message": "Scan this QR code to reconnect your WhatsApp.",
    }


def _reservation_key(connection_id: str) -> str:
    return f"whatsapp:qr:reserved:{connection_id}"


async def _try_reserve_connection(connection_id: str, owner_id: str) -> bool:
    """Claim the connection for this owner. False = held by ANOTHER owner.

    Redis being unavailable allows the claim (loudly): the reservation is the
    UX-level guard; the metadata unique index is the hard one.
    """
    client = get_shared_redis()
    if client is None:
        logger.warning("[WhatsAppQR] Redis unavailable — QR reservation skipped")
        return True
    key = _reservation_key(connection_id)
    try:
        if await client.set(key, owner_id, ex=QR_RESERVATION_TTL_S, nx=True):
            return True
        holder = await client.get(key)
        if holder is not None and holder.decode() != owner_id:
            return False
        # Same owner restarting the flow — refresh the window.
        await client.set(key, owner_id, ex=QR_RESERVATION_TTL_S)
        return True
    except Exception as e:
        logger.warning(f"[WhatsAppQR] Reservation write failed for {connection_id}: {e}")
        return True


async def _reservation_status(connection_id: str, owner_id: str) -> str:
    """'held' | 'expired' | 'other' | 'unavailable' for the bind-time check.

    'expired' is rejected (a vanished key can mean another flow's stale polling
    loop could otherwise claim a freshly scanned phone); 'unavailable' (Redis
    down) proceeds — the unique index still blocks double-binding.
    """
    client = get_shared_redis()
    if client is None:
        return "unavailable"
    try:
        holder = await client.get(_reservation_key(connection_id))
    except Exception as e:
        logger.warning(f"[WhatsAppQR] Reservation read failed for {connection_id}: {e}")
        return "unavailable"
    if holder is None:
        return "expired"
    return "held" if holder.decode() == owner_id else "other"


async def _bound_to_other_owner(pool, connection_id: str, owner_id: str) -> bool:
    """True if an existing credential binds this connection to ANOTHER owner.

    The owner's OWN binding stays reusable: re-scanning relinks their existing
    credential (finalize resolves it as idempotent success)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT owner_id FROM credentials
               WHERE credential_type = 'whatsapp_qr'
                 AND metadata->>'connection_id' = $1""",
            connection_id,
        )
    return row is not None and not is_own_binding(row["owner_id"], owner_id)


def is_own_binding(existing_owner_id, owner_id) -> bool:
    """Duplicate finalize of the owner's OWN bound connection is idempotent
    success (double poll / retry after the first bind won); a connection bound
    to another owner is a real conflict."""
    return str(existing_owner_id) == str(owner_id)


async def start_qr_connection(
    pool, owner_id: str, reconnect_credential_id: Optional[str] = None
) -> dict[str, Any]:
    """Create (or reuse) a scannable WAHooks connection bound to ``owner_id``.

    ``reconnect_credential_id``: re-scan into that credential's EXISTING
    connection instead of minting a new one — WAHooks resets a failed/stopped
    session to scan_qr on QR fetch, the scan relinks the same session, and
    finalize resolves it as the idempotent own-binding success, so the
    credential id (and its webhooks, workflows) survives untouched. Minting a
    fresh connection during reconnect can create duplicate credentials and
    device links, so reconnect must reuse the existing binding.
    If the old connection is gone at WAHooks, falls through to a fresh scan —
    finalize's same-phone rebind then repairs the credential in place.

    Returns ``{success, connection_id?, qr_code?, message, reconnect?}``.
    Never raises for the expected WAHooks/config failure modes — callers map
    ``success`` to their own transport response.
    """
    try:
        api_key = get_wahooks_api_key()
    except ValueError as e:
        return {"success": False, "message": str(e)}

    from wahooks import WAHooks, WAHooksError

    if reconnect_credential_id:
        try:
            if reconnected := await _reconnect_qr(pool, api_key, owner_id, reconnect_credential_id):
                return reconnected
        except WAHooksError as e:
            logger.warning(
                f"[WhatsAppQR] Reconnect for credential {reconnect_credential_id} "
                f"failed ({e}) — falling back to a fresh scan"
            )

    def _get_scannable_connection():
        # wahooks ships only a sync httpx client; keep the blocking WhatsApp API
        # call off the event loop. Single call: reuses an idle connection or
        # creates a new one, returns connection ID + QR code ready to scan.
        # virgin_only: NoClick is multi-tenant on one WAHooks account, so only
        # never-phone-linked, config-less sessions may be recycled (server-side
        # counterpart of the _bound_to_other_owner guard below).
        with WAHooks(api_key=api_key) as client:
            return client.get_or_create_scannable_connection(virgin_only=True)

    def _create_fresh_connection():
        # The idle connection is reserved by another flow mid-scan — mint a
        # brand-new one. Its QR may take a moment to boot.
        with WAHooks(api_key=api_key) as client:
            conn = client.create_connection()
            cid = conn.get("id")
            return {"id": cid, "qr": _poll_qr(client, cid, conn.get("qr", ""))}

    try:
        result = await asyncio.to_thread(_get_scannable_connection)
        connection_id = result.get("id")

        # A recycled connection is unusable if another owner's credential
        # already binds it (their webhooks still point at it — scanning would
        # attach this owner's phone to their workflow), or if another connect
        # flow holds its reservation (they're looking at the same QR). Either
        # way: mint a fresh one. Binding is checked first so a rejected
        # connection is never left reserved against its real owner's reconnect.
        rejected = False
        if connection_id:
            if await _bound_to_other_owner(pool, connection_id, owner_id):
                logger.warning(
                    f"[WhatsAppQR] Connection {connection_id} is bound to another owner's "
                    f"credential — creating a fresh one for owner {owner_id}"
                )
                rejected = True
            elif not await _try_reserve_connection(connection_id, owner_id):
                logger.info(
                    f"[WhatsAppQR] Connection {connection_id} reserved by another flow — "
                    f"creating a fresh one for owner {owner_id}"
                )
                rejected = True
        if rejected:
            result = await asyncio.to_thread(_create_fresh_connection)
            connection_id = result.get("id")
            if connection_id and not await _try_reserve_connection(connection_id, owner_id):
                connection_id = None  # brand-new id already claimed: give up

        qr_value = result.get("qr", "")
        if not connection_id or not qr_value:
            return {"success": False, "message": "Failed to get scannable WhatsApp connection"}

        logger.info(f"[WhatsAppQR] QR code ready for owner {owner_id}, connection {connection_id}")
        return {
            "success": True,
            "connection_id": connection_id,
            "qr_code": qr_value,
            "message": "Scan this QR code with your WhatsApp to connect.",
        }
    except WAHooksError as e:
        return {"success": False, "message": f"WhatsApp error: {e}"}


async def finalize_qr_connection(
    pool,
    owner_id: str,
    connection_id: str,
    user_tier: str,
    encryption,
    credential_name: Optional[str] = None,
) -> dict[str, Any]:
    """Poll the connection; on ``connected`` bind it to ``owner_id`` as a
    ``whatsapp_qr`` credential (reservation + unique-index guarded).

    Returns ``{success, status, credential_id?, credential_name?, phone_number?,
    message, created?}``. ``created`` is True only when THIS call inserted the
    credential (False on the idempotent double-finalize) — callers use it to
    decide whether an out-of-band claim that lost the race should roll back.
    """
    try:
        api_key = get_wahooks_api_key()
    except ValueError as e:
        return {"success": False, "status": "error", "message": str(e)}

    from wahooks import WAHooks, WAHooksError

    def _get_connection():
        with WAHooks(api_key=api_key) as client:
            return client.get_connection(connection_id)

    try:
        connection = await asyncio.to_thread(_get_connection)
        status = connection.get("status", "")

        if status in ("failed", "disconnected", "logout"):
            return {
                "success": False,
                "status": "error",
                "message": "WhatsApp connection failed. Please try again by scanning a new QR code.",
            }

        if status != "connected":
            return {"success": True, "status": "pending", "message": "Waiting for QR code scan..."}

        phone_number = connection.get("phoneNumber") or ""
        logger.info("[WhatsAppQR] Connected")
        remember_connection_status(connection_id, "connected")

        # Bind guard: only the owner who was shown this QR may mint a credential
        # for the connection. An expired reservation is rejected too — a stale
        # polling loop from an earlier flow must never claim a phone someone
        # else just scanned.
        reservation = await _reservation_status(connection_id, owner_id)
        if reservation in ("other", "expired"):
            logger.warning(
                f"[WhatsAppQR] Refusing to bind connection {connection_id} for owner "
                f"{owner_id}: reservation {reservation}"
            )
            message = (
                "This QR session has expired. Please start over and scan a new QR code."
                if reservation == "expired"
                else "This WhatsApp connection belongs to another connection attempt."
            )
            return {"success": False, "status": "error", "message": message}

        # Store credential (only connection_id, no api_key). Encryption happens
        # at the INSERT below — the rebind path's sanctioned writer encrypts
        # internally, so encrypting here would do the work twice.
        credential_data = {"credential_type": "whatsapp_qr", "connection_id": connection_id}
        cred_name = credential_name or (
            f"WhatsApp ({phone_number})" if phone_number else "WhatsApp (QR)"
        )

        async with pool.acquire() as conn:
            # Hard guard: one credential per WAHooks connection, backed by the
            # partial unique index on metadata->>'connection_id'. Catches
            # anything the reservation can't (Redis down, concurrent polls).
            existing = await conn.fetchrow(
                """SELECT id, owner_id, name FROM credentials
                   WHERE credential_type = 'whatsapp_qr'
                     AND metadata->>'connection_id' = $1""",
                connection_id,
            )
            if existing:
                # Idempotent finalize: a duplicate poll of the owner's own
                # just-bound connection is success, not an error. Only a
                # connection bound to ANOTHER owner is a real conflict.
                if is_own_binding(existing["owner_id"], owner_id):
                    return {
                        "success": True,
                        "status": "connected",
                        "credential_id": str(existing["id"]),
                        "credential_name": existing["name"],
                        "phone_number": phone_number,
                        "message": "WhatsApp connected successfully!",
                        "created": False,
                    }
                return {
                    "success": False,
                    "status": "error",
                    "message": "This WhatsApp connection is already linked to a credential.",
                }

            # Same-owner same-phone REBIND: a fresh scan for a phone that
            # already has a credential repairs that credential in place
            # instead of minting a duplicate. Duplicate bindings can create
            # multiple provider-side device links. The newest
            # row wins; its replaced connection is deleted best-effort (the
            # nightly orphan sweep backstops a failed delete).
            if phone_number:
                prior = await conn.fetchrow(
                    """SELECT id, name, metadata FROM credentials
                       WHERE credential_type = 'whatsapp_qr' AND owner_id = $1
                         AND metadata->>'phone_number' = $2
                       ORDER BY updated_at DESC LIMIT 1""",
                    owner_id, phone_number,
                )
                if prior:
                    from utils.credentials import credential_metadata

                    old_connection_id = credential_metadata(prior).get("connection_id")
                    # The ONE sanctioned blob writer (also un-bricks a
                    # previously auto-revoked credential — a fresh scan is a
                    # re-authorization). Unconditional write: the new scan is
                    # authoritative, same stance as fresh OAuth installs.
                    from utils.credentials import update_credential_data_detailed

                    rows_updated, persist_err = await update_credential_data_detailed(
                        str(prior["id"]), owner_id, credential_data,
                        metadata_updates={
                            "connection_id": connection_id,
                            "phone_number": phone_number,
                        },
                        pool=pool,
                    )
                    if not rows_updated or persist_err:
                        logger.error(
                            f"[WhatsAppQR] Rebind persist failed for credential "
                            f"{prior['id']} ({persist_err}) — not inserting a duplicate"
                        )
                        return {
                            "success": False,
                            "status": "error",
                            "message": "Failed to update your existing WhatsApp credential. Please retry.",
                        }
                    if old_connection_id and old_connection_id != connection_id:
                        from utils.wahooks_connections import (
                            delete_wahooks_connection,
                            migrate_wahooks_webhooks,
                        )
                        # WAHooks webhooks are per-connection: every trigger
                        # registered on the replaced connection dies with it
                        # unless carried over FIRST (a re-scan left a trigger
                        # deaf while its config still said registered,
                        # 2026-08-29). A failed carry-over keeps the old link
                        # alive — it still delivers until the orphan sweep
                        # reaps it, and the node loader re-registers on the
                        # next panel open.
                        try:
                            await migrate_wahooks_webhooks(old_connection_id, connection_id)
                        except Exception as e:
                            logger.error(
                                f"[WhatsAppQR] Webhooks NOT migrated from {old_connection_id} "
                                f"to {connection_id} ({e}) — old connection kept",
                                exc_info=True,
                            )
                        else:
                            try:
                                await delete_wahooks_connection(old_connection_id)
                            except Exception as e:
                                logger.warning(
                                    f"[WhatsAppQR] Old connection {old_connection_id} not deleted "
                                    f"after rebind ({e}) — orphan sweep will reap it"
                                )
                    logger.info(
                        f"[WhatsAppQR] Rebound credential {prior['id']} "
                        f"to connection {connection_id}"
                    )
                    return {
                        "success": True,
                        "status": "connected",
                        "credential_id": str(prior["id"]),
                        "credential_name": prior["name"],
                        "phone_number": phone_number,
                        "message": "WhatsApp reconnected successfully!",
                        "created": False,
                    }

            try:
                encrypted_data = encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[WhatsAppQR] Encryption failed: {e}")
                return {"success": False, "status": "error", "message": "Failed to encrypt credentials"}

            from repositories.credentials import create_credential_with_limit_check
            try:
                row, error = await create_credential_with_limit_check(
                    conn, owner_id, user_tier, "whatsapp_qr",
                    cred_name, encrypted_data, {
                        "provider": "wahooks",
                        "phone_number": phone_number,
                        "connection_id": connection_id,
                    },
                )
            except asyncpg.UniqueViolationError:
                # Lost the race to a concurrent poll of the same connection — if
                # the winner is this same owner, that poll's credential IS the
                # success result.
                winner = await conn.fetchrow(
                    """SELECT id, owner_id, name FROM credentials
                       WHERE credential_type = 'whatsapp_qr'
                         AND metadata->>'connection_id' = $1""",
                    connection_id,
                )
                if winner and is_own_binding(winner["owner_id"], owner_id):
                    return {
                        "success": True,
                        "status": "connected",
                        "credential_id": str(winner["id"]),
                        "credential_name": winner["name"],
                        "phone_number": phone_number,
                        "message": "WhatsApp connected successfully!",
                        "created": False,
                    }
                return {
                    "success": False,
                    "status": "error",
                    "message": "This WhatsApp connection is already linked to a credential.",
                }
            if error:
                return {"success": False, "status": "error", "message": error}

            credential_id = str(row["id"])

            # A platform that bills the persistent connection starts its clock
            # here; the engine's default is nothing to bill.
            from billing.recurring import start_connection_charge

            await start_connection_charge(
                conn, user_id=owner_id, credential_id=row["id"], charge_type="whatsapp_connection"
            )
            logger.info(f"[WhatsAppQR] Created WhatsApp QR credential {credential_id} for owner {owner_id}")
            return {
                "success": True,
                "status": "connected",
                "credential_id": credential_id,
                "credential_name": row["name"],
                "phone_number": phone_number,
                "message": "WhatsApp connected successfully!",
                "created": True,
            }
    except WAHooksError as e:
        return {"success": False, "status": "error", "message": f"WhatsApp error: {e}"}
