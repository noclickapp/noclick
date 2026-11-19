"""Approvals: the calls NoClick holds for your account's owner's yes, read and answered from your own code.

When an agent, a connected app, a key used through MCP or an app's own code makes a purchase, a deletion that can't
be undone, a call your policy holds or one that raises a spending limit, NoClick holds the exact call and sends your
account's owner a link to approve it. Your code may answer it too, with one of your account's secret keys that
names the ``approvals:answer`` scope (a key with every scope, ``*``, holds it only when it's named too)::

    for approval in noclick.Approval.list(status="pending"):
        if approval.price and approval.price["amount_usd"] <= 20:
            approval.approve(note="Under $20: fine.")

A key never answers a call made with it (by its own code, through MCP, or by an agent or app acting as it), never
approves one whose terms a person accepts (it may decline it), and approves only what it could make itself: the
scopes the call needs (never a call only the owner and their NoClick assistant make), and a price that fits the key's
own monthly cap beside what it spent and approved this month. NoClick then runs an approved call itself, once, exactly
as it was held, with no scope the answering key lacks. While your account holds such a key, a call whose link reaches
no person is still held, with an empty ``sent_to``, for your code to answer.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import _Object, compact, field, list_all, parse_time
from ._sync import synced
from ._scope import AMBIENT

STATUSES = ("pending", "approved", "declined", "expired", "used", "canceled")


class Approval(_Object):
    """A call held for your account's owner's yes, as they see it on its page."""

    _repr_keys = ("id", "status", "action")

    id: str = field("id")
    status: str = field("status", doc=f"One of {', '.join(STATUSES)} (``used``: approved, and run).")
    action: Optional[str] = field("action", doc="What the call does, in a person's words.")
    price: Optional[Dict[str, Any]] = field(
        "price", doc="A purchase's price: ``amount_usd``, ``recurrence``, ``terms`` and ``renewal``; None for "
        "anything else.",
    )
    reason: Optional[str] = field("reason", doc="Why it waits for a person.")
    operation: str = field("operation", doc="The API operation it calls, by name (``phone_numbers_create``).")
    method: Optional[str] = field("method")
    path: Optional[str] = field("path")
    arguments: Dict[str, Any] = field("arguments", doc="Its arguments as the page shows them, secrets masked.")
    connection: Dict[str, Any] = field(
        "connection", doc="Who made it: ``kind`` (``assistant``, ``agent``, ``connected_app`` or ``key``) and "
        "``name``.",
    )
    user_id: Optional[str] = field("user_id", doc="The user it acts for (None for your account).")
    operation_id: str = field(
        "operation_id", doc="The held call's operation: ``noclick.Operation.from_id(...).wait()`` gives what it "
        "returned once approved, or raises once declined or expired.",
    )
    impact: Optional[Dict[str, Any]] = field("impact", doc="What a deletion takes with it; None for anything else.")
    consent: List[Dict[str, Any]] = field(
        "consent", doc="Terms a person accepts by approving it (each ``terms``, ``title``, ``url``): only the owner "
        "approves such a call.",
    )
    sent_to: List[str] = field("sent_to", doc="Where NoClick sent the owner its link: ``whatsapp``, ``imessage``, "
                               "``email``, or ``web`` (a card in the chat they were watching); empty when it reached "
                               "nobody and waits for your code.")
    created_at: Any = field("created_at", parse_time)
    expires_at: Any = field("expires_at", parse_time, doc="When it lapses unanswered (a day after it was held).")
    decided_at: Any = field("decided_at", parse_time)
    decided_by: Optional[str] = field(
        "decided_by", doc="Who decided: ``owner`` (signed in, or from NoClick's link) or ``code``; None while "
        "pending.",
    )
    decided_by_key: Optional[Dict[str, Any]] = field(
        "decided_by_key", doc="The key whose code decided (``key_id``, ``key_name``); None otherwise.",
    )
    note: Optional[str] = field("note", doc="What whoever decided wrote with it.")

    @classmethod
    def from_id(cls, approval_id: str, *, client: Optional[Client] = None) -> "Approval":
        """A lazy reference to an approval by its id (an ``noclick.ApprovalRequired``'s ``approval_id``).

        Returns:
            The approval; it loads the first time it's used.

        Usage::

            approval = noclick.Approval.from_id(held.approval_id)
            print(approval.status, approval.action, approval.price)
        """
        return cls._new(hints={"id": approval_id}, client=client, user=None)

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", self._path(), user=None)

    def _path(self, suffix: str = "") -> str:
        return f"/v1/approvals/{quote(str(self._known('id')), safe='')}{suffix}"

    @synced
    @classmethod
    async def list(
        cls, *, status: Optional[str] = None, limit: Optional[int] = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Approval"]:
        """Calls held for your account's owner's yes, newest first: the first 20, or the first ``limit`` (at
        most 100), with ``status`` one of ``pending``, ``approved``, ``declined``, ``expired``, ``used`` or
        ``canceled``. Acting for a user, that user's alone.

        Returns:
            Each approval as its page shows it.

        Usage::

            for approval in noclick.Approval.list(status="pending"):
                print(approval.action, approval.connection["name"], approval.expires_at)
        """
        return await list_all("/v1/approvals", lambda raw, _scope: cls._new(raw=raw, client=client, user=None),
                              params={"status": status}, user=user, limit=limit, client=client)

    async def _answer(self, approved: bool, note: Optional[str]) -> "Approval":
        self._raw = await resolve_client(self._client).request(
            "POST", self._path("/answer"), json=compact(approved=approved, note=note), user=None)
        return self

    @synced
    async def approve(self, *, note: Optional[str] = None) -> "Approval":
        """Approve it from your own code, with one of your account's secret keys that names the
        ``approvals:answer`` scope; NoClick then runs the call itself, once, exactly as it was held. Refused
        with ``noclick.PermissionDenied`` for the key the call was made with, a call whose terms a person
        accepts, one needing a scope the key lacks or only the owner makes, a key acting for a user, and a key
        without the scope; with ``noclick.SpendCapExceeded`` when its price, beside what the key spent and
        approved this month, is past the key's own monthly cap.

        Returns:
            This approval, answered: ``status`` is ``approved``, then ``used`` once the call ran;
            ``decided_by`` is ``code``.

        Usage::

            approval = noclick.Approval.from_id(held.approval_id)
            approval.approve(note="Within this week's budget.")
            noclick.Operation.from_id(approval.operation_id).wait()
        """
        return await self._answer(True, note)

    @synced
    async def decline(self, *, note: Optional[str] = None) -> "Approval":
        """Decline it from your own code, as ``approve`` answers it: the call never runs, and whoever made it
        is told why, with your ``note``. A call whose terms a person accepts may be declined from code too.

        Returns:
            This approval, answered: ``status`` is ``declined``.

        Usage::

            for approval in noclick.Approval.list(status="pending"):
                if approval.impact:
                    approval.decline(note="Deletions wait for Monday's review.")
        """
        return await self._answer(False, note)
