"""Files people send an agent, kept as files in the workspace its turn opens (``inbox/<chat>/``).

A channel's delivery fetches a message's media once, to rehost it (``utils.inbound_media``). The bytes that fetch
streams past are held (``Held``) and written, server-side through the volume backend, into the durable workspace of
each agent the delivery wakes (``agent_inbox_volume``), in a folder of the chat's own: a photo someone sends is a file
the agent opens, edits and sends back, and no sandbox boots to receive it.

Which workspaces those are is the engine's wiring (each agent the trigger's event reaches, in the conversation it
adopts from the event), unless the platform delivering the trigger says (``DELIVERY_WORKSPACES``).

A chat's folder is its name or number, or a group's name, made safe for a shell, with a short id of the chat after
it (``asha-3f9c2a``); a chat whose name changes keeps the folder its id already has. A file is named for when it was
sent, in the time of the workspace's owner, and what it is, with the name it was sent under when it had one:
``inbox/asha-3f9c2a/2026-11-14_2257_photo.jpg``, ``inbox/book-club-07d1e4/2026-11-14_2301_document_Q3-report.pdf``.
A name already taken (two photos in one minute) gets a short suffix (``_2``). A name is claimed before the bytes
arrive, so deliveries landing together never take the same one.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import posixpath
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Sequence, Tuple, Union
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

INBOX = "inbox"
MB = 1024 * 1024
# A saved file is held in memory between its download and its write.
MAX_BYTES = 25 * MB
# How long a name stays claimed: past the minute it names, and a clock's repeated hour.
CLAIM_S = 3 * 3600
_MAX_SUFFIX = 99
# Where the system's table picks an extension people don't use.
_EXTENSIONS = {"image/jpeg": ".jpg", "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
               "video/quicktime": ".mov", "text/plain": ".txt"}
_UNSAFE = re.compile(r"[^\w.-]+")
_CHAT_ID_CHARS = 6
_EXT = re.compile(r"^\.[A-Za-z0-9]{1,8}$")
FAILED = "saving it failed"
TOO_LARGE = f"it is over the {MAX_BYTES // MB} MB a saved file can be"
# A process with no Redis claims names in itself (an instance of one process).
_claimed_here: Dict[str, float] = {}


@dataclass(frozen=True)
class Workspace:
    """A conversation's durable workspace: its volume, where its turns mount it, and the zone its files are named in."""

    volume: str
    mount: str
    timezone: str = "UTC"


class Held:
    """A download's bytes as they stream past, up to ``cap``; past it, nothing is held (``over``)."""

    def __init__(self, cap: int = MAX_BYTES):
        self.cap = cap
        self.over = False
        self._data = bytearray()

    def add(self, chunk: bytes) -> None:
        if self.over:
            return
        if len(self._data) + len(chunk) > self.cap:
            self.over, self._data = True, bytearray()
            return
        self._data += chunk

    @property
    def data(self) -> bytes:
        return bytes(self._data)


@dataclass(frozen=True)
class Spot:
    """Where one file goes: ``inbox/<folder>/<name>`` in each workspace, claimed under ``keys``."""

    workspaces: Tuple[Workspace, ...]
    folder: str
    name: str
    keys: Tuple[str, ...]

    @property
    def rel(self) -> str:
        return f"{INBOX}/{self.folder}/{self.name}"

    @property
    def path(self) -> str:
        """Where a turn opens it: under its workspace's mount, when every workspace mounts in one place."""
        mounts = {w.mount for w in self.workspaces}
        return posixpath.join(mounts.pop(), self.rel) if len(mounts) == 1 else self.rel


def agent_inbox_volume(workflow_id: str, agent_node_id: str, conversation_key: Optional[str], nodes, edges):
    """The workspace (``WorkspaceSource``) an agent keeps a conversation's files in, as its turns mount it; None when
    the conversation has no durable one. Every inbox write resolves its volume here: today each conversation has its
    own workspace, and once an agent is one session with one workspace, this is the one line to change."""
    from utils.agent_workspace import resolve_workspace_source

    return resolve_workspace_source(workflow_id, agent_node_id, conversation_key, nodes, edges)


async def delivery_workspaces(pool, *, workflow_id: str, node_id: str, payload: Any,
                              conversation_key: Optional[str]) -> Sequence[Workspace]:
    """The workspaces a trigger's delivery lands in: the platform's word for a node it delivers itself
    (``DELIVERY_WORKSPACES``), else each live agent its event reaches (``agent_event_source_ids``, as
    ``AgentNode._find_fired_trigger``), in the conversation the agent adopts from the event's key."""
    from utils.capabilities import DELIVERY_WORKSPACES, capability

    platform = capability(DELIVERY_WORKSPACES)
    if platform is not None:
        found = await platform(pool, workflow_id=workflow_id, node_id=node_id, payload=payload)
        if found is not None:
            return found
    from coder.workflow.workflow_ops import agent_event_source_ids
    from nodes.agent.rehearsal import effective_conversation_key
    from utils.graph_nodes import graph_edges, graph_nodes, node_config, node_disabled, node_type

    graph = await pool.fetchval("SELECT workflow FROM workflows WHERE id = $1::uuid", workflow_id)
    nodes, edges = graph_nodes(graph), graph_edges(graph)
    spaces = []
    for agent in nodes:
        if node_type(agent) != "agent" or node_disabled(agent):
            continue
        if node_id not in agent_event_source_ids(agent.get("id"), nodes, edges):
            continue
        key = effective_conversation_key(None, conversation_key, node_config(agent).get("conversation_key"))
        source = agent_inbox_volume(workflow_id, agent["id"], key, nodes, edges)
        if source is not None:
            spaces.append(Workspace(source.volume_name, source.mount_path))
    return spaces


def chat_id(chat_key: str) -> str:
    """A chat's short id: the same chat always, another chat almost never."""
    return hashlib.sha256(str(chat_key).encode()).hexdigest()[:_CHAT_ID_CHARS]


def chat_folder(chat_key: str, chat_name: Optional[str] = None) -> str:
    """``asha-3f9c2a``: a chat's name (else its key's own part, a number), made safe for a shell, and its short id."""
    shown = _UNSAFE.sub("-", str(chat_name or str(chat_key).split("@", 1)[0])).strip("-._").lower()[:32]
    return f"{shown.strip('-._') or 'chat'}-{chat_id(chat_key)}"


def extension(mimetype: Optional[str]) -> str:
    base = str(mimetype or "").split(";", 1)[0].strip().lower()
    return _EXTENSIONS.get(base) or (mimetypes.guess_extension(base) if base else None) or ".bin"


def file_name(kind: str, sent_at: datetime, zone: str, *, original: Optional[str] = None,
              mimetype: Optional[str] = None, suffix: int = 1) -> str:
    """``2026-11-14_2257_photo.jpg``: when it was sent in ``zone``, what it is, the name it was sent under (made safe
    for a shell), ``_<suffix>`` past the first, and its extension (the sent name's, else its type's)."""
    stem, ext = posixpath.splitext(posixpath.basename(str(original or "")))
    if not _EXT.match(ext):
        stem, ext = f"{stem}{ext}", ""
    sent = _UNSAFE.sub("-", stem).strip("-._")[:60]
    parts = [sent_at.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d_%H%M"), kind, *([sent] if sent else [])]
    return "_".join(parts) + (f"_{suffix}" if suffix > 1 else "") + (ext.lower() or extension(mimetype))


async def reserve(workspaces: Sequence[Workspace], kind: str, sent_at: datetime, *, chat_key: str,
                  chat_name: Optional[str] = None, original: Optional[str] = None,
                  mimetype: Optional[str] = None) -> Optional[Spot]:
    """A name free in the chat's inbox folder of every workspace, claimed; None when no workspace takes the file. The
    folder is the one the chat's id already has (its name may have changed since), else a new one."""
    if not workspaces:
        return None
    from utils.volume_backend import get_volume_backend

    backend = get_volume_backend()
    tail = f"-{chat_id(chat_key)}"
    listings = await asyncio.gather(*(backend.list_entries(w.volume, INBOX) for w in workspaces))
    held = sorted(posixpath.basename(e["path"]) for listing in listings for e in listing["entries"]
                  if e["type"] == "dir" and e["path"].endswith(tail))
    folder = held[0] if held else chat_folder(chat_key, chat_name)
    listings = await asyncio.gather(*(backend.list_entries(w.volume, f"{INBOX}/{folder}") for w in workspaces))
    taken = {posixpath.basename(e["path"]) for listing in listings for e in listing["entries"]}
    for suffix in range(1, _MAX_SUFFIX + 1):
        name = file_name(kind, sent_at, workspaces[0].timezone, original=original, mimetype=mimetype, suffix=suffix)
        if name in taken:
            continue
        keys = tuple(f"agent_inbox:{w.volume}:{folder}/{name}" for w in workspaces)
        if await _claim(keys):
            return Spot(tuple(workspaces), folder, name, keys)
    raise RuntimeError(f"no free name in {INBOX}/{folder}/ for a {kind} sent {sent_at.isoformat()}")


async def _claim(keys: Tuple[str, ...]) -> bool:
    from utils.redis_client import get_shared_redis

    client = get_shared_redis()
    if client is None:
        now = time.monotonic()
        for key in [k for k, until in _claimed_here.items() if until < now]:
            del _claimed_here[key]
        if any(k in _claimed_here for k in keys):
            return False
        _claimed_here.update({k: now + CLAIM_S for k in keys})
        return True
    got = []
    for key in keys:
        if not await client.set(key, b"1", ex=CLAIM_S, nx=True):
            if got:
                await client.delete(*got)
            return False
        got.append(key)
    return True


async def release(spot: Spot) -> None:
    """Free the name of a file that wasn't written."""
    from utils.redis_client import get_shared_redis

    client = get_shared_redis()
    if client is None:
        for key in spot.keys:
            _claimed_here.pop(key, None)
        return
    try:
        await client.delete(*spot.keys)
    except Exception:
        logger.warning("[agent_inbox] releasing %s failed; its claim expires", spot.rel, exc_info=True)


async def keep(spot: Union[Spot, BaseException, None], held: Held, *, deadline: float,
               what: str) -> Optional[Dict[str, Any]]:
    """What a delivered file's media slot says of the inbox: ``{"path", "folder", "name"}`` once it's written in every
    workspace; ``{"error"}`` when it couldn't be, logged at ERROR (the message still runs, with its link); None when no
    agent's workspace takes the delivery. ``spot`` is ``reserve``'s answer, or what it raised; ``what`` names the
    delivery in the log; ``deadline`` (the loop's clock) bounds the write."""
    if spot is None:
        return None
    if isinstance(spot, BaseException):
        logger.error(f"[agent_inbox] {what}: no place found to save it: {type(spot).__name__}: {spot}")
        return {"error": FAILED}
    if held.over:
        await release(spot)
        logger.error(f"[agent_inbox] {what}: not saved, {TOO_LARGE}")
        return {"error": TOO_LARGE}
    from utils.volume_backend import get_volume_backend

    backend, data = get_volume_backend(), held.data
    try:
        async with asyncio.timeout_at(deadline):
            await asyncio.gather(*(backend.write_file(w.volume, spot.rel, data) for w in spot.workspaces))
    except Exception as e:
        await release(spot)
        logger.error(f"[agent_inbox] {what}: saving {spot.rel} failed: {type(e).__name__}: {e}")
        return {"error": FAILED}
    logger.info(f"[agent_inbox] {what}: saved {len(data)} bytes as {spot.path} "
                f"({', '.join(w.volume for w in spot.workspaces)})")
    return {"path": spot.path, "folder": spot.folder, "name": spot.name}
