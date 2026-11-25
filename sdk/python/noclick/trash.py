"""The trash: what was deleted and can still be put back.

Deleting an app, database, bucket, dict, queue, repo, volume, inbox or agent
moves it here, restorable for 30 days, then purged for good. ``delete()`` on each of
them returns its ``TrashItem``::

    item = noclick.Dict.from_name("rates-cache").delete()
    item.restore()   # back under its name, every key with it

A database's restore lands what it rewound here too, as a ``database_copy``:
restoring that puts it back into its database. While it's in the trash its
name is free and its storage is billed as before; restoring is free.
``purge()`` deletes it for good now: the one deletion that can't be undone, so
through MCP it waits for a person.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client
from ._object import Page, _Object, field, list_all, list_page, parse_time
from ._sync import synced
from ._scope import AMBIENT, resolve_scope

KINDS = ("project", "database", "database_copy", "bucket", "dict", "queue", "repo", "volume", "inbox", "agent",
         "skill", "memory")


class TrashItem(_Object):
    """Something deleted, restorable until ``purge_after``."""

    _repr_keys = ("id", "kind", "name")

    id: str = field("id")
    kind: str = field("kind", doc=f"What it is: one of {', '.join(KINDS)}.")
    resource_id: str = field("resource_id", doc="Its id as it was, and will be again once restored.")
    name: Optional[str] = field("name")
    user_id: Optional[str] = field("user_id", doc="The user it was deleted from (None for the account's).")
    trashed_at: Any = field("trashed_at", parse_time)
    purge_after: Any = field("purge_after", parse_time, doc="When it's purged for good unless restored first.")
    operation_id: Optional[str] = field(
        "operation_id", doc="The deletion's operation (on the item a ``delete()`` returned): ``Operation.undo()`` "
        "on it restores it too.",
    )

    @classmethod
    def from_id(cls, trash_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "TrashItem":
        """A lazy reference to an item in the trash by its id.

        Returns:
            The item; it loads the first time it's used.

        Usage::

            item = noclick.TrashItem.from_id("4b1e2c7d-0a9f-4e6b-8c3d-5f2a1b7e9d60")
            print(item.kind, item.name, item.purge_after)
        """
        return cls._new(hints={"id": trash_id}, client=client, user=resolve_scope(user))

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", self._path())

    def _path(self, suffix: str = "") -> str:
        return f"/v1/trash/{quote(str(self._known('id')), safe='')}{suffix}"

    @synced
    @classmethod
    async def list(
        cls, *, kind: Optional[str] = None, limit: Optional[int] = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["TrashItem"]:
        """What's in the trash, newest first: every kind, or one (``kind="dict"``).

        Returns:
            Each item, with when it's purged unless restored first.

        Usage::

            for item in noclick.TrashItem.list(kind="database"):
                print(item.name, item.trashed_at, item.purge_after)
        """
        return await list_all("/v1/trash", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
                              params={"kind": kind}, user=user, limit=limit, client=client)

    @synced
    @classmethod
    async def list_page(
        cls, *, kind: Optional[str] = None, cursor: Optional[str] = None, limit: Optional[int] = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of the trash; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the items and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.TrashItem.list_page(limit=20)
            print([item.name for item in page.data])
        """
        return await list_page("/v1/trash", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
                               params={"kind": kind}, user=user, cursor=cursor, limit=limit, client=client)

    @synced
    async def restore(self) -> Dict[str, Any]:
        """Put it back where it was, under its name, with everything in it. Refused with ``noclick.Conflict``
        when something new has taken its name since (rename or delete that first). A ``database_copy`` goes back
        into its database: a restore of its own (its ``operation``), which keeps what the database holds now as a
        copy the same way.

        Returns:
            The restored resource as its own API shows it, with ``restored: True``.

        Usage::

            item = noclick.Database.from_name("orders").delete()
            restored = item.restore()
            print(restored["name"], restored["status"])
        """
        return await self._request("POST", self._path("/restore"))

    @synced
    async def purge(self) -> None:
        """Delete it for good now rather than when ``purge_after`` comes: the one deletion that can't be undone.

        Usage::

            for item in noclick.TrashItem.list(kind="bucket"):
                item.purge()
        """
        await self._request("DELETE", self._path())


@dataclass(frozen=True)
class DeletePreview:
    """What a deletion would do, in words a person reads before agreeing: what it ``deletes``, what stops working
    (``depends_on_it``), the data that goes (``data_lost``), what stops being billed (``stops_billing``), and whether
    it's ``reversible`` and how (``undo``). Nothing is deleted by asking. ``confirm_token`` is what a call through
    MCP sends to confirm it, within ``expires_in_s``."""

    deletes: str
    depends_on_it: List[str]
    data_lost: List[str]
    stops_billing: List[str]
    reversible: bool
    undo: Optional[str]
    confirm_token: Optional[str]
    expires_in_s: Optional[int]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "DeletePreview":
        raw = raw if isinstance(raw, dict) else {}
        impact = raw.get("impact") or {}
        return cls(impact.get("deletes") or "", list(impact.get("depends_on_it") or []),
                   list(impact.get("data_lost") or []), list(impact.get("stops_billing") or []),
                   bool(impact.get("reversible")), impact.get("undo"), raw.get("confirm_token"),
                   raw.get("expires_in_s"), raw)


def trashed(raw: Dict[str, Any], *, client: Optional[Client], user: Any) -> TrashItem:
    """The ``TrashItem`` a delete answered with."""
    return TrashItem._new(raw={**raw["trash"], "operation_id": raw.get("operation_id")}, client=client, user=user)
