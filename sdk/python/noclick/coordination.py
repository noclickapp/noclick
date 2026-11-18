"""Agents that coordinate agents: wake-ups, jobs and their updates, and the ``agents`` capability.

    coordinator = noclick.Agent.from_name(
        "coordinator", create_if_missing=True, tools=["search", "agents"],
        instructions="You run product launches. Hand research to helpers and keep the plan current.",
    )
    researcher = coordinator.spawn(
        "Find three recent launches in our category and what worked.",
        updates=["blocked", noclick.Every(900)], conversation="launch-plan",
    )
    coordinator.wake("launch-plan", when=researcher.job, note="The research is in: update the plan.")

A wake-up is a turn an agent will take later, in one conversation: at a time,
when an operation settles, or on a NoClick event. A spawned child's job reports to its parent when the parent asked to hear
(its ``updates``), and every update is a wake-up in the parent's conversation,
the way a React component calls the ``onChange`` its parent handed it. With the
``agents`` capability in its tools, an agent spawns, messages, asks and keeps
track of other agents itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union

from ._object import Page, _Object, field, iso_time, paginate, parse_time, ref_id
from ._sync import synced
from .cron import Cron
from .operation import Operation, OperationSummary, _with_kinds

if TYPE_CHECKING:
    from .agent import Agent

WAKEUP_STATUSES = ("pending", "delivered", "canceled", "failed")
WAKEUP_SOURCES = ("code", "wake_me", "update", "answer", "approval", "notice", "continue")
MAX_NOTE_CHARS = 4000
UPDATE_KINDS = ("done", "blocked", "before", "every", "message")
# ``Every`` asks no more often than this.
MIN_EVERY_S = 60
JOB_KINDS = {"task": "agent.task", "message": "agent.message"}
# ``Job.list`` reads tasks: a message job is an ``agent.message``, which only ``agent.jobs()`` tells apart.
_KINDS = ("agent.task",)


# --- wake-ups ------------------------------------------------------------------


def _seconds(after: Union[int, float, timedelta]) -> float:
    if isinstance(after, timedelta):
        return after.total_seconds()
    if isinstance(after, bool) or not isinstance(after, (int, float)):
        raise TypeError(f"after= is seconds or a timedelta, not {type(after).__name__}")
    return after


def every_wire(every: Any) -> Dict[str, Any]:
    """A recurring wake-up's schedule on the wire: a ``Cron``, whose ``message`` a note replaces."""
    if not isinstance(every, Cron):
        raise TypeError(f"every= is a noclick.Cron, like noclick.Cron('0 9 * * 1', tz='Europe/London'), "
                        f"not {type(every).__name__}")
    if every.message is not None:
        raise ValueError("A recurring wake-up is told its note=, so its Cron takes no message=")
    return {"cron": every.expr, "tz": every.tz}


async def wake_condition(at: Any, after: Any, when: Any, filters: Optional[Dict[str, Any]],
                         every: Any = None) -> Dict[str, Any]:
    """The wire form of what a wake-up waits for: exactly one of ``at``, ``after``, ``when`` and ``every``."""
    given = [name for name, value in (("at", at), ("after", after), ("when", when), ("every", every))
             if value is not None]
    if len(given) != 1:
        raise ValueError("A wake-up waits for exactly one of at=, after=, when= and every=" + (
            f"; got {', '.join(given)}" if given else ""))
    if filters is not None and not isinstance(when, str):
        raise ValueError("filters= narrows an event: pass it with when='<event type>'")
    if every is not None:
        return {"every": every_wire(every)}
    if at is not None:
        return {"at": iso_time(at)}
    if after is not None:
        seconds = _seconds(after)
        if seconds <= 0:
            raise ValueError(f"after= is a time ahead, not {after!r}")
        return {"after_s": seconds}
    if isinstance(when, Operation):
        return {"when": {"operation_id": await ref_id(when)}}
    if isinstance(when, (list, tuple)) and when and all(isinstance(w, Operation) for w in when):
        return {"when": {"operation_ids": [await ref_id(w) for w in when]}}
    if isinstance(when, str):
        return {"when": {"event": when, **({"filters": dict(filters)} if filters else {})}}
    raise TypeError(f"when= is an Operation (a Job, a HumanRequest, ...), a list of them or an event type, not "
                    f"{type(when).__name__}")


def check_note(note: Any) -> str:
    if not isinstance(note, str) or not note.strip():
        raise ValueError("A wake-up needs a note=: what the agent is told when it wakes")
    if len(note) > MAX_NOTE_CHARS:
        raise ValueError(f"A wake-up's note is at most {MAX_NOTE_CHARS} characters, not {len(note)}")
    return note


class Wakeup(_Object):
    """A turn an agent will take later, in one of its conversations: at a time, when an
    operation settles, on a NoClick event, or at each time of a schedule (``agent.wake``,
    or its own ``wake_me`` tool). At its moment the conversation takes a turn whose
    message is the ``note``, followed by what woke it.
    A turn already running in that conversation goes first: the wake-up waits behind
    it, one turn at a time. It survives restarts, starts its turn once, and is billed
    and capped like any turn. A recurring one (``every``) stays ``pending`` after each
    turn, due at its schedule's next time; times it missed fold into one turn. NoClick
    sets its own too: for a child's update, the link the agent asked its user to connect
    an account with being done, and a decided approval of a held call. Your webhooks
    hear each one delivered or failed (``agent.wakeup.delivered``, ``agent.wakeup.failed``),
    and each time a recurring one missed because your account couldn't pay
    (``agent.wakeup.missed``)."""

    _repr_keys = ("id", "conversation", "status")

    id: str = field("id")
    agent_id: str = field("agent_id")
    user_id: Optional[str] = field("user_id", doc="Whose conversation it wakes (``None``: the account's).")
    conversation: str = field("conversation", doc="The conversation that takes the turn.")
    note: str = field("note", doc="What the agent is told when it wakes.")
    at: Any = field("at", parse_time, doc="When it's due (a time wake-up), or when what it waited for happened.")
    when: Optional[Dict[str, Any]] = field(
        "when", doc="What it waits for besides a time: ``{operation_id}`` or ``{event, filters}`` (``None`` for a time).",
    )
    every: Optional[Cron] = field(
        "every", lambda v: Cron(v["cron"], tz=v["tz"]) if v else None,
        doc="Its schedule, for a recurring wake-up (``None`` for one that comes once); ``at`` is its next time.",
    )
    fired: int = field("fired", doc="How many turns it has started (a recurring one counts up).")
    source: str = field(
        "source",
        doc="What set it: ``code`` (``agent.wake``), ``wake_me`` (the agent's own tool), ``update`` (a job's update "
        "for this agent as its parent), ``answer`` (the link it asked its user to connect an account with is done: "
        "connected or expired), ``approval`` (a held call was decided), ``notice`` (news for the account's own "
        "assistant) or ``continue`` (a turn its step limit ended, carried on by itself: ``turn_limits``).",
    )
    status: str = field(
        "status",
        doc="``pending``, ``delivered`` (its turn started), ``canceled`` or ``failed``; a recurring one stays "
        "``pending`` until it's canceled.",
    )
    woken_by: Optional[Dict[str, Any]] = field(
        "woken_by",
        doc="What woke it: ``{at}`` for a time (once delivered), ``{operation_id, kind, status, result}`` (or ``error``) "
        "once its operation settled, ``{update}`` for a job's update, and ``{event}`` (the event as "
        "``Event.list`` reads it) for an event; ``None`` until then.",
    )
    operation_id: Optional[str] = field("operation_id", doc="The turn it started (an ``agent.message`` operation).")
    depth: int = field(
        "depth", doc="How many ``wake_me`` wake-ups in a row led to this one, with nothing else in between (0 for any other).",
    )
    error: Optional[Dict[str, Any]] = field("error", doc="Why it failed: ``{type, message}`` (the account couldn't pay, say).")
    missed: Optional[Dict[str, Any]] = field(
        "missed",
        doc="A recurring one's last missed time: ``{at, reason}``, ``reason`` being ``credits``, ``spend_cap`` (the "
        "account's monthly cap) or ``budget`` (the agent's, its key's or its user's); ``None`` if it never missed.",
    )
    created_at: Any = field("created_at", parse_time)
    delivered_at: Any = field("delivered_at", parse_time, doc="When its turn started (``None`` until then).")

    @property
    def operation(self) -> Optional[Operation]:
        """The turn it started, as an ``Operation`` (``None`` until it's delivered)."""
        op_id = self.operation_id
        return Operation.from_id(op_id, client=self._client, user=self._call_scope()) if op_id else None

    def _path(self) -> str:
        return f"/v1/agents/{self._known('agent_id')}/wakeups/{self._known('id')}"

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", self._path())

    @synced
    async def cancel(self) -> "Wakeup":
        """Call it off before it's due. A wake-up that already started its turn, or was
        canceled or failed, raises ``noclick.Conflict``.

        Returns:
            This wake-up, ``canceled``.

        Usage::

            digest = noclick.Agent.from_name("digest")
            for wakeup in digest.wakeups("weekly-report", status="pending"):
                wakeup.cancel()
        """
        self._raw = await self._request("POST", f"{self._path()}/cancel")
        return self

    @synced
    async def update(self, *, note: Optional[str] = None, at: Any = None, after: Any = None,
                     every: Any = None) -> "Wakeup":
        """Change a pending wake-up: its ``note``, and its time with one of ``at``,
        ``after`` and ``every`` (a ``Cron``; a one-off time makes a recurring one come
        once more). A delivery under way of what it said before starts no turn. One
        waiting on an operation or an event keeps that; one already delivered,
        canceled or failed raises ``noclick.Conflict``.

        Returns:
            This wake-up, as it is now.

        Usage::

            digest = noclick.Agent.from_name("digest")
            [weekly] = digest.wakeups("weekly-report", status="pending")
            weekly.update(every=noclick.Cron("0 8 * * 1", tz="Europe/London"))
        """
        given = [name for name, value in (("at", at), ("after", after), ("every", every)) if value is not None]
        if len(given) > 1:
            raise ValueError("A wake-up's new time is one of at=, after= and every=; got " + ", ".join(given))
        if note is None and not given:
            raise ValueError("Nothing to change: pass note=, or a new time with at=, after= or every=")
        body: Dict[str, Any] = {"note": check_note(note)} if note is not None else {}
        if given:
            body.update(await wake_condition(at, after, None, None, every))
        self._raw = await self._request("PATCH", self._path(), json=body)
        return self


# --- jobs and their updates --------------------------------------------------


class Before:
    """An update the parent requires before its child makes a tool call: ``Before`` with
    tool patterns written as policy writes them (``"gmail.send_email_message"``,
    ``"stripe.*"``, ``"code"``). When the child calls a matching tool, NoClick sends the
    parent an update holding the call and what the child wrote before it (its reason),
    then the call runs: the parent hears first but doesn't hold it (a call that must
    wait for a yes is a policy ``require_approval`` rule). A coding harness's own
    shell commands and file edits aren't tool calls NoClick sees, so ``Before`` can't
    match them, and its words reach NoClick only when its turn ends, so the update
    carries the call without a reason.

    Usage::

        support = noclick.Agent.from_name("support")
        refunder = support.spawn(
            "Refund order 1841 if it's within our 30 days, then email the customer.",
            tools=["stripe.create_refund", "gmail.send_email_message"],
            updates=[noclick.Before("stripe.create_refund")],
            conversation="ticket-1841",
        )
    """

    #: The tool patterns it covers.
    tools: List[str]

    def __init__(self, *tools: str) -> None:
        if not tools:
            raise ValueError("Before() takes at least one tool pattern, like 'gmail.send_email_message' or 'stripe.*'")
        bad = [t for t in tools if not isinstance(t, str) or not t]
        if bad:
            raise TypeError(f"Before() takes tool patterns as strings, not {bad[0]!r}")
        self.tools = list(tools)

    def __repr__(self) -> str:
        return f"Before({', '.join(repr(t) for t in self.tools)})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Before) and other.tools == self.tools

    def _wire(self) -> Dict[str, Any]:
        return {"before": list(self.tools)}


class Every:
    """An update the parent requires at least this often while its child works:
    ``Every`` with an interval in seconds (or a ``timedelta``), 60 seconds or more.
    When that long has passed since the child's last update, NoClick asks it for one
    (a coding harness by steering its running turn, an ``sdk`` agent before its next
    model call), and the ``tell_parent`` it answers with is the ``every`` update. A
    child that's only waiting (for a wake-up, for a person) isn't asked.

    Usage::

        planner = noclick.Agent.from_name("planner")
        migrator = planner.spawn(
            "Move every customer from the old CRM to the new one, in batches of 200.",
            tools=["hubspot", "salesforce"],
            updates=[noclick.Every(1800)],
            conversation="crm-move",
        )
    """

    #: How often, at most, the parent hears while the child works.
    interval_s: int

    def __init__(self, interval: Union[int, float, timedelta]) -> None:
        seconds = _seconds(interval)
        if seconds < MIN_EVERY_S or seconds != int(seconds):
            raise ValueError(f"Every() is a whole number of seconds, at least {MIN_EVERY_S}, not {seconds:g}")
        self.interval_s = int(seconds)

    def __repr__(self) -> str:
        return f"Every({self.interval_s})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Every) and other.interval_s == self.interval_s

    def _wire(self) -> Dict[str, Any]:
        return {"every_s": self.interval_s}


def updates_wire(updates: Optional[Sequence[Any]]) -> List[Any]:
    """``spawn(updates=)`` on the wire: ``"done"`` first (always on), then each as given."""
    if isinstance(updates, (str, Before, Every)):
        updates = [updates]
    wire: List[Any] = ["done"]
    for update in updates or ():
        if isinstance(update, (Before, Every)):
            wire.append(update._wire())
        elif update == "blocked":
            wire.append("blocked")
        elif update != "done":
            raise ValueError(
                f"An update is 'done', 'blocked', noclick.Before(...) or noclick.Every(...), not {update!r}"
            )
    return wire


@dataclass(frozen=True)
class JobUpdate:
    """One update a job sent its parent. ``kind`` is ``done`` (the job finished, any
    outcome: ``result`` or ``error``), ``blocked`` (it started waiting on a person:
    ``waiting_on``), ``before`` (it's about to make the call in ``tool`` with
    ``arguments``), ``every`` (it was due one) or ``message`` (the child's own
    ``tell_parent``). ``text`` is what the child wrote (for ``blocked``, NoClick's line
    saying what it waits on); ``status`` is the job's status then, and ``wakeup_id``
    the parent's wake-up it set (``None`` when nothing was there to wake)."""

    id: str
    job_id: str
    agent_id: str
    kind: str
    text: Optional[str]
    tool: Optional[str]
    arguments: Optional[Dict[str, Any]]
    status: Optional[str]
    result: Any
    error: Optional[Dict[str, Any]]
    #: A ``blocked`` update's wait: ``{kind, url, operation_id}``, ``kind`` being ``connection`` (a link it asked
    #: its user to connect an account with: ``url``), ``approval`` (a held call; never a ``url``, so no agent
    #: approves its child's call), ``person`` (a question it asked someone) or ``sign_in`` (a step its browser
    #: needs a person for).
    waiting_on: Optional[Dict[str, Any]]
    wakeup_id: Optional[str]
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "JobUpdate":
        return cls(
            raw["id"], raw.get("job_id"), raw.get("agent_id"), raw["kind"], raw.get("text"), raw.get("tool"),
            raw.get("arguments"), raw.get("status"), raw.get("result"), raw.get("error"), raw.get("waiting_on"),
            raw.get("wakeup_id"), parse_time(raw.get("created_at")), raw,
        )


class Job(Operation):
    """Work one agent gave another: a spawned child's task (kind ``agent.task``), or a
    message a coordinator sent with its ``agents`` tools (kind ``agent.message``), whose
    only update is ``done``. It's an ``Operation``: ``wait()`` returns the ``AgentReply``.

    A task runs while the child works on it, across as many turns as it takes, and
    finishes when its conversation goes quiet with nothing left to continue it: no turn
    running, no wake-up pending, nothing waiting on a person. While it runs, ``step`` is
    ``working`` (a turn is running) or ``waiting`` (only a wake-up is pending); it's
    ``awaiting_human`` (step ``blocked``) while it waits on a person: a held call, or a
    connection it asked its user for. It ``succeeded`` once the child stopped, its last reply the result (a child
    that needs a decision says so and stops; the parent's ``message`` to it starts a new
    job in the same conversation), ``failed`` when a turn failed, ``canceled`` when
    canceled (its running turn stops and its pending wake-ups are called off), and
    ``expired`` when the child's ``ttl_s`` ran out first."""

    started_by: Optional[str] = field(
        "started_by", doc="The agent whose job it is: a task's parent, whether your code spawned it or the parent did.",
    )
    conversation: Optional[str] = field("conversation", doc="The conversation the worker does it in.")
    parent_conversation: Optional[str] = field(
        "parent_conversation", doc="The parent's conversation its updates wake (``None``: they wake nobody).",
    )
    required_updates: List[Any] = field(
        "updates", list, doc="The updates its parent required, as on the wire: ``done``, ``blocked``, ``{before}``, ``{every_s}``.",
    )

    @classmethod
    def _typed(cls, ops: List[Operation]) -> List["Job"]:
        return [cls._new(raw=op._raw, client=op._client, user=op._scope) for op in ops]

    @synced
    @classmethod
    async def list(cls, *, limit: Optional[int] = None, **filters: Any) -> List["Job"]:
        """Spawned children's tasks across your agents (kind ``agent.task``), newest first.
        Takes ``Operation.list``'s filters except ``kind`` (``agent=`` keeps the ones one
        agent does). ``agent.jobs()`` reads the ones one agent started, its message jobs
        (kind ``agent.message``) too.

        Returns:
            Every matching job (or the first ``limit``), each with its ``status``, ``step`` and ``latest_update``.

        Usage::

            for job in noclick.Job.list(status="awaiting_human", user_filter=noclick.ALL_USERS):
                print(job.agent_id, job.started_by, job.latest_update)
        """
        return cls._typed(await Operation.list.aio(limit=limit, **_with_kinds(filters, _KINDS, "Job.list")))

    @synced
    @classmethod
    async def list_page(cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, **filters: Any) -> Page:
        """One page of jobs; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the jobs and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Job.list_page(status="failed", limit=50)
            for job in page.data:
                print(job.agent_id, job.error)
        """
        page = await Operation.list_page.aio(cursor=cursor, limit=limit, **_with_kinds(filters, _KINDS, "Job.list_page"))
        return Page(cls._typed(page.data), page.next_cursor)

    @synced
    @classmethod
    async def summary(cls, **filters: Any) -> OperationSummary:
        """How many jobs match, by status; takes ``Operation.summary``'s filters except ``kind``.

        Returns:
            The number that match in ``total``, and per operation status in ``by_status``.

        Usage::

            counts = noclick.Job.summary(status="live")
            print(counts.total, counts.by_status["awaiting_human"])
        """
        return await Operation.summary.aio(**_with_kinds(filters, _KINDS, "Job.summary"))

    @property
    def latest_update(self) -> Optional[JobUpdate]:
        """Its newest update (``None`` before the first)."""
        raw = self._sync_raw().get("latest_update")
        return JobUpdate._from(raw) if raw else None

    @property
    def agent(self) -> "Agent":
        """The agent doing the work, lazy."""
        from .agent import Agent  # agent imports this module

        return Agent.from_id(self.agent_id, client=self._client, user=self._call_scope())

    @synced
    async def updates(self) -> List[JobUpdate]:
        """Every update it has sent its parent, oldest first.

        Returns:
            Each ``JobUpdate`` with its ``kind``, the child's ``text`` and, by kind, the call it was about to
            make, what it waits on, or the result.

        Usage::

            planner = noclick.Agent.from_name("planner")
            for job in planner.jobs(kind="task"):
                for update in job.updates():
                    print(update.created_at, update.kind, update.text)
        """
        rows = await paginate(self._api, f"/v1/operations/{self._id()}/updates", user=self._call_scope())
        return [JobUpdate._from(row) for row in rows]


def job_kinds(kind: Union[None, str, Sequence[str]]) -> Optional[str]:
    """``jobs(kind=)`` on the wire: ``task`` and ``message`` as their operation kinds."""
    if kind is None:
        return None
    kinds = [kind] if isinstance(kind, str) else list(kind)
    unknown = [k for k in kinds if k not in JOB_KINDS]
    if unknown:
        raise ValueError(f"A job's kind is 'task' or 'message', not {unknown[0]!r}")
    return ",".join(JOB_KINDS[k] for k in kinds)


# --- the agents capability ---------------------------------------------------


class Agents:
    """The ``agents`` capability, for an agent's ``tools``: the same as the string
    ``"agents"``, narrowed with ``Agents.only(...)``. It gives a coordinator six tools,
    within its own scope, in its own conversations (in a channel, agents work by
    mentions instead): ``spawn`` (a child of its own, whose updates wake it in the
    conversation it spawned from), ``message`` (any agent it can reach: a user's agent
    reaches that user's and the account's, an account agent the account's; it waits up
    to 50 seconds for the reply, and a reply that takes longer, or one it doesn't wait
    for, is a job whose ``done`` update wakes it), ``ask`` (as ``agent.ask``),
    ``status`` (an agent's or a job's), ``list`` (as ``Agent.list`` filters) and
    ``cancel`` (a job it started). Its work runs in the threads of the user it's acting
    for, and its children get the capability only when it lists it for them. Policy
    names them ``agents.spawn`` ... ``agents.cancel`` (``agents.*``); the model sees
    ``agents__spawn``, ``agents__message`` and so on, and its tools count toward an
    agent's 64.

    Usage::

        coordinator = noclick.Agent.from_name(
            "coordinator", create_if_missing=True,
            instructions="You run our launches. Spawn a researcher for each competitor, then write the plan.",
            tools=["search", noclick.Agents()],
        )
    """

    TOOLS = ("spawn", "message", "ask", "status", "list", "cancel")
    #: The capability's tools this gives.
    tools: List[str]

    def __init__(self) -> None:
        self.tools = list(self.TOOLS)

    @classmethod
    def only(cls, *tools: str) -> "Agents":
        """Some of the capability's tools: ``spawn``, ``message``, ``ask``, ``status``,
        ``list`` and ``cancel``.

        Returns:
            The capability narrowed to those tools, for ``tools=`` (on the wire, ``"agents.spawn"``, ...).

        Usage:
            A supervisor that watches and asks but never starts work::

                supervisor = noclick.Agent.from_name(
                    "supervisor", create_if_missing=True,
                    instructions="You check on our agents every morning and report anything stuck.",
                    tools=[noclick.Agents.only("list", "status", "ask")],
                )
        """
        if not tools:
            raise ValueError(f"only() takes at least one of {', '.join(repr(t) for t in cls.TOOLS)}")
        unknown = [t for t in tools if t not in cls.TOOLS]
        if unknown:
            raise ValueError(f"The agents capability's tools are {', '.join(repr(t) for t in cls.TOOLS)}, not {unknown[0]!r}")
        narrowed = cls()
        narrowed.tools = [t for t in cls.TOOLS if t in tools]
        return narrowed

    def __repr__(self) -> str:
        return "Agents()" if self.tools == list(self.TOOLS) else f"Agents.only({', '.join(repr(t) for t in self.tools)})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Agents) and other.tools == self.tools

    async def _tool_refs(self, scope: Any) -> List[str]:
        if self.tools == list(self.TOOLS):
            return ["agents"]
        return [f"agents.{tool}" for tool in self.tools]


class Platform:
    """NoClick itself, for an agent's ``tools``: the same as the string ``"noclick"``,
    narrowed with ``Platform.only(...)``. It gives the agent what a connected app
    gets on NoClick's MCP server: ``search`` and ``fetch`` (NoClick's guides and your
    account's objects), ``api_describe`` and ``api_call`` (any API operation), and
    ``quote``, ``buy`` and ``delete``. They act as the turn's key and the user it acts
    for, never more than that key may, judged by the same gate as any connected app:
    a purchase or a deletion waits for the account's owner, who approves it on NoClick
    with its exact price or what goes with it (the turn waits on them, and the call's
    outcome is the conversation's next turn); a secret's value never comes from the
    conversation; and a turn answering someone outside the agent's scope (an email, a
    caller) asks a person before acting outside the account. A long action it starts
    is an operation, which ``wake_me`` waits on. Policy names them ``noclick.search``
    ... ``noclick.delete``; the model sees ``noclick__search`` and so on, and they
    count toward an agent's 64 tools. Watchers see an ``approval`` and an
    ``operation`` event for them (``agent.stream``, ``agent.watch``).

    Usage::

        ops = noclick.Agent.from_name(
            "ops", create_if_missing=True, tools=[noclick.Platform()],
            instructions="You run our NoClick account: numbers, domains and agents.",
        )
        ops.message("Get us a phone number in the 415 area code.")  # buys once you approve
    """

    #: The capability groups ``only`` narrows to, as a connected app's grant names them.
    GROUPS = ("read", "build", "deploy", "spend", "delete")
    #: What it's narrowed to: capability groups and API areas (empty: all of NoClick).
    names: List[str]

    def __init__(self) -> None:
        self.names = []

    @classmethod
    def only(cls, *names: str) -> "Platform":
        """Part of NoClick: capability groups (``read``, ``build``, ``deploy``, ``spend``,
        ``delete``) bound what kind of call it makes, and API areas (a key's scopes, like
        ``domains``, ``phone`` or ``agents``) which part of the API it reaches; each
        narrows only its own kind. Without ``spend`` it isn't offered ``quote`` and
        ``buy``, without ``delete`` not ``delete``. Names are checked when the agent is saved.

        Returns:
            NoClick narrowed to those names, for ``tools=`` (on the wire, ``"noclick.read"``, ...).

        Usage:
            An agent that keeps your domains, and buys new ones once you approve::

                registrar = noclick.Agent.from_name(
                    "registrar", create_if_missing=True,
                    instructions="You look after our domains and their DNS.",
                    tools=[noclick.Platform.only("domains")],
                )

            One that only reads, to answer questions about the account::

                analyst = noclick.Agent.from_name(
                    "analyst", create_if_missing=True, instructions="You explain our usage and spend.",
                    tools=[noclick.Platform.only("read")],
                )
        """
        if not names or not all(isinstance(n, str) and n for n in names):
            raise ValueError(f"only() takes capability groups ({', '.join(cls.GROUPS)}) or API areas, like 'domains'")
        narrowed = cls()
        narrowed.names = list(dict.fromkeys(names))
        return narrowed

    def __repr__(self) -> str:
        return f"Platform.only({', '.join(repr(n) for n in self.names)})" if self.names else "Platform()"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Platform) and other.names == self.names

    async def _tool_refs(self, scope: Any) -> List[str]:
        return [f"noclick.{name}" for name in self.names] or ["noclick"]
