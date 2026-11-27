"""Operations: work that outlives a request (a human's answer, a connect
link, an agent turn). ``op.wait()`` returns the typed outcome for its kind."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field as dc_field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Sequence, Union

from ._client import Client, resolve_client
from ._object import (
    Page, _Object, csv, field, iso_time, list_all, list_page, paginate, parse_time, read_scope, ref_id, required_number,
)
from ._sync import synced
from ._scope import AMBIENT
from .tool_call import ToolCall
from .exceptions import (
    Error,
    OperationCanceled,
    OperationExpired,
    OperationFailed,
    OperationTimeout,
    error_from_payload,
)

STATUSES = (
    "queued", "running", "awaiting_human",
    "succeeded", "failed", "canceled", "expired",
)
TERMINAL = frozenset({"succeeded", "failed", "canceled", "expired"})

# Long-poll window per request; the server caps ``timeout_s`` near this.
_LONG_POLL_S = 50

ResultReader = Callable[[Any, "Operation"], Any]
_READERS: Dict[str, ResultReader] = {}


def register_result(kind: str, reader: ResultReader) -> None:
    """Decode a succeeded operation of ``kind`` into its typed outcome."""
    _READERS[kind] = reader


@dataclass(frozen=True)
class OperationEvent:
    """A status or step change observed by ``Operation.events()``: ``step`` is where a running
    operation is (``delivering`` or ``working`` for a CLI agent's turn, ``submitted`` or ``scheduled``
    for a port; ``None`` otherwise)."""

    status: str
    step: Optional[str]
    updated_at: Any
    result: Any
    error: Optional[Error]
    raw: Dict[str, Any]


@dataclass(frozen=True)
class OperationTransition:
    """One status change the server recorded (``by`` names who canceled)."""

    status: str
    at: Any
    by: Optional[str]


@dataclass(frozen=True)
class OperationSummary:
    """How many operations match, by status."""

    total: int
    by_status: Dict[str, int]
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class OperationFailure:
    """One cause of failures (``Operation.failures()``): ``count`` failed operations between ``first_at`` and
    ``last_at`` that failed the same way, on the same thing (one cap used up, one connection disconnected).
    ``failed_on`` is what their fix acts on (``Operation.failed_on``). ``error`` is the latest one's,
    ``operation_id`` that operation; ``cause`` is the key their views carry and ``Operation.list(cause=)`` takes. Up
    to ten of the agents, users and keys they touched, beside how many."""

    cause: str
    count: int
    first_at: Any
    last_at: Any
    failed_on: Optional[Dict[str, Any]]
    error: Optional[Error]
    operation_id: str
    kinds: List[str]
    agent_ids: List[str]
    agent_count: int
    user_ids: List[Optional[str]]
    user_count: int
    key_ids: List[str]
    key_count: int
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class OperationFailures:
    """``Operation.failures()``: each cause, the one that failed most lately first; ``total`` counts every failure
    matched, and ``has_more`` says causes past the limit were left out."""

    causes: List[OperationFailure]
    total: int
    has_more: bool
    raw: Dict[str, Any] = dc_field(repr=False)


Many = Union[None, str, Sequence[str]]


async def _filter_params(
    kind: Many, status: Many, status_not: Many, agent: Any, key: Optional[str],
    created_after: Any, created_before: Any, updated_after: Any, cause: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "kind": csv(kind), "status": csv(status), "status_not": csv(status_not),
        "agent_id": await ref_id(agent), "key_id": key,
        "created_after": iso_time(created_after), "created_before": iso_time(created_before),
        "updated_after": iso_time(updated_after), "cause": cause,
    }


def _failure(raw: Dict[str, Any]) -> OperationFailure:
    error = raw.get("error")
    return OperationFailure(
        cause=str(raw["cause"]), count=int(raw["count"]), first_at=parse_time(raw.get("first_at")),
        last_at=parse_time(raw.get("last_at")), failed_on=raw.get("failed_on"),
        error=error_from_payload(error, default=OperationFailed) if error else None,
        operation_id=str(raw["operation_id"]), kinds=list(raw.get("kinds") or []),
        agent_ids=list(raw.get("agent_ids") or []), agent_count=int(raw.get("agent_count") or 0),
        user_ids=list(raw.get("user_ids") or []), user_count=int(raw.get("user_count") or 0),
        key_ids=list(raw.get("key_ids") or []), key_count=int(raw.get("key_count") or 0), raw=raw,
    )


def _with_kinds(filters: Dict[str, Any], kinds: Sequence[str], method: str) -> Dict[str, Any]:
    """Pin ``filters`` to ``kinds``; a caller-supplied kind is refused, never silently replaced."""
    if filters.get("kind") is not None:
        raise TypeError(
            f"{method} reads only {', '.join(kinds)} operations; "
            f"filter other kinds with Operation.{method.split('.')[1]}."
        )
    return {**filters, "kind": list(kinds)}


def _error_of(raw: Dict[str, Any], op: Optional["Operation"] = None) -> Optional[Error]:
    payload = raw.get("error")
    if not payload:
        return None
    status = raw.get("status")
    default = {"canceled": OperationCanceled, "expired": OperationExpired}.get(status, OperationFailed)
    err = error_from_payload(payload, default=default)
    err.details.setdefault("operation_id", raw.get("id"))
    if op is not None:
        err._origin = (op._client, op._scope)
    return err


class Operation(_Object):
    """A long-running piece of work. Block on it with ``wait()``."""

    _repr_keys = ("id", "kind", "status")
    # Set on operations a method returned: that method knows the outcome's type,
    # whatever the server names the kind.
    _reader: Optional[ResultReader] = None
    # How long one read in wait() lets the server hold it; it answers sooner once the operation finishes.
    _wait_window_s: int = _LONG_POLL_S

    id: str = field("id")
    kind: str = field("kind")
    status: str = field("status")
    step: Optional[str] = field(
        "step",
        doc="Where a running operation is. A turn of an agent on a CLI harness: ``delivering`` (starting its sandbox "
        "and handing it the message) or ``working`` (the harness is on it). A number's port (``phone.port_in``, "
        "invite-only beta): ``submitted`` (with the current carrier) or ``scheduled`` (it moves at "
        "``port_at``). ``None`` otherwise.",
    )
    result: Optional[Dict[str, Any]] = field("result", doc="The raw result once succeeded.")
    created_at: Any = field("created_at", parse_time)
    updated_at: Any = field("updated_at", parse_time)
    summary_text: Optional[str] = field(
        "summary", doc="A short line saying what it is (a message preview, an addressee, a command).",
    )
    user_id: Optional[str] = field("user_id")
    key_id: Optional[str] = field("key_id", doc="The key that started it.")
    agent_id: Optional[str] = field("agent_id")
    input: Optional[Dict[str, Any]] = field(
        "input", doc="What it was started with (single-operation views, account principals).",
    )
    workstream: Optional[Dict[str, str]] = field(
        "workstream",
        doc="The workstream its work belongs to, as it reads now (``{\"id\", \"name\"}``: a renamed one by its new "
        "name, a merged one as the one it joined); ``None`` when its work named none. A single operation's view and "
        "``Operation.list()`` name it.",
    )
    cause: Optional[str] = field(
        "cause",
        doc="Why a failed one failed, as one key: its error's type and reason and what its fix acts on (the cap "
        "that stopped it, the connection it couldn't use). Operations that failed the same way share it; "
        "``Operation.failures()`` groups by it and ``Operation.list(cause=)`` takes it. On the list and a read of "
        "one; ``None`` unless it failed.",
    )
    failed_on: Optional[Dict[str, Any]] = field(
        "failed_on",
        doc="What a failed one's fix acts on, by id: the cap that stopped it (``{\"object\": \"cap\", \"scope\": "
        "\"user\", \"id\": \"acme\"}``, its scope ``key``, ``user``, ``agent``, ``project`` or ``account``), a "
        "``connection``, the ``account``'s funds or plan, a paused ``user``, an ``app``, a ``workflow`` or an "
        "``agent``; ``None`` when it's NoClick's own to fix, or it didn't fail. On the list and a read of one.",
    )
    started_at: Any = field("started_at", parse_time)
    finished_at: Any = field("finished_at", parse_time)
    wait_ms: Optional[int] = field("wait_ms", doc="Time queued before it ran.")
    run_ms: Optional[int] = field("run_ms", doc="Time running.")
    held_ms: Optional[int] = field("held_ms", doc="Time waiting on a person.")
    progress: Optional[Dict[str, Any]] = field(
        "progress",
        doc="What the work reported as it went, or ``None`` before it reported anything: its ``step``, its "
        "``stages`` (each ``{name, status, started_at, ended_at}``, ``status`` being ``done``, ``current`` or "
        "``pending``; a deploy's are Queued, Building, Shipping and Live), the last 50 ``lines`` it printed (a "
        "build's log, a call's turns, an agent's tool calls), ``line_count`` (every line so far) and "
        "``updated_at``. An agent that started it hears each report as an ``operation`` event.",
    )

    undoable: Optional[bool] = field(
        "undoable",
        doc="Whether ``undo()`` can take it back now: a reversible write (a deletion that went to the trash, a "
        "dict's clear, a database migration) not undone yet. ``None`` for kinds that record no undo.",
    )
    undone_at: Any = field("undone_at", parse_time, doc="When it was undone, if it was.")
    undo_rewinds: Optional[str] = field(
        "undo_rewinds",
        doc="On a promote that bound databases, while it can be undone: what undoing it takes back from them (each "
        "goes back to the moment before the promote; what was written since is kept in the trash as a database "
        "copy). ``None`` otherwise.",
    )
    kept_copy_id: Optional[str] = field(
        "kept_copy_id",
        doc="On a database's restore: the copy it keeps of what the database held just before, in the trash (a "
        "``TrashItem`` of kind ``database_copy`` whose ``resource_id`` this is) once it's done. ``undo()`` puts it "
        "back. ``None`` on other kinds.",
    )

    @property
    def transitions(self) -> List[OperationTransition]:
        """Every status change, oldest first (empty for operations recorded before they were kept)."""
        return [
            OperationTransition(e.get("status"), parse_time(e.get("at")), e.get("by"))
            for e in self._sync_raw().get("events") or []
        ]

    @property
    def console_url(self) -> Optional[str]:
        """This operation in the developer console (None off the hosted API)."""
        return self._api.console_url("operations", self._id())

    def _repr_parts(self) -> list:
        url = self.console_url
        return super()._repr_parts() + ([f"console_url={url!r}"] if url else [])

    @property
    def error(self) -> Optional[Error]:
        """The failure as an ``noclick.Error`` (None unless it failed)."""
        return _error_of(self._sync_raw(), self)

    @property
    def done(self) -> bool:
        """Whether the operation reached a terminal status."""
        return self._sync_raw().get("status") in TERMINAL

    @synced
    @classmethod
    async def list(
        cls, *, kind: Many = None, status: Many = None, status_not: Many = None, agent: Any = None,
        key: Optional[str] = None, created_after: Any = None, created_before: Any = None,
        updated_after: Any = None, cause: Optional[str] = None, limit: Optional[int] = None,
        user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> List["Operation"]:
        """Operations matching the filters, newest first (or the first ``limit``).
        ``status="live"`` means every non-terminal status; ``key`` is a key id or
        prefix (``nk_live_ab12``); ``agent`` an ``Agent`` or id; ``cause`` the failed
        ones of one cause (an ``OperationFailure``'s, from ``failures()``).

        Returns:
            Every matching operation, fetched page by page.

        Usage:
            See what failed in the last day::

                from datetime import datetime, timedelta, timezone

                yesterday = datetime.now(timezone.utc) - timedelta(days=1)
                for op in noclick.Operation.list(status="failed", created_after=yesterday):
                    print(op.kind, op.error)

            Or the turns one agent is still working on::

                support = noclick.Agent.from_name("support")
                live = noclick.Operation.list(kind="agent.message", status="live", agent=support)

            A read acts for the current user; ``user_filter`` reads across them::

                failed = noclick.Operation.list(status="failed", user_filter=noclick.ALL_USERS, limit=20)
        """
        params = await _filter_params(
            kind, status, status_not, agent, key, created_after, created_before, updated_after, cause,
        )
        return await list_all(
            "/v1/operations", lambda raw, scope: Operation._new(raw=raw, client=client, user=scope),
            params=params, user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, kind: Many = None, status: Many = None,
        status_not: Many = None, agent: Any = None, key: Optional[str] = None, created_after: Any = None,
        created_before: Any = None, updated_after: Any = None, cause: Optional[str] = None,
        user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of matching operations; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the operations and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Operation.list_page(status="failed", limit=100)
            while True:
                for op in page.data:
                    print(op.id, op.kind, op.error)
                if page.next_cursor is None:
                    break
                page = noclick.Operation.list_page(status="failed", limit=100, cursor=page.next_cursor)
        """
        params = await _filter_params(
            kind, status, status_not, agent, key, created_after, created_before, updated_after, cause,
        )
        return await list_page(
            "/v1/operations", lambda raw, scope: Operation._new(raw=raw, client=client, user=scope),
            params=params, user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def summary(
        cls, *, kind: Many = None, status: Many = None, status_not: Many = None, agent: Any = None,
        key: Optional[str] = None, created_after: Any = None, created_before: Any = None,
        updated_after: Any = None, cause: Optional[str] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> OperationSummary:
        """How many operations match the same filters, by status.

        Returns:
            The ``total``, and in ``by_status`` a count for every status, zeros included.

        Usage::

            counts = noclick.Operation.summary(kind="agent.message", status="live")
            print(counts.total, counts.by_status["running"], counts.by_status["awaiting_human"])
        """
        scope, user_id = await read_scope(user, user_filter)
        params = await _filter_params(
            kind, status, status_not, agent, key, created_after, created_before, updated_after, cause,
        )
        raw = await resolve_client(client).request(
            "GET", "/v1/operations/summary", params={**params, "user_id": user_id}, user=scope,
        ) or {}
        return OperationSummary(int(required_number(raw, "total")), dict(raw.get("by_status") or {}), raw)

    @synced
    @classmethod
    async def failures(
        cls, *, kind: Many = None, agent: Any = None, key: Optional[str] = None, created_after: Any = None,
        created_before: Any = None, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> OperationFailures:
        """The failed operations matching the filters, grouped by why they failed: one cap used up or one
        connection disconnected fails every run behind it the same way, and each is one ``OperationFailure``
        with how many, since when, the latest error and what it touched. ``limit`` caps how many causes (50).

        Returns:
            Each cause, the one that failed most lately first; ``total`` counts every failure matched.

        Usage:
            What failed in the last day, and why::

                from datetime import datetime, timedelta, timezone

                yesterday = datetime.now(timezone.utc) - timedelta(days=1)
                found = noclick.Operation.failures(created_after=yesterday, user_filter=noclick.ALL_USERS)
                for cause in found.causes:
                    print(cause.count, cause.error, cause.error.next_step)

            Then the runs behind one of them::

                runs = noclick.Operation.list(cause=found.causes[0].cause, user_filter=noclick.ALL_USERS)
        """
        scope, user_id = await read_scope(user, user_filter)
        params = await _filter_params(kind, None, None, agent, key, created_after, created_before, None)
        raw = await resolve_client(client).request(
            "GET", "/v1/operations/failures", params={**params, "user_id": user_id, "limit": limit}, user=scope,
        ) or {}
        return OperationFailures(
            [_failure(c) for c in raw.get("data") or []], int(raw.get("total") or 0), bool(raw.get("has_more")), raw,
        )

    @classmethod
    def from_id(cls, operation_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Operation":
        """A lazy reference to an operation by id.

        Returns:
            An operation that loads the first time you read a field. Nothing is sent yet.

        Usage:
            Operations outlive your process, so keep the id and pick it up anywhere::

                op = noclick.Operation.from_id("3b9d6f2e-1c4a-4e8b-9f7d-2a6c5e8b1d40")
                reply = op.wait()

            Or check on it without waiting::

                op = noclick.Operation.from_id("3b9d6f2e-1c4a-4e8b-9f7d-2a6c5e8b1d40").hydrate()
                print(op.status, op.done)
        """
        return cls._new(hints={"id": operation_id}, client=client, user=user)

    @classmethod
    def _from_payload(
        cls,
        payload: Any,
        *,
        client: Optional[Client],
        user: Any,
        kind: Optional[str] = None,
        reader: Optional[ResultReader] = None,
    ) -> "Operation":
        hints = {"kind": kind} if kind else {}
        if isinstance(payload, str):
            op = cls._new(hints={**hints, "id": payload}, client=client, user=user)
        else:
            op = cls._new(raw=payload, hints=hints, client=client, user=user)
        if reader is not None:
            op._reader = reader
        return op

    def _id(self) -> str:
        return self._known("id")

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", f"/v1/operations/{self._id()}")

    def _absorb(self, raw: Dict[str, Any]) -> None:
        self._raw = {**(self._raw or {}), **raw}

    @synced
    async def wait(self, timeout: Optional[float] = None) -> Any:
        """Block until the operation finishes.

        Raises the operation's error if it failed, ``OperationCanceled`` /
        ``OperationExpired``, or ``OperationTimeout`` after ``timeout`` seconds.

        Returns:
            The outcome, typed for the operation's kind: an ``AgentReply`` from ``agent.send``,
            ``True`` or ``False`` from ``human.approve``, the connected ``Connection`` from a
            connect link. A kind the client has no type for gives the raw ``result``.

        Usage:
            Start an agent turn, then block on it::

                agent = noclick.Agent.from_name("support")
                turn = agent.send("Draft the monthly report", user="user_42")
                reply = turn.wait(timeout=120)
                print(reply.text)

            A timeout leaves the operation running, so you can wait on it again later::

                op = noclick.Operation.from_id("3b9d6f2e-1c4a-4e8b-9f7d-2a6c5e8b1d40")
                try:
                    reply = op.wait(timeout=30)
                except noclick.OperationTimeout:
                    print(op.status)   # still running
        """
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        while self._raw is None or not self._waited():
            if deadline is None:
                window = self._wait_window_s
            else:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    if self._raw is None:
                        await self._ensure()
                        continue
                    raise self._linked(OperationTimeout(
                        f"Operation {self._id()} is still {self._raw.get('status')} after {timeout}s.",
                        next_step="Call wait() again, or check op.status later.",
                        details={"operation_id": self._id(), "operation_status": self._raw.get("status")},
                    ))
                window = min(self._wait_window_s, max(1, math.ceil(remaining)))
            self._absorb(await self._request(
                "GET", f"/v1/operations/{self._id()}/wait",
                params={"timeout_s": window}, timeout=window + 15,
            ))
        return self._outcome()

    def _waited(self) -> bool:
        """Whether wait() is done: the operation finished (a kind may stop it sooner)."""
        return (self._raw or {}).get("status") in TERMINAL

    def _outcome(self) -> Any:
        raw = self._raw or {}
        status = raw.get("status")
        if status == "succeeded":
            reader = self._reader or _READERS.get(self._known("kind") or "")
            result = raw.get("result")
            return reader(result, self) if reader is not None else result
        err = _error_of(raw, self)
        if err is None:
            cls = {"canceled": OperationCanceled, "expired": OperationExpired}.get(status, OperationFailed)
            err = cls(f"Operation {self._id()} {status}.", details={"operation_id": self._id()})
        raise self._linked(err)

    def _linked(self, err: Error) -> Error:
        """Point a raised error at this operation's console page."""
        url = self.console_url
        if url:
            err.message = f"{err.message} See {url}"
            err.args = (err.message,)
        return err

    @synced
    async def tool_calls(self) -> List[ToolCall]:
        """The tool calls an ``agent.message`` turn made, oldest first (none for other kinds).

        Returns:
            Each call's tool, arguments, status, duration and a preview of its result.

        Usage::

            agent = noclick.Agent.from_name("support")
            turn = agent.send("Find last week's invoices", user="user_42")
            turn.wait()
            for call in turn.tool_calls():
                print(call.tool_name, call.status, call.duration_ms)
        """
        rows = await paginate(self._api, f"/v1/operations/{self._id()}/tool_calls", user=self._call_scope())
        return [ToolCall._from(row) for row in rows]

    @synced
    async def events(self, *, interval: float = 1.0) -> AsyncIterator[OperationEvent]:
        """Yield an ``OperationEvent`` for each status or step change until it finishes.

        Returns:
            The changes, polled every ``interval`` seconds: first the status (and ``step``) it has
            now, last its final one. An event's ``result`` is the raw result, not the typed outcome
            ``wait()`` returns.

        Usage:
            Print each change as it happens, a CLI agent's turn going from ``delivering`` to ``working``::

                op = noclick.Operation.from_id("3b9d6f2e-1c4a-4e8b-9f7d-2a6c5e8b1d40")
                for event in op.events(interval=5):
                    print(event.status, event.step, event.updated_at)

            In async code, iterate the ``.aio()`` form::

                op = noclick.Operation.from_id("3b9d6f2e-1c4a-4e8b-9f7d-2a6c5e8b1d40")
                async for event in op.events.aio():
                    print(event.status)
        """
        last = None
        while True:
            raw = await self._request("GET", f"/v1/operations/{self._id()}")
            self._absorb(raw)
            marker = (raw.get("status"), raw.get("step"), raw.get("updated_at"))
            if marker != last:
                last = marker
                yield OperationEvent(
                    status=raw.get("status"),
                    step=raw.get("step"),
                    updated_at=parse_time(raw.get("updated_at")),
                    result=raw.get("result"),
                    error=_error_of(raw, self),
                    raw=raw,
                )
            if raw.get("status") in TERMINAL:
                return
            await asyncio.sleep(interval)

    @synced
    async def cancel(self) -> "Operation":
        """Ask the server to cancel. A coding agent's turn (``agent.message`` on a coding harness) stops in its
        sandbox first, its harness going on from the same session, so the next turn never runs beside it.

        Returns:
            This operation, now ``canceled``.

        Usage:
            Cancel a turn you no longer need::

                agent = noclick.Agent.from_name("support")
                turn = agent.send("Draft the monthly report", user="user_42")
                turn.cancel()
                print(turn.status)   # canceled

            An operation that already finished can't be canceled::

                op = noclick.Operation.from_id("3b9d6f2e-1c4a-4e8b-9f7d-2a6c5e8b1d40")
                try:
                    op.cancel()
                except noclick.Conflict as err:
                    print(err.operation_status)   # succeeded, failed, ...
        """
        raw = await self._request("POST", f"/v1/operations/{self._id()}/cancel")
        if isinstance(raw, dict):
            self._absorb(raw)
        return self

    @synced
    async def undo(self) -> Dict[str, Any]:
        """Take back a reversible write, once: a deletion comes out of the trash, a dict's cleared keys come
        back, a migrated database is restored to the moment before, a restored database gets back what the restore
        rewound, a promote puts production back on the release before with the app's databases as they were (each
        restore keeping what it rewinds in the trash, named in the result's ``copies``). What reached the world (an
        email sent, a payment) has no undo: that raises ``noclick.Conflict``, as does undoing twice.

        Returns:
            What the undo put back, as its own API shows it (a restore of a database is an operation of its own).

        Usage::

            item = noclick.Dict.from_name("rates-cache").delete()
            noclick.Operation.from_id(item.operation_id).undo()
        """
        result = await self._request("POST", f"/v1/operations/{self._id()}/undo")
        self._raw = None
        return result["result"]
