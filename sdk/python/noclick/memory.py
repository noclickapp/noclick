"""Memories: named notes any agent of their scope can attach.

    company = noclick.Memory.from_name("company", create_if_missing=True)
    company.save("refunds", "Within 30 days, to the original card.", description="Our refund rules")
    support = noclick.Agent.from_name("support", create_if_missing=True, instructions="...",
                                      memories=[company])              # it reads company
    closer = noclick.Agent.from_name("closer", create_if_missing=True, instructions="...",
                                     memories=[company.writable()])     # it reads and writes it

Every agent also has a memory of its own, ``agent.memory``, which it always
reads and writes. A memory attached to it is read-only unless attached with
``writable()``; every turn starts with the names and descriptions of every
entry it can read, its own memory's first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import Page, _Object, compact, field, list_all, list_page, parse_time, ref_id
from ._scope import AMBIENT, resolve_scope
from ._sync import synced
from .agent_extras import AgentMemory, MemoryEntry, MemoryEntryVersion
from .exceptions import Conflict, NotFound
from .trash import TrashItem, trashed
from .volume import is_id


@dataclass(frozen=True)
class MemoryLink:
    """A memory attached with writes (``memory.writable()``): the agent may change it as well as read it."""

    memory: Any
    writes: bool = True


class Memory(_Object):
    """Named notes any agent of its scope can attach: the account's (every user's
    agents may read them) or one user's. Its entries are what ``agent.memory``
    holds: a name, a one-line description, Markdown content and a version.

    A memory of the account keeps two layers, as an account agent's own memory
    does: its own entries, and each user's, which only that user's
    conversations see. A user's memory keeps one, its user's.
    """

    _repr_keys = ("id", "name")

    id: str = field("id")
    name: Optional[str] = field("name", doc="Its name, unique in its scope (``None`` for an agent's own memory).")
    description: Optional[str] = field("description", doc="One line saying what it holds.")
    agent_id: Optional[str] = field(
        "agent_id", doc="The agent whose own memory this is (``None`` for a memory with a name).",
    )
    attached_to: List[Dict[str, Any]] = field(
        "attached_to", doc="The agents that attach it besides: each one's ``id``, ``name`` and whether it ``writes``.",
    )
    entry_count: Optional[int] = field("entry_count", doc="How many entries it holds, in all its layers.")
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)
    updated_at: Any = field("updated_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls, name: str, *, description: Optional[str] = None, allow_existing: bool = False, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Memory":
        """Create an empty memory called ``name`` (1-64 letters, digits and
        ``. _ -``), unique to its user, or to the account outside ``as_user`` (a
        taken name raises ``noclick.Conflict`` with ``existing_id``, or with
        ``allow_existing=True`` returns the memory already there, entries and description as they are).

        Returns:
            The new, empty memory.

        Usage::

            company = noclick.Memory.create("company", description="What every agent should know")
            company.save("tone", "Warm and brief.", description="How we write")
        """
        scope = resolve_scope(user)
        raw = await cls._create_named("/v1/memories", compact(name=name, description=description),
                                      allow_existing=allow_existing, user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls, name: str, *, create_if_missing: bool = False, description: Optional[str] = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Memory":
        """A lazy reference to the memory called ``name``. Acting for a user,
        that user's own memory is found first, then the account's. With
        ``create_if_missing=True`` the current (or given) user's is created on
        first use.

        Returns:
            A memory that loads (or is created) the first time it's used. Nothing is sent yet.

        Usage::

            company = noclick.Memory.from_name("company", create_if_missing=True)
            support = noclick.Agent.from_name("support", create_if_missing=True,
                                              instructions="Answer billing questions.", memories=[company])
        """
        memory = cls._new(hints={"name": name}, client=client, user=user)
        if create_if_missing:
            memory._create_with = compact(name=name, description=description)
        return memory

    @classmethod
    def from_id(cls, memory_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Memory":
        """A lazy reference to a memory by id, such as an agent's own (``agent.memory_id``).

        Returns:
            A memory that loads the first time you read a field. Nothing is sent yet.

        Usage::

            support = noclick.Agent.from_name("support")
            own = noclick.Memory.from_id(support.memory_id)
            print(own.entry_count)
        """
        return cls._new(hints={"id": memory_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, memory_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Memory":
        """Load a memory by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The memory, loaded: who attaches it and how many entries it holds.

        Usage::

            company = noclick.Memory.get("5d1c9a3e-7b2f-4e60-8a19-3c4d6e8f0b21")
            print(company.name, company.entry_count, company.attached_to)
        """
        memory = cls.from_id(memory_id, client=client, user=user)
        await memory._ensure()
        return memory

    @synced
    @classmethod
    async def list(
        cls, *, agent: Any = None, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Memory"]:
        """The current user's named memories and the account's (or those ``user_filter`` covers).
        An agent's own memory isn't listed: it's ``agent.memory``. With ``agent`` (an ``Agent`` or its id),
        what that agent reads: its own memory first, then those it attaches, in its order.

        Returns:
            Every matching memory, newest first, fetched page by page.

        Usage::

            for memory in noclick.Memory.list():
                print(memory.name, memory.entry_count, memory.user_id)   # user_id is None for the account's
            reads = noclick.Memory.list(agent=noclick.Agent.from_name("support"))
        """
        return await list_all(
            "/v1/memories", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params=compact(agent_id=await ref_id(agent) if agent is not None else None),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of named memories; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the memories and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Memory.list_page(limit=50)
            for memory in page.data:
                print(memory.name)
        """
        return await list_page(
            "/v1/memories", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        memory_id = self._known("id")
        if memory_id:
            return await self._request("GET", f"/v1/memories/{memory_id}")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/memories", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        # This scope's own memory first; a definition is only ever for its own.
        own = [row for row in rows if bool(row.get("user_id")) == bool(self._scope)]
        rows = own if self._create_with is not None else own + [row for row in rows if row not in own]
        if rows:
            return rows[0]
        if self._create_with is None:
            raise NotFound(
                f"No memory is named {name!r}.",
                next_step="Create it with noclick.Memory.create(...) or pass create_if_missing=True.",
                details={"name": name, "kind": "memory"},
            )
        try:
            return await self._request("POST", "/v1/memories", json=self._create_with)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._request("GET", f"/v1/memories/{exc.existing_id}")

    async def _url(self, suffix: str = "") -> str:
        if not self._known("id"):
            await self._ensure()
        return f"/v1/memories/{self._known('id')}{suffix}"

    def _layer(self, user: Any) -> Any:
        """Whose layer a call reads or writes: a user's memory's own user's, else the acting user's."""
        owner = self._owner_scope((self._raw or {}).get("user_id"))
        return owner if owner else resolve_scope(user)

    # --- the memory ------------------------------------------------------

    def writable(self) -> MemoryLink:
        """This memory, for an agent's ``memories=``, with writes: the agent may save to it and forget from it,
        not only read it. Only a call acting for the memory's own scope can attach it so.

        Returns:
            What ``memories=`` takes for a memory the agent writes.

        Usage::

            team = noclick.Memory.from_name("team-notes", create_if_missing=True)
            noclick.Agent.from_name("scribe", create_if_missing=True, instructions="Keep the team's notes.",
                                    memories=[team.writable()])
        """
        return MemoryLink(self)

    @synced
    async def update(self, *, name: Optional[str] = None, description: Optional[str] = None) -> "Memory":
        """Rename it, or change its description. An agent's own memory takes no name.

        Returns:
            This memory, as it is now.

        Usage::

            noclick.Memory.from_name("company").update(name="handbook")
        """
        self._raw = await self._request("PATCH", await self._url(), json=compact(name=name, description=description))
        return self

    @synced
    async def delete(self) -> TrashItem:
        """Delete the memory and every entry in it: it goes to the trash, restorable for 30 days, and comes off
        every agent that attaches it (``attached_to``); restoring puts it back on them. An agent's own memory goes
        only with its agent (``noclick.Conflict``).

        Returns:
            Its ``TrashItem``: ``restore()`` puts it back.

        Usage::

            noclick.Memory.from_name("old-notes").delete()
        """
        raw = await self._request("DELETE", await self._url())
        return trashed(raw, client=self._client, user=self._call_scope())

    # --- entries ---------------------------------------------------------

    @synced
    async def entries(self, *, user: Any = AMBIENT) -> List[MemoryEntry]:
        """The entries of one layer: the account's outside ``as_user``, else the user's.

        Returns:
            Each entry's name, description, version and when it last changed, by name; ``content`` is ``None``
            here, so ``read`` an entry for its body.

        Usage::

            for entry in noclick.Memory.from_name("company").entries():
                print(entry.name, entry.description)
        """
        response = await self._request("GET", await self._url("/entries"), user=self._layer(user)) or {}
        return [MemoryEntry._from(row) for row in response.get("data") or []]

    @synced
    async def search(self, query: str, *, limit: Optional[int] = None, user: Any = AMBIENT) -> List[MemoryEntry]:
        """Search the memory the way an agent does: a user's entries and the account's. An entry matches when
        its name, description or content holds any of the query's words (``refund`` finds ``refunds``), or its
        name or description holds the query.

        Returns:
            The best matches first (10 unless ``limit`` says otherwise, at most 100), with their ``content``.

        Usage::

            for entry in noclick.Memory.from_name("company").search("refund policy"):
                print(entry.name, entry.content)
        """
        response = await self._request("GET", await self._url("/entries"), params={"q": query, "limit": limit},
                                       user=self._layer(user)) or {}
        return [MemoryEntry._from(row) for row in response.get("data") or []]

    @synced
    async def read(self, name: str, *, user: Any = AMBIENT) -> MemoryEntry:
        """One entry in full; a name with no entry raises ``noclick.NotFound``.

        Returns:
            The entry with its ``content`` and the ``version`` to pass back when you change it.

        Usage::

            tone = noclick.Memory.from_name("company").read("tone")
            print(tone.version, tone.content)
        """
        return MemoryEntry._from(
            await self._request("GET", await self._url(f"/entries/{quote(name, safe='')}"), user=self._layer(user)))

    @synced
    async def save(
        self, name: str, content: str, *, description: Optional[str] = None, version: Optional[int] = None,
        user: Any = AMBIENT,
    ) -> MemoryEntry:
        """Write an entry, creating it if the name is new. ``description`` is the
        line every agent attaching the memory sees each turn (required for a new
        entry, kept when you leave it out). With ``version``, the save only lands
        if the entry is still at that version, else ``noclick.Conflict``.

        Returns:
            The entry as saved, with its new ``version``.

        Usage::

            company = noclick.Memory.from_name("company", create_if_missing=True)
            company.save("tone", "Warm and brief, no jargon.", description="How we write")
        """
        body = compact(content=content, description=description, version=version)
        return MemoryEntry._from(await self._request(
            "PUT", await self._url(f"/entries/{quote(name, safe='')}"), json=body, user=self._layer(user)))

    @synced
    async def versions(self, name: str, *, user: Any = AMBIENT) -> List[MemoryEntryVersion]:
        """An entry's versions, newest first: the one it holds now, then those kept from earlier saves (its last
        50 in all). A name with no entry raises ``noclick.NotFound``.

        Returns:
            Each version's number, description, who wrote it and when, without its ``content``.

        Usage::

            for v in noclick.Memory.from_name("company").versions("tone"):
                print(v.version, v.current, v.written_by.type, v.saved_at)
        """
        response = await self._request("GET", await self._url(f"/entries/{quote(name, safe='')}/versions"),
                                       user=self._layer(user)) or {}
        return [MemoryEntryVersion._from(row) for row in response.get("data") or []]

    @synced
    async def get_version(self, name: str, version: int, *, user: Any = AMBIENT) -> MemoryEntryVersion:
        """One version of an entry, with its content; one it no longer keeps raises ``noclick.NotFound``.

        Returns:
            That version in full.

        Usage::

            first = noclick.Memory.from_name("company").get_version("tone", 1)
            print(first.content)
        """
        return MemoryEntryVersion._from(await self._request(
            "GET", await self._url(f"/entries/{quote(name, safe='')}/versions/{version}"), user=self._layer(user)))

    @synced
    async def restore(self, name: str, version: int, *, user: Any = AMBIENT) -> MemoryEntry:
        """Put an entry back as it was at ``version``: a new version holding that one's content and description,
        so the one it replaces is kept too.

        Returns:
            The entry as restored, at its new ``version``.

        Usage::

            noclick.Memory.from_name("company").restore("tone", 1)
        """
        return MemoryEntry._from(await self._request(
            "POST", await self._url(f"/entries/{quote(name, safe='')}/versions/{version}/restore"),
            user=self._layer(user)))

    @synced
    async def forget(self, name: str, *, version: Optional[int] = None, user: Any = AMBIENT) -> None:
        """Forget an entry. With ``version``, only if it is still at that version (else ``noclick.Conflict``).

        Returns:
            None once it's gone; a name with no entry raises ``noclick.NotFound``.

        Usage::

            noclick.Memory.from_name("company").forget("old-pricing")
        """
        await self._request("DELETE", await self._url(f"/entries/{quote(name, safe='')}"),
                            params=compact(version=version), user=self._layer(user))


def memory_refs(memories: Optional[Sequence[Any]], *, user: Any, client: Optional[Client]) -> Optional[List[Any]]:
    """``memories=`` on an agent: ``Memory``s (``memory.writable()`` to let it write one), an agent's
    ``agent.memory``, or a memory's id or name, looked up lazily in ``user`` (its own, then the account's)."""
    if memories is None:
        return None
    if isinstance(memories, (str, Memory, MemoryLink, AgentMemory)):
        raise TypeError("memories= is a list: memories=[noclick.Memory.from_name('company')]")
    refs: List[Any] = []
    for memory in memories:
        if isinstance(memory, str):
            memory = (Memory.from_id(memory, user=user, client=client) if is_id(memory)
                      else Memory.from_name(memory, user=user, client=client))
        if not isinstance(memory, (Memory, MemoryLink, AgentMemory)):
            raise TypeError(f"memories= takes noclick.Memory, memory.writable(), agent.memory or a memory's id or "
                            f"name, not {type(memory).__name__}")
        refs.append(memory)
    return refs


async def _memory_id(memory: Any) -> str:
    if isinstance(memory, AgentMemory):
        return (await memory._agent._ensure())["memory_id"]
    return await ref_id(memory)


async def memory_links(refs: Sequence[Any]) -> List[Dict[str, Any]]:
    """``memories`` as the API takes and shows it: ``[{id, writes}]``, in order."""
    return [{"id": await _memory_id(ref.memory if isinstance(ref, MemoryLink) else ref),
             "writes": isinstance(ref, MemoryLink)} for ref in refs]
