"""Triggers: what wakes an agent besides a message.

    fulfilment = noclick.Agent.from_name(
        "fulfilment", create_if_missing=True, instructions="You confirm new orders with the customer.",
        triggers=[noclick.OnWebhook(name="orders", message="A new order arrived.")],
    )

An ``OnWebhook`` gives it a URL whose POST body is the turn, an ``OnEvent``
subscribes it to a connection's app events, an ``OnPlatformEvent`` to
NoClick's own events (an operation failing, a connection breaking), and a
``Cron`` wakes it on a schedule (an agent with one is an automation), and an
``OnQueue`` makes each message on a queue a turn. Mail and calls wake it too, set
up where they live (``Inbox(agent=)``, ``PhoneNumber.answer_with``);
``triggers()`` lists them as kinds ``email`` and ``call``, and while its policy
may hold one of its tools for a person, as kind ``approval``: an answered
approval wakes it in the held call's conversation.

A webhook, app event or queue trigger takes ``conversation=``, a template over
what arrived (``"issue-{issue.number}"``): deliveries that render the same key
continue one conversation, and the turn's operation records the key as
``input["conversation"]``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from ._object import compact, parse_time
from .connection import Connection
from .cron import Cron
from .queues import Queue

# The kinds your code defines; ``email`` and ``call`` come from an inbox or a number.
DEFINED_KINDS = ("cron", "webhook", "event", "platform", "queue")


@dataclass(frozen=True)
class OnWebhook:
    """A URL that wakes the agent: each POST to it is a turn, its body the
    message (a JSON body is passed as JSON). The URL is ``AgentTrigger.url``;
    anyone who has it can wake the agent, so keep it like a key. It stays the
    same while a trigger of that ``name`` stays on the agent. ``message`` is
    what the agent is told with every delivery, above the body.

    Usage:
        Let your order system wake an agent::

            fulfilment = noclick.Agent.from_name(
                "fulfilment", create_if_missing=True, instructions="You confirm new orders with the customer.",
                triggers=[noclick.OnWebhook(name="orders", message="A new order arrived. Confirm it with the customer.")],
            )
            [orders] = fulfilment.triggers()
            print(orders.url)   # POST your order JSON here

        Keep each order in one conversation, keyed by a field of the body::

            fulfilment = noclick.Agent.from_name("fulfilment")
            fulfilment.add_trigger(noclick.OnWebhook(name="order-updates", conversation="order-{order.id}"))
    """

    name: str
    # Standing instructions sent with each delivery, above its body. A channel can subscribe to one too
    # (``channel.subscribe(noclick.OnWebhook(...))``), its POSTs posted in the room.
    message: Optional[str] = None
    # The conversation a delivery continues: a template over its body, ``"order-{order.id}"``; a
    # ``NoClick-Conversation`` header wins.
    conversation: Optional[str] = None

    def _wire(self) -> Dict[str, Any]:
        return {"kind": "webhook", "name": self.name, **compact(message=self.message, conversation=self.conversation)}


class OnEvent:
    """An app event from one of the agent's connections, such as a Slack
    message or a new HubSpot contact. ``connection`` is a ``Connection`` or its
    name, the agent's own user's (an account agent's may be one connected in the
    app, ``credential:<id>``); ``event`` names one of the integration's
    app events (``channel_message`` for Slack, ``contact_created`` for HubSpot; list them with
    ``connection.events()``) and each keyword argument narrows it the way the integration
    takes it, like ``channel="C0123ABCD"`` (a Slack channel's id: ``slack.lookup("channel")``
    lists them). ``message`` is what the agent is told with every event, above it. A thread
    (a Slack thread) stays one conversation, so the agent's replies land in it. ``conversation``
    keys conversations yourself, a template over the event as the app sent it:
    ``"issue-{issue.number}"`` keeps everything about one issue in one. A channel subscribes
    to the same events (``channel.subscribe(noclick.OnEvent(...))``), each posted in the room.
    The connection needn't be connected yet: the trigger is ``error`` until it is.

    Usage:
        Answer every message in a Slack channel::

            slack = noclick.Connection.from_name("slack", integration="slack", create_if_missing=True)
            support = noclick.Agent.from_name(
                "support", create_if_missing=True, instructions="You answer questions in #support.",
                tools=[slack],
                triggers=[noclick.OnEvent(slack, "channel_message", channel="C0123ABCD")],
            )

        Or wake a sales agent for each new contact::

            sales = noclick.Agent.from_name("sales")
            sales.add_trigger(noclick.OnEvent("hubspot", "contact_created", message="Research this contact and draft a first email."))

        Pick up GitHub issues when they're labelled, one conversation per issue::

            github = noclick.Connection.from_name("github", integration="github", create_if_missing=True)
            triage = noclick.Agent.from_name("triage")
            triage.add_trigger(noclick.OnEvent(github, "issue_labeled", repository="acme/api", conversation="issue-{issue.number}"))
    """

    connection: Any
    event: str
    filters: Dict[str, Any]
    message: Optional[str]
    conversation: Optional[str]

    def __init__(
        self, connection: Any, event: str, *, message: Optional[str] = None, conversation: Optional[str] = None,
        **filters: Any,
    ) -> None:
        if not isinstance(connection, (str, Connection)):
            raise TypeError(f"OnEvent takes a Connection or its name, not {type(connection).__name__}")
        self.connection = connection
        self.event = event
        self.filters = dict(filters)
        self.message = message
        self.conversation = conversation

    def __repr__(self) -> str:
        name = self.connection if isinstance(self.connection, str) else self.connection._known("name")
        extra = "".join(f", {k}={v!r}" for k, v in self.filters.items())
        return f"OnEvent({name!r}, {self.event!r}{extra})"

    async def _wire_async(self) -> Dict[str, Any]:
        connection = self.connection
        if isinstance(connection, Connection):
            raw = await connection._ensure()  # a lazy create_if_missing one is created first
            connection = raw["id"] if raw.get("origin") == "app" else raw["name"]  # credential:<id> for the app's
        body: Dict[str, Any] = {"kind": "event", "connection": connection, "event": self.event, "filters": self.filters}
        return {**body, **compact(message=self.message, conversation=self.conversation)}


@dataclass(frozen=True)
class OnPlatformEvent:
    """One of NoClick's own events (the types ``noclick.Event.types()`` lists, as your
    webhooks receive them): an operation failing, a connection breaking, a channel
    halting, a workflow's run failing, an agent built in the app asking for you, a
    payment going through. ``type`` names one, and ``*`` matches the rest of a name
    (``"operation.*"``); ``filters`` are dotted paths into the event's ``data`` and the
    values they must have. ``message`` is what the agent is told with every event,
    above it; ``conversation`` keys conversations by a template over the event
    (``"connection-{data.id}"``), else each event is a conversation of its own.

    The agent hears its user's events, and an agent of your account's hears every
    event, your users' included. It never hears what its own turns caused (its
    turn finishing), and a chain of agents waking each other this way stops five
    turns deep. A channel subscribes to the same events
    (``channel.subscribe(noclick.OnPlatformEvent(...))``).

    Usage:
        Have an agent look into every failed job of your coding agents::

            triage = noclick.Agent.from_name(
                "triage", create_if_missing=True, instructions="You find out why work failed and say what to do.",
                triggers=[noclick.OnPlatformEvent("operation.failed", filters={"kind": "agent.task"},
                                                  message="A job failed. Find out why.")],
            )

        One conversation per broken connection::

            support = noclick.Agent.from_name("support")
            support.add_trigger(noclick.OnPlatformEvent("connection.disconnected", conversation="connection-{data.id}",
                                                        message="Tell the user how to reconnect it."))

        Watch over the workflows built in the app, one conversation per workflow::

            ops = noclick.Agent.from_name("ops")
            ops.add_trigger(noclick.OnPlatformEvent("workflow.run.failed", conversation="workflow-{data.workflow_id}",
                                                    message="A workflow failed. Find out why; pause it if it's useless."))
    """

    type: str
    filters: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    conversation: Optional[str] = None

    def _wire(self) -> Dict[str, Any]:
        return {"kind": "platform", "type": self.type,
                **compact(filters=dict(self.filters) if self.filters else None, message=self.message,
                          conversation=self.conversation)}


class OnQueue:
    """Each message on a queue becomes a turn: the agent reads ``message`` (its
    standing instructions, if any) and then the message's JSON body. With
    ``batch_size`` above 1 (up to 25), one turn takes up to that many waiting
    messages at once, as a JSON list, for work that's cheaper in bulk.
    ``queue`` is a ``Queue`` or its name, the agent's own user's.

    Delivery follows the queue's rules: a turn that finishes acks its messages;
    a turn that fails hands them back for another try (after 30 seconds per
    attempt they've had), and a message that fails the queue's ``max_attempts``
    times becomes a dead letter, the turn's error its ``last_error``. Each turn is
    a conversation of its own, unless ``conversation`` keys it from the message
    (one message a turn only). The agent takes one turn at a time, in order; for
    more throughput raise ``batch_size``, or put several agents on the queue.
    While the agent is paused, messages wait.

    When the agent's budget, its user's cap or your account's funds run out, the
    trigger pauses instead of failing turns: messages wait with their attempts
    unchanged, the trigger's ``status`` is ``error`` saying why, and it carries on
    by itself once there's money to spend again (it looks every half minute).

    Usage:
        Let an agent work through a queue your app fills::

            invoices = noclick.Queue.from_name("invoices", create_if_missing=True)
            support = noclick.Agent.from_name(
                "support-bot", create_if_missing=True, instructions="You chase unpaid invoices by email.",
                tools=["gmail.send_email", "stripe.list_invoices"],
                triggers=[noclick.OnQueue(invoices, message="Chase this unpaid invoice.")],
            )
            invoices.put({"invoice": "INV-1042", "customer": "acme"})

        Ten messages a turn, by the queue's name::

            digest = noclick.Agent.from_name("digest")
            digest.add_trigger(noclick.OnQueue("webhook-buffer", batch_size=10, message="Summarize these events."))

        Each customer's messages in their own conversation::

            enrich = noclick.Agent.from_name("enrich")
            enrich.add_trigger(noclick.OnQueue("signups", conversation="customer-{customer_id}"))
    """

    queue: Any
    message: Optional[str]
    batch_size: int
    conversation: Optional[str]

    def __init__(
        self, queue: Any, *, message: Optional[str] = None, batch_size: int = 1, conversation: Optional[str] = None,
    ) -> None:
        if not isinstance(queue, (str, Queue)):
            raise TypeError(f"OnQueue takes a Queue or its name, not {type(queue).__name__}")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError(f"batch_size is a whole number of messages, 1 or more, not {batch_size!r}")
        if conversation is not None and batch_size != 1:
            raise ValueError("conversation= keys a turn by its one message; a batch holds several")
        self.queue = queue
        self.message = message
        self.batch_size = batch_size
        self.conversation = conversation

    def __repr__(self) -> str:
        name = self.queue if isinstance(self.queue, str) else self.queue._known("name")
        extra = f", batch_size={self.batch_size!r}" if self.batch_size != 1 else ""
        return f"OnQueue({name!r}{extra})"

    async def _wire_async(self) -> Dict[str, Any]:
        queue = self.queue
        if isinstance(queue, Queue):
            queue = (await queue._ensure())["name"]  # a lazy create_if_missing one is created first
        return {"kind": "queue", "queue": queue, "batch_size": self.batch_size,
                **compact(message=self.message, conversation=self.conversation)}


@dataclass(frozen=True)
class AgentTrigger:
    """One thing that wakes an agent, as ``agent.triggers()`` reads it.

    ``kind`` is ``cron``, ``webhook``, ``event``, ``platform``, ``queue``, ``email``, ``call``,
    ``approval``, ``app``, ``channel`` or ``routine``; ``spec`` is its definition (``name``
    for a webhook; ``connection``, ``event`` and ``filters`` for an app event; ``type`` and
    ``filters`` for a NoClick event; ``message`` and
    ``conversation`` where they were given; ``inbox_id`` and ``address`` for email;
    ``phone_number_id`` and ``number`` for calls; ``cron``, ``tz`` and ``message`` for a
    schedule; ``queue`` and ``batch_size`` for a queue; ``tools``, the ones
    policy may hold, for an approval; ``step``, ``name``, ``type`` and ``operation`` for a trigger
    wired into the agent in the app, as a step of its workflow, and changed only there;
    ``channel_id``, ``name`` and ``mode`` for a channel it sits in; ``cron``, ``tz``, ``note`` and
    ``conversation`` for a recurring wake-up, changed through ``agent.wakeups``). An ``approval``
    trigger is there while your policy may hold one of its tools for a person: an answered
    approval wakes it in the held call's conversation. ``state`` is ``live``, ``paused`` (the
    agent, or the trigger itself: ``paused`` says which) or ``stopped`` (it can't fire), ``reason``
    says why in words and ``fix`` what makes it live again (``{"action": ...}``: ``resume_agent``,
    ``resume``, ``connect`` or ``replace`` with its ``connection``, or ``open_in_app``). ``status``
    is the older reading of it: ``active``, ``paused`` or ``error``, with ``error`` saying why it
    can't fire (a connection that isn't connected, say, a queue's turns waiting for money, or its
    turns failing the same way five times in a row, which stops it until it or the agent is
    resumed). ``set_by`` says who set it up (``{"kind": "person" | "agent" | "automation",
    "agent_id": ...}``), ``read_only`` whether it's changed only where it lives, and ``actions``
    what it takes here (``pause``, ``resume``, ``test``, ``update``, ``remove``)."""

    id: str
    kind: str
    spec: Dict[str, Any]
    status: str
    # The URL a webhook trigger listens at (None for other kinds).
    url: Optional[str]
    # When a schedule next wakes the agent (None for other kinds, and while paused or in error).
    next_run: Any
    last_fired_at: Any
    error: Optional[str]
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)
    # Paused on its own (``agent.pause_trigger``), its agent running on.
    paused: bool = False
    # A turn it started is queued or running (for a channel, the agent's turn there).
    running: bool = False
    state: str = "live"
    reason: Optional[str] = None
    fix: Optional[Dict[str, Any]] = None
    # When a schedule or a recurring wake-up comes round next, paused or not (None for other kinds).
    next_run_at: Any = None
    set_by: Dict[str, Any] = dc_field(default_factory=lambda: {"kind": "person", "agent_id": None})
    read_only: bool = False
    actions: List[str] = dc_field(default_factory=list)
    # An app event's in a few words ("Messages to +1 202-555-0101"); None for other kinds.
    title: Optional[str] = None
    # What an app event hears through: ``app``, ``integration``, ``icon`` (the node type its mark is drawn by),
    # ``credential_type``, ``account`` (as Connections names it), ``number`` (E.164, a phone's), ``hears``,
    # ``groups``, ``status`` (``connected``, ``pending``, ``disconnected`` or ``missing``), and ``problem`` and
    # ``remedy`` while it isn't linked. None for other kinds.
    summary: Optional[Dict[str, Any]] = None

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "AgentTrigger":
        return cls(
            raw["id"], raw["kind"], dict(raw.get("spec") or {}), raw.get("status") or "active", raw.get("url"),
            parse_time(raw.get("next_run")), parse_time(raw.get("last_fired_at")), raw.get("error"),
            parse_time(raw.get("created_at")), raw, paused=raw.get("paused") is True, running=raw.get("running") is True,
            state=raw.get("state") or "live", reason=raw.get("reason"), fix=raw.get("fix"),
            next_run_at=parse_time(raw.get("next_run_at")),
            set_by=dict(raw.get("set_by") or {"kind": "person", "agent_id": None}),
            read_only=raw.get("read_only") is True, actions=list(raw.get("actions") or []),
            title=raw.get("title"), summary=raw.get("summary"),
        )

    @property
    def defined(self) -> bool:
        """Whether your code defines it (``cron``, ``webhook``, ``event``, ``platform``, ``queue``); ``email`` and ``call`` come
        from an inbox or a phone number and are changed there, ``approval`` from your policy, ``app`` from the
        agent's workflow in the app, ``channel`` from the channels it sits in and ``routine`` from its wake-ups."""
        return self.kind in DEFINED_KINDS


async def trigger_wire(trigger: Any) -> Dict[str, Any]:
    """A trigger definition as the API takes it."""
    if isinstance(trigger, Cron):
        return {"kind": "cron", **trigger._wire()}
    if isinstance(trigger, (OnWebhook, OnPlatformEvent)):
        return trigger._wire()
    if isinstance(trigger, (OnEvent, OnQueue)):
        return await trigger._wire_async()
    raise TypeError(
        f"A trigger is a noclick.Cron, OnWebhook, OnEvent, OnPlatformEvent or OnQueue, not {type(trigger).__name__}")


def spec_key(spec: Dict[str, Any]) -> str:
    """One definition's identity, to tell which of an agent's triggers match your code."""
    return json.dumps({k: v for k, v in spec.items() if v not in (None, {})}, sort_keys=True, default=str)


def named_by(spec: Dict[str, Any]) -> str:
    """Which of an agent's triggers a definition names: a webhook by its name, unique on an agent; any other by
    its whole definition (``spec_key``)."""
    return spec_key({"kind": "webhook", "name": spec.get("name")} if spec.get("kind") == "webhook" else spec)
