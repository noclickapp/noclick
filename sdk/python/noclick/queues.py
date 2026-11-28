"""Queues: durable background work, delivered at least once.

    jobs = noclick.Queue.from_name("invoices", create_if_missing=True)
    jobs.put({"invoice": "INV-1042"})

    for msg in jobs.iterate(lease_s=60):
        print("Sending", msg.body["invoice"])
        msg.ack()

A message you take is leased to you for ``lease_s`` seconds: ``ack()`` it when
the work is done, or it comes back for another try (so handle a message twice
safely). A message that fails ``max_attempts`` times moves to the dead letters,
where you can retry or discard it. An agent can take the messages instead:
``triggers=[noclick.OnQueue(jobs)]`` makes each one a turn.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field as dc_field
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import Page, _Object, compact, field, list_all, list_page, paginate, parse_time
from ._sync import synced
from .trash import TrashItem, trashed
from ._scope import AMBIENT, resolve_scope
from .exceptions import Conflict, InvalidRequest, NotFound
from .export import ExportBundle
from .operation import Operation, register_result

# Attempts before a message is dead-lettered, unless the queue says otherwise.
_DEFAULT_MAX_ATTEMPTS = 5
# Long-poll window per request while iterating (``wait_s``).
_ITERATE_WAIT_S = 25


@dataclass(frozen=True)
class QueueDepth:
    """How full a queue was at one moment: ``depth`` messages waiting and
    ``in_flight`` leased, at ``at``."""

    at: Any
    depth: int
    in_flight: int

    @classmethod
    def _from(cls, raw: Any) -> "QueueDepth":
        raw = raw if isinstance(raw, dict) else {}
        return cls(parse_time(raw.get("at")), int(raw.get("depth") or 0), int(raw.get("in_flight") or 0))


class QueueMessage(_Object):
    """One message on a queue. ``body`` is the JSON you put; ``attempts`` counts
    its deliveries, this one included. A message you took with ``get`` or
    ``iterate`` is leased to you until ``lease_expires_at``: ``ack()`` when the work
    is done, ``nack()`` to hand it back now as a failed try, ``release()`` to hand it
    back without spending one. A dead letter (from
    ``dead_letters()``) says why its last attempt failed in ``last_error``;
    ``retry()`` puts it back on the queue and ``discard()`` deletes it.

    ``status`` is ``waiting`` (``delayed`` until ``visible_at``), ``in_flight``
    while leased, or ``dead``."""

    _repr_keys = ("id", "status", "attempts")

    id: str = field("id")
    queue_id: str = field("queue_id")
    body: Any = field("body", doc="The message as you put it: JSON.")
    status: str = field("status", doc="``waiting``, ``delayed``, ``in_flight`` or ``dead``.")
    attempts: int = field("attempts", doc="How many times it has been delivered, this delivery included.")
    enqueued_at: Any = field("enqueued_at", parse_time)
    visible_at: Any = field("visible_at", parse_time, doc="When a delayed message can first be taken (None once it can).")
    lease_expires_at: Any = field(
        "lease_expires_at", parse_time, doc="When your lease ends and the message goes back (None unless you hold it).",
    )
    last_error: Optional[str] = field("last_error", doc="Why its last attempt failed (None if none has).")
    dead_lettered_at: Any = field("dead_lettered_at", parse_time, doc="When it became a dead letter (None unless it is one).")

    def _path(self, suffix: str = "") -> str:
        return f"/v1/queues/{self._known('queue_id')}/messages/{quote(str(self._known('id')), safe='')}{suffix}"

    async def _load(self) -> Dict[str, Any]:
        raw = await self._request("GET", self._path())
        lease_id = self._known("lease_id")  # a re-read keeps the lease you hold
        return {**raw, "lease_id": lease_id} if lease_id and not raw.get("lease_id") else raw

    def _lease(self) -> str:
        lease_id = self._known("lease_id")
        if not lease_id:
            raise InvalidRequest(
                "This message isn't leased to you, so there's nothing to ack, nack or release.",
                next_step="Take messages with queue.get(...) or queue.iterate(...); peek() and dead_letters() only read them.",
            )
        return lease_id

    @synced
    async def ack(self) -> None:
        """Mark the message done: it's deleted and never delivered again. Ack only
        after the work has succeeded. Once the lease has run out the message may
        already be someone else's, so a late ack raises ``noclick.Conflict``; your
        work must then be safe to do twice.

        Usage::

            jobs = noclick.Queue.from_name("invoices")
            msg = jobs.get(timeout_s=30)
            if msg is not None:
                print("Sending", msg.body["invoice"])
                msg.ack()
        """
        await self._request("POST", self._path("/ack"), json={"lease_id": self._lease()})

    @synced
    async def nack(self, *, delay_s: int = 0, error: Optional[str] = None) -> None:
        """Hand the message back unfinished, for another try after ``delay_s``
        seconds. It counts as an attempt: after the queue's ``max_attempts`` it
        moves to the dead letters instead. ``error`` (up to 2 KB) says why; it's the
        message's ``last_error``, which a dead letter keeps.

        Usage::

            jobs = noclick.Queue.from_name("invoices")
            msg = jobs.get(timeout_s=30)
            if msg is not None:
                msg.nack(delay_s=60, error="The invoicing service answered 503")   # try again in a minute
        """
        body = {"lease_id": self._lease(), **compact(delay_s=delay_s or None, error=error)}
        await self._request("POST", self._path("/nack"), json=body)

    @synced
    async def release(self, *, delay_s: int = 0) -> None:
        """Hand the message back untouched, for someone to take after ``delay_s`` seconds,
        without spending an attempt: ``attempts`` goes back to what it was before this
        delivery, and ``last_error`` is left as it was. Use it when the failure isn't the
        message's (your account is out of money, a service everything depends on is down),
        so a backlog doesn't burn its tries and land in the dead letters. A message you
        release keeps coming back until the cause is fixed, so stop taking more meanwhile.

        Usage::

            jobs = noclick.Queue.from_name("recordings")
            msg = jobs.get(timeout_s=30)
            if msg is not None:
                try:
                    words = noclick.AI.transcribe(msg.body["url"])
                except noclick.PaymentRequired:
                    msg.release(delay_s=3600)   # not the recording's fault: no try spent
                else:
                    print(words.text)
                    msg.ack()
        """
        body = {"lease_id": self._lease(), **compact(delay_s=delay_s or None)}
        await self._request("POST", self._path("/release"), json=body)

    @synced
    async def retry(self) -> None:
        """Put a dead letter back on the queue, with its attempts reset, once
        you've fixed what made it fail.

        Usage::

            jobs = noclick.Queue.from_name("invoices")
            for letter in jobs.dead_letters():
                letter.retry()
        """
        await self._request("POST", f"/v1/queues/{self._known('queue_id')}/dead_letters/{quote(self.id, safe='')}/retry")

    @synced
    async def discard(self) -> None:
        """Delete a dead letter for good.

        Usage::

            jobs = noclick.Queue.from_name("invoices")
            for letter in jobs.dead_letters():
                if "unknown invoice" in (letter.last_error or ""):
                    letter.discard()
        """
        await self._request("DELETE", f"/v1/queues/{self._known('queue_id')}/dead_letters/{quote(self.id, safe='')}")


def _read_export(result: Any, op: Operation) -> ExportBundle:
    return ExportBundle._from(result)


register_result("queue.export", _read_export)


class Queue(_Object):
    """A durable queue of JSON messages, delivered at least once.

    ``put`` adds work; ``get`` and ``iterate`` take it under a lease, and each
    message is ``ack``ed when done or delivered again. ``depth`` is how many wait,
    ``in_flight`` how many are leased, ``dead_letter_count`` how many failed
    ``max_attempts`` times (as of the last load; ``len()`` reads the depth fresh).
    ``used_by`` lists who consumes it: agents with an ``OnQueue`` trigger and apps
    that bind it."""

    _repr_keys = ("id", "name")

    id: str = field("id")
    name: str = field("name")
    depth: int = field("depth", doc="Messages waiting to be taken, delayed ones included.")
    in_flight: int = field("in_flight", doc="Messages leased and not yet acked.")
    dead_letter_count: int = field("dead_letter_count", doc="Messages that failed ``max_attempts`` times.")
    max_attempts: int = field("max_attempts", doc="Deliveries a message gets before it's a dead letter.")
    used_by: List[Dict[str, Any]] = field(
        "used_by",
        doc="Who consumes it: agents with an ``OnQueue`` trigger (``kind`` ``agent``) and apps that bind it (``kind`` "
            "``project``, with the ``binding`` name).",
    )
    region: Optional[str] = field(
        "region", doc="The region it keeps its data in (``noclick.regions()``), fixed when it was created.",
    )
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        self._converge: Optional[int] = None
        super()._init(**kwargs)

    @property
    def console_url(self) -> Optional[str]:
        """This queue in the developer console, with its messages and dead letters (None off the hosted API)."""
        base = self._api.console_url("resources", "queues")
        return f"{base}?queue={quote(str(self._known('id')), safe='')}" if base and self._known("id") else base

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls, name: str, *, max_attempts: int = _DEFAULT_MAX_ATTEMPTS, region: Optional[str] = None,
        allow_existing: bool = False, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> "Queue":
        """Create a queue called ``name`` (1-64 letters, digits and ``. _ -``),
        unique to its user (a taken name raises ``noclick.Conflict`` with
        ``existing_id``, or with ``allow_existing=True`` returns the queue already there, as it
        is). A message is delivered up to ``max_attempts`` times (1 to 100) before it's a dead
        letter. ``region`` (``noclick.regions(kind="queue")``)
        is where its messages are kept, for good; without one, your account's
        default region, else ``us-east``. Queues are kept in ``us-east`` only for
        now: another region, or a default region elsewhere, raises
        ``noclick.InvalidRequest`` naming it.

        Returns:
            The new queue, empty.

        Usage:
            A queue of the account's own::

                jobs = noclick.Queue.create("invoices")

            Give flaky work more tries, for one user::

                with noclick.as_user("acme"):
                    exports = noclick.Queue.create("erp-exports", max_attempts=10)
        """
        scope = resolve_scope(user)
        raw = await cls._create_named(
            "/v1/queues", {"name": name, "max_attempts": max_attempts, **compact(region=region)},
            allow_existing=allow_existing, user=scope, client=client,
        )
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls, name: str, *, create_if_missing: bool = False, max_attempts: Optional[int] = None,
        region: Optional[str] = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> "Queue":
        """A lazy reference to the queue called ``name`` in the current (or given)
        user. A ``max_attempts`` you pass is set on the queue every time it runs. With
        ``create_if_missing=True`` it's created on first use, in ``region`` (as ``create``), with
        ``max_attempts`` (5 if you leave it out); without it, a missing queue raises
        ``noclick.NotFound``.

        Inside a deployed app (signed in by its deployment) the name is looked up in the app's own
        namespace for the environment the code runs in, and one made there is the app's: a name bound to
        the app by hand wins, and in a preview of an app whose ``preview_resources`` is ``branch`` the
        branch gets its own empty queue, so a preview never changes production's data.

        Returns:
            A queue that loads (or is created) on first use. Nothing is sent yet.

        Usage:
            Name it in your code, so the first run creates it::

                jobs = noclick.Queue.from_name("invoices", create_if_missing=True)
                jobs.put({"invoice": "INV-1042"})

            Change how many tries a message gets::

                buffer = noclick.Queue.from_name("webhook-buffer", create_if_missing=True, max_attempts=8)
                print(buffer.max_attempts)   # 8
        """
        queue = cls._new(hints={"name": name}, client=client, user=user)
        if create_if_missing:
            queue._create_with = {"name": name, "max_attempts": max_attempts or _DEFAULT_MAX_ATTEMPTS,
                                  **compact(region=region)}
        queue._converge = max_attempts
        return queue

    @classmethod
    def from_id(cls, queue_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Queue":
        """A lazy reference to a queue by id. There's no ``Queue.get(id)``, since
        ``get`` takes a message: call ``hydrate()`` on this to load it now.

        Returns:
            A queue that loads the first time you use it. Nothing is sent yet.

        Usage::

            jobs = noclick.Queue.from_id("8d3f1a6c-2b7e-4c95-9e10-4a6b2c8d7f31").hydrate()
            print(jobs.name, jobs.depth, jobs.dead_letter_count)
        """
        return cls._new(hints={"id": queue_id}, client=client, user=user)

    @synced
    @classmethod
    async def list(
        cls, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Queue"]:
        """The current user's queues (the account's own outside ``as_user``, or
        those ``user_filter`` covers).

        Returns:
            Every matching queue, newest first, fetched page by page.

        Usage:
            How deep each of your queues is::

                for queue in noclick.Queue.list():
                    print(queue.name, queue.depth, queue.in_flight, queue.dead_letter_count)

            Every user's::

                every = noclick.Queue.list(user_filter=noclick.ALL_USERS)
        """
        return await list_all(
            "/v1/queues", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of queues; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the queues and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Queue.list_page(limit=50, user_filter=noclick.ALL_USERS)
            for queue in page.data:
                print(queue.user_id, queue.name, queue.depth)
        """
        return await list_page(
            "/v1/queues", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        queue_id = self._known("id")
        if queue_id:
            return await self._request("GET", f"/v1/queues/{queue_id}")
        name = self._hints["name"]
        found = await self._in_app("queue", name, self._create_with)
        if found is not None:
            return found
        page = await self._request("GET", "/v1/queues", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        if rows:
            raw = rows[0]
            if self._converge is not None and raw.get("max_attempts") != self._converge:
                raw = await self._request("PATCH", f"/v1/queues/{raw['id']}", json={"max_attempts": self._converge})
            return raw
        if self._create_with is None:
            raise NotFound(
                f"No queue is named {name!r}.",
                next_step="Create it with noclick.Queue.create(...) or pass create_if_missing=True.",
                details={"name": name, "kind": "queue"},
            )
        try:
            return await self._request("POST", "/v1/queues", json=self._create_with)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._request("GET", f"/v1/queues/{exc.existing_id}")

    async def _url(self, suffix: str = "") -> str:
        """This queue's route; a reference by name is looked up (or created) first."""
        if not self._known("id"):
            await self._ensure()
        return f"/v1/queues/{self._known('id')}{suffix}"

    def _message(self, raw: Dict[str, Any]) -> QueueMessage:
        return QueueMessage._new(
            raw=raw, hints={"queue_id": self._known("id")}, client=self._client, user=self._call_scope(),
        )

    # --- settings --------------------------------------------------------

    @synced
    async def update(self, *, max_attempts: int) -> "Queue":
        """Change how many deliveries a message gets before it's a dead letter
        (1 to 100). Messages already on the queue follow the new number.

        Returns:
            This queue, with its new ``max_attempts``.

        Usage::

            jobs = noclick.Queue.from_name("invoices")
            jobs.update(max_attempts=10)
        """
        self._raw = await self._request("PATCH", await self._url(), json={"max_attempts": max_attempts})
        return self

    # --- putting work on -------------------------------------------------

    @synced
    async def put(self, body: Any, *, delay_s: int = 0, dedupe_key: Optional[str] = None) -> str:
        """Add a message: any JSON, up to 256 KB. With ``delay_s`` (up to 7 days)
        nobody can take it until then, for a retry later or a reminder.
        ``dedupe_key`` (up to 128 characters) makes the put safe to repeat: for 24
        hours, another put with the same key adds nothing and returns the first
        message's id, so code that crashes and puts again doesn't enqueue twice.

        Returns:
            The new message's id (the first one's, for a repeated ``dedupe_key``).

        Usage:
            Hand a job to your workers::

                jobs = noclick.Queue.from_name("invoices", create_if_missing=True)
                jobs.put({"invoice": "INV-1042", "customer": "acme"})

            Check back on a payment in an hour::

                jobs = noclick.Queue.from_name("invoices", create_if_missing=True)
                message_id = jobs.put({"check_payment": "INV-1042"}, delay_s=3600)
                print(message_id)

            Enqueue each order once, however often this code runs for it::

                jobs = noclick.Queue.from_name("fulfilment", create_if_missing=True)
                jobs.put({"order": "o_981"}, dedupe_key="order-o_981")
        """
        [message_id] = await self._put([body], delay_s, dedupe_key)
        return message_id

    @synced
    async def put_many(self, bodies: Sequence[Any], *, delay_s: int = 0) -> List[str]:
        """Add up to 100 messages in one call, all of them or none.

        Returns:
            The new messages' ids, in the order you gave them.

        Usage::

            jobs = noclick.Queue.from_name("invoices", create_if_missing=True)
            ids = jobs.put_many([{"invoice": f"INV-{n}"} for n in range(1042, 1052)])
            print(len(ids))   # 10
        """
        return await self._put(list(bodies), delay_s)

    async def _put(self, bodies: List[Any], delay_s: int, dedupe_key: Optional[str] = None) -> List[str]:
        wire = [{"body": body, **compact(delay_s=delay_s or None, dedupe_key=dedupe_key)} for body in bodies]
        response = await self._request("POST", await self._url("/messages"), json={"messages": wire}) or {}
        return [row["id"] for row in response.get("data") or []]

    # --- taking work off -------------------------------------------------

    async def _take(self, wait_s: int, lease_s: int) -> List[QueueMessage]:
        response = await self._request(
            "GET", await self._url("/messages"), params={"wait_s": wait_s or None, "lease_s": lease_s, "limit": 1},
            timeout=None if not wait_s else wait_s + 15,
        ) or {}
        return [self._message(row) for row in response.get("data") or []]

    @synced
    async def get(self, *, timeout_s: int = 0, lease_s: int = 60) -> Optional[QueueMessage]:
        """Take the next message, waiting up to ``timeout_s`` seconds (at most 60)
        for one to arrive. It's leased to you for ``lease_s`` seconds (up to 12
        hours): ``ack()`` it before then, or it's delivered again. Messages come out
        roughly in the order they went in, but order isn't guaranteed.

        Returns:
            The message, or ``None`` if none arrived in time.

        Usage::

            jobs = noclick.Queue.from_name("invoices")
            msg = jobs.get(timeout_s=30, lease_s=120)
            if msg is not None:
                print(msg.body, msg.attempts)
                msg.ack()
        """
        batch = await self._take(timeout_s, lease_s)
        return batch[0] if batch else None

    @synced
    async def iterate(self, *, lease_s: int = 60, stop_when_empty: bool = False) -> AsyncIterator[QueueMessage]:
        """Take messages as they arrive, each leased for ``lease_s`` seconds; it
        waits while the queue is empty and runs until you stop iterating. With
        ``stop_when_empty=True`` it ends instead the first time nothing is waiting
        (messages leased to someone else, or delayed, don't keep it going), to drain a
        queue in a batch job. Ack each message when its work is done. ``async for msg in
        queue.iterate.aio()`` in async code.

        Returns:
            Each message as it's taken. Without ``stop_when_empty`` it never ends on its own, so ``break`` when you're done.

        Usage:
            A worker::

                jobs = noclick.Queue.from_name("invoices", create_if_missing=True)
                for msg in jobs.iterate(lease_s=120):
                    try:
                        print("Sending", msg.body["invoice"])
                    except Exception:
                        msg.nack(delay_s=30)
                    else:
                        msg.ack()

            In async code::

                jobs = noclick.Queue.from_name("invoices", create_if_missing=True)
                async for msg in jobs.iterate.aio(lease_s=120):
                    print(msg.body)
                    await msg.ack.aio()

            Drain what's there, then finish::

                jobs = noclick.Queue.from_name("invoices")
                for msg in jobs.iterate(stop_when_empty=True):
                    print("Sending", msg.body["invoice"])
                    msg.ack()
        """
        loop = asyncio.get_running_loop()
        while True:
            started = loop.time()
            batch = await self._take(0 if stop_when_empty else _ITERATE_WAIT_S, lease_s)
            for message in batch:
                yield message
            if not batch and stop_when_empty:
                return
            if not batch:
                await self._api._sleep(max(0.0, 1.0 - (loop.time() - started)))  # never spin on a short poll

    # --- looking -----------------------------------------------------------

    @synced
    async def len(self) -> int:
        """How many messages wait (delayed ones included, leased ones and dead letters not), read now.

        Returns:
            The queue's depth.

        Usage::

            jobs = noclick.Queue.from_name("invoices")
            print(jobs.len(), "invoices waiting")
        """
        self._raw = await self._request("GET", await self._url())
        return int(self._raw.get("depth") or 0)

    @synced
    async def peek(self, *, limit: int = 10) -> List[QueueMessage]:
        """Look at the oldest messages without taking them: waiting and in flight,
        oldest first. Nothing is leased, so you can't ack these.

        Returns:
            Up to ``limit`` (at most 100) messages, with their ``status`` and ``attempts``.

        Usage::

            jobs = noclick.Queue.from_name("invoices")
            for msg in jobs.peek(limit=5):
                print(msg.status, msg.attempts, msg.body)
        """
        response = await self._request("GET", await self._url("/messages"), params={"view": "peek", "limit": limit}) or {}
        return [self._message(row) for row in response.get("data") or []]

    @synced
    async def dead_letters(self, *, limit: Optional[int] = None) -> List[QueueMessage]:
        """The messages that failed ``max_attempts`` times, newest first. Each says
        why in ``last_error``; ``retry()`` or ``discard()`` it. Dead letters are
        kept 14 days.

        Returns:
            Every dead letter (or the first ``limit``), fetched page by page.

        Usage::

            jobs = noclick.Queue.from_name("invoices")
            for letter in jobs.dead_letters():
                print(letter.body, letter.attempts, letter.last_error)
        """
        rows = await paginate(self._api, await self._url("/dead_letters"), user=self._call_scope(), limit=limit)
        return [self._message(row) for row in rows]

    @synced
    async def depth_history(self, *, hours: int = 24) -> List[QueueDepth]:
        """How deep the queue has been over the last ``hours`` (up to 168), a point
        every 15 minutes: whether your workers keep up.

        Returns:
            A ``QueueDepth`` (``at``, ``depth``, ``in_flight``) per point, oldest first.

        Usage::

            jobs = noclick.Queue.from_name("invoices")
            worst = max(jobs.depth_history(hours=24), key=lambda point: point.depth)
            print(worst.at, worst.depth)
        """
        response = await self._request("GET", await self._url("/depth"), params={"hours": hours}) or {}
        return [QueueDepth._from(row) for row in response.get("data") or []]

    # --- lifecycle -------------------------------------------------------

    @synced
    async def clear(self) -> None:
        """Drop every waiting message and every dead letter. Messages in flight
        finish as usual. The queue itself stays.

        Usage::

            jobs = noclick.Queue.from_name("invoices")
            jobs.clear()
        """
        await self._request("POST", await self._url("/clear"))

    @synced
    async def export(self) -> Operation:
        """Export every message as it stands at one moment, dead letters
        included, as JSON Lines: one per line, oldest first, with its ``status``
        (``waiting``, ``delayed``, ``in_flight`` or ``dead``), ``attempts`` and ``body``.

        Returns:
            An operation whose ``wait()`` gives an ``ExportBundle``: a zip at ``url`` holding the files.

        Usage::

            jobs = noclick.Queue.from_name("invoices")
            bundle = jobs.export().wait()
            print(bundle.url)
        """
        payload = await self._request("POST", await self._url("/export"))
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="queue.export", reader=_read_export,
        )

    @synced
    async def delete(self) -> TrashItem:
        """Delete the queue and every message on it: it goes to the trash, restorable for 30 days. A queue an
        app binds or an agent's ``OnQueue`` trigger reads raises ``noclick.Conflict`` until you unbind it or
        remove the trigger.

        Returns:
            Its ``TrashItem``: ``restore()`` puts it back, messages and all.

        Usage::

            jobs = noclick.Queue.from_name("invoices")
            jobs.delete()
        """
        raw = await self._request("DELETE", await self._url())
        return trashed(raw, client=self._client, user=self._call_scope())
