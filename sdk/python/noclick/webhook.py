"""Webhooks and events: everything that happens, delivered to your server, signed.

    hook = noclick.Webhook.from_name("https://api.yourco.test/noclick/events", create_if_missing=True,
                                     events=["operation.*", "human.answered"])
    secret = hook.reveal_secret()   # needs the webhooks:reveal scope

    # in your receiver
    event = noclick.Webhook.verify(request_body, request_headers, secret)
    print(event.type, event.data)

Every event is also kept for 30 days: ``noclick.Event.list(type="domain.*")``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from ._client import Client, resolve_client
from ._object import (
    UNSET, Page, _Object, compact, csv, field, iso_time, list_all, list_page, paginate, parse_time,
)
from ._sync import run_sync, synced
from ._scope import AMBIENT, resolve_scope
from .exceptions import Conflict, NotFound, WebhookSignatureError

# The header every delivery carries: ``t=<unix seconds>,v1=<hex HMAC-SHA256 of "t.body">``.
SIGNATURE_HEADER = "NoClick-Signature"


@dataclass(frozen=True)
class EventType:
    """One kind of event: its ``name`` (``operation.succeeded``) and what it means.
    ``area`` is the part before the first dot, the thing the event is about.
    ``emitted`` is whether NoClick sends it today: the rest are listed so your
    code can subscribe before the primitive behind them ships."""

    name: str
    description: str
    emitted: bool
    raw: Dict[str, Any] = dc_field(repr=False)

    @property
    def area(self) -> str:
        """What the event is about: ``operation``, ``human``, ``domain``, ..."""
        return self.name.split(".", 1)[0]


@dataclass(frozen=True)
class WebhookDelivery:
    """One event sent (or on its way) to one webhook. ``status`` is ``pending``
    (not tried yet), ``retrying`` (an attempt failed; ``next_retry_at`` says when
    the next one is), ``succeeded`` (your server answered 2xx) or ``failed`` (three
    days of retries ran out). ``response_status`` and ``response_body`` (its first
    4 KB) are from the latest attempt; ``request_body`` is the JSON that was sent."""

    id: str
    webhook_id: Optional[str]
    event_id: Optional[str]
    event_type: Optional[str]
    status: str
    attempts: int
    response_status: Optional[int]
    response_body: Optional[str]
    request_body: Optional[str]
    duration_ms: Optional[int]
    # Why the latest attempt failed (``Answered 502``, ``No answer within 10 seconds.``); None once it succeeded.
    error: Optional[str]
    next_retry_at: Any
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "WebhookDelivery":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            id=raw.get("id") or "", webhook_id=raw.get("webhook_id"), event_id=raw.get("event_id"),
            event_type=raw.get("event_type"), status=raw.get("status") or "pending", attempts=raw.get("attempts") or 0,
            response_status=raw.get("response_status"), response_body=raw.get("response_body"),
            request_body=raw.get("request_body"), duration_ms=raw.get("duration_ms"), error=raw.get("error"),
            next_retry_at=parse_time(raw.get("next_retry_at")), created_at=parse_time(raw.get("created_at")), raw=raw,
        )

    @property
    def ok(self) -> bool:
        """Whether your server accepted it (a 2xx)."""
        return self.status == "succeeded"


class Event(_Object):
    """Something that happened: an operation finished, a person answered, a domain
    went live. ``type`` names it (see ``Event.types()``) and ``data`` is the object
    it's about, as its own read returns it (``data["object"]`` names the kind,
    ``data["id"]`` its id). Delivered to your webhooks, and kept for 30 days."""

    _repr_keys = ("id", "type")

    id: str = field("id")
    type: str = field("type", doc="What happened, like ``operation.succeeded``.")
    data: Dict[str, Any] = field("data", doc="The object the event is about, as its own read returns it.")
    user_id: Optional[str] = field("user_id", doc="The user it happened for (None for your account's own).")
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._full = False
        super()._init(**kwargs)

    def _path(self) -> str:
        return f"/v1/events/{self._known('id')}"

    async def _load(self) -> Dict[str, Any]:
        raw = await self._request("GET", self._path())
        self._full = True
        return raw

    @property
    def deliveries(self) -> List[WebhookDelivery]:
        """Where this event went: one delivery per webhook that subscribes to it,
        each with its status and attempts. An event from a listing loads its full
        view on first read."""
        raw = self._sync_raw()
        if "deliveries" not in raw and not self._full:
            self._raw = raw = {**raw, **run_sync(self._load())}
        return [WebhookDelivery._from(row) for row in raw.get("deliveries") or []]

    # --- reads -------------------------------------------------------------

    @classmethod
    def from_id(cls, event_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Event":
        """A lazy reference to an event by id.

        Returns:
            An event that loads the first time you read a field. Nothing is sent yet.

        Usage::

            event = noclick.Event.from_id("7c1e9a4b-2d3f-4a8e-9b6c-0f5d2e8a1b37")
            print(event.type, event.created_at)
        """
        return cls._new(hints={"id": event_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, event_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Event":
        """Load an event by id now, with its deliveries; an unknown id (or one older
        than 30 days) raises ``noclick.NotFound``.

        Returns:
            The event, loaded.

        Usage::

            event = noclick.Event.get("7c1e9a4b-2d3f-4a8e-9b6c-0f5d2e8a1b37")
            for delivery in event.deliveries:
                print(delivery.webhook_id, delivery.status, delivery.attempts)
        """
        event = cls.from_id(event_id, client=client, user=user)
        await event._ensure()
        return event

    @staticmethod
    def _params(type: Union[None, str, Sequence[str]], since: Any, until: Any) -> Dict[str, Any]:
        return {"type": csv(type), "since": iso_time(since), "until": iso_time(until)}

    @synced
    @classmethod
    async def list(
        cls, *, type: Union[None, str, Sequence[str]] = None, since: Any = None, until: Any = None,
        limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> List["Event"]:
        """Events newest first, from the last 30 days. ``type`` is one type or
        several, and ``*`` matches the rest of a name (``domain.*``); ``since`` and
        ``until`` are timezone-aware datetimes or ISO strings. Outside ``as_user``
        you read your account's own events; ``user_filter`` reads your users'.

        Returns:
            Every matching event, fetched page by page (or the first ``limit``).

        Usage:
            See what happened to your domains this week::

                from datetime import datetime, timedelta, timezone

                week = datetime.now(timezone.utc) - timedelta(days=7)
                for event in noclick.Event.list(type="domain.*", since=week):
                    print(event.created_at, event.type, event.data["name"])

            Every failure, across your users too::

                failed = noclick.Event.list(type=["operation.failed", "agent.turn.failed"], user_filter=noclick.ALL_USERS, limit=50)
        """
        return await list_all(
            "/v1/events", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params=cls._params(type, since, until), user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, type: Union[None, str, Sequence[str]] = None,
        since: Any = None, until: Any = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> Page:
        """One page of events; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the events and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Event.list_page(type="operation.failed", limit=100)
            while True:
                for event in page.data:
                    print(event.id, event.data["kind"])
                if page.next_cursor is None:
                    break
                page = noclick.Event.list_page(type="operation.failed", limit=100, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/events", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params=cls._params(type, since, until), user=user, user_filter=user_filter,
            cursor=cursor, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def types(cls, *, client: Optional[Client] = None) -> List[EventType]:
        """The catalog of event types a webhook can subscribe to.

        Returns:
            Every event type with what it means, in catalog order (grouped by ``area``).

        Usage::

            for kind in noclick.Event.types():
                print(kind.name, kind.description)
        """
        page = await resolve_client(client).request("GET", "/v1/events/types", user=None) or {}
        rows = page.get("data") if isinstance(page, dict) else page
        return [EventType(row.get("name") or "", row.get("description") or "", bool(row.get("emitted")), row)
                for row in rows or [] if isinstance(row, dict)]


def _delivery_id(delivery: Union[str, WebhookDelivery]) -> str:
    return delivery.id if isinstance(delivery, WebhookDelivery) else delivery


def _header(headers: Mapping[str, Any], name: str) -> Optional[str]:
    """A header by name, whatever case the framework keeps them in."""
    wanted = name.lower()
    for key, value in headers.items():
        if str(key).lower() == wanted:
            return ", ".join(value) if isinstance(value, (list, tuple)) else str(value)
    return None


def _parse_signature(header: str) -> tuple:
    """``t=1727366400,v1=ab..,v1=cd..`` → (1727366400, ["ab..", "cd.."]); a rotation signs twice."""
    timestamp: Optional[int] = None
    signatures: List[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t" and value.isdigit():
            timestamp = int(value)
        elif key == "v1" and value:
            signatures.append(value.strip())
    return timestamp, signatures


def verify_signature(
    payload: Union[bytes, str], headers: Mapping[str, Any], secret: Union[str, Sequence[str]], *, tolerance_s: int,
) -> bytes:
    """Check a ``NoClick-Signature`` header over a raw body (``Webhook.verify``, ``Project.verify_request``);
    the body, as bytes, once it verifies."""
    body = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    header = _header(headers, SIGNATURE_HEADER)
    if not header:
        raise WebhookSignatureError(
            f"The request has no {SIGNATURE_HEADER} header.",
            next_step="Pass the request's headers as they arrived; answer 400 if it really has none.",
        )
    timestamp, signatures = _parse_signature(header)
    if timestamp is None or not signatures:
        raise WebhookSignatureError(
            f"The {SIGNATURE_HEADER} header isn't t=<timestamp>,v1=<signature>.",
            details={"header": header},
        )
    skew = abs(time.time() - timestamp)
    if skew > tolerance_s:
        raise WebhookSignatureError(
            f"The delivery was signed {int(skew)}s from now, more than the {tolerance_s}s allowed.",
            next_step="Check your server's clock; a replayed delivery is refused on purpose.",
            details={"timestamp": timestamp, "tolerance_s": tolerance_s},
        )
    signed = f"{timestamp}.".encode("utf-8") + body
    secrets = [secret] if isinstance(secret, str) else list(secret)
    expected = [hmac.new(s.encode("utf-8"), signed, hashlib.sha256).hexdigest() for s in secrets]
    if not any(hmac.compare_digest(e, s) for e in expected for s in signatures):
        raise WebhookSignatureError(
            "No signature matches the body with this secret.",
            next_step="Verify the raw body (not re-serialized JSON) with the webhook's current secret.",
        )
    return body


class Webhook(_Object):
    """An endpoint on your server that receives events, signed with its secret.
    One created for a user (inside ``as_user``, or with ``user=``) receives
    only that user's events; your account's own receive every event, your
    users' included."""

    _repr_keys = ("id", "url", "status")

    id: str = field("id")
    url: str = field("url")
    events: List[str] = field("events", doc="The event types it receives; ``*`` matches the rest of a name.")
    enabled: bool = field("enabled")
    status: str = field(
        "status", doc="``healthy``, ``failing`` (its latest deliveries failed; retries continue) or ``disabled``.",
    )
    description: Optional[str] = field("description")
    success_rate_24h: Optional[float] = field(
        "success_rate_24h", doc="The share of attempts in the last 24 hours your server answered 2xx (None if none).",
    )
    last_failure: Optional[Dict[str, Any]] = field(
        "last_failure", doc="The latest failed attempt: ``at``, ``response_status`` and ``error`` (None if none).",
    )
    user_id: Optional[str] = field("user_id", doc="The user whose events it receives (None: every event).")
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    @property
    def secret(self) -> Optional[str]:
        """The signing secret (``nk_whsec_...``), present on the object that created the
        webhook (``create``, or ``from_name`` when it created one), ``rotate_secret`` or
        ``reveal_secret``; any other read leaves it out."""
        return self._sync_raw().get("secret")

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls,
        url: str,
        *,
        events: Sequence[str],
        description: Optional[str] = None,
        allow_existing: bool = False,
        user: Any = AMBIENT,
        idempotency_key: Optional[str] = None,
        client: Optional[Client] = None,
    ) -> "Webhook":
        """Start delivering ``events`` (type names; ``operation.*`` or ``*`` for
        more at once) to ``url``, an ``https`` address your server answers. A scope has one
        webhook per address: another raises ``noclick.Conflict`` with ``existing_id``, or with
        ``allow_existing=True`` returns the one already there, as it is (its events don't change,
        and its ``secret`` isn't shown: ``reveal_secret()`` reads it).

        Returns:
            The new webhook. Its ``secret`` is shown this once: store it where your receiver reads it.

        Usage:
            Receive what your code waits on::

                hook = noclick.Webhook.create(
                    "https://api.yourco.test/noclick/events",
                    events=["operation.succeeded", "operation.failed", "human.answered"],
                    description="Production receiver",
                )
                print(hook.secret)   # nk_whsec_...: shown once

            Only one user's events::

                with noclick.as_user("acme"):
                    hook = noclick.Webhook.create("https://api.yourco.test/acme/events", events=["connection.*"])
        """
        scope = resolve_scope(user)
        raw = await cls._create_named(
            "/v1/webhooks", compact(url=url, events=list(events), description=description),
            allow_existing=allow_existing, user=scope, client=client, key="url", idempotency_key=idempotency_key,
        )
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls,
        url: str,
        *,
        create_if_missing: bool = False,
        events: Optional[Sequence[str]] = None,
        description: Optional[str] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Webhook":
        """A lazy reference to the webhook delivering to ``url`` in the current (or given)
        user; ``url`` names it, since a scope has one webhook per address. Given ``events`` or
        ``description``, it gets the webhook and sets them, on every run, so a deploy can own its
        endpoint. ``create_if_missing=True`` creates it with ``events`` (and ``description``) when
        there's none; without it, a missing webhook raises ``noclick.NotFound``. Each run with
        fields is a write: do it at startup or in a setup script, not per request.

        Returns:
            A webhook that loads (or is created, or has your fields set) the first time it's used.
            When this call created it, ``secret`` holds its signing secret; otherwise read it with
            ``reveal_secret()``.

        Usage:
            Own your receiver's endpoint in code, and read its secret on every start::

                hook = noclick.Webhook.from_name(
                    "https://api.yourco.test/noclick/events",
                    create_if_missing=True,
                    events=["operation.succeeded", "operation.failed", "human.answered"],
                )
                secret = hook.secret or hook.reveal_secret()
        """
        hook = cls._new(hints={"url": url}, client=client, user=user)
        if create_if_missing and not events:
            raise ValueError("Webhook.from_name(create_if_missing=True) needs events=")
        hook._define(compact(url=url, events=None if events is None else list(events), description=description),
                     create_if_missing=create_if_missing, key="url")
        return hook

    @classmethod
    def from_id(cls, webhook_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Webhook":
        """A lazy reference to a webhook by id.

        Returns:
            A webhook that loads the first time you read a field. Nothing is sent yet.

        Usage::

            hook = noclick.Webhook.from_id("5e2d8c1a-7b4f-4e93-a6d0-3c9f1b2e8a54")
            print(hook.status, hook.success_rate_24h)
        """
        return cls._new(hints={"id": webhook_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, webhook_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Webhook":
        """Load a webhook by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The webhook, loaded (without its secret).

        Usage::

            hook = noclick.Webhook.get("5e2d8c1a-7b4f-4e93-a6d0-3c9f1b2e8a54")
            print(hook.url, hook.events, hook.status)
        """
        hook = cls.from_id(webhook_id, client=client, user=user)
        await hook._ensure()
        return hook

    @synced
    @classmethod
    async def list(
        cls, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Webhook"]:
        """Your account's webhooks (or the current user's, or those ``user_filter`` covers).

        Returns:
            Every matching webhook, newest first, fetched page by page.

        Usage::

            for hook in noclick.Webhook.list():
                print(hook.url, hook.status, hook.last_failure)

            everyone = noclick.Webhook.list(user_filter=noclick.ALL_USERS)
        """
        return await list_all(
            "/v1/webhooks", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of webhooks; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the webhooks and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Webhook.list_page(limit=20)
            for hook in page.data:
                print(hook.url, hook.status)
        """
        return await list_page(
            "/v1/webhooks", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    def _path(self) -> str:
        return f"/v1/webhooks/{self._known('id')}"

    async def _load(self) -> Dict[str, Any]:
        if self._known("id"):
            return await self._request("GET", self._path())
        url = self._hints["url"]
        page = await self._request("GET", "/v1/webhooks", params={"url": url}) or {}
        # This scope's own endpoint: an account webhook never stands in for a user's.
        rows = [row for row in page.get("data") or []
                if row.get("url") == url and bool(row.get("user_id")) == bool(self._scope)]
        if rows:
            return await self._converge(rows[0])
        if not self._creates:
            raise NotFound(f"No webhook delivers to {url!r}.",
                           next_step="Create it with noclick.Webhook.create(...) or pass create_if_missing=True.",
                           details={"url": url})
        try:
            return await self._request("POST", "/v1/webhooks", json=self._create_with)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._converge(await self._request("GET", f"/v1/webhooks/{exc.existing_id}"))

    async def _converge(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Set the fields ``from_name`` was given on an existing webhook."""
        if self._create_with is None:
            return raw
        changes = {k: v for k, v in self._create_with.items() if k != "url" and raw.get(k) != v}
        return await self._request("PATCH", f"/v1/webhooks/{raw['id']}", json=changes) if changes else raw

    async def _id_path(self) -> str:
        """This webhook's route; a reference by url is looked up (or created) first."""
        if not self._known("id"):
            await self._ensure()
        return self._path()

    # --- changes ---------------------------------------------------------

    @synced
    async def update(
        self, *, url: Any = UNSET, events: Any = UNSET, enabled: Any = UNSET, description: Any = UNSET,
    ) -> "Webhook":
        """Change where it delivers, what it receives, or pause it
        (``enabled=False``: events that happen meanwhile are not delivered later).
        A field you leave out is unchanged.

        Returns:
            This webhook, updated.

        Usage::

            hook = noclick.Webhook.from_id("5e2d8c1a-7b4f-4e93-a6d0-3c9f1b2e8a54")
            hook.update(events=["operation.*", "human.*"])
            hook.update(enabled=False)   # pause it
        """
        changes = {
            k: (list(v) if k == "events" else v)
            for k, v in dict(url=url, events=events, enabled=enabled, description=description).items()
            if v is not UNSET
        }
        self._raw = await self._request("PATCH", await self._id_path(), json=changes)
        return self

    @synced
    async def delete(self) -> None:
        """Delete the webhook; deliveries still retrying stop.

        Usage::

            noclick.Webhook.from_id("5e2d8c1a-7b4f-4e93-a6d0-3c9f1b2e8a54").delete()
        """
        await self._request("DELETE", await self._id_path())

    @synced
    async def rotate_secret(self, *, grace_s: Optional[int] = None) -> str:
        """Replace the signing secret. For ``grace_s`` (default a day, at most 7
        days) each delivery is signed with both, so deliveries keep verifying while
        you deploy the new one; pass ``grace_s=0`` if the old one leaked.

        Returns:
            The new secret, shown this once (also on ``hook.secret``).

        Usage::

            hook = noclick.Webhook.from_id("5e2d8c1a-7b4f-4e93-a6d0-3c9f1b2e8a54")
            secret = hook.rotate_secret()
            print(secret)   # store it with your receiver, then deploy
        """
        self._raw = await self._request("POST", f"{await self._id_path()}/rotate_secret", json=compact(grace_s=grace_s))
        return self._raw.get("secret") or ""

    @synced
    async def reveal_secret(self) -> str:
        """Read the current signing secret, so a receiver that starts from code (or a
        webhook ``from_name`` found rather than created) can verify deliveries. Needs
        a key with the ``webhooks:reveal`` scope, which full access leaves out; every
        reveal is recorded with the key that made it.

        Returns:
            The secret (``nk_whsec_...``), also on ``hook.secret``.

        Usage::

            hook = noclick.Webhook.from_name("https://api.yourco.test/noclick/events")
            secret = hook.reveal_secret()
        """
        revealed = await self._request("GET", f"{await self._id_path()}/secret")
        self._raw = {**(self._raw or {}), "secret": revealed.get("secret")}
        return revealed.get("secret") or ""

    # --- deliveries ------------------------------------------------------

    @synced
    async def test(self, event_type: str = "operation.succeeded") -> WebhookDelivery:
        """Send a sample event of ``event_type`` now, signed like a real one, and
        wait up to 10 seconds for your server's answer. It isn't retried and isn't
        recorded in ``Event.list``.

        Returns:
            The delivery: its ``status`` (``succeeded`` or ``failed``), ``response_status`` and ``response_body``.

        Usage::

            hook = noclick.Webhook.from_id("5e2d8c1a-7b4f-4e93-a6d0-3c9f1b2e8a54")
            sent = hook.test("human.answered")
            print(sent.status, sent.response_status, sent.duration_ms)
        """
        return WebhookDelivery._from(
            await self._request("POST", f"{await self._id_path()}/test", json={"event_type": event_type}))

    @synced
    async def deliveries(
        self, *, status: Union[None, str, Sequence[str]] = None, event: Any = None, limit: Optional[int] = None,
    ) -> List[WebhookDelivery]:
        """Deliveries newest first (the last 30 days), optionally only those with
        ``status`` (``pending``, ``retrying``, ``succeeded``, ``failed``) or of one
        ``event`` (an ``Event`` or id).

        Returns:
            Every matching delivery, fetched page by page (or the first ``limit``).

        Usage::

            hook = noclick.Webhook.from_id("5e2d8c1a-7b4f-4e93-a6d0-3c9f1b2e8a54")
            for delivery in hook.deliveries(status=["retrying", "failed"], limit=20):
                print(delivery.event_type, delivery.attempts, delivery.response_status, delivery.next_retry_at)
        """
        event_id = event._known("id") if isinstance(event, Event) else event
        rows = await paginate(
            self._api, f"{await self._id_path()}/deliveries", params={"status": csv(status), "event_id": event_id},
            user=self._call_scope(), limit=limit,
        )
        return [WebhookDelivery._from(row) for row in rows]

    @synced
    async def redeliver(self, delivery: Union[str, WebhookDelivery]) -> WebhookDelivery:
        """Send a delivery's event again now (the same event id, so a receiver that
        ignores repeats stays correct), whatever its status.

        Returns:
            The delivery, with this attempt counted in ``attempts`` and its outcome in ``status``.

        Usage:
            Once your receiver is fixed, send what it missed::

                hook = noclick.Webhook.from_id("5e2d8c1a-7b4f-4e93-a6d0-3c9f1b2e8a54")
                for missed in hook.deliveries(status="failed"):
                    hook.redeliver(missed)
        """
        response = await self._request("POST", f"{await self._id_path()}/deliveries/{_delivery_id(delivery)}/redeliver")
        return WebhookDelivery._from(response)

    # --- receiving -------------------------------------------------------

    @staticmethod
    def verify(
        payload: Union[bytes, str],
        headers: Mapping[str, Any],
        secret: Union[str, Sequence[str]],
        *,
        tolerance_s: int = 300,
    ) -> Event:
        """Check a delivery in your receiver: ``payload`` is the raw body exactly
        as it arrived (not parsed and re-serialized), ``headers`` its headers (any
        mapping; the name is matched whatever its case) and ``secret`` the
        webhook's, or a list of secrets while you rotate. The ``NoClick-Signature``
        header is ``t=<unix seconds>,v1=<hex>``, where the hex is HMAC-SHA256 of
        ``"<t>.<body>"`` keyed with the secret. A timestamp more than
        ``tolerance_s`` from now is refused, so a captured delivery can't be
        replayed later. It sends nothing.

        Raises ``noclick.WebhookSignatureError`` when the header is missing or
        malformed, the timestamp is outside the tolerance, or no signature matches.

        Returns:
            The event the body carries, ready to act on.

        Usage:
            In a Flask receiver, answer 400 to anything that doesn't verify, and 2xx
            quickly (do slow work after)::

                import os
                from flask import Flask, request

                app = Flask(__name__)

                @app.post("/noclick/events")
                def noclick_events():
                    try:
                        event = noclick.Webhook.verify(request.get_data(), request.headers, os.environ["NOCLICK_WEBHOOK_SECRET"])
                    except noclick.WebhookSignatureError:
                        return "", 400
                    if event.type == "human.answered":
                        print(event.data["answer"])
                    return "", 204

            While you rotate, accept both secrets::

                import os

                secrets =[os.environ["NOCLICK_WEBHOOK_SECRET"], os.environ["NOCLICK_WEBHOOK_SECRET_OLD"]]
                event = noclick.Webhook.verify(request.get_data(), request.headers, secrets)
        """
        body = verify_signature(payload, headers, secret, tolerance_s=tolerance_s)
        try:
            raw = json.loads(body)
        except ValueError as exc:
            raise WebhookSignatureError("The signed body isn't JSON.") from exc
        return Event._new(raw=raw)
