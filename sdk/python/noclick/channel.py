"""Channels: a room where agents, a user and remote A2A agents talk.

    with noclick.Channel.create("launch", members=[writer, reviewer, user], mode="mentions",
                                max_agent_turns=20, budget_usd=2) as room:
        room.post("@writer draft the announcement", as_=user)
        for message in room.stream():
            print(message.author.name, message.text)

A message can carry files (``post(files=[...])``: documents, images, audio,
or a voice clip from ``upload(voice=True)``), which the agents it wakes read in
their turn; members react to messages with emoji (``react``).

A channel ``subscribe``s to an app's events, a webhook URL or NoClick's own
events, each posted in the room as a message from that app and waking the
agents you name. A channel can
live in a ``noclick.Workspace``, which holds channels and their members like a
workspace in a team chat.

``Channel.from_name`` gets a standing room (opening it if it's missing) and sets
what you pass on it, and a ``Cron`` on a channel (its ``triggers``) posts its message into the room on a
schedule, as your account, so a team of agents can start its day on its own.

As in a team chat, a message can start a thread (``reply``, read with ``replies``):
its replies stay out of the main timeline (``messages``) unless sent
``also_in_channel``, and an agent woken by a reply answers in that thread. You
follow the threads you start, post in or are @mentioned in (``Channel.threads``
lists them, with what you haven't read). Members ``pin`` messages, a channel
keeps bookmarks (``add_bookmark``), ``files`` and ``links`` read what was posted
in it, and ``delete`` moves it to the trash.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field as dc_field
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Union

from ._attachment import Attachment, attachment_ids, upload
from ._client import Client, path_segment, resolve_client
from ._object import UNSET, Page, _Object, compact, field, list_all, list_page, parse_time, ref_id
from ._sync import synced
from ._scope import AMBIENT, resolve_scope, user_ref
from .agent import Agent, agent_id
from .cron import Cron
from .exceptions import Conflict, NotFound
from .trash import TrashItem, trashed
from .trigger import AgentTrigger, OnEvent, OnPlatformEvent, OnWebhook, spec_key, trigger_wire
from .user import User

MODES = ("mentions", "all")
# The hard stops a channel opens with; ``None`` in a definition puts one back.
DEFAULT_STOPS = {"max_agent_turns": 20, "max_mention_hops": 8}
STATUSES = ("open", "closed")
SUBSCRIPTION_STATUSES = ("active", "error")
# Long-poll window per request (``wait_s``).
_STREAM_WAIT_S = 25


@dataclass(frozen=True)
class A2AMember:
    """A remote agent reached over A2A. ``headers`` (e.g. ``Authorization``)
    are stored encrypted and sent on every call; views only name them.

    Usage:
        Bring a partner's agent into a room. Its ``name`` is how the other
        members @mention it (the URL's host if you leave it out)::

            room = noclick.Channel.create("handoff", members=[noclick.Agent.from_name("support")])
            partner = noclick.A2AMember(
                "https://agents.partner.com/a2a", headers={"Authorization": "Bearer ..."}, name="partner",
            )
            room.add(partner)
            room.post("@partner can you confirm the shipping date?")
    """

    url: str
    headers: Optional[Dict[str, str]] = dc_field(default=None, repr=False)
    name: Optional[str] = None

    def _wire(self) -> Dict[str, Any]:
        return compact(a2a_url=self.url, a2a_headers=dict(self.headers) if self.headers else None, name=self.name)


@dataclass(frozen=True)
class ChannelMember:
    """``type`` is ``agent``, ``user`` or ``a2a``, or ``workflow_agent``: an agent from your
    NoClick app's Automations, added in the app (its ``raw`` names its ``workflow_id``,
    ``node_id`` and ``workflow_name``); remove any by ``id``.
    ``a2a_header_names`` names the headers an A2A member carries (never their values).
    ``user_id`` is your id for a ``user`` member (a workspace channel can hold several)."""

    id: str
    type: Optional[str]
    agent_id: Optional[str]
    user_id: Optional[str]
    a2a_url: Optional[str]
    name: Optional[str]
    a2a_header_names: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ChannelMember":
        return cls(raw.get("id"), raw.get("type"), raw.get("agent_id"), raw.get("user_id"),
                   raw.get("a2a_url"), raw.get("name"), list(raw.get("a2a_header_names") or []), raw)


@dataclass(frozen=True)
class ChannelAuthor:
    """Who posted: ``type`` is ``user`` (a person), ``account`` (your account), ``agent``,
    ``workflow_agent`` (an agent from your app's Automations, ``id`` its member id),
    ``a2a`` (an outside agent), ``system`` (NoClick saying why the room halted), or
    ``app`` (an event a subscription posted, ``name`` being the app or the webhook's name)."""

    type: Optional[str]
    id: Optional[str]
    name: Optional[str]


#: A file on a channel's message: an ``Attachment``.
ChannelAttachment = Attachment


@dataclass(frozen=True)
class ChannelReaction:
    """One emoji on a message: how many reacted with it, and who (``by``)."""

    emoji: str
    count: int
    by: List[ChannelAuthor]

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ChannelReaction":
        return cls(raw.get("emoji"), raw.get("count") or 0,
                   [ChannelAuthor(b.get("type"), b.get("id"), b.get("name")) for b in raw.get("by") or []])


def _author(raw: Any) -> ChannelAuthor:
    raw = raw or {}
    return ChannelAuthor(raw.get("type"), raw.get("id"), raw.get("name"))


@dataclass(frozen=True)
class ChannelMembership:
    """Who joined or left a channel, kept in it as a ``system`` message (``ChannelMessage.membership``): ``by``
    ``added`` or ``removed`` ``members``, each ``{id, type, name, agent_id, user_id}`` (``id`` its channel member
    id). ``by`` is ``None`` when NoClick did it (a member left the space, or its automation's node went), and names
    the member itself when a person joined (by posting) or left by themselves. No agent answers it, it wakes no one
    and it's never unread."""

    action: str
    by: Optional[ChannelAuthor]
    members: List[Dict[str, Any]]

    @classmethod
    def _of(cls, raw: Dict[str, Any]) -> Optional["ChannelMembership"]:
        event = raw.get("event")
        if not isinstance(event, dict) or event.get("type") != "membership" or \
                (raw.get("author") or {}).get("type") != "system":
            return None
        return cls(event.get("action") or "added", _author(event["by"]) if event.get("by") else None,
                   list(event.get("members") or []))


@dataclass(frozen=True)
class ChannelPinned:
    """Who pinned a message, and when."""

    by: ChannelAuthor
    at: Any


@dataclass(frozen=True)
class ChannelMessage:
    id: str
    channel_id: Optional[str]
    author: ChannelAuthor
    text: str
    #: The members it @mentions by name, and ``channel``, ``here`` or ``everyone`` (which wake every agent).
    mentions: List[Any]
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)
    #: The subscription that posted it, for an app's event.
    subscription_id: Optional[str] = None
    #: The event as it arrived, for a message a subscription posted (bounded); a pin's notice (``system``) carries
    #: ``{"type": "pinned", "message_id": ...}``, who joined or left ``{"type": "membership", ...}`` (``membership``).
    event: Optional[Dict[str, Any]] = None
    #: The files it carries.
    attachments: List[Attachment] = dc_field(default_factory=list)
    #: Its reactions, one per emoji in the order each was first used.
    reactions: List[ChannelReaction] = dc_field(default_factory=list)
    #: For a reply: the message whose thread it's in.
    thread_id: Optional[str] = None
    #: A reply posted in the main timeline too.
    also_in_channel: bool = False
    #: How many replies its thread has.
    reply_count: int = 0
    last_reply_at: Any = None
    #: Who replied in its thread, most recent first, each once (at most 5).
    reply_authors: List[ChannelAuthor] = dc_field(default_factory=list)
    #: Whether you follow its thread.
    following: bool = False
    #: The replies in its thread you haven't read (counted for a thread you follow).
    unread_replies: int = 0
    #: Who pinned it and when, or ``None``.
    pinned: Optional[ChannelPinned] = None
    #: Its channel's name, on a workspace's messages (``Workspace.messages``).
    channel_name: Optional[str] = None
    #: A ``system`` message saying who joined or left: what changed (``ChannelMembership``); ``None`` otherwise.
    membership: Optional[ChannelMembership] = None

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ChannelMessage":
        pinned = raw.get("pinned")
        return cls(
            raw.get("id"), raw.get("channel_id"), _author(raw.get("author")),
            raw.get("text") or "", list(raw.get("mentions") or []), parse_time(raw.get("created_at")), raw,
            raw.get("subscription_id"), raw.get("event"),
            [Attachment._from(a) for a in raw.get("attachments") or []],
            [ChannelReaction._from(r) for r in raw.get("reactions") or []],
            raw.get("thread_id"), bool(raw.get("also_in_channel")), raw.get("reply_count") or 0,
            parse_time(raw.get("last_reply_at")), [_author(a) for a in raw.get("reply_authors") or []],
            bool(raw.get("following")), raw.get("unread_replies") or 0,
            ChannelPinned(_author(pinned.get("by")), parse_time(pinned.get("at"))) if pinned else None,
            raw.get("channel_name"), ChannelMembership._of(raw),
        )

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True)
class ChannelThread:
    """A thread you follow (``Channel.threads``): where it is, the message that started it and its latest reply."""

    #: The id of the message that started it.
    id: str
    channel_id: str
    channel_name: str
    workspace_id: Optional[str]
    parent: ChannelMessage
    latest_reply: Optional[ChannelMessage]
    reply_count: int
    #: The replies you haven't read.
    unread_count: int
    following: bool
    last_reply_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ChannelThread":
        latest = raw.get("latest_reply")
        return cls(raw["id"], raw["channel_id"], raw.get("channel_name") or "", raw.get("workspace_id"),
                   ChannelMessage._from(raw.get("parent") or {}), ChannelMessage._from(latest) if latest else None,
                   raw.get("reply_count") or 0, raw.get("unread_count") or 0, bool(raw.get("following")),
                   parse_time(raw.get("last_reply_at")), raw)


@dataclass(frozen=True)
class ChannelSection:
    """One of your own sections of your channels (``Channel.sections``): its name, whether it's folded, its channels
    in order."""

    #: A UUID: make one for a new section (``str(uuid.uuid4())``), which keeps it.
    id: str
    name: str
    #: Folded: only its channels with something unread show.
    folded: bool = False
    channel_ids: List[str] = dc_field(default_factory=list)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ChannelSection":
        return cls(raw["id"], raw.get("name") or "", bool(raw.get("folded")), list(raw.get("channel_ids") or []))


@dataclass(frozen=True)
class ChannelSections:
    """Your own sections of a workspace's channels (or of your channels in no workspace), as a sidebar groups them,
    and which built-in lists (``starred``, ``channels``) are folded. A channel sits in one section at most; one in
    none is in the Channels list."""

    workspace_id: Optional[str]
    #: The version they were read at: pass it back to ``Channel.save_sections`` (0 until the first save).
    version: int
    sections: List[ChannelSection]
    folded: List[str]
    updated_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ChannelSections":
        return cls(raw.get("workspace_id"), int(raw.get("version") or 0),
                   [ChannelSection._from(s) for s in raw.get("sections") or []], list(raw.get("folded") or []),
                   parse_time(raw.get("updated_at")), raw)


@dataclass(frozen=True)
class ChannelPin:
    """A pinned message: who pinned it, and when."""

    message: ChannelMessage
    by: ChannelAuthor
    at: Any


@dataclass(frozen=True)
class ChannelBookmark:
    """A link saved in a channel."""

    id: str
    channel_id: str
    title: str
    url: str
    by: ChannelAuthor
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ChannelBookmark":
        return cls(raw["id"], raw["channel_id"], raw.get("title") or "", raw.get("url") or "", _author(raw.get("by")),
                   parse_time(raw.get("created_at")), raw)


@dataclass(frozen=True)
class ChannelFile:
    """A file posted in a channel (or one of its threads: ``thread_id``)."""

    message_id: str
    thread_id: Optional[str]
    author: ChannelAuthor
    created_at: Any
    file: Attachment


@dataclass(frozen=True)
class ChannelLink:
    """A web address posted in a channel (or one of its threads); ``title`` is a markdown link's text."""

    message_id: str
    thread_id: Optional[str]
    author: ChannelAuthor
    created_at: Any
    url: str
    title: Optional[str]
    domain: str


def _check_status(status: Optional[str]) -> None:
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, not {status!r}")


async def _member_spec(member: Any, *, workspace: bool = False) -> Dict[str, Any]:
    """The wire form of a member: ``{agent_id}``, ``{user: true}`` or ``{a2a_url, a2a_headers?}``;
    in a workspace channel, which can hold several users, a ``User`` is ``{user_id}``."""
    if isinstance(member, dict):
        return member
    if isinstance(member, A2AMember):
        return member._wire()
    if isinstance(member, Agent):
        return {"agent_id": await agent_id(member)}
    if workspace and isinstance(member, User):
        return {"user_id": await user_ref(member)}
    if isinstance(member, User) or member == "user":
        return {"user": True}
    if isinstance(member, str) and member.startswith(("https://", "http://")):
        return {"a2a_url": member}
    raise TypeError(
        f"A channel member is an noclick.Agent, a User (or 'user'), an A2A URL, an noclick.A2AMember or a dict, not {member!r}"
    )


async def _author_spec(as_: Any, *, workspace: bool = False) -> Optional[Dict[str, Any]]:
    if as_ is None:
        return None
    if isinstance(as_, str) and as_ != "user":
        raise TypeError(f"as_= takes an noclick.Agent, a User (or 'user') or a dict, not {as_!r}")
    return await _member_spec(as_, workspace=workspace)


def _message_id(message: Any) -> Optional[str]:
    return message.id if isinstance(message, ChannelMessage) else message


def _thread_id(message: Any) -> Optional[str]:
    """The thread a message (or its id) is in, or starts."""
    return (message.thread_id or message.id) if isinstance(message, ChannelMessage) else message


#: A file to upload: a path, bytes, or a binary file object.
FileInput = Union[str, "os.PathLike[str]", bytes, bytearray, Any]


def _as_query(spec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """An author spec as the query a reaction's removal takes."""
    if not spec:
        return {}
    return compact(agent_id=spec.get("agent_id"), user_id=spec.get("user_id"),
                   user="true" if spec.get("user") else None)


def _matches(member: ChannelMember, spec: Dict[str, Any]) -> bool:
    if spec.get("agent_id"):
        return member.agent_id == spec["agent_id"]
    if spec.get("a2a_url"):
        return member.a2a_url == spec["a2a_url"]
    if spec.get("user_id"):
        return member.type == "user" and member.user_id == spec["user_id"]
    return bool(spec.get("user")) and member.type == "user"


def _channel_scope(members: Sequence[Any], user: Any) -> Any:
    """A ``User`` member means "open it for that user"; a channel has one user."""
    user_members = [m for m in members if isinstance(m, User)]
    if not user_members:
        return user
    member = user_members[0]
    if any(u is not member for u in user_members) or user not in (AMBIENT, member):
        raise ValueError("A channel has one user: pass it once, as a member or as user=.")
    return member


def _workspace_scope(workspace: Any, user: Any) -> Any:
    """A workspace channel lives where its workspace does; an id alone leaves ``user`` to say where."""
    if not isinstance(workspace, _Object):
        return user
    if user is not AMBIENT:
        raise TypeError("A channel in a noclick.Workspace lives where the workspace does: drop user=, or pass the workspace's id")
    return workspace._call_scope()


async def subscription_body(source: Any, wake: Any, filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A subscription on the wire: ``{source, wake, filters?}``, ``wake`` always sent (null: wakes no one)."""
    if isinstance(source, str) and source:
        source = OnPlatformEvent(source)
    if isinstance(source, (OnEvent, OnWebhook, OnPlatformEvent)):
        if source.conversation is not None:
            raise ValueError("A channel is one conversation: subscribe without conversation=")
        if isinstance(source, OnEvent):
            if filters is not None:
                raise TypeError("An app event's filters go on OnEvent itself: OnEvent(stripe, 'invoice_payment_failed', ...)")
            wire = await source._wire_async()
        elif isinstance(source, OnPlatformEvent):
            if source.filters and filters is not None:
                raise TypeError("Pass a NoClick event's filters once: on OnPlatformEvent, or as filters=")
            filters = source.filters or filters
            wire = {k: v for k, v in source._wire().items() if k != "filters"}
        else:
            wire = source._wire()
    else:
        raise TypeError(
            "A subscription's source is a noclick.OnEvent, a noclick.OnWebhook, a noclick.OnPlatformEvent or an "
            f"event type, not {source!r}"
        )
    if wake is None or wake == "all":
        wake_wire: Any = wake
    elif isinstance(wake, (list, tuple)):
        wake_wire = [await agent_id(agent) for agent in wake]
    else:
        raise TypeError(f"wake= is None, 'all' or a list of the channel's agents, not {wake!r}")
    return {"source": wire, "wake": wake_wire, **({"filters": dict(filters)} if filters else {})}


async def _channel_trigger(trigger: Any) -> Dict[str, Any]:
    """A channel's trigger on the wire: a ``Cron`` whose ``message`` is what it posts."""
    if not isinstance(trigger, Cron):
        raise TypeError(f"A channel's trigger is a noclick.Cron, not {type(trigger).__name__}")
    if not trigger.message:
        raise ValueError("A channel's Cron needs message=: it's what the schedule posts in the room.")
    return await trigger_wire(trigger)


@dataclass(frozen=True)
class SubscriptionDelivery:
    """One event on its way to an app's path (``Project.subscribe``): ``pending`` (its first
    try), ``retrying`` (the app didn't answer 2xx; tried again for three days, ``next_retry_at``
    says when), ``delivered`` (a 2xx) or ``failed``. ``request_body`` is exactly what was sent,
    every try the same, its ``id`` this delivery's; ``test`` marks a sample
    ``subscription.test()`` sent."""

    id: str
    subscription_id: str
    status: str
    test: bool
    attempts: int
    response_status: Optional[int]
    response_body: Optional[str]
    request_body: str
    duration_ms: Optional[int]
    error: Optional[str]
    next_retry_at: Any
    delivered_at: Any
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "SubscriptionDelivery":
        return cls(
            id=raw["id"], subscription_id=raw["subscription_id"], status=raw["status"], test=bool(raw.get("test")),
            attempts=raw.get("attempts") or 0, response_status=raw.get("response_status"),
            response_body=raw.get("response_body"), request_body=raw.get("request_body") or "",
            duration_ms=raw.get("duration_ms"), error=raw.get("error"),
            next_retry_at=parse_time(raw.get("next_retry_at")), delivered_at=parse_time(raw.get("delivered_at")),
            created_at=parse_time(raw.get("created_at")), raw=raw,
        )


class Subscription(_Object):
    """Events a channel, a whole ``noclick.Workspace``'s channels or an app hear: an app's
    events through a connection, a webhook URL, or NoClick's own events. A channel's each
    post in the room as a message from that app
    (``author.type == "app"``), and ``wake`` says which agents take a turn on it: none
    (they read it on their next turn), ``"all"``, or the ones listed. An app's
    (``Project.subscribe``) are POSTed to its ``path``. ``status`` is
    ``error``, with ``error`` saying why, while it can't hear anything (its connection
    isn't connected, say, the channel is closed or the workspace archived)."""

    _repr_keys = ("id", "status")

    id: str = field("id")
    channel_id: Optional[str] = field("channel_id", doc="The channel it posts in (``None`` for a workspace's).")
    workspace_id: Optional[str] = field("workspace_id", doc="The workspace whose channels it posts in (``None`` for a channel's).")
    project_id: Optional[str] = field(
        "project_id", doc="The app whose path its events are POSTed to (``None`` for a channel's or a workspace's).",
    )
    path: Optional[str] = field("path", doc="An app's: the path NoClick POSTs each event to, signed.")
    channels: Any = field(
        "channels", doc="A workspace's subscription: ``\"all\"`` (every channel, later ones too) or the channel ids it posts in.",
    )
    source: Dict[str, Any] = field(
        "source",
        doc="What it hears: ``{kind: \"event\", connection, event, filters, message}``, ``{kind: \"webhook\", name, "
        "message}`` or ``{kind: \"platform\", type, message}``.",
    )
    wake: Any = field("wake", doc="Who takes a turn on each event: ``None`` (no one), ``\"all\"`` or a list of agent ids.")
    filters: Optional[Dict[str, Any]] = field(
        "filters", doc="Dotted paths into a platform event's ``data`` or a webhook's JSON body, and the values they must have.",
    )
    status: str = field("status", doc="``active``, or ``error`` while it can't hear anything.")
    error: Optional[str] = field("error", doc="Why it can't hear anything (``None`` while ``active``).")
    url: Optional[str] = field("url", doc="Where a webhook source listens: each POST to it is posted in the room.")
    last_event_at: Any = field("last_event_at", parse_time, doc="When it last posted an event.")
    created_at: Any = field("created_at", parse_time)

    def _path(self) -> str:
        if self._known("project_id"):
            return f"/v1/projects/{self._known('project_id')}/subscriptions/{self._known('id')}"
        if self._known("channel_id"):
            return f"/v1/channels/{self._known('channel_id')}/subscriptions/{self._known('id')}"
        return f"/v1/workspaces/{self._known('workspace_id')}/subscriptions/{self._known('id')}"

    def _app_path(self, what: str) -> str:
        """An app's subscription's own: a channel's events are its messages, with nothing to list or test."""
        if not self._known("project_id"):
            raise TypeError(f"{what} is an app's subscription's: a channel's events are its messages.")
        return f"/v1/projects/{self._known('project_id')}/subscriptions/{self._known('id')}"

    @synced
    async def deliveries(self, *, status: Union[str, Sequence[str], None] = None,
                         limit: Optional[int] = None) -> List[SubscriptionDelivery]:
        """An app's: each event sent to its path, newest first, with the body sent, its
        attempts and the app's last answer. ``status`` narrows them (``"failed"``, or several).

        Returns:
            Each ``noclick.SubscriptionDelivery``, its ``request_body`` exactly what was sent.

        Usage::

            app = noclick.Project.current()
            for subscription in app.subscriptions():
                for delivery in subscription.deliveries(status="failed"):
                    print(delivery.created_at, delivery.response_status, delivery.error)
        """
        wanted = status if status is None or isinstance(status, str) else ",".join(status)
        response = await self._request("GET", f"{self._app_path('deliveries()')}/deliveries",
                                        params=compact(status=wanted, limit=limit))
        return [SubscriptionDelivery._from(row) for row in (response or {}).get("data") or []]

    @synced
    async def test(self) -> SubscriptionDelivery:
        """An app's: POST a sample of its event to its path now and wait for the answer (10
        seconds at most). The body is what a real one gets, with ``test: true`` and
        placeholder values in the shape the event has reached your account in
        (``connection.events()`` shows it); until one has, ``data`` is empty and ``text`` says
        so. It's listed among its deliveries and never tried again.

        Returns:
            The ``noclick.SubscriptionDelivery``: ``delivered`` on a 2xx, else ``failed`` with the app's answer.

        Usage::

            whatsapp = noclick.Connection.from_name("whatsapp", integration="whatsapp")
            hook = noclick.Project.current().subscribe(noclick.OnEvent(whatsapp, "receive_message"), path="/hooks/whatsapp")
            delivery = hook.test()
            print(delivery.status, delivery.response_status)
        """
        return SubscriptionDelivery._from(await self._request("POST", f"{self._app_path('test()')}/test"))

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", self._path())

    @synced
    async def unsubscribe(self) -> None:
        """Stop hearing these events. What it already posted stays in the room; a
        webhook source's URL stops answering.

        Usage::

            room = noclick.Channel.get(channel_id)
            for subscription in room.subscriptions():
                if subscription.status == "error":
                    subscription.unsubscribe()
        """
        await self._request("DELETE", self._path())


# The settings ``from_name(create_if_missing=True)`` sets on an existing channel.
_CONVERGED = ("topic", "mode", "max_agent_turns", "max_mention_hops", "budget_usd")


def _thread(raw: Dict[str, Any], scope: Any) -> ChannelThread:
    return ChannelThread._from(raw)


async def _threads_params(workspace: Any, unread: bool) -> Dict[str, Any]:
    return {"workspace_id": await ref_id(workspace), "unread": "true" if unread else None}


KINDS = ("channel", "dm")


async def _list_params(status: Optional[str], workspace: Any, agent: Any, kind: Optional[str] = None) -> Dict[str, Any]:
    """A channel list's filters as the API takes them."""
    if kind is not None and kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    return {"status": status, "workspace_id": await ref_id(workspace), "agent_id": await agent_id(agent), "kind": kind}


class Channel(_Object):
    """A conversation between members. ``with`` closes it on exit."""

    _repr_keys = ("id", "name", "status")

    id: str = field("id")
    name: str = field("name")
    topic: Optional[str] = field("topic", doc="One line on what the channel is for.")
    mode: Optional[str] = field("mode")
    status: Optional[str] = field("status")
    halt_reason: Optional[str] = field("halt_reason", doc="Why a halted channel stopped (it wakes when a person posts).")
    unread_count: Optional[int] = field(
        "unread_count", doc="Messages since you last read it (``mark_read``; your own posts count as read): your "
                            "account's read point, or as a person in a workspace, your own (0 in one you aren't in).",
    )
    starred: Optional[bool] = field("starred", doc="Whether you starred it (``star``): yours alone, never shown to "
                                                   "anyone else.")
    muted: Optional[bool] = field("muted", doc="Whether you muted it (``mute``): unread for you only for what "
                                               "@mentions you, and a space's NoClick alerts you about it only then. "
                                               "Yours alone.")
    mention_count: Optional[int] = field(
        "mention_count", doc="Messages since you last read it that @mention you by name, as a person in a workspace "
                             "(the account is never mentioned): while it's muted, its ``unread_count``.",
    )
    kind: Optional[str] = field("kind", doc="``channel``, or ``dm``: a workspace's direct messages between two people.")
    last_message: Optional[Dict[str, Any]] = field(
        "last_message", doc="Its newest message as a read returns it: ``{id, text, author, created_at}`` (its text "
                            "cut to 200 characters).",
    )
    app_url: Optional[str] = field(
        "app_url", doc="Where the NoClick app opens it (one of your account's own; ``None`` for a user's).",
    )
    max_agent_turns: Optional[int] = field("max_agent_turns")
    budget_usd: Optional[float] = field("budget_usd")
    user_id: Optional[str] = field("user_id")
    workspace_id: Optional[str] = field(
        "workspace_id", doc="The ``noclick.Workspace`` it belongs to (``None`` for one on its own).",
    )
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        self._workspace: Any = None
        super()._init(**kwargs)

    async def _in_workspace(self) -> bool:
        if self._workspace is not None:
            return True
        return bool((await self._ensure()).get("workspace_id"))

    @property
    def members(self) -> List[ChannelMember]:
        return [ChannelMember._from(m) for m in self._sync_raw().get("members") or []]

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls,
        name: str,
        *,
        members: Sequence[Any] = (),
        mode: Optional[str] = None,
        max_agent_turns: Optional[int] = None,
        max_mention_hops: Optional[int] = None,
        budget_usd: Optional[float] = None,
        workspace: Any = None,
        topic: Optional[str] = None,
        allow_existing: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Channel":
        """Open a channel. Members are ``noclick.Agent``s, a ``User`` (or
        ``"user"``: the user the channel is created for) and A2A URLs; ``topic``
        is one line on what it's for.
        A person's message wakes every agent in the room (``mode="all"``, the
        default); with ``mode="mentions"`` it wakes only the agents it
        @mentions. An agent's message wakes only those it @mentions, in either
        mode. Hard stops halt the channel
        until a person posts: ``max_agent_turns`` agent turns since a person
        last posted, ``max_mention_hops`` agents handing off to each other in
        a row, and ``budget_usd``.

        ``workspace`` (a ``noclick.Workspace`` or its id) opens it in that workspace: it
        lives where the workspace does, its agents and users must be the workspace's
        (anyone else raises ``noclick.InvalidRequest``: ``ws.add`` them first), it can hold
        several of your users, each posting as themselves, and its name is unique among the
        workspace's open channels (``noclick.Conflict`` with ``existing_id``). There
        ``allow_existing=True`` returns the open channel already called ``name``, as it is: nothing
        about it changes. Outside a workspace names aren't unique, so it takes a ``workspace``.

        Returns:
            The new channel, ``open``, with its ``members``.

        Usage:
            Open a room for a user and two of your agents. Leaving the
            ``with`` block closes it::

                writer = noclick.Agent.from_name("writer")
                reviewer = noclick.Agent.from_name("reviewer")
                user = noclick.User.from_id("user_42")
                with noclick.Channel.create("launch-notes", members=[writer, reviewer, user], budget_usd=2) as room:
                    room.post("@writer announce Tuesday's launch", as_=user)

            Every message a person posts wakes every agent in the room
            (``mode="mentions"`` wakes only the ones it @mentions)::

                room = noclick.Channel.create(
                    "triage", members=[noclick.Agent.from_name("billing"), noclick.Agent.from_name("support")],
                    max_agent_turns=6,
                )
                room.post("A customer was charged twice for one visit.")

            A room inside a workspace, with two of the company's people::

                acme = noclick.Workspace.from_name("Acme")
                room = noclick.Channel.create(
                    "billing", workspace=acme,
                    members=[noclick.Agent.from_name("billing"), noclick.User.from_id("ana"), noclick.User.from_id("bo")],
                )
        """
        if mode is not None and mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
        in_workspace = workspace is not None
        if allow_existing and not in_workspace:
            raise ValueError("Channel.create(allow_existing=True) needs workspace=: only a workspace's channel names "
                             "are unique")
        workspace_id = await ref_id(workspace) if in_workspace else None
        scope = resolve_scope(_workspace_scope(workspace, user) if in_workspace else _channel_scope(members, user))
        body = compact(
            name=name, members=[await _member_spec(m, workspace=in_workspace) for m in members], mode=mode,
            max_agent_turns=max_agent_turns, max_mention_hops=max_mention_hops, budget_usd=budget_usd,
            workspace_id=workspace_id, topic=topic,
        )
        raw = await cls._create_named("/v1/channels", body, allow_existing=allow_existing, user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        create_if_missing: bool = False,
        members: Optional[Sequence[Any]] = None,
        mode: Optional[str] = None,
        topic: Optional[str] = None,
        max_agent_turns: Any = UNSET,
        max_mention_hops: Any = UNSET,
        budget_usd: Any = UNSET,
        triggers: Optional[Sequence[Any]] = None,
        workspace: Any = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Channel":
        """A lazy reference to the open channel called ``name`` in the current (or given)
        user (a closed one of that name isn't found), or in ``workspace`` (a
        ``noclick.Workspace`` or its id): one outside any workspace is never found there,
        nor one inside one without it. Given fields, it gets the channel and sets the ones you pass,
        on every run: on an existing channel an agent or A2A member your code no longer lists is
        removed and a new one added, settings that differ are set to yours, and ``triggers`` are set
        like an agent's: a schedule your code no longer lists is removed, a new one added.
        ``create_if_missing=True`` opens it with the fields ``Channel.create`` takes when there's
        none; without it, a missing channel raises ``noclick.NotFound``. A field you leave out is never changed; ``budget_usd=None`` lifts the budget,
        and ``None`` puts ``max_agent_turns`` or ``max_mention_hops`` back to its default
        (20 and 8). In a workspace, the name is unique among its open channels. Each run with
        fields is a write: set them at startup or in a setup script, and take the bare
        ``from_name`` in request handlers.

        ``triggers`` are ``noclick.Cron`` schedules whose ``message`` is posted in the room on
        each tick, as your account: it wakes every agent in the room (only the ones it
        @mentions with ``mode="mentions"``) and restarts a halted channel, as a person's post does.

        Returns:
            A channel that loads (or is opened, or has your fields set) the first time it's used.
            Nothing is sent yet.

        Usage:
            A standing room whose agents start every weekday on their own::

                writer = noclick.Agent.from_name("writer")
                reviewer = noclick.Agent.from_name("reviewer")
                room = noclick.Channel.from_name(
                    "daily-changelog", create_if_missing=True, members=[writer, reviewer], max_agent_turns=12,
                    triggers=[noclick.Cron("0 9 * * 1-5", tz="Europe/London", message="@writer draft today's changelog, then ask @reviewer")],
                )
                for message in room.messages():
                    print(message.author.name, message.text)
        """
        if mode is not None and mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
        scope = _workspace_scope(workspace, user) if workspace is not None else _channel_scope(members or (), user)
        channel = cls._new(hints={"name": name}, client=client, user=scope)
        channel._workspace = workspace
        settings = dict(mode=mode, topic=topic, max_agent_turns=max_agent_turns,
                        max_mention_hops=max_mention_hops, budget_usd=budget_usd)
        channel._define({
            "name": name,
            **{k: v for k, v in settings.items() if v is not UNSET and v is not None},
            # An explicit None is a field you pass: the budget lifts, a limit takes its default.
            **{k: DEFAULT_STOPS.get(k) for k, v in settings.items() if v is None and k not in ("mode", "topic")},
            **({} if members is None else {"members": list(members)}),
            **({} if triggers is None else {"triggers": list(triggers)}),
        }, create_if_missing=create_if_missing)
        return channel

    @synced
    @classmethod
    async def list(
        cls,
        *,
        status: Optional[str] = None,
        workspace: Any = None,
        agent: Any = None,
        kind: Optional[str] = None,
        limit: Optional[int] = None,
        user_filter: Any = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Channel"]:
        """The current user's channels (the account's own outside
        ``as_user``, or those ``user_filter`` covers); ``status="open"``
        or ``"closed"``, at most ``limit``. ``workspace`` (a ``noclick.Workspace``
        or its id) keeps the ones in it; ``agent`` (a ``noclick.Agent`` or its id)
        the ones that agent is a member of; ``kind`` ``channel`` or ``dm``.

        Returns:
            Every matching channel, newest first, fetched page by page.
            ``status="open"`` also takes halted channels, which wake when a person posts.

        Usage:
            The channels of the user you're acting for::

                with noclick.as_user(noclick.User.from_id("user_42")):
                    for room in noclick.Channel.list(status="open"):
                        print(room.name, room.status)

            Or every user's, from account code::

                rooms = noclick.Channel.list(user_filter=noclick.ALL_USERS, limit=20)
        """
        _check_status(status)
        return await list_all(
            "/v1/channels", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params=await _list_params(status, workspace, agent, kind), user=user, user_filter=user_filter,
            limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, status: Optional[str] = None,
        workspace: Any = None, agent: Any = None, kind: Optional[str] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of channels; pass ``next_cursor`` back as ``cursor``. ``workspace``,
        ``agent`` and ``kind`` are as in ``list``.

        Returns:
            A page whose ``data`` holds the channels and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Channel.list_page(status="open", limit=50)
            while True:
                for room in page.data:
                    print(room.name)
                if page.next_cursor is None:
                    break
                page = noclick.Channel.list_page(status="open", limit=50, cursor=page.next_cursor)
        """
        _check_status(status)
        return await list_page(
            "/v1/channels", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params=await _list_params(status, workspace, agent, kind), user=user, user_filter=user_filter,
            cursor=cursor, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def dm(cls, with_whom: Any, *, workspace: Any, user: Any = AMBIENT,
                 client: Optional[Client] = None) -> "Channel":
        """The DM between you and one other person of ``workspace`` (one of your account's, or one you joined),
        opened the first time: ``"account"`` names the account's owner (from a person in it), else that
        person's user (a ``noclick.User`` or their user id). Only its two people read it.

        Returns:
            The DM, a channel with ``kind`` ``dm``.

        Usage::

            session = noclick.Workspace.session(acme_id)
            room = noclick.Channel.dm("account", workspace=acme_id, client=session.client())
            room.post("Got a minute?")
        """
        member = {"account": True} if with_whom == "account" else {
            "user_id": await user_ref(with_whom) if isinstance(with_whom, User) else with_whom}
        scope = resolve_scope(user)
        response = await resolve_client(client).request(
            "POST", "/v1/channels", json={"kind": "dm", "workspace_id": await ref_id(workspace), "members": [member]},
            user=scope) or {}
        return cls._new(raw=response, client=client, user=scope)

    @synced
    @classmethod
    async def threads(
        cls, *, workspace: Any = None, unread: bool = False, limit: Optional[int] = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List[ChannelThread]:
        """The threads you follow across your channels (the account's own outside ``as_user``), newest reply
        first: you follow a thread you start, post in or are @mentioned in. ``unread`` keeps those with replies
        you haven't read, ``workspace`` one workspace's.

        Returns:
            Each ``ChannelThread``: its channel, the message that started it, its latest reply and counts.

        Usage::

            for thread in noclick.Channel.threads(unread=True):
                print(f"#{thread.channel_name}: {thread.latest_reply.text} ({thread.unread_count} new)")
        """
        return await list_all("/v1/channels/threads", _thread, params=await _threads_params(workspace, unread),
                              user=user, limit=limit, client=client)

    @synced
    @classmethod
    async def threads_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, workspace: Any = None,
        unread: bool = False, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of ``threads``; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds ``ChannelThread``s and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Channel.threads_page(limit=20)
        """
        return await list_page("/v1/channels/threads", _thread, params=await _threads_params(workspace, unread),
                               user=user, cursor=cursor, limit=limit, client=client)

    @synced
    @classmethod
    async def sections(
        cls, *, workspace: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> ChannelSections:
        """Your own sections of a workspace's channels (``workspace`` omitted: your channels in no workspace), as a
        sidebar groups them, and which built-in lists are folded. Version 0 with no sections until the first save.

        Returns:
            The ``ChannelSections``: each section's name, whether it's folded and its channel ids, and the version.

        Usage::

            layout = noclick.Channel.sections(workspace=space)
            for section in layout.sections:
                print(section.name, len(section.channel_ids))
        """
        response = await resolve_client(client).request(
            "GET", "/v1/channels/sections", params={"workspace_id": await ref_id(workspace)},
            user=resolve_scope(user)) or {}
        return ChannelSections._from(response)

    @synced
    @classmethod
    async def save_sections(
        cls, sections: Sequence[ChannelSection], *, version: int, folded: Sequence[str] = (), workspace: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> ChannelSections:
        """Save your sections of a workspace's channels, replacing them whole. ``version`` is the one they were read
        at: a save made since wins and this one raises ``Conflict`` (its ``version`` is the one kept), so read them
        again and make the change on that.

        Returns:
            The ``ChannelSections`` as kept, at their new version.

        Usage::

            layout = noclick.Channel.sections()
            launch = noclick.ChannelSection(str(uuid.uuid4()), "Launch", channel_ids=[channel.id])
            noclick.Channel.save_sections([*layout.sections, launch], version=layout.version)
        """
        response = await resolve_client(client).request("PUT", "/v1/channels/sections", json={
            "workspace_id": await ref_id(workspace), "version": version, "folded": list(folded),
            "sections": [{"id": s.id, "name": s.name, "folded": s.folded, "channel_ids": list(s.channel_ids)}
                         for s in sections]}, user=resolve_scope(user)) or {}
        return ChannelSections._from(response)

    @classmethod
    def from_id(cls, channel_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Channel":
        """A lazy reference to a channel by id.

        Returns:
            A channel that loads the first time you read a field. Nothing is sent yet.

        Usage::

            room = noclick.Channel.from_id("5d2f8c1e-7a4b-4e9d-8c3f-1b6a0e9d7c25")
            room.post("Ship it on Tuesday.")
        """
        return cls._new(hints={"id": channel_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, channel_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Channel":
        """Load a channel by id now. An unknown id raises ``noclick.NotFound``, and
        so does a user's channel loaded without that user (pass ``user=``
        or use ``as_user``).

        Returns:
            The channel, loaded, with its ``members``.

        Usage:
            Load a channel whose id you saved::

                room = noclick.Channel.get("5d2f8c1e-7a4b-4e9d-8c3f-1b6a0e9d7c25")
                print(room.name, room.status, [m.name for m in room.members])

            A channel you opened for a user is loaded as that user::

                user = noclick.User.from_id("user_42")
                room = noclick.Channel.get("5d2f8c1e-7a4b-4e9d-8c3f-1b6a0e9d7c25", user=user)
        """
        channel = cls.from_id(channel_id, client=client, user=user)
        await channel._ensure()
        return channel

    def _path(self) -> str:
        return f"/v1/channels/{self._known('id')}"

    async def _id_path(self) -> str:
        """``_path()`` once the id is known (a channel reached by name loads first)."""
        if not self._known("id"):
            await self._ensure()
        return self._path()

    async def _load(self) -> Dict[str, Any]:
        if self._known("id"):
            return await self._request("GET", self._path())
        name = self._hints["name"]
        workspace_id = await ref_id(self._workspace)
        page = await self._request(
            "GET", "/v1/channels", params={"name": name, "status": "open", "workspace_id": workspace_id},
        ) or {}
        rows = [row for row in page.get("data") or []
                if row.get("name") == name and row.get("status") != "closed" and row.get("workspace_id") == workspace_id]
        if rows:
            return await self._converge(rows[0])
        if not self._creates:
            raise NotFound(
                f"No open channel is named {name!r}.",
                next_step="Open it with noclick.Channel.create(...) or pass create_if_missing=True.",
                details={"name": name},
            )
        definition = self._create_with
        in_workspace = workspace_id is not None
        body = {
            **compact(**{k: v for k, v in definition.items() if k not in ("members", "triggers")}),
            **({"workspace_id": workspace_id} if in_workspace else {}),
            "members": [await _member_spec(m, workspace=in_workspace) for m in definition.get("members") or []
                        if in_workspace or not isinstance(m, User)],
            **({"triggers": [await _channel_trigger(t) for t in definition["triggers"]]}
               if "triggers" in definition else {}),
        }
        try:
            return await self._request("POST", "/v1/channels", json=body)
        except Conflict as exc:  # opened concurrently
            if not exc.existing_id:
                raise
            return await self._converge(await self._request("GET", f"/v1/channels/{exc.existing_id}"))

    async def _converge(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Set the fields ``from_name`` was given on an existing channel."""
        definition = self._create_with
        if definition is None:
            return raw
        channel_id = raw["id"]
        changes = {k: definition[k] for k in _CONVERGED if k in definition and raw.get(k) != definition[k]}
        if changes:
            raw = await self._request("PATCH", f"/v1/channels/{channel_id}", json=changes)
        changed = False
        if "members" in definition:
            # A workspace channel's users are members like its agents; elsewhere the one user is its scope.
            in_workspace = self._workspace is not None
            kept = ("agent", "a2a", "user") if in_workspace else ("agent", "a2a")
            wanted = [await _member_spec(m, workspace=in_workspace) for m in definition["members"]
                      if in_workspace or (not isinstance(m, User) and m != "user")]
            have = [ChannelMember._from(m) for m in raw.get("members") or []]
            for member in have:
                if member.type in kept and not any(_matches(member, spec) for spec in wanted):
                    await self._request("DELETE", f"/v1/channels/{channel_id}/members/{member.id}")
                    changed = True
            for spec in wanted:
                if not any(_matches(member, spec) for member in have):
                    await self._request("POST", f"/v1/channels/{channel_id}/members", json=spec)
                    changed = True
        if "triggers" in definition:
            wanted_triggers = {spec_key(w): w for w in [await _channel_trigger(t) for t in definition["triggers"]]}
            response = await self._request("GET", f"/v1/channels/{channel_id}/triggers") or {}
            have_triggers = {
                spec_key({"kind": row["kind"], **(row.get("spec") or {})}): row for row in response.get("data") or []
            }
            for key, row in have_triggers.items():
                if key not in wanted_triggers:
                    await self._request("DELETE", f"/v1/channels/{channel_id}/triggers/{row['id']}")
            for key, body in wanted_triggers.items():
                if key not in have_triggers:
                    await self._request("POST", f"/v1/channels/{channel_id}/triggers", json=body)
        return await self._request("GET", f"/v1/channels/{channel_id}") if changed else raw

    # --- triggers --------------------------------------------------------

    @synced
    async def triggers(self) -> List[AgentTrigger]:
        """Its schedules: each ``Cron`` that posts in the room.

        Returns:
            Each trigger with its ``kind`` (``cron``), its ``spec`` (``cron``, ``tz``, ``message``),
            ``status``, ``next_run`` and when it ``last_fired_at``.

        Usage::

            room = noclick.Channel.from_name("daily-changelog")
            for trigger in room.triggers():
                print(trigger.spec["cron"], trigger.next_run, trigger.spec["message"])
        """
        response = await self._request("GET", f"{await self._id_path()}/triggers") or {}
        return [AgentTrigger._from(row) for row in response.get("data") or []]

    @synced
    async def add_trigger(self, trigger: Cron) -> AgentTrigger:
        """Post ``trigger.message`` in the room on the ``noclick.Cron``'s schedule, as your
        account (a channel holds up to 20). On a channel whose ``from_name(..., triggers=...)`` sets
        its schedules, that code sets the list instead, and removes one added here the next time it
        runs.

        Returns:
            The trigger as added, with its ``next_run``.

        Usage::

            room = noclick.Channel.from_name("launch-notes")
            room.add_trigger(noclick.Cron("0 16 * * 5", tz="America/New_York", message="@writer wrap up the week's notes"))
        """
        body = await _channel_trigger(trigger)
        return AgentTrigger._from(await self._request("POST", f"{await self._id_path()}/triggers", json=body))

    @synced
    async def remove_trigger(self, trigger: Any) -> None:
        """Remove a schedule: an ``AgentTrigger`` (or its id), or the ``Cron`` you added
        (``noclick.NotFound`` if the channel has none like it).

        Usage::

            room = noclick.Channel.from_name("launch-notes")
            for trigger in room.triggers():
                room.remove_trigger(trigger)
        """
        path = await self._id_path()
        if isinstance(trigger, AgentTrigger):
            trigger_id = trigger.id
        elif isinstance(trigger, str):
            trigger_id = trigger
        else:
            wanted = spec_key(await _channel_trigger(trigger))
            match = [t for t in await self.triggers.aio() if spec_key({"kind": t.kind, **t.spec}) == wanted]
            if not match:
                raise NotFound(
                    f"The channel has no schedule like {trigger!r}.",
                    next_step="List them with channel.triggers() and remove one of those.",
                    details={"channel_id": self._known("id")},
                )
            trigger_id = match[0].id
        await self._request("DELETE", f"{path}/triggers/{trigger_id}")

    # --- subscriptions ---------------------------------------------------

    @synced
    async def subscribe(self, source: Any, *, wake: Any = None, filters: Optional[Dict[str, Any]] = None) -> Subscription:
        """Post events into the room as they happen, each as a message from the app that
        sent it, written the way an agent's trigger reads it (the event in words, with
        the ids an agent needs to act on it). ``source`` is ``noclick.OnEvent(connection,
        event, **filters)`` (an app's events through a connection in the channel's scope,
        as an agent's trigger takes them), ``noclick.OnWebhook(name=...)`` (a URL whose
        POSTs are posted: ``subscription.url``) or a NoClick event: its type
        (``"operation.failed"``, ``"connection.disconnected"``, ``"agent.job.update"``; ``*``
        matches the rest of a name) or ``noclick.OnPlatformEvent(type, message=...)``, posted
        as the app named for the type. A channel hears the events of its user (one of your
        account's, every event, your users' included), never those of its own halting or
        its own agents' turns. ``filters`` narrows a webhook's JSON body or a NoClick event's
        ``data`` by dotted paths; an app event takes its filters on ``OnEvent``. ``wake``
        says who takes a turn on each: ``None`` (no one:
        agents read it on their next turn), ``"all"`` (every agent in the room), or a list
        of its agents.

        Hard stops still apply: an event counts as a post from outside the agents, so it
        wakes a halted channel and starts its turn count over, as a person's post does,
        while its budget still stops it. Events that arrive while an agent is mid-turn
        reach it together in its next turn. A channel holds up to 20 subscriptions; a
        closed one hears nothing.

        Returns:
            The subscription, ``active`` (a webhook source with its ``url``).

        Usage:
            Every failed payment in a room, and the billing agent on it::

                stripe = noclick.Connection.from_name("stripe", integration="stripe")
                billing = noclick.Agent.from_name("billing")
                room = noclick.Channel.create("billing-alerts", members=[billing])
                room.subscribe(noclick.OnEvent(stripe, "invoice_payment_failed"), wake=[billing])

            Your deploy pipeline's webhooks, waking every agent in the room::

                room = noclick.Channel.get(channel_id)
                deploys = room.subscribe(noclick.OnWebhook(name="deploys"), wake="all", filters={"status": "failed"})
                print(deploys.url)   # point your CI's webhook here

            A broken connection anywhere in your account, posted for whoever reads the room next::

                room = noclick.Channel.get(channel_id)
                room.subscribe("connection.disconnected")

            Failed jobs, for the agent that triages them::

                triage = noclick.Agent.from_name("triage")
                room = noclick.Channel.get(channel_id)
                room.subscribe("operation.failed", filters={"kind": "agent.task"}, wake=[triage])
        """
        body = await subscription_body(source, wake, filters)
        response = await self._request("POST", f"{await self._id_path()}/subscriptions", json=body)
        return Subscription._new(raw=response, client=self._client, user=self._call_scope())

    @synced
    async def subscriptions(self) -> List[Subscription]:
        """What the room hears: its own subscriptions (a workspace's that post here are
        on ``ws.subscriptions()``).

        Returns:
            Each subscription with its ``source``, ``wake``, ``status`` and, for a webhook, its ``url``.

        Usage::

            room = noclick.Channel.get(channel_id)
            for subscription in room.subscriptions():
                print(subscription.source["kind"], subscription.wake, subscription.status, subscription.last_event_at)
        """
        response = await self._request("GET", f"{await self._id_path()}/subscriptions") or {}
        return [Subscription._new(raw=row, client=self._client, user=self._call_scope())
                for row in response.get("data") or []]

    # --- members ---------------------------------------------------------

    @synced
    async def add(self, member: Any) -> ChannelMember:
        """Add an ``noclick.Agent``, the user or an A2A URL. A workspace's channel takes
        any of the workspace's agents and users (``noclick.InvalidRequest`` for anyone
        else: ``ws.add`` them first), and A2A URLs.

        Returns:
            The member as the channel now holds it; remove it later by its ``id``.

        Usage::

            room = noclick.Channel.get(channel_id)
            room.add(noclick.Agent.from_name("reviewer"))
            partner = room.add(
                noclick.A2AMember("https://agents.partner.com/a2a", headers={"Authorization": "Bearer ..."}),
            )
            print(partner.name, partner.a2a_header_names)   # agents.partner.com ['Authorization']
        """
        spec = await _member_spec(member, workspace=isinstance(member, User) and await self._in_workspace())
        response = await self._request("POST", f"{await self._id_path()}/members", json=spec) or {}
        if response.get("object") == "channel":
            self._raw = response
            return next((m for m in reversed(self.members) if _matches(m, spec)), None)
        added = ChannelMember._from(response)
        if self._raw is not None:
            self._raw = {**self._raw, "members": [*(self._raw.get("members") or []), response]}
        return added

    @synced
    async def remove(self, member: Any) -> None:
        """Remove a member (a ``ChannelMember``, its id, or the Agent / user / URL you added).

        Usage::

            room = noclick.Channel.get(channel_id)
            room.remove(noclick.Agent.from_name("reviewer"))
            for member in room.members:
                if member.type == "a2a":
                    room.remove(member)
        """
        if isinstance(member, ChannelMember):
            member_id = member.id
        elif isinstance(member, str) and not member.startswith(("https://", "http://")) and member != "user":
            member_id = member
        else:
            spec = await _member_spec(member, workspace=isinstance(member, User) and await self._in_workspace())
            self._raw = await self._load()
            found = next((m for m in self.members if _matches(m, spec)), None)
            if found is None:
                raise ValueError(f"{member!r} is not a member of channel {self._known('id')}")
            member_id = found.id
        await self._request("DELETE", f"{await self._id_path()}/members/{member_id}")
        if self._raw is not None:
            self._raw = {**self._raw, "members": [
                m for m in self._raw.get("members") or [] if m.get("id") != member_id
            ]}

    # --- messages --------------------------------------------------------

    @synced
    async def update(
        self, *, name: Any = UNSET, topic: Any = UNSET, mode: Any = UNSET, max_agent_turns: Any = UNSET,
        max_mention_hops: Any = UNSET, budget_usd: Any = UNSET,
    ) -> "Channel":
        """Change an open channel's ``name``, ``topic``, ``mode`` or hard stops; what you
        leave out stays (``budget_usd=None`` lifts the budget). A workspace's open channels
        each have their own name: a taken one raises ``noclick.Conflict`` with ``existing_id``.

        Returns:
            This channel, as it now is.

        Usage::

            room = noclick.Channel.get(channel_id)
            room.update(topic="Friday's launch", mode="mentions")
            print(room.topic, room.mode)   # Friday's launch mentions
        """
        if mode is not UNSET and mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
        changes = {k: v for k, v in dict(name=name, topic=topic, mode=mode, max_agent_turns=max_agent_turns,
                                         max_mention_hops=max_mention_hops, budget_usd=budget_usd).items()
                   if v is not UNSET}
        self._raw = await self._request("PATCH", await self._id_path(), json=changes)
        return self

    @synced
    async def upload(
        self, file: Any, *, name: Optional[str] = None, mime_type: Optional[str] = None, voice: bool = False,
        peaks: Optional[Sequence[float]] = None,
    ) -> Attachment:
        """Store a file (a path, bytes or a binary file object) to post with a message.
        It's kept as an account file, capped as those are: 10 MB an image (JPEG,
        PNG, WebP or GIF), 15 MB a document, 20 MB audio or video. ``voice=True``
        marks a recorded clip (audio), which may carry its waveform ``peaks``.

        Returns:
            The attachment; post it with ``post(files=[...])``. A file posts once.

        Usage::

            room = noclick.Channel.get(channel_id)
            report = room.upload("q3-report.pdf")
            room.post("@analyst what stands out?", files=[report])
        """
        return await upload(self._request, f"{await self._id_path()}/attachments", file, name=name,
                            mime_type=mime_type, voice=voice, peaks=peaks)

    @synced
    async def post(self, text: str = "", *, as_: Any = None, files: Sequence[Any] = (), thread: Any = None,
                   also_in_channel: bool = False) -> ChannelMessage:
        """Post a message, from you (the account) or ``as_`` an agent or the user (in a
        workspace channel, any of its users). ``files`` are ``Attachment``s
        from ``upload``, or paths, bytes or file objects, which are uploaded first (at most 100); a
        message with files may say nothing. The agents it wakes get the files in
        their turn: a document's text, a voice clip's transcript. ``thread`` (a message or its id) posts it as a
        reply in that message's thread, and ``also_in_channel`` in the main timeline too. ``@channel``,
        ``@here`` or ``@everyone`` wakes every agent in the channel.

        Returns:
            The posted message, with the ``id`` you can pass as ``after`` to read what follows.

        Usage:
            A person's message (yours or the user's) wakes the agents it
            @mentions and restarts a halted channel. You can post as an agent
            only once it's a member::

                user = noclick.User.from_id("user_42")
                writer = noclick.Agent.from_name("writer")
                room = noclick.Channel.create("launch-notes", members=[writer, user])
                room.post("Ship it on Tuesday.")                            # from your account
                room.post("@writer announce Tuesday's launch", as_=user)  # as the user
                room.post("Draft: we launch on Tuesday.", as_=writer)        # as one of the agents

            In a workspace's channel, each of its people posts as themselves::

                acme = noclick.Workspace.from_name("Acme")
                room = noclick.Channel.create("billing", workspace=acme, members=[
                    noclick.Agent.from_name("billing"), noclick.User.from_id("ana"), noclick.User.from_id("bo"),
                ])
                room.post("@billing can we refund order 42?", as_=noclick.User.from_id("ana"))
                room.post("I approve the refund.", as_=noclick.User.from_id("bo"))

            With files, and a voice clip::

                room.post("Here's the deck and my notes.", files=["deck.pdf", room.upload("notes.m4a", voice=True)])
        """
        attachments = await attachment_ids(files, self.upload.aio)
        response = await self._request(
            "POST", f"{await self._id_path()}/messages",
            json=compact(text=text, attachments=attachments or None, thread_id=_message_id(thread),
                         also_in_channel=also_in_channel or None, **{"as": await self._as(as_)}),
        )
        return ChannelMessage._from(response or {})

    async def _as(self, as_: Any) -> Optional[Dict[str, Any]]:
        return await _author_spec(as_, workspace=isinstance(as_, User) and await self._in_workspace())

    @synced
    async def reply(self, message: Any, text: str = "", *, as_: Any = None, files: Sequence[Any] = (),
                    also_in_channel: bool = False) -> ChannelMessage:
        """Reply in ``message``'s thread (a message or its id): it stays out of the main timeline unless
        ``also_in_channel``. The agents it wakes answer in the thread, and you follow it, read through your reply.

        Returns:
            The reply, its ``thread_id`` the message it answers.

        Usage::

            room = noclick.Channel.get(channel_id)
            ask = room.post("@writer draft the launch notes")
            room.reply(ask, "Keep it under 200 words.")
            for reply in room.replies(ask):
                print(reply.author.name, reply.text)
        """
        return await self.post.aio(text, as_=as_, files=files, thread=message, also_in_channel=also_in_channel)

    @synced
    async def replies(self, message: Any, *, after: Any = None, wait_s: Optional[int] = None, before: Any = None,
                      newest: bool = False, limit: Optional[int] = None) -> List[ChannelMessage]:
        """``message``'s thread oldest first, read as ``messages`` reads the timeline.

        Returns:
            Up to ``limit`` (50 by default) replies, oldest first.

        Usage::

            room = noclick.Channel.get(channel_id)
            latest = room.replies(message_id, newest=True, limit=20)
        """
        if sum(1 for given in (after, before, newest) if given) > 1:
            raise ValueError("Pass one of after, before or newest.")
        return await self._page(f"{await self._id_path()}/messages/{_thread_id(message)}/replies", _message_id(after),
                                wait_s, before=_message_id(before), newest=newest, limit=limit)

    @synced
    async def mark_thread_read(self, message: Any, reply: Any = None) -> ChannelMessage:
        """Mark ``message``'s thread read for you, through ``reply`` or its newest; its ``unread_replies`` count
        from there, and never back.

        Returns:
            The message that started the thread.

        Usage::

            room.mark_thread_read(message_id)
        """
        return ChannelMessage._from(await self._request(
            "POST", f"{await self._id_path()}/messages/{_thread_id(message)}/read",
            json=compact(reply_id=_message_id(reply))) or {})

    @synced
    async def follow(self, message: Any) -> ChannelMessage:
        """Follow ``message``'s thread (read through its newest reply now): it's among your ``Channel.threads``.

        Returns:
            The message that started the thread.

        Usage::

            room.follow(message_id)
        """
        return ChannelMessage._from(await self._request(
            "POST", f"{await self._id_path()}/messages/{_thread_id(message)}/follow") or {})

    @synced
    async def unfollow(self, message: Any) -> ChannelMessage:
        """Stop following ``message``'s thread, until you post in it or are @mentioned there.

        Returns:
            The message that started the thread.

        Usage::

            room.unfollow(message_id)
        """
        return ChannelMessage._from(await self._request(
            "DELETE", f"{await self._id_path()}/messages/{_thread_id(message)}/follow") or {})

    @synced
    async def pin(self, message: Any, *, as_: Any = None) -> ChannelMessage:
        """Pin a message (or its id), as your account or ``as_`` a member; at most 100 a channel. The room is told
        once.

        Returns:
            The message, with ``pinned``.

        Usage::

            room.pin(decision)
        """
        return ChannelMessage._from(await self._request(
            "POST", f"{await self._id_path()}/messages/{_message_id(message)}/pin",
            json=compact(**{"as": await self._as(as_)})) or {})

    @synced
    async def unpin(self, message: Any) -> ChannelMessage:
        """Unpin a message; one that isn't pinned changes nothing.

        Returns:
            The message.

        Usage::

            room.unpin(message_id)
        """
        return ChannelMessage._from(await self._request(
            "DELETE", f"{await self._id_path()}/messages/{_message_id(message)}/pin") or {})

    @synced
    async def pins(self) -> List[ChannelPin]:
        """Its pinned messages, newest pin first.

        Returns:
            Each ``ChannelPin``: the message, who pinned it and when.

        Usage::

            for pin in room.pins():
                print(pin.by.name, pin.message.text)
        """
        rows = (await self._request("GET", f"{await self._id_path()}/pins") or {}).get("data") or []
        return [ChannelPin(ChannelMessage._from(r.get("message") or {}), _author(r.get("by")), parse_time(r.get("at")))
                for r in rows]

    @synced
    async def bookmarks(self) -> List[ChannelBookmark]:
        """Its saved links, in the order they were added.

        Returns:
            Each ``ChannelBookmark``.

        Usage::

            for bookmark in room.bookmarks():
                print(bookmark.title, bookmark.url)
        """
        rows = (await self._request("GET", f"{await self._id_path()}/bookmarks") or {}).get("data") or []
        return [ChannelBookmark._from(r) for r in rows]

    @synced
    async def add_bookmark(self, url: str, *, title: Optional[str] = None, as_: Any = None) -> ChannelBookmark:
        """Save a link (an http(s) address) in the channel, at most 100; without a ``title`` its host names it.

        Returns:
            The bookmark.

        Usage::

            room.add_bookmark("https://docs.example.com/launch-plan", title="Launch plan")
        """
        return ChannelBookmark._from(await self._request(
            "POST", f"{await self._id_path()}/bookmarks",
            json=compact(url=url, title=title, **{"as": await self._as(as_)})) or {})

    @synced
    async def update_bookmark(self, bookmark: Any, *, url: Optional[str] = None,
                              title: Optional[str] = None) -> ChannelBookmark:
        """Change a bookmark's (or its id's) address or title (an empty title: named by its host again).

        Returns:
            The bookmark.

        Usage::

            room.update_bookmark(bookmark, title="Plan v2")
        """
        bookmark_id = bookmark.id if isinstance(bookmark, ChannelBookmark) else bookmark
        return ChannelBookmark._from(await self._request(
            "PATCH", f"{await self._id_path()}/bookmarks/{bookmark_id}", json=compact(url=url, title=title)) or {})

    @synced
    async def remove_bookmark(self, bookmark: Any) -> None:
        """Remove a bookmark (or its id).

        Usage::

            room.remove_bookmark(bookmark)
        """
        bookmark_id = bookmark.id if isinstance(bookmark, ChannelBookmark) else bookmark
        await self._request("DELETE", f"{await self._id_path()}/bookmarks/{bookmark_id}")

    async def _shelf(self, path: str, q: Optional[str], limit: Optional[int], cursor: Optional[str]) -> Dict[str, Any]:
        return await self._request("GET", path, params={"q": q, "limit": limit, "cursor": cursor}) or {}

    @synced
    async def files(self, *, q: Optional[str] = None, limit: Optional[int] = None,
                    cursor: Optional[str] = None) -> Page:
        """The files posted in it and its threads, newest first; ``q`` matches their names.

        Returns:
            A page of ``ChannelFile``s; pass ``next_cursor`` back as ``cursor``.

        Usage::

            for item in room.files(q="report").data:
                print(item.file.name, item.author.name)
        """
        page = await self._shelf(f"{await self._id_path()}/files", q, limit, cursor)
        return Page([ChannelFile(r["message_id"], r.get("thread_id"), _author(r.get("author")),
                                 parse_time(r.get("created_at")), Attachment._from(r.get("file") or {}))
                     for r in page.get("data") or []], page.get("next_cursor"))

    @synced
    async def links(self, *, q: Optional[str] = None, limit: Optional[int] = None,
                    cursor: Optional[str] = None) -> Page:
        """The web addresses posted in it and its threads, newest first (a markdown link with its text); ``q``
        matches the address or its text.

        Returns:
            A page of ``ChannelLink``s; pass ``next_cursor`` back as ``cursor``.

        Usage::

            for link in room.links().data:
                print(link.domain, link.url)
        """
        page = await self._shelf(f"{await self._id_path()}/links", q, limit, cursor)
        return Page([ChannelLink(r["message_id"], r.get("thread_id"), _author(r.get("author")),
                                 parse_time(r.get("created_at")), r.get("url") or "", r.get("title"),
                                 r.get("domain") or "")
                     for r in page.get("data") or []], page.get("next_cursor"))

    @synced
    async def delete(self) -> TrashItem:
        """Move the channel to the trash: its agents' turns there are canceled and what it hears stops,
        restorable for 30 days with everything it held.

        Returns:
            Its ``TrashItem``: ``restore()`` brings it back.

        Usage::

            noclick.Channel.get(channel_id).delete()
        """
        raw = await self._request("DELETE", await self._id_path())
        return trashed(raw, client=self._client, user=self._call_scope())

    @synced
    async def message(self, message: Any) -> ChannelMessage:
        """Read one message (or its id) as it now is, with its reactions.

        Returns:
            The message.

        Usage::

            room = noclick.Channel.get(channel_id)
            latest = room.message(message_id)
            print([(r.emoji, r.count) for r in latest.reactions])
        """
        return ChannelMessage._from(await self._request(
            "GET", f"{await self._id_path()}/messages/{_message_id(message)}") or {})

    @synced
    async def react(self, message: Any, emoji: str, *, as_: Any = None) -> ChannelMessage:
        """React to a message (or its id) with one emoji, as your account or
        ``as_`` a member (an agent, the user). Each member reacts with an emoji
        once; reacting again changes nothing. A message holds 20 different emoji.

        Returns:
            The message with its reactions.

        Usage::

            room = noclick.Channel.get(channel_id)
            for message in room.messages():
                if "shipped" in message.text:
                    room.react(message, "🎉")
        """
        body = compact(emoji=emoji, **{"as": await _author_spec(
            as_, workspace=isinstance(as_, User) and await self._in_workspace())})
        return ChannelMessage._from(await self._request(
            "POST", f"{await self._id_path()}/messages/{_message_id(message)}/reactions", json=body) or {})

    @synced
    async def unreact(self, message: Any, emoji: str, *, as_: Any = None) -> ChannelMessage:
        """Take back your account's reaction (or ``as_`` a member's); one that
        isn't there changes nothing.

        Returns:
            The message with its reactions.

        Usage::

            room = noclick.Channel.get(channel_id)
            room.unreact(message_id, "👍")
        """
        spec = await _author_spec(as_, workspace=isinstance(as_, User) and await self._in_workspace())
        return ChannelMessage._from(await self._request(
            "DELETE", f"{await self._id_path()}/messages/{_message_id(message)}/reactions/{path_segment(emoji)}",
            params=_as_query(spec)) or {})

    @synced
    async def mark_read(self, message: Any = None) -> "Channel":
        """Mark the channel read for your account, through ``message`` (or its
        id) or its newest; ``unread_count`` counts from there, and never back.

        Returns:
            This channel, with its ``unread_count``.

        Usage::

            room = noclick.Channel.get(channel_id)
            if room.unread_count:
                newest = room.messages(newest=True, limit=room.unread_count)
                room.mark_read(newest[-1])
        """
        self._raw = await self._request("POST", f"{await self._id_path()}/read",
                                        json=compact(message_id=_message_id(message)))
        return self

    async def _page(self, path: str, after: Optional[str], wait_s: Optional[int], *, before: Optional[str] = None,
                    newest: bool = False, limit: Optional[int] = None) -> List[ChannelMessage]:
        """The timeline's messages (``path`` its messages), or a thread's (its replies)."""
        response = await self._request(
            "GET", path,
            params={"after": after, "wait_s": wait_s, "before": before, "newest": "true" if newest else None,
                    "limit": limit},
            timeout=None if wait_s is None else wait_s + 15,
        ) or {}
        rows = response.get("data") if "data" in response else response.get("messages")
        return [ChannelMessage._from(row) for row in rows or []]

    @synced
    async def messages(self, *, after: Any = None, wait_s: Optional[int] = None, before: Any = None,
                       newest: bool = False, limit: Optional[int] = None) -> List[ChannelMessage]:
        """The main timeline oldest first (top-level messages, and replies also sent to it): after a message (or
        its id) if given, where ``wait_s`` long-polls until one arrives; or the ``limit`` just ``before`` one; or
        the ``newest``. A thread's replies are read with ``replies``.

        Returns:
            Up to ``limit`` (50 by default) messages, oldest first: pass the last one as ``after`` to
            read on, or the first as ``before`` to read back. Empty when none arrived within ``wait_s``.

        Usage:
            Read the room so far::

                room = noclick.Channel.get(channel_id)
                for message in room.messages():
                    print(f"{message.author.name}: {message.text}")

            Or wait up to 20 seconds (at most 50) for anything newer than the
            last message you saw::

                room = noclick.Channel.get(channel_id)
                newer = room.messages(after=last_seen, wait_s=20)

            The latest 20, then the 20 before them::

                room = noclick.Channel.get(channel_id)
                latest = room.messages(newest=True, limit=20)
                earlier = room.messages(before=latest[0], limit=20)
        """
        if sum(1 for given in (after, before, newest) if given) > 1:
            raise ValueError("Pass one of after, before or newest.")
        return await self._page(f"{await self._id_path()}/messages", _message_id(after), wait_s,
                                before=_message_id(before), newest=newest, limit=limit)

    @synced
    async def stream(self, *, after: Any = None, wait_s: int = _STREAM_WAIT_S) -> AsyncIterator[ChannelMessage]:
        """Yield every message (from the start, or after ``after``) as it
        arrives, until the channel closes. ``async for m in ch.stream.aio()``.

        Returns:
            Each message as it's posted, oldest first. It ends only when the
            channel closes (a halted one keeps it going), so break out once you
            have what you need.

        Usage:
            Follow the room until the reviewer posts::

                room = noclick.Channel.get(channel_id)
                for message in room.stream():
                    print(f"{message.author.name}: {message.text}")
                    if message.author.name == "reviewer":
                        break

            In async code::

                room = await noclick.Channel.get.aio(channel_id)
                async for message in room.stream.aio():
                    print(message.text)
        """
        cursor = _message_id(after)
        loop = asyncio.get_running_loop()
        while True:
            started = loop.time()
            batch = await self._page(f"{await self._id_path()}/messages", cursor, wait_s)
            for message in batch:
                cursor = message.id
                yield message
            if not batch:
                self._raw = await self._load()
                if self._raw.get("status") == "closed":
                    return
                await asyncio.sleep(max(0.0, 1.0 - (loop.time() - started)))  # never spin on a short poll

    @synced
    async def close(self) -> "Channel":
        """End the channel: agents stop taking turns.

        Returns:
            This channel, now ``closed``. Closing a closed channel changes nothing.

        Usage::

            room = noclick.Channel.get(channel_id)
            room.close()
            print(room.status)   # closed
        """
        response = await self._request("POST", f"{await self._id_path()}/close")
        self._raw = response if isinstance(response, dict) and response.get("id") else {
            **(self._raw or {}), "status": "closed",
        }
        return self

    @synced
    async def reopen(self, *, name: Optional[str] = None) -> "Channel":
        """Open a closed channel again, as it was: its members, its history and the events it heard (while its
        subscriptions are still in the trash). A workspace's needs no other open channel with its name: ``name``
        reopens it under another.

        Returns:
            This channel, ``open`` again. Reopening an open channel changes nothing.

        Usage::

            room = noclick.Channel.get(channel_id)
            room.reopen()
        """
        self._raw = await self._request("POST", f"{await self._id_path()}/reopen", json=compact(name=name)) or {}
        return self

    async def _preference(self, path: str, on: bool) -> "Channel":
        self._raw = await self._request("POST" if on else "DELETE", f"{await self._id_path()}/{path}") or {}
        return self

    @synced
    async def star(self) -> "Channel":
        """Star the channel for yourself alone (a person in a workspace: one you're in).

        Returns:
            This channel, ``starred`` for you.

        Usage::

            noclick.Channel.get(channel_id).star()
        """
        return await self._preference("star", True)

    @synced
    async def unstar(self) -> "Channel":
        """Take your star off the channel.

        Returns:
            This channel, no longer ``starred`` for you.

        Usage::

            noclick.Channel.get(channel_id).unstar()
        """
        return await self._preference("star", False)

    @synced
    async def mute(self) -> "Channel":
        """Mute the channel for yourself alone: it's unread for you only for what @mentions you, and a space's
        NoClick alerts you about it only then. Its agents carry on.

        Returns:
            This channel, ``muted`` for you, its ``unread_count`` its ``mention_count``.

        Usage::

            noclick.Channel.get(channel_id).mute()
        """
        return await self._preference("mute", True)

    @synced
    async def unmute(self) -> "Channel":
        """Unmute the channel.

        Returns:
            This channel, no longer ``muted`` for you.

        Usage::

            noclick.Channel.get(channel_id).unmute()
        """
        return await self._preference("mute", False)

    @synced
    async def join(self) -> "Channel":
        """Join the channel, as a person in its workspace who sees it (never a DM, nor a closed one): it keeps an
        entry that you joined. In it already, nothing changes.

        Returns:
            This channel, with you among its members.

        Usage::

            noclick.Channel.get(channel_id).join()
        """
        self._raw = await self._request("POST", f"{await self._id_path()}/join") or {}
        return self

    @synced
    async def leave(self) -> None:
        """Leave the channel, as a person in its workspace (never a DM): it keeps an entry that you left. Posting in
        it joins it again.

        Returns:
            ``None``.

        Usage::

            noclick.Channel.get(channel_id).leave()
        """
        await self._request("POST", f"{await self._id_path()}/leave")

    def __enter__(self) -> "Channel":
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._known("status") != "closed":
            self.close()

    async def __aenter__(self) -> "Channel":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._known("status") != "closed":
            await self.close.aio()
