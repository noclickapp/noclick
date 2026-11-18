"""Inboxes: an email address your code or agent receives mail at.

    inbox = noclick.Inbox.create(local_part="signup")
    print(inbox.address)
    mail = inbox.wait_for(sender="noreply@github.com", subject_contains="code", timeout_s=300).wait()
    print(mail.text)

With ``agent=``, every inbound message wakes that agent, in its email
thread's own conversation (``message.conversation``), and the agent answers on
the thread with a ``reply`` tool bound to the thread's latest message. Replies
go to the sender only; an inbox on a domain you bought also writes new mail to
one person at a time (``inbox.send``). Inboxes have
names (``Inbox.from_name``). Mail proven to be from one of your users runs as
that user, and ``senders`` says whose mail wakes the agent.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field as dc_field
from typing import Any, AsyncIterator, Dict, List, Optional

from ._client import Client, resolve_client
from ._object import (
    UNSET, Page, _Object, check_unchanged, compact, field, iso_time, list_all, list_page, parse_time,
)
from ._sync import run_sync, synced
from ._scope import AMBIENT, resolve_scope
from .agent import agent_id
from .domain import domain_name
from .exceptions import Conflict, NotFound
from .operation import Operation, register_result
from .trash import TrashItem, trashed

# Long-poll window per request (``wait_s``).
_STREAM_WAIT_S = 25
# Whose mail wakes an inbox's agent.
SENDERS = ("anyone", "users", "owner")
# What ``from_name`` sets on an existing inbox.
_CONVERGED = ("agent_id", "senders", "conversation")


def _check_senders(senders: Any) -> None:
    if senders is not None and senders is not UNSET and senders not in SENDERS:
        raise ValueError(f"senders must be one of {SENDERS}, not {senders!r}")


@dataclass(frozen=True)
class InboxReply:
    """What ``message.reply(...)`` sent: ``status`` is ours, ``delivery_status`` the mail provider's."""

    id: Optional[str]
    status: Optional[str]
    delivery_status: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)


def _detail(key: str, default: Any = None, doc: Optional[str] = None) -> property:
    """A field only the full message view is sure to carry: a message from a
    listing loads it on first read."""

    def getter(self: "InboxMessage") -> Any:
        raw = self._sync_raw()
        if key not in raw and not self._full:
            raw = run_sync(self._fetch_full())
        value = raw.get(key)
        return default if value is None else value

    return property(getter, doc=doc or f"The message's ``{key}``.")


class InboxMessage(_Object):
    """One email an inbox received (or, in a thread, sent). ``message.reply("...")`` answers the sender."""

    _repr_keys = ("id", "from", "subject")

    id: str = field("id")
    inbox_id: Optional[str] = field("inbox_id")
    direction: Optional[str] = field("direction", doc="``inbound`` (received), or ``outbound``: mail the inbox sent "
                                            "(a reply, or new mail), in a thread's messages.")
    status: Optional[str] = field("status", doc="``received``; for mail the inbox sent, ``sending`` (queued), "
                                      "``sent`` or ``failed`` (it never went: ``delivery_error`` says why).")
    delivery_status: Optional[str] = field(
        "delivery_status", doc="How mail the inbox sent landed: ``delivered``, ``bounced``, ``complained`` or "
                               "``failed``; None until the receiving server answers.")
    delivery_error: Optional[str] = field("delivery_error", doc="Why sent mail failed or bounced, when it did.")
    sender: Optional[str] = field(
        "from", doc="Who sent it: the message's From address when a DKIM signature aligned with it verified (as "
                    "for mail a sending service delivers under its own bounce address), else the envelope sender. "
                    "``sender_source`` says which.")
    sender_source: Optional[str] = field(
        "from_source", doc="Where ``sender`` comes from: ``header`` (the From address, vouched for by an aligned "
                           "DKIM signature) or ``envelope`` (the envelope sender). None for mail the inbox sent.")
    envelope_sender: Optional[str] = field(
        "envelope_from", doc="The envelope sender (SMTP MAIL FROM), often a sending service's bounce address. None "
                             "for mail the inbox sent.")
    authenticated: Optional[bool] = field(
        "authenticated", doc="Whether ``sender`` is vouched for, by an aligned DKIM signature (or, for the envelope "
                             "sender, SPF). ``wait_for(sender=...)`` matches only authenticated mail. Who the mail "
                             "runs as, and whether it's from the inbox's own person, is decided on the envelope "
                             "sender alone.")
    to: Any = field("to")
    subject: Optional[str] = field("subject")
    received_at: Any = field("received_at", parse_time)
    text: str = _detail("text", "", doc="The body as text.")
    html: Optional[str] = _detail("html", doc="The HTML body, if it had one.")
    attachments: List[Dict[str, Any]] = _detail(
        "attachments", [],
        doc="Attachments: ``name``, ``mime_type``, ``size_bytes``, ``url``, and ``text`` once digested "
            "(documents always; audio and video when the inbox has an agent).")
    conversation: Optional[str] = _detail(
        "conversation",
        doc="The conversation its email thread is with the inbox's agent: every message of one thread shares it. "
            "A message from one of your users is in that user's conversations (``agent.history(conversation, "
            "user=...)``).")
    agent_error: Optional[str] = _detail(
        "agent_error",
        doc="Why the message didn't wake the inbox's agent, or why the turn it woke failed: a sender ``senders`` "
            "doesn't let in, a paused agent, a spent budget, the turn's own error. None otherwise.")
    _agent_operation_id: Optional[str] = _detail("agent_operation_id")

    def _init(self, **kwargs: Any) -> None:
        self._full = False
        super()._init(**kwargs)

    @classmethod
    def _from_view(cls, raw: Dict[str, Any], *, inbox_id: Optional[str], client: Optional[Client], user: Any,
                   full: bool = False) -> "InboxMessage":
        message = cls._new(raw=raw, hints=compact(inbox_id=inbox_id), client=client, user=user)
        message._full = full
        return message

    def _path(self) -> str:
        return f"/v1/inboxes/{self._known('inbox_id')}/messages/{self._known('id')}"

    async def _load(self) -> Dict[str, Any]:
        raw = await self._request("GET", self._path())
        self._full = True
        return raw

    async def _fetch_full(self) -> Dict[str, Any]:
        self._raw = {**(self._raw or {}), **await self._load()}
        return self._raw

    def __str__(self) -> str:
        return self.text

    @property
    def agent_operation(self) -> Optional[Operation]:
        """The agent turn this message woke, if it woke one: ``.wait()`` gives the ``AgentReply``.
        ``agent_error`` says why there's none, or why it failed."""
        operation_id = self._agent_operation_id
        return Operation.from_id(operation_id, client=self._client, user=self._call_scope()) if operation_id else None

    @synced
    async def reply(self, text: str) -> InboxReply:
        """Reply to the sender (only the sender; the thread is kept).

        Returns:
            The reply as sent; ``delivery_status`` is the mail provider's word on it.

        Usage::

            inbox = noclick.Inbox.get("3d9b6f1e-8a2c-4e57-b0d4-6c1f2a9e7b35")
            mail = inbox.message("b41c7e02-95d3-4f6a-8e1b-0a7d2c5f9e63")
            sent = mail.reply("Thanks, we've received your invoice.")
            print(sent.status, sent.delivery_status)
        """
        response = await self._request("POST", f"{self._path()}/reply", json={"text": text}) or {}
        return InboxReply(response.get("id"), response.get("status"), response.get("delivery_status"), response)


def _read_message(result: Any, op: Operation, inbox_id: Optional[str] = None) -> InboxMessage:
    """A wait settles with ``{"message": <the message view>}``."""
    view = (result or {}).get("message") or {}
    return InboxMessage._from_view(view, inbox_id=inbox_id, client=op._client, user=op._scope, full=True)


register_result("inbox.wait_for", _read_message)


@dataclass(frozen=True)
class InboxThread:
    """One email thread of an inbox: what it received from one correspondent and
    the replies it sent them. ``messages`` (both ways, oldest first) only when it's
    read whole (``inbox.thread(id)``)."""

    id: str
    conversation: Optional[str]
    subject: Optional[str]
    correspondent: Optional[str]
    message_count: int
    last_direction: str
    snippet: Optional[str]
    last_at: Any
    messages: List[InboxMessage]
    raw: Dict[str, Any] = dc_field(repr=False)


def _message_id(message: Any) -> Optional[str]:
    return message._known("id") if isinstance(message, InboxMessage) else message


class Inbox(_Object):
    """An email address that receives mail. ``inbox.address`` is where to send it."""

    _repr_keys = ("id", "address")

    id: str = field("id")
    name: Optional[str] = field(
        "name", doc="What your code calls it, unique among its user's inboxes (None for one created without a name).",
    )
    address: str = field("address")
    agent_id: Optional[str] = field("agent_id", doc="The agent each inbound message wakes (None if none).")
    senders: Optional[str] = field(
        "senders",
        doc="Whose mail wakes its agent: ``anyone``, ``users`` (only mail proven to be from one of your users) or "
            "``owner`` (the inbox's own user, or your account's owner). It never changes who a turn runs as.",
    )
    conversation: Optional[str] = field(
        "conversation",
        doc="The agent's conversation each message lands in, a template over ``{sender}`` and ``{thread}`` "
            "(None: each email thread is a conversation of its own).",
    )
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls,
        local_part: Optional[str] = None,
        *,
        name: Optional[str] = None,
        agent: Any = None,
        domain: Any = None,
        senders: Optional[str] = None,
        conversation: Optional[str] = None,
        allow_existing: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Inbox":
        """Create an inbox. ``local_part`` asks for the part before the ``@``
        (generated when omitted; one already taken is ``noclick.Conflict``, a reserved
        role name such as ``support`` on NoClick's domain ``noclick.InvalidRequest``); ``agent`` (an ``noclick.Agent`` or id) is woken by
        every inbound message. ``name`` is what your code calls it (unique among its
        user's inboxes, ``noclick.Conflict`` with ``existing_id`` when taken;
        ``Inbox.from_name`` finds it). With ``allow_existing=True`` (and a ``name``) a taken name
        returns the inbox already there, as it is: nothing about it changes. ``domain`` (a
        ``noclick.Domain``, its name, or a subdomain of it) puts the address on your own domain:
        any address on one you bought, and on one you connected a subdomain of it
        (``help@mail.acme.com``), so its existing mail keeps working (the bare connected domain is
        ``noclick.Conflict``).

        On an account inbox, a message from one of your users, known by the email on their
        ``User`` and proven by the message's authenticated sender (a DKIM signature aligned
        with it, or SPF), runs as that user, in their connections, whatever ``senders`` says; any
        other message runs as your account. A user's own inbox runs every message as that
        user. ``senders`` only says whose mail wakes the agent: ``"anyone"`` (the default),
        ``"users"`` (only mail proven to be from one of your users) or ``"owner"`` (only the
        inbox's own user, or your account's owner for an account inbox). Mail from anyone
        else is still kept and listed, with ``agent_error`` saying why it woke no one.

        Each email thread is a conversation of its own with the agent (``message.conversation``):
        a message answering one of the inbox's messages, or one of its replies, from the same
        correspondent joins that thread. The agent gets a ``reply`` tool bound to the thread's
        latest message: it answers that sender, on that thread, and nobody else. So a turn that
        resumes after an approval, with no new message, still answers on the same thread.
        ``conversation`` names another conversation instead, a template over ``{sender}`` and
        ``{thread}``: ``"mail-{sender}"`` is one per correspondent, and ``"owner"`` puts every
        message in the same conversation as ``agent.message(..., conversation="owner")`` and a
        number's calls with that key. There the ``reply`` tool answers the newest email. Mail from
        outside the inbox's scope never lands in your own thread with the agent (where your texts
        and calls reach it): it takes its thread's own.

        Returns:
            The new inbox; ``address`` is where to send its mail.

        Usage:
            Give your code an address to receive mail at::

                inbox = noclick.Inbox.create(local_part="signup")
                print(inbox.address)   # signup@noclick.email

            Hand every message that arrives to an agent::

                support = noclick.Agent.from_name("support", create_if_missing=True, instructions="Answer customer email.")
                inbox = noclick.Inbox.create(local_part="acme-help", agent=support)

            Created inside ``as_user``, the inbox belongs to that user. Leave out
            ``local_part`` for a generated address::

                with noclick.as_user(noclick.User.from_id("user_42")):
                    inbox = noclick.Inbox.create()

            Put the address on a domain you bought, or a subdomain of one you connected. Mail
            arrives once the mail records are live (a connected domain lists them in its
            ``records``), and role names like ``help`` are yours to use there::

                support = noclick.Agent.from_name("support-bot")
                inbox = noclick.Inbox.create(local_part="help", domain="mail.acme.test", agent=support)
                print(inbox.address)   # help@mail.acme.test

            Let only your users' mail wake an account agent; each turn acts for the user who wrote::

                concierge = noclick.Agent.from_name("concierge")
                inbox = noclick.Inbox.create(local_part="ask", name="ask", agent=concierge, senders="users")

            Keep each correspondent in one conversation, whatever the subject::

                sales = noclick.Agent.from_name("sales")
                inbox = noclick.Inbox.create(local_part="acme-sales", agent=sales, conversation="mail-{sender}")
        """
        _check_senders(senders)
        if allow_existing and name is None:
            raise ValueError("Inbox.create(allow_existing=True) needs name=: it's the name that's found taken")
        scope = resolve_scope(user)
        body = compact(
            name=name, local_part=local_part, agent_id=await agent_id(agent), domain=await domain_name(domain),
            senders=senders, conversation=conversation,
        )
        raw = await cls._create_named("/v1/inboxes", body, allow_existing=allow_existing, user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        create_if_missing: bool = False,
        local_part: Optional[str] = None,
        agent: Any = UNSET,
        domain: Any = None,
        senders: Any = UNSET,
        conversation: Any = UNSET,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Inbox":
        """A lazy reference to the inbox called ``name`` in the current (or given) user.
        Given fields, it gets the inbox and sets the ones you pass, on every run: an existing inbox
        whose ``agent``, ``senders`` or ``conversation`` differ gets yours. ``create_if_missing=True``
        creates it with the fields ``Inbox.create`` takes when there's none; without it, a missing
        inbox raises ``noclick.NotFound``. Its
        address (``local_part``, ``domain``) is set when it's created and never changes: an existing
        inbox at another raises ``noclick.Conflict`` naming it. A field you leave out is never
        changed, and ``agent=None`` takes the inbox from its agent, as in ``update()``. Each run
        with fields is a write: set them at startup or in a setup script, and take the bare
        ``from_name`` in request handlers.

        Returns:
            An inbox that loads (or is created, or has your fields set) the first time it's used.
            Nothing is sent yet.

        Usage:
            Refer to an inbox by name::

                inbox = noclick.Inbox.from_name("support")
                print(inbox.address)

            Or get it, creating it if it's missing, and set its agent (in a setup script you run on deploy)::

                support = noclick.Agent.from_name("support")
                inbox = noclick.Inbox.from_name("support", create_if_missing=True, local_part="acme-help", agent=support)
                print(inbox.address)

            On your own domain, waking the agent for anyone's mail::

                support = noclick.Agent.from_name("support")
                inbox = noclick.Inbox.from_name(
                    "support", create_if_missing=True, local_part="help", domain="mail.acme.test",
                    agent=support, senders="anyone",
                )
                print(inbox.address)   # help@mail.acme.test
        """
        _check_senders(senders)
        inbox = cls._new(hints={"name": name}, client=client, user=user)
        inbox._define({
            **compact(name=name, local_part=local_part, domain=domain,
                      senders=None if senders is UNSET else senders,
                      conversation=None if conversation is UNSET else conversation,
                      agent_id=None if agent is UNSET else agent),
            # An explicit None is a field you pass: it takes the inbox from its agent.
            **({"agent_id": None} if agent is None else {}),
        }, create_if_missing=create_if_missing)
        return inbox

    @classmethod
    def from_id(cls, inbox_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Inbox":
        """A lazy reference to an inbox by id.

        Returns:
            An inbox that loads the first time you read a field. Nothing is sent yet.

        Usage::

            inbox = noclick.Inbox.from_id("3d9b6f1e-8a2c-4e57-b0d4-6c1f2a9e7b35")
            for message in inbox.messages():
                print(message.sender, message.subject)
        """
        return cls._new(hints={"id": inbox_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, inbox_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Inbox":
        """Load an inbox by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The inbox, loaded.

        Usage::

            inbox = noclick.Inbox.get("3d9b6f1e-8a2c-4e57-b0d4-6c1f2a9e7b35")
            print(inbox.address, inbox.agent_id)
        """
        inbox = cls.from_id(inbox_id, client=client, user=user)
        await inbox._ensure()
        return inbox

    @synced
    @classmethod
    async def list(
        cls, *, agent: Any = None, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Inbox"]:
        """The current user's inboxes (the account's own outside ``as_user``, or those ``user_filter`` covers).
        ``agent`` (an ``noclick.Agent`` or id) keeps the ones whose mail wakes it.

        Returns:
            Every matching inbox, newest first, fetched page by page.

        Usage::

            for inbox in noclick.Inbox.list():
                print(inbox.address, inbox.agent_id)

            everyone = noclick.Inbox.list(user_filter=noclick.ALL_USERS)   # every user's, plus your account's
            supports = noclick.Inbox.list(agent=noclick.Agent.from_name("support"))
        """
        return await list_all(
            "/v1/inboxes", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"agent_id": await agent_id(agent)}, user=user, user_filter=user_filter, limit=limit,
            client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, agent: Any = None,
        user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of inboxes; pass ``next_cursor`` back as ``cursor``, ``agent`` as in ``list``.

        Returns:
            A page whose ``data`` holds the inboxes and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Inbox.list_page(limit=50)
            while True:
                for inbox in page.data:
                    print(inbox.address)
                if page.next_cursor is None:
                    break
                page = noclick.Inbox.list_page(limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/inboxes", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"agent_id": await agent_id(agent)}, user=user, user_filter=user_filter, cursor=cursor,
            limit=limit, client=client,
        )

    def _path(self) -> str:
        return f"/v1/inboxes/{self._known('id')}"

    async def _id_path(self) -> str:
        """``_path()`` once the id is known (an inbox reached by name loads first)."""
        if not self._known("id"):
            await self._ensure()
        return self._path()

    async def _load(self) -> Dict[str, Any]:
        if self._known("id"):
            return await self._request("GET", self._path())
        name = self._hints["name"]
        page = await self._request("GET", "/v1/inboxes", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        if rows:
            return await self._converge(rows[0])
        if not self._creates:
            raise NotFound(
                f"No inbox is named {name!r}.",
                next_step="Create it with noclick.Inbox.create(name=...) or pass create_if_missing=True.",
                details={"name": name},
            )
        definition = self._create_with
        body = compact(**{**definition, "agent_id": await agent_id(definition.get("agent_id")),
                          "domain": await domain_name(definition.get("domain"))})
        try:
            return await self._request("POST", "/v1/inboxes", json=body)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._converge(await self._request("GET", f"/v1/inboxes/{exc.existing_id}"))

    async def _converge(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Set the fields ``from_name`` was given on an existing inbox, after checking its address."""
        if self._create_with is None:
            return raw
        local, _, host = str(raw.get("address") or "").lower().partition("@")
        given = {"local_part": self._create_with.get("local_part"),
                 "domain": await domain_name(self._create_with.get("domain"))}
        check_unchanged("inbox", {**raw, "local_part": local, "domain": host},
                        {k: v.lower() for k, v in given.items() if v is not None})
        wanted = {k: v for k, v in self._create_with.items() if k in _CONVERGED}
        if "agent_id" in wanted:
            wanted["agent_id"] = await agent_id(wanted["agent_id"])
        changes = {k: v for k, v in wanted.items() if raw.get(k) != v}
        return await self._request("PATCH", f"/v1/inboxes/{raw['id']}", json=changes) if changes else raw

    @synced
    async def update(self, *, agent: Any = UNSET, senders: Any = UNSET, conversation: Any = UNSET) -> "Inbox":
        """Change which agent its mail wakes (``agent=None``: none), whose mail
        does (``senders``), or the conversation it lands in (``conversation``, a
        template; None: each thread's own), from the next message.

        Returns:
            This inbox, updated. A field you leave out is unchanged.

        Usage::

            inbox = noclick.Inbox.from_name("support")
            inbox.update(agent=noclick.Agent.from_name("support-v2"))
            inbox.update(senders="users")   # from now on only your users' mail wakes it
            inbox.update(conversation="mail-{sender}")   # one conversation per correspondent
        """
        _check_senders(senders)
        changes: Dict[str, Any] = {} if senders is UNSET else {"senders": senders}
        if conversation is not UNSET:
            changes["conversation"] = conversation
        if agent is not UNSET:
            changes["agent_id"] = await agent_id(agent)
        raw = await self._ensure()
        self._raw = await self._request("PATCH", f"/v1/inboxes/{raw['id']}", json=changes)
        return self

    @synced
    async def delete(self) -> TrashItem:
        """Delete the inbox: its address stops receiving mail, and it goes to the trash with its mail,
        restorable for 30 days.

        Returns:
            Its ``TrashItem``: ``restore()`` puts it back at its address.

        Usage::

            inbox = noclick.Inbox.from_id("3d9b6f1e-8a2c-4e57-b0d4-6c1f2a9e7b35")
            inbox.delete()
        """
        raw = await self._request("DELETE", await self._id_path())
        return trashed(raw, client=self._client, user=self._call_scope())

    # --- messages --------------------------------------------------------

    def _message(self, raw: Dict[str, Any], *, full: bool = False) -> InboxMessage:
        return InboxMessage._from_view(
            raw, inbox_id=self._known("id"), client=self._client, user=self._call_scope(), full=full,
        )

    async def _page(self, after: Optional[str], wait_s: Optional[int], since: Any = None) -> List[InboxMessage]:
        response = await self._request(
            "GET", f"{await self._id_path()}/messages",
            params={"after": after, "since": iso_time(since), "wait_s": wait_s},
            timeout=None if wait_s is None else wait_s + 15,
        ) or {}
        return [self._message(row) for row in response.get("data") or []]

    @synced
    async def messages(
        self, *, after: Any = None, since: Any = None, wait_s: Optional[int] = None,
    ) -> List[InboxMessage]:
        """Messages oldest first, after a message (or its id) if given.
        ``wait_s`` long-polls until one arrives. ``since`` (a timezone-aware ``datetime``)
        keeps those received at or after it.

        Returns:
            Up to 50 messages. Pass the last one as ``after`` for the ones that follow;
            an empty list means none arrived in time.

        Usage:
            Read what's there::

                inbox = noclick.Inbox.get("3d9b6f1e-8a2c-4e57-b0d4-6c1f2a9e7b35")
                for message in inbox.messages():
                    print(message.sender, message.subject)

            Wait up to 30 seconds (at most 50) for anything newer than the last one you read::

                inbox = noclick.Inbox.get("3d9b6f1e-8a2c-4e57-b0d4-6c1f2a9e7b35")
                seen = inbox.messages()
                newer = inbox.messages(after=seen[-1], wait_s=30)

            Or what arrived today, by time::

                from datetime import datetime, timezone

                inbox = noclick.Inbox.from_name("support")
                midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                for message in inbox.messages(since=midnight):
                    print(message.received_at, message.subject, message.agent_error)
        """
        return await self._page(_message_id(after), wait_s, since)

    @synced
    async def message(self, message_id: str) -> InboxMessage:
        """One message in full: text, sender, subject and digested attachments.

        Returns:
            The message, loaded. An attachment's ``text`` appears once extraction,
            which runs just after the message arrives, has finished.

        Usage::

            inbox = noclick.Inbox.get("3d9b6f1e-8a2c-4e57-b0d4-6c1f2a9e7b35")
            mail = inbox.message("b41c7e02-95d3-4f6a-8e1b-0a7d2c5f9e63")
            print(mail.subject, mail.text)
            for attachment in mail.attachments:
                print(attachment["name"], attachment.get("text"))
        """
        raw = await self._request("GET", f"{await self._id_path()}/messages/{message_id}")
        return self._message(raw, full=True)

    def _thread(self, raw: Dict[str, Any]) -> InboxThread:
        messages = [self._message(m, full=True) for m in raw.get("messages") or []]
        return InboxThread(
            id=raw["id"], conversation=raw.get("conversation"), subject=raw.get("subject"),
            correspondent=raw.get("correspondent"), message_count=raw.get("message_count", len(messages)),
            last_direction=raw.get("last_direction") or "inbound", snippet=raw.get("snippet"),
            last_at=parse_time(raw.get("last_at")), messages=messages, raw=raw,
        )

    @synced
    async def threads(self, *, cursor: Optional[str] = None, limit: Optional[int] = None) -> Page[InboxThread]:
        """One page of its email threads, the most recently active first.

        Returns:
            Threads without their messages; pass ``next_cursor`` back as ``cursor`` for the next page.

        Usage::

            inbox = noclick.Inbox.from_name("support")
            for thread in inbox.threads().data:
                print(thread.last_at, thread.correspondent, thread.subject, thread.message_count)
        """
        response = await self._request("GET", f"{await self._id_path()}/threads",
                                       params={"cursor": cursor, "limit": limit}) or {}
        return Page([self._thread(row) for row in response.get("data") or []], response.get("next_cursor"))

    @synced
    async def thread(self, thread_id: str) -> InboxThread:
        """One thread whole: what it received and the replies it sent, oldest first.

        Returns:
            The thread; each message's ``direction`` says which way it went.

        Usage::

            inbox = noclick.Inbox.from_name("support")
            latest = inbox.threads(limit=1).data[0]
            for message in inbox.thread(latest.id).messages:
                print(message.direction, message.sender, message.text)
        """
        return self._thread(await self._request("GET", f"{await self._id_path()}/threads/{thread_id}"))

    @synced
    async def send(
        self, text: Optional[str] = None, *, to: Optional[str] = None, subject: Optional[str] = None,
        html: Optional[str] = None, thread: Any = None, idempotency_key: Optional[str] = None,
    ) -> InboxMessage:
        """New mail from this inbox to one person: business mail you mean to send, never bulk or cold
        outreach. Only an inbox on a domain you bought sends new mail (one on ``noclick.email``
        replies); up to 100 new emails per address a day.

        Args:
            text: The message (``html`` instead, or as well).
            to: Who it goes to. Optional with ``thread``: the thread's correspondent.
            subject: One line. Optional with ``thread``: ``Re:`` its subject.
            thread: An ``InboxThread`` (or its id) to follow up on: the mail lands in the
                recipient's copy of the thread, and their answer in the inbox's.

        Returns:
            The message as sent: ``status`` is ``sending`` until it goes (minutes, the first time an
            address sends), then ``sent``; ``delivery_status`` follows.

        Usage::

            inbox = noclick.Inbox.from_name("hello")
            inbox.send("Can you deliver 20 kg of rye flour on Saturday?", to="orders@millbrook.test",
                       subject="Saturday delivery")
            latest = inbox.threads(limit=1).data[0]
            inbox.send("Following up on Saturday's delivery: does 7am work?", thread=latest)
        """
        thread_id = thread.id if isinstance(thread, InboxThread) else thread
        raw = await self._request(
            "POST", f"{await self._id_path()}/messages",
            json=compact(to=to, subject=subject, text=text, html=html, thread_id=thread_id),
            idempotency_key=idempotency_key)
        return self._message(raw, full=True)

    @synced
    async def stream(
        self, *, after: Any = None, since: Any = None, wait_s: int = _STREAM_WAIT_S,
    ) -> AsyncIterator[InboxMessage]:
        """Yield every message (from the start, or after ``after``, or received at or
        after ``since``) as it arrives; runs until you stop iterating.
        ``async for m in inbox.stream.aio()``.

        Returns:
            Each message in the order it arrived. It never ends on its own, so
            ``break`` when you're done.

        Usage:
            Handle mail as it comes in::

                inbox = noclick.Inbox.get("3d9b6f1e-8a2c-4e57-b0d4-6c1f2a9e7b35")
                for message in inbox.stream():
                    print(message.sender, message.subject)

            In async code, iterate ``stream.aio()``, starting after a message you've already handled::

                inbox = noclick.Inbox.from_id("3d9b6f1e-8a2c-4e57-b0d4-6c1f2a9e7b35")
                async for message in inbox.stream.aio(after="b41c7e02-95d3-4f6a-8e1b-0a7d2c5f9e63"):
                    print(message.subject)
        """
        cursor = _message_id(after)
        loop = asyncio.get_running_loop()
        while True:
            started = loop.time()
            batch = await self._page(cursor, wait_s, None if cursor else since)
            for message in batch:
                cursor = message.id
                yield message
            if not batch:
                await asyncio.sleep(max(0.0, 1.0 - (loop.time() - started)))  # never spin on a short poll

    @synced
    async def wait_for(
        self,
        *,
        sender: Optional[str] = None,
        subject_contains: Optional[str] = None,
        since: Any = None,
        timeout_s: Optional[int] = None,
    ) -> Operation:
        """Watch for the first message matching ``sender`` and/or
        ``subject_contains`` (a sign-up code, a receipt). ``since`` (a timezone-aware
        ``datetime``) lets a message that arrived at or after it match too, so a wait
        started after you trigger the email can't miss it.

        Returns:
            An operation whose ``.wait()`` gives the ``InboxMessage``, or raises
            ``noclick.Expired`` once ``timeout_s`` passes without one.

        Usage:
            Only mail that arrives after the call matches, so start the wait before
            you trigger the email. ``sender`` is an address or a domain, matched
            only on authenticated mail::

                inbox = noclick.Inbox.create(local_part="signup")
                waiting = inbox.wait_for(sender="noreply@github.com", subject_contains="code", timeout_s=300)
                # ... sign up with inbox.address ...
                mail = waiting.wait()
                print(mail.subject, mail.text)

            ``timeout_s`` defaults to 5 minutes and goes up to 15::

                inbox = noclick.Inbox.get("3d9b6f1e-8a2c-4e57-b0d4-6c1f2a9e7b35")
                try:
                    receipt = inbox.wait_for(sender="stripe.com", subject_contains="receipt", timeout_s=900).wait()
                except noclick.Expired:
                    print("No receipt arrived.")

            Note the time, trigger the email, then wait: a message that landed in between
            still counts::

                from datetime import datetime, timezone

                inbox = noclick.Inbox.from_name("signup")
                started = datetime.now(timezone.utc)
                # ... sign up with inbox.address ...
                mail = inbox.wait_for(sender="noreply@github.com", since=started).wait()
        """
        scope = self._call_scope()
        path = await self._id_path()
        inbox_id = self._known("id")
        payload = await self._request(
            "POST", f"{path}/wait_for",
            json=compact(sender=sender, subject_contains=subject_contains, since=iso_time(since), timeout_s=timeout_s),
        )
        return Operation._from_payload(
            payload, client=self._client, user=scope, kind="inbox.wait_for",
            reader=lambda result, op: _read_message(result, op, inbox_id),
        )
