"""Profile pictures and group names of the chats a linked WhatsApp connection talks with.

WAHooks reads both per connection: a person's or group's picture with
``GET /connections/{id}/contacts/{jid}/picture`` (a short-lived WhatsApp CDN
link, or null for none, a private one, or its own failure), and a group's name,
which no message event carries, from the connection's chat list
(``GET /connections/{id}/chats``, newest first). A picture is copied into the
bucket inbound media goes to, under an unguessable key, so its URL lasts and
loads in a browser. ``whatsapp_chat_profiles`` keeps one row per (connection,
chat id) until its refresh window ends.

A read never waits on WhatsApp unless asked to (``wait_s``): a delivery takes
what is kept and leaves a refresh running for the next message, waiting briefly
only for a group it has no name for (``name_wait_s``). Any gateway or storage
failure is logged and reads as nothing known.

Callers gate access: a connection id comes here only from a credential the
caller may use. The URLs are capabilities for the connection's owner and their
space, never for a public or share-link page.
"""

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote, urlsplit

import httpx

logger = logging.getLogger(__name__)

PICTURE_REFRESH_S = 24 * 3600
# WAHooks answers null for its own failures too, so "no picture" is asked again sooner.
NO_PICTURE_REFRESH_S = 6 * 3600
FAILED_REFRESH_S = 15 * 60
PICTURE_MAX_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT_S = 15.0
MAX_JIDS = 100
# Chat-list pages read for group names: a group that just wrote is on the first.
_CHAT_PAGE = 100
_CHAT_PAGES = 3
_CONCURRENCY = 6
_KEY_PREFIX = "whatsapp-profiles"
_PICTURE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

_IN_FLIGHT: Dict[Tuple[str, str], asyncio.Task] = {}


@dataclass(frozen=True)
class ChatProfile:
    jid: str
    avatar_url: Optional[str] = None
    name: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"jid": self.jid, "name": self.name, "avatar_url": self.avatar_url}


def is_group(jid: str) -> bool:
    return jid.endswith("@g.us")


def _wahooks_client(api_key: str) -> httpx.AsyncClient:
    from wahooks.client import DEFAULT_BASE_URL

    return httpx.AsyncClient(base_url=f"{DEFAULT_BASE_URL}/api", timeout=FETCH_TIMEOUT_S,
                             headers={"Authorization": f"Bearer {api_key}"})


def _cdn_client() -> httpx.AsyncClient:
    from utils.ssrf import guarded_async_client

    return guarded_async_client(timeout=FETCH_TIMEOUT_S)


async def chat_profiles(pool, connection_id: str, jids: Iterable[str], *,
                        wait_s: float = 0.0, name_wait_s: float = 0.0) -> Dict[str, ChatProfile]:
    """What is kept of each chat id's picture and (a group's) name on ``connection_id``. Ids never fetched or past
    their refresh window are fetched in the background; ``wait_s`` waits that long for them, else they read as
    they were (nothing, the first time). ``name_wait_s`` waits that long only when a group due a fetch has no name
    kept: none of its messages carry it, so its first one would otherwise reach its agent unnamed."""
    from utils.wahooks_connections import get_wahooks_api_key

    wanted = list(dict.fromkeys(j.strip() for j in jids if isinstance(j, str) and j.strip()))[:MAX_JIDS]
    if not wanted or not connection_id:
        return {j: ChatProfile(j) for j in wanted}
    try:
        rows = await _rows(pool, connection_id, wanted)
    except Exception as e:
        logger.warning(f"[whatsapp_profiles] Couldn't read kept profiles on {connection_id}: {e}")
        return {j: ChatProfile(j) for j in wanted}
    stale = [j for j in wanted if j not in rows or rows[j]["stale"]]
    if stale and get_wahooks_api_key():
        tasks = _refreshing(pool, connection_id, stale)
        if any(is_group(j) and not (rows.get(j) or {}).get("name") for j in stale):
            wait_s = max(wait_s, name_wait_s)
        if wait_s > 0:
            _, pending = await asyncio.wait(tasks, timeout=wait_s)
            if pending:
                logger.info(f"[whatsapp_profiles] {len(pending)} refresh(es) on {connection_id} still running")
            try:
                rows.update(await _rows(pool, connection_id, stale))
            except Exception as e:
                logger.warning(f"[whatsapp_profiles] Couldn't read refreshed profiles on {connection_id}: {e}")
    return {j: _profile(j, rows.get(j)) for j in wanted}


async def credential_connection_id(pool, credential_id: str) -> Optional[str]:
    """The WAHooks connection a ``whatsapp_qr`` credential holds: its metadata's, else its encrypted blob's."""
    from utils.credentials import credential_metadata
    from utils.encryption import get_encryption

    row = await pool.fetchrow(
        "SELECT credential, metadata FROM credentials WHERE id = $1::uuid AND credential_type = 'whatsapp_qr'",
        credential_id)
    if row is None:
        return None
    found = credential_metadata(row).get("connection_id") or get_encryption().decrypt_credential(
        row["credential"]).get("connection_id")
    return str(found) if found else None


async def workflow_group_names(pool, workflow_id: str, jids: Iterable[str]) -> Dict[str, str]:
    """The kept names of the groups ``jids`` on the connections a workflow's WhatsApp nodes hold. A group not kept
    yet is fetched in the background, there for a later read."""
    from utils.credentials import _is_credential_uuid
    from utils.graph_nodes import graph_nodes, node_config, node_type

    groups = [j for j in jids if isinstance(j, str) and is_group(j)]
    if not groups:
        return {}
    graph = await pool.fetchval("SELECT workflow FROM workflows WHERE id = $1::uuid", workflow_id)
    held = [node_config(n).get("credentialIds") for n in graph_nodes(graph) if node_type(n) == "automation-whatsapp"]
    credential_ids = {ids.get("whatsapp_qr") for ids in held if isinstance(ids, dict)}
    names: Dict[str, str] = {}
    for credential_id in filter(_is_credential_uuid, credential_ids):
        connection_id = await credential_connection_id(pool, credential_id)
        for jid, profile in (await chat_profiles(pool, connection_id, groups)).items() if connection_id else ():
            if profile.name:
                names.setdefault(jid, profile.name)
    return names


async def forget_connection(pool, connection_id: str) -> int:
    """Remove what is kept for a torn-down connection, pictures included. The count of rows removed."""
    from utils.r2_cloudflare import delete_files_from_r2_async_native
    from utils.resource_store import RESOURCE_BUCKET

    rows = await pool.fetch(
        "DELETE FROM whatsapp_chat_profiles WHERE connection_id = $1 RETURNING avatar_key", connection_id)
    keys = [r["avatar_key"] for r in rows if r["avatar_key"]]
    if keys:
        await delete_files_from_r2_async_native(RESOURCE_BUCKET, keys)
    return len(rows)


def _profile(jid: str, row: Optional[Dict[str, Any]]) -> ChatProfile:
    from utils.r2_cloudflare import get_public_download_url

    if row is None:
        return ChatProfile(jid)
    return ChatProfile(jid, avatar_url=get_public_download_url(row["avatar_key"]) if row["avatar_key"] else None,
                       name=row["name"] if is_group(jid) else None)


async def _rows(pool, connection_id: str, jids: List[str]) -> Dict[str, Dict[str, Any]]:
    rows = await pool.fetch(
        """SELECT jid, avatar_key, name, refresh_after <= now() AS stale FROM whatsapp_chat_profiles
           WHERE connection_id = $1 AND jid = ANY($2::text[])""", connection_id, jids)
    return {r["jid"]: dict(r) for r in rows}


def _refreshing(pool, connection_id: str, jids: List[str]) -> Set[asyncio.Task]:
    """The refreshes covering ``jids``: one already running for an id, else one new one for the rest."""
    from utils.async_helpers import spawn

    loop = asyncio.get_running_loop()
    running = {jid: _IN_FLIGHT.get((connection_id, jid)) for jid in jids}
    tasks = {t for t in running.values() if t is not None and not t.done() and t.get_loop() is loop}
    new = [jid for jid, t in running.items() if t not in tasks]
    if new:
        task = spawn(_refresh(pool, connection_id, new), name=f"whatsapp-profiles:{connection_id}")
        for jid in new:
            _IN_FLIGHT[(connection_id, jid)] = task

        def done(_t, keys=[(connection_id, jid) for jid in new]):
            for k in keys:
                if _IN_FLIGHT.get(k) is task:
                    del _IN_FLIGHT[k]

        task.add_done_callback(done)
        tasks.add(task)
    return tasks


async def _refresh(pool, connection_id: str, jids: List[str]) -> None:
    from utils.wahooks_connections import get_wahooks_api_key

    gate = asyncio.Semaphore(_CONCURRENCY)
    async with _wahooks_client(get_wahooks_api_key()) as wahooks:
        names = await _group_names(wahooks, connection_id, [j for j in jids if is_group(j)])

        async def one(jid: str) -> None:
            async with gate:
                await _refresh_one(pool, wahooks, connection_id, jid, names.get(jid))

        await asyncio.gather(*(one(jid) for jid in jids))


async def _group_names(wahooks: httpx.AsyncClient, connection_id: str, groups: List[str]) -> Dict[str, str]:
    """The names of ``groups`` the connection's newest chats list. A group not found keeps the name it had: WAHooks
    lists no chats when its gateway fails, and a page can end before an older group."""
    found: Dict[str, str] = {}
    try:
        for page in range(_CHAT_PAGES if groups else 0):
            response = await wahooks.get(f"/connections/{quote(connection_id, safe='')}/chats",
                                         params={"limit": _CHAT_PAGE, "offset": page * _CHAT_PAGE})
            response.raise_for_status()
            chats = response.json() or []
            for chat in chats:
                if isinstance(chat, dict) and chat.get("id") in groups and str(chat.get("name") or "").strip():
                    found[chat["id"]] = str(chat["name"]).strip()
            if len(found) == len(groups) or len(chats) < _CHAT_PAGE:
                break
    except Exception as e:
        logger.warning(f"[whatsapp_profiles] Group names on {connection_id} not read: {type(e).__name__}: {e}")
    return found


async def _refresh_one(pool, wahooks: httpx.AsyncClient, connection_id: str, jid: str,
                       name: Optional[str]) -> None:
    try:
        url = await _picture_url(wahooks, connection_id, jid)
        picture = await _download(url) if url else None
    except Exception as e:
        # By name: a CDN error's message holds the signed URL.
        logger.warning(f"[whatsapp_profiles] Picture on {connection_id} not refreshed: {type(e).__name__}")
        await _upsert(pool, connection_id, jid, name=name, refresh_s=FAILED_REFRESH_S)
        return
    try:
        await _store(pool, connection_id, jid, picture, name)
    except Exception as e:
        logger.warning(f"[whatsapp_profiles] Picture on {connection_id} not kept: {type(e).__name__}: {e}")


async def _picture_url(wahooks: httpx.AsyncClient, connection_id: str, jid: str) -> Optional[str]:
    response = await wahooks.get(
        f"/connections/{quote(connection_id, safe='')}/contacts/{quote(jid, safe='@')}/picture")
    response.raise_for_status()
    url = (response.json() or {}).get("profilePictureUrl")
    if not url:
        return None
    parts = urlsplit(str(url))
    # The CDN WhatsApp serves pictures from, over https: nothing else is fetched.
    if parts.scheme != "https" or not (parts.hostname or "").endswith(".whatsapp.net"):
        logger.warning(f"[whatsapp_profiles] Ignored a picture link on {connection_id} from {parts.hostname!r}")
        return None
    return str(url)


async def _download(url: str) -> Tuple[bytes, str]:
    async with _cdn_client() as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            mime = (response.headers.get("content-type") or "image/jpeg").split(";", 1)[0].strip().lower()
            # Raster images only: the copy is served from NoClick's own file host.
            if mime not in _PICTURE_TYPES:
                raise ValueError(f"a picture link served {mime}")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > PICTURE_MAX_BYTES:
                    raise ValueError(f"a picture over {PICTURE_MAX_BYTES} bytes")
    return bytes(body), mime


async def _store(pool, connection_id: str, jid: str, picture: Optional[Tuple[bytes, str]],
                 name: Optional[str]) -> None:
    """Keep what a refresh found. A picture the row already holds (same sha256) is not stored again; one that
    replaces another, or a picture taken down, deletes the old one."""
    from utils.r2_cloudflare import delete_files_from_r2_async_native, upload_bytes_to_r2_async
    from utils.resource_store import RESOURCE_BUCKET

    body, mime = picture if picture else (b"", "")
    sha = hashlib.sha256(body).hexdigest() if picture else None
    held = await pool.fetchval(
        "SELECT avatar_sha256 FROM whatsapp_chat_profiles WHERE connection_id = $1 AND jid = $2", connection_id, jid)
    key = None
    if picture and held != sha:
        key = f"{_KEY_PREFIX}/{uuid.uuid4()}.{_PICTURE_TYPES[mime]}"
        await upload_bytes_to_r2_async(bucket=RESOURCE_BUCKET, key=key, body=body, content_type=mime)
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Takes the row (another refresh of it waits here) and reads what it holds now.
            row = await conn.fetchrow(
                """INSERT INTO whatsapp_chat_profiles (connection_id, jid, refresh_after) VALUES ($1, $2, now())
                   ON CONFLICT (connection_id, jid) DO UPDATE SET updated_at = whatsapp_chat_profiles.updated_at
                   RETURNING avatar_key, avatar_sha256""", connection_id, jid)
            if picture and (row["avatar_sha256"] == sha or key is None):
                # The same picture, or (not uploaded: the same at the peek) one another refresh kept since.
                keep, keep_sha, drop = row["avatar_key"], row["avatar_sha256"], key
            else:
                keep, keep_sha, drop = key, sha, row["avatar_key"]
            await conn.execute(
                """UPDATE whatsapp_chat_profiles SET avatar_key = $3, avatar_sha256 = $4, name = COALESCE($5, name),
                       refresh_after = now() + make_interval(secs => $6), updated_at = now()
                   WHERE connection_id = $1 AND jid = $2""",
                connection_id, jid, keep, keep_sha, name,
                float(PICTURE_REFRESH_S if keep else NO_PICTURE_REFRESH_S))
    if drop:
        try:
            await delete_files_from_r2_async_native(RESOURCE_BUCKET, [drop])
        except Exception as e:
            logger.warning(f"[whatsapp_profiles] Old picture {drop} not deleted: {e}")


async def _upsert(pool, connection_id: str, jid: str, *, name: Optional[str], refresh_s: float) -> None:
    """A refresh that failed: the row keeps its picture, takes a name that was found, and is asked again soon."""
    try:
        await pool.execute(
            """INSERT INTO whatsapp_chat_profiles (connection_id, jid, name, refresh_after)
               VALUES ($1, $2, $3, now() + make_interval(secs => $4))
               ON CONFLICT (connection_id, jid) DO UPDATE SET name = COALESCE(EXCLUDED.name, whatsapp_chat_profiles.name),
                   refresh_after = EXCLUDED.refresh_after, updated_at = now()""",
            connection_id, jid, name, float(refresh_s))
    except Exception as e:
        logger.warning(f"[whatsapp_profiles] Retry window on {connection_id} not kept: {e}")
