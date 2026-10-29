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
4. ``start`` never shows the QR of a recycled connection that holds a WhatsApp
   login (a phone number, or connected) unless it is the owner's own: finalize
   would bind that login into this owner's credential.

A reused connection is brought to a fresh QR before it is shown (a ``failed``
one is restarted), and a flow that gives up on a connection lets go of it, so a
Retry never lands back on the session that just failed.
"""

import asyncio
import logging
import os
import time
from typing import Any, Iterable, NamedTuple, Optional

import asyncpg
import httpx

from utils.redis_client import get_shared_redis

logger = logging.getLogger(__name__)

# Generously covers display → scan → status poll; a stale reservation must
# expire so an abandoned idle connection can be handed out again.
QR_RESERVATION_TTL_S = 15 * 60
# start_qr_connection's failure codes when the owner's credit gate refused: credits, or the monthly spending cap.
INSUFFICIENT_CREDITS = "insufficient_credits"
SPEND_CAP = "spend_cap"
# How long a scan waits for WAHooks' first QR. Its get-or-create answers "pending" (fetch the QR yourself) when
# its own ~20s poll found none, and a session it has just made needs a worker and a booted WhatsApp client first;
# a start that gave up at that "pending" left the page saying the connection failed.
QR_WAIT_S = 60.0
# A connection a start already holds (a re-scan of a credential's own, the QR an earlier start is
# showing) gets this long to show a QR before a fresh one is tried instead.
HELD_QR_WAIT_S = 15.0
QR_POLL_S = 2.0
# WAHooks answers that end a QR wait at once: no such connection, not this account's, bad key. Anything
# else is a session still coming up: 503 while it or its worker starts, and WAHA's 422 "Session status is
# not as expected" for a QR asked of a session mid-restart.
_FINAL_STATUS_CODES = frozenset({401, 403, 404, 410})
# Connection statuses a QR flow can't continue on. WAHooks' ``stopped`` means deleted; ``disconnected``
# and ``logout`` are kept for older WAHooks answers.
DEAD_STATUSES = ("failed", "stopped", "disconnected", "logout")
NO_QR_MESSAGE = ("WhatsApp's linking service didn't send a QR code in time; it may be busy. "
                 "Please try again in a few minutes.")


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


class QrAnswer(NamedTuple):
    qr: str = ""
    why: str = ""  # why there's no QR, for the log
    linked: bool = False  # a phone already scanned it
    foreign: bool = False  # it holds a WhatsApp login this owner must never be handed


def _wait_for_qr(client, connection_id: str, deadline: float) -> QrAnswer:
    """Blocking (thread-pool): the connection's QR, asked for until ``deadline``
    (``time.monotonic``). WAHooks answers ``{value}`` once the session shows a
    QR, ``{connected: true}`` once a phone is linked, and 503 while the session
    or its worker starts. When WAHA refuses the QR it resets the session only if
    WAHA reports it FAILED/STOPPED at that instant, and still answers 503 then;
    see ``_scannable_qr`` for why that alone never revived a failing session."""
    from wahooks import WAHooksError

    while True:
        try:
            answer = client.get_qr(connection_id)
        except WAHooksError as e:
            code = getattr(e, "status_code", None)
            if code in _FINAL_STATUS_CODES:
                return QrAnswer(why=f"WAHooks answered {code} for connection {connection_id}: {e}")
            why = f"WAHooks answered {code}: {e}"
        except httpx.HTTPError as e:
            why = f"WAHooks didn't answer ({type(e).__name__})"
        else:
            if answer.get("value"):
                return QrAnswer(qr=answer["value"])
            if answer.get("connected"):
                return QrAnswer(why="a phone is already linked to it", linked=True)
            why = f"WAHooks answered with no QR: {sorted(answer)}"
        if time.monotonic() + QR_POLL_S >= deadline:
            return QrAnswer(why=why)
        time.sleep(QR_POLL_S)


def _scannable_qr(client, connection_id: str, deadline: float, *, own: bool, offered_qr: str = "") -> QrAnswer:
    """Blocking (thread-pool): the QR of a connection with a past, brought to a
    fresh scan first. ``own``: a credential of this owner binds it.

    - One holding a WhatsApp login (a phone number, or connected) is refused
      unless ``own``: its QR would carry that login into this owner's credential.
    - ``stopped`` is deleted at WAHooks, whose QR fetch answers 503 for it forever.
    - ``failed`` is restarted (WAHooks' full reset: fresh session, fresh QR
      cycle). A QR fetch resets it only when its status read lands on FAILED;
      an unscanned session the health cron keeps restarting (QR times out →
      FAILED → restart → STARTING → QR …) refuses the QR with WAHA's 422
      whenever it isn't showing one, and a read during STARTING resets nothing.
    ``offered_qr``: the QR WAHooks handed over with the connection, used while
    it still shows one."""
    from wahooks import WAHooksError

    try:
        connection = client.get_connection(connection_id)
        status = connection.get("status") or ""
        if not own and (connection.get("phoneNumber") or status == "connected"):
            return QrAnswer(why="it holds a WhatsApp login", foreign=True)
        if status == "stopped":
            return QrAnswer(why="WAHooks deleted it")
        if status == "failed":
            client.restart_connection(connection_id)
            logger.info(f"[WhatsAppQR] Restarted failed connection {connection_id} for a fresh QR")
        elif offered_qr and status == "scan_qr":
            return QrAnswer(qr=offered_qr)
    except WAHooksError as e:
        return QrAnswer(why=f"WAHooks answered {getattr(e, 'status_code', '?')} for connection {connection_id}: {e}")
    except httpx.HTTPError as e:
        return QrAnswer(why=f"WAHooks didn't answer ({type(e).__name__})")
    answer = _wait_for_qr(client, connection_id, deadline)
    if answer.linked and not own:
        # No one has been shown its QR since WAHooks reset it, so the login it
        # came up with is somebody else's.
        return answer._replace(why="it came up holding a WhatsApp login", foreign=True)
    return answer


async def _reconnect_qr(
    pool, api_key: str, owner_id: str, credential_id: str
) -> Optional[dict[str, Any]]:
    """QR for re-scanning INTO an existing credential's own connection, or
    None to fall through to a fresh scan (finalize's same-phone rebind then
    repairs the credential in place). A failed session is restarted first, so
    the scan relinks the same session and finalize resolves it as the
    idempotent own-binding success — credential id and webhooks survive untouched."""
    from wahooks import WAHooks
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

    def _get_own_qr() -> QrAnswer:
        with WAHooks(api_key=api_key) as client:
            return _scannable_qr(client, own_conn_id, time.monotonic() + HELD_QR_WAIT_S, own=True)

    answer = await asyncio.to_thread(_get_own_qr)
    if not answer.qr:
        logger.warning(
            f"[WhatsAppQR] Reconnect via connection {own_conn_id} yielded no QR ({answer.why}) — "
            f"falling back to a fresh scan (finalize rebinds by phone)"
        )
        await _release(owner_id, own_conn_id)
        return None
    logger.info(
        f"[WhatsAppQR] Reconnect QR ready for credential {credential_id} "
        f"(connection {own_conn_id})"
    )
    return {
        "success": True,
        "connection_id": own_conn_id,
        "qr_code": answer.qr,
        "reconnect": True,
        "message": "Scan this QR code to reconnect your WhatsApp.",
    }


def _reservation_key(connection_id: str) -> str:
    return f"whatsapp:qr:reserved:{connection_id}"


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


async def _release(owner_id: str, connection_id: str) -> None:
    """Drop this owner's hold on a connection their flow gave up on, so neither
    a later finalize nor a Retry's re-show comes back to it. Another owner's
    hold is never touched."""
    client = get_shared_redis()
    if client is None:
        return
    try:
        key = _reservation_key(connection_id)
        holder = await client.get(key)
        if holder is not None and _text(holder) == owner_id:
            await client.delete(key)
        shown = await client.get(_shown_key(owner_id))
        if shown is not None and _text(shown) == connection_id:
            await client.delete(_shown_key(owner_id))
    except Exception as e:
        logger.warning(f"[WhatsAppQR] Release of connection {connection_id} for owner {owner_id} failed: {e}")


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
        if holder is not None and _text(holder) != owner_id:
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
    return "held" if _text(holder) == owner_id else "other"


async def _binding_owner(pool, connection_id: str) -> Optional[str]:
    """The owner of the credential that binds this connection, if any."""
    async with pool.acquire() as conn:
        owner = await conn.fetchval(
            """SELECT owner_id FROM credentials
               WHERE credential_type = 'whatsapp_qr'
                 AND metadata->>'connection_id' = $1""",
            connection_id,
        )
    return None if owner is None else str(owner)


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
    connection instead of minting a new one — a failed session is restarted,
    the scan relinks the same session, and finalize resolves it as the
    idempotent own-binding success, so the credential id (and its webhooks,
    workflows) survives untouched. Minting a fresh connection during reconnect
    can create duplicate credentials and device links, so reconnect must reuse
    the existing binding. If the old connection is gone at WAHooks, falls
    through to a fresh scan — finalize's same-phone rebind then repairs the
    credential in place.

    A new connection is billed by the hour once scanned, so it needs the
    owner's credit gate first; a re-scan of an existing one starts no new
    charge and is never refused for credits.

    Returns ``{success, connection_id?, qr_code?, message, reconnect?, code?}``
    (``code`` ``insufficient_credits`` or ``spend_cap`` when the gate refused). Never raises for
    the expected WAHooks/config/credit failure modes — callers map ``success``
    to their own transport response.
    """
    try:
        api_key = get_wahooks_api_key()
    except ValueError as e:
        return {"success": False, "message": str(e)}

    if not reconnect_credential_id:
        from billing.exceptions import InsufficientBalanceError, SpendCapReached
        from billing.usage_tracker import usage_tracker

        try:
            await usage_tracker.enforce_credit_gate(owner_id, surface="whatsapp_connection")
        except SpendCapReached as e:  # adding funds wouldn't lift it
            return {"success": False, "code": SPEND_CAP, "message": str(e)}
        except InsufficientBalanceError as e:
            return {"success": False, "code": INSUFFICIENT_CREDITS,
                    "message": f"A connected WhatsApp number is billed by the hour; add funds to connect one. {e}"}

    from wahooks import WAHooks, WAHooksError

    if reconnect_credential_id and (
        reconnected := await _reconnect_qr(pool, api_key, owner_id, reconnect_credential_id)
    ):
        return reconnected
    if shown := await _still_shown(pool, api_key, owner_id):
        return shown

    def _create_fresh_connection():
        with WAHooks(api_key=api_key) as client:
            return client.create_connection()

    def _wait(connection_id: str, deadline: float) -> QrAnswer:
        with WAHooks(api_key=api_key) as client:
            return _wait_for_qr(client, connection_id, deadline)

    started = time.monotonic()
    deadline = started + QR_WAIT_S
    connection_id = None  # the connection this start holds the reservation of
    try:
        recycled = await _recycled_qr(pool, api_key, owner_id, deadline)
        if recycled is not None:
            connection_id, answer = recycled
        else:
            # Nothing reusable can serve this owner: a brand-new connection,
            # which comes with no QR of its own yet.
            answer = QrAnswer(why="the connection WAHooks created couldn't be reserved")
            created = await asyncio.to_thread(_create_fresh_connection)
            if created.get("id") and await _try_reserve_connection(created["id"], owner_id):
                connection_id = created["id"]
                answer = await asyncio.to_thread(_wait, connection_id, deadline)
    except (WAHooksError, httpx.HTTPError) as e:
        answer = QrAnswer(why=f"WAHooks failed: {type(e).__name__}: {e}")

    if not connection_id or not answer.qr:
        logger.warning(
            f"[WhatsAppQR] No QR for owner {owner_id} on connection {connection_id} after "
            f"{time.monotonic() - started:.0f}s: {answer.why}"
        )
        if connection_id and not answer.linked:
            await _abandon(pool, owner_id, connection_id)
        return {"success": False, "message": NO_QR_MESSAGE}

    await _remember_shown(owner_id, connection_id)
    logger.info(f"[WhatsAppQR] QR code ready for owner {owner_id}, connection {connection_id}")
    return {
        "success": True,
        "connection_id": connection_id,
        "qr_code": answer.qr,
        "message": "Scan this QR code with your WhatsApp to connect.",
    }


async def _recycled_qr(
    pool, api_key: str, owner_id: str, deadline: float
) -> Optional[tuple[Optional[str], QrAnswer]]:
    """``(connection_id, answer)`` for the idle connection WAHooks hands this
    owner, reserved to them; None when what it offered can't serve them and a
    brand-new connection is minted instead."""
    from wahooks import WAHooks, WAHooksError

    def _offer():
        # wahooks ships only a sync httpx client; keep the blocking WhatsApp API
        # call off the event loop. Single call: resets an idle connection (or
        # creates one) and polls ~20s for its QR. virgin_only: NoClick is
        # multi-tenant on one WAHooks account, so only never-phone-linked,
        # config-less sessions may be recycled (server-side counterpart of the
        # binding and login checks below).
        with WAHooks(api_key=api_key) as client:
            return client.get_or_create_scannable_connection(virgin_only=True)

    try:
        offer = await asyncio.to_thread(_offer)
    except WAHooksError as e:
        if e.status_code in _FINAL_STATUS_CODES:
            raise
        # Its reset of the session it picked broke midway (WAHA refuses a
        # session mid-restart); asking again would pick that same session.
        logger.warning(
            f"[WhatsAppQR] WAHooks couldn't ready an idle connection ({e.status_code}: {e}) — "
            f"creating a fresh one for owner {owner_id}"
        )
        return None
    offered = offer.get("id")
    if not offered:
        return None, QrAnswer(why=f"WAHooks offered no connection: {sorted(offer)}")

    # Unusable if another owner's credential already binds it (their webhooks
    # still point at it — scanning would attach this owner's phone to their
    # workflow), or if another connect flow holds its reservation (they're
    # looking at the same QR). Binding is checked first so a rejected
    # connection is never left reserved against its real owner's reconnect.
    binder = await _binding_owner(pool, offered)
    if binder is not None and not is_own_binding(binder, owner_id):
        logger.warning(
            f"[WhatsAppQR] Connection {offered} is bound to another owner's "
            f"credential — creating a fresh one for owner {owner_id}"
        )
        return None
    if not await _try_reserve_connection(offered, owner_id):
        logger.info(
            f"[WhatsAppQR] Connection {offered} reserved by another flow — "
            f"creating a fresh one for owner {owner_id}"
        )
        return None

    def _qr() -> QrAnswer:
        with WAHooks(api_key=api_key) as client:
            return _scannable_qr(
                client, offered, deadline, own=binder is not None, offered_qr=offer.get("qr") or ""
            )

    answer = await asyncio.to_thread(_qr)
    if answer.foreign:
        await _release(owner_id, offered)
        logger.warning(
            f"[WhatsAppQR] Connection {offered} was offered for reuse but {answer.why} — "
            f"creating a fresh one for owner {owner_id}"
        )
        return None
    return offered, answer


def _shown_key(owner_id: str) -> str:
    return f"whatsapp:qr:shown:{owner_id}"


async def _remember_shown(owner_id: str, connection_id: str) -> None:
    client = get_shared_redis()
    if client is None:
        return
    try:
        await client.set(_shown_key(owner_id), connection_id, ex=QR_RESERVATION_TTL_S)
    except Exception as e:
        logger.warning(f"[WhatsAppQR] Shown-QR write failed for owner {owner_id}: {e}")


async def _still_shown(pool, api_key: str, owner_id: str) -> Optional[dict[str, Any]]:
    """The QR this owner's last start is showing, read again while its
    connection is still reserved to them and unscanned. WAHooks' get-or-create
    resets the idle session it hands out, so a second start (a page that starts
    twice, a retry) asking it again would void the QR the first is showing.

    A connection that can't show one is let go so this start moves on to
    another, and deleted when its session failed: a Retry must never land back
    on it, nor on its next restart."""
    client = get_shared_redis()
    if client is None:
        return None
    try:
        held = await client.get(_shown_key(owner_id))
    except Exception as e:
        logger.warning(f"[WhatsAppQR] Shown-QR read failed for owner {owner_id}: {e}")
        return None
    if held is None:
        return None
    connection_id = _text(held)
    if await _reservation_status(connection_id, owner_id) != "held":
        return None
    from wahooks import WAHooks, WAHooksError

    def _read() -> tuple[str, QrAnswer]:
        with WAHooks(api_key=api_key) as client:
            status = client.get_connection(connection_id).get("status") or ""
            if status in DEAD_STATUSES:
                return status, QrAnswer(why=f"its session is {status}")
            if status == "connected":  # scanned: the first start's finalize binds it
                return status, QrAnswer(why="a phone is already linked to it", linked=True)
            return status, _wait_for_qr(client, connection_id, time.monotonic() + HELD_QR_WAIT_S)

    try:
        status, answer = await asyncio.to_thread(_read)
    except (WAHooksError, httpx.HTTPError) as e:
        logger.warning(f"[WhatsAppQR] Shown connection {connection_id} unreadable for owner {owner_id}: {e}")
        return None
    if not answer.qr:
        if not answer.linked:
            logger.info(f"[WhatsAppQR] Letting go of shown connection {connection_id}: {answer.why}")
            if status in DEAD_STATUSES:
                await _abandon(pool, owner_id, connection_id)
            else:
                await _release(owner_id, connection_id)
        return None
    logger.info(f"[WhatsAppQR] QR still shown for owner {owner_id}, connection {connection_id}")
    return {
        "success": True,
        "connection_id": connection_id,
        "qr_code": answer.qr,
        "message": "Scan this QR code with your WhatsApp to connect.",
    }


async def _abandon(pool, owner_id: str, connection_id: str) -> None:
    """This owner's flow is done with a connection it got no scan from: let go
    of it and delete it, so no later start is handed it as this one was."""
    await _release(owner_id, connection_id)
    await _discard(pool, connection_id)


async def _discard(pool, connection_id: str) -> None:
    """Delete a connection a flow got no scan from, unless a credential binds it."""
    if await _binding_owner(pool, connection_id) is not None:
        return
    from utils.wahooks_connections import delete_wahooks_connection

    try:
        await delete_wahooks_connection(connection_id)
    except Exception as e:
        logger.error(
            f"[WhatsAppQR] Connection {connection_id} not deleted after its flow failed ({e}); "
            f"left for the orphan sweep"
        )


async def finalize_qr_connection(
    pool,
    owner_id: str,
    connection_id: str,
    user_tier: str,
    encryption,
    credential_name: Optional[str] = None,
    held_for_someone_else: bool = False,
) -> dict[str, Any]:
    """Poll the connection; on ``connected`` bind it to ``owner_id`` as a
    ``whatsapp_qr`` credential (reservation + unique-index guarded).
    ``held_for_someone_else``: the scan answers a request whose credential the
    owner won't hold, so it never rebinds into one of the owner's rows.

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

    def _current_qr() -> QrAnswer:
        with WAHooks(api_key=api_key) as client:
            return _wait_for_qr(client, connection_id, time.monotonic())  # asked once

    try:
        connection = await asyncio.to_thread(_get_connection)
        status = connection.get("status", "")

        if status in DEAD_STATUSES:
            # This attempt is over (an unscanned QR times out into `failed`).
            # Let go of the connection so the Retry this asks for starts on
            # another one, never on this one's next restart.
            if await _reservation_status(connection_id, owner_id) == "held":
                await _abandon(pool, owner_id, connection_id)
            return {
                "success": False,
                "status": "error",
                "message": "WhatsApp connection failed. Please try again by scanning a new QR code.",
            }

        if status != "connected":
            pending = {"success": True, "status": "pending", "message": "Waiting for QR code scan..."}
            # WhatsApp rotates the linking code while it waits for a scan; a page
            # still showing the first one shows a code the phone refuses.
            if status == "scan_qr" and await _reservation_status(connection_id, owner_id) == "held":
                if qr := (await asyncio.to_thread(_current_qr)).qr:
                    pending["qr_code"] = qr
            return pending

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
            # Rows held for someone else are never rebound: that would merge
            # this scan into a credential its holder alone uses.
            if phone_number and not held_for_someone_else:
                from repositories.credentials import listed_to_owner_sql

                prior = await conn.fetchrow(
                    f"""SELECT id, name, metadata FROM credentials
                       WHERE credential_type = 'whatsapp_qr' AND owner_id = $1
                         AND metadata->>'phone_number' = $2 AND {listed_to_owner_sql('credentials')}
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
