"""Dicts: a key-value store for small state that code and agents share.

    seen = noclick.Dict.from_name("processed-orders", create_if_missing=True)
    if "o_1841" not in seen:
        seen["o_1841"] = {"status": "refunded"}
    print(seen.increment("refunds-today"))

Keys are strings and values are JSON (a dict, list, string, number, bool or
``None``), never pickled, so a value your Python code writes reads the same from
TypeScript, an agent or the console. A dict works like Python's own: ``d[key]``,
``d[key] = value``, ``key in d``, ``del d[key]``, ``len(d)`` and iterating its
keys, plus expiry (``ttl_s``), locks (``put_if_absent``) and atomic counters
(``increment``). Each of those reads or writes the API, so the ``.aio`` forms of
``get``, ``put`` and ``pop`` are how async code does the same.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from typing import Any, AsyncIterator, Iterator, List, Mapping, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import Page, _Object, compact, fetch_page, field, list_all, list_page, paginate, parse_time
from ._sync import _iterate_sync, run_sync, synced
from ._scope import AMBIENT, resolve_scope
from .exceptions import Conflict, NotFound
from .export import ExportBundle
from .operation import Operation, register_result
from .trash import TrashItem, trashed

# "No default given": Ellipsis, which no JSON value can be.
_MISSING = ...


def _key(key: Any) -> str:
    if not isinstance(key, str) or not key:
        raise TypeError(f"A Dict key is a non-empty string, not {key!r}.")
    return key


def _json(value: Any) -> Any:
    """The value as it's stored: JSON, checked here so a bad value fails before it's sent."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"A Dict stores JSON values (dict, list, str, int, float, bool, None): {exc}. "
            "Convert it first, a datetime to an ISO string say."
        ) from None
    return value


def _missing_key(exc: NotFound, key: str) -> bool:
    """A 404 about the key (the dict exists) rather than about the dict."""
    return exc.details.get("key") == key


@dataclass(frozen=True)
class DictItem:
    """One key of a dict as ``items()`` reads it: its ``key`` and ``value``, when it
    ``expires_at`` (None if it doesn't), when it was last written (``updated_at``)
    and ``size_bytes``, the size of its value as JSON. It unpacks like a pair, so
    ``for key, value in d.items()`` and ``dict(d.items())`` work as they do on a
    Python dict. A listing from ``keys()`` carries no values."""

    key: str
    value: Any = dc_field(repr=False)
    expires_at: Any
    updated_at: Any
    size_bytes: Optional[int]
    raw: dict[str, Any] = dc_field(repr=False)

    def __iter__(self) -> Iterator[Any]:
        return iter((self.key, self.value))

    @classmethod
    def _from(cls, raw: Any) -> "DictItem":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            raw.get("key") or "", raw.get("value"), parse_time(raw.get("expires_at")), parse_time(raw.get("updated_at")),
            raw.get("size_bytes"), raw,
        )


@dataclass(frozen=True)
class DictChange:
    """One write to a dict, from its history: ``op`` is ``created`` (the key was new), ``changed`` or
    ``deleted``, and ``previous`` the value it replaced (None for a new key), which expired at
    ``previous_expires_at``. A key changed again within a minute adds none, so a busy key keeps one a minute."""

    id: str
    key: str
    op: str
    previous: Any = dc_field(repr=False)
    previous_expires_at: Any
    at: Any
    raw: dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: dict) -> "DictChange":
        return cls(raw["id"], raw["key"], raw["op"], raw.get("previous"), parse_time(raw.get("previous_expires_at")),
                   parse_time(raw.get("at")), raw)


def _read_export(result: Any, op: Operation) -> ExportBundle:
    return ExportBundle._from(result)


register_result("dict.export", _read_export)


class Dict(_Object):
    """A key-value store: string keys, JSON values, optional expiry per key.

    Read and write it like a Python dict (``d[key]``, ``d[key] = value``,
    ``key in d``, ``del d[key]``, ``len(d)``, ``for key in d``); a missing key
    raises ``KeyError`` there and ``get`` returns a default instead. Each of those
    is a call to the API, never a local copy, so two processes see each other's
    writes at once. A dict object is always truthy, so ``if seen:`` never makes a
    call. ``key_count`` and ``size_bytes`` are as of the last load; ``len(d)``
    reads the count fresh."""

    _repr_keys = ("id", "name")

    id: str = field("id")
    name: str = field("name")
    key_count: Optional[int] = field("key_count", doc="How many keys it holds (expired keys are gone).")
    size_bytes: Optional[int] = field("size_bytes", doc="The size of its keys and values as JSON.")
    used_by: List[dict[str, Any]] = field(
        "used_by", doc="The apps that bind it: ``kind`` (``project``), ``id``, ``name`` and the ``binding`` name.",
    )
    region: Optional[str] = field(
        "region", doc="The region it keeps its data in (``noclick.regions()``), fixed when it was created.",
    )
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[dict[str, Any]] = None
        super()._init(**kwargs)

    @property
    def console_url(self) -> Optional[str]:
        """This dict in the developer console, with its key browser (None off the hosted API)."""
        base = self._api.console_url("resources", "dicts")
        return f"{base}?dict={quote(str(self._known('id')), safe='')}" if base and self._known("id") else base

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls, name: str, *, region: Optional[str] = None, allow_existing: bool = False, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Dict":
        """Create a dict called ``name`` (1-64 letters, digits and ``. _ -``),
        unique to its user (a taken name raises ``noclick.Conflict`` with
        ``existing_id``, or with ``allow_existing=True`` returns the dict already there, as it
        is). ``region`` (``noclick.regions(kind="dict")``) is where its keys are kept, for good;
        without one, your account's default region, else
        ``us-east``. Dicts are kept in ``us-east`` only for now: another region, or
        a default region elsewhere, raises ``noclick.InvalidRequest`` naming it.

        Returns:
            The new dict, empty.

        Usage:
            A dict of the account's own::

                seen = noclick.Dict.create("processed-orders")

            Created inside ``as_user``, it belongs to (and bills) that user::

                with noclick.as_user("acme"):
                    flags = noclick.Dict.create("feature-flags")
        """
        scope = resolve_scope(user)
        raw = await cls._create_named("/v1/dicts", compact(name=name, region=region), allow_existing=allow_existing,
                                      user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls, name: str, *, create_if_missing: bool = False, region: Optional[str] = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Dict":
        """A lazy reference to the dict called ``name`` in the current (or given)
        user. With ``create_if_missing=True`` it's created the first time it's used,
        in ``region`` (as ``create``).

        Inside a deployed app (signed in by its deployment) the name is looked up in the app's own
        namespace for the environment the code runs in, and one made there is the app's: a name bound to
        the app by hand wins, and in a preview of an app whose ``preview_resources`` is ``branch`` the
        branch gets its own copy of the keys the first time it uses it, so a preview never changes
        production's data.

        Returns:
            A dict that loads (or is created) on first use. Nothing is sent yet.

        Usage:
            Name it in your code, so the first run creates it::

                seen = noclick.Dict.from_name("processed-orders", create_if_missing=True)
                if "o_1841" not in seen:
                    seen["o_1841"] = {"status": "refunded"}

            A user's own, for per-customer settings::

                with noclick.as_user("acme"):
                    flags = noclick.Dict.from_name("feature-flags", create_if_missing=True)
                    print(flags.get("new-checkout", default=False))
        """
        store = cls._new(hints={"name": name}, client=client, user=user)
        if create_if_missing:
            store._create_with = compact(name=name, region=region)
        return store

    @classmethod
    def from_id(cls, dict_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Dict":
        """A lazy reference to a dict by id. There's no ``Dict.get(id)``, since
        ``get`` reads a key: call ``hydrate()`` on this to load it now.

        Returns:
            A dict that loads the first time you use it. Nothing is sent yet.

        Usage::

            seen = noclick.Dict.from_id("5b8e2c71-4d9a-4f36-a0e2-7c1b9d3f6a58").hydrate()
            print(seen.name, seen.key_count)
        """
        return cls._new(hints={"id": dict_id}, client=client, user=user)

    @synced
    @classmethod
    async def list(
        cls, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Dict"]:
        """The current user's dicts (the account's own outside ``as_user``, or
        those ``user_filter`` covers).

        Returns:
            Every matching dict, newest first, fetched page by page.

        Usage:
            Your account's dicts::

                for store in noclick.Dict.list():
                    print(store.name, store.key_count, store.size_bytes)

            Every user's::

                every = noclick.Dict.list(user_filter=noclick.ALL_USERS)
        """
        return await list_all(
            "/v1/dicts", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of dicts; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the dicts and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Dict.list_page(limit=50, user_filter=noclick.ALL_USERS)
            for store in page.data:
                print(store.user_id, store.name, store.key_count)
        """
        return await list_page(
            "/v1/dicts", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    # --- hydration -------------------------------------------------------

    async def _load(self) -> dict[str, Any]:
        dict_id = self._known("id")
        if dict_id:
            return await self._request("GET", f"/v1/dicts/{dict_id}")
        name = self._hints["name"]
        found = await self._in_app("dict", name, self._create_with)
        if found is not None:
            return found
        page = await self._request("GET", "/v1/dicts", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        if rows:
            return rows[0]
        if self._create_with is None:
            raise NotFound(
                f"No dict is named {name!r}.",
                next_step="Create it with noclick.Dict.create(...) or pass create_if_missing=True.",
                details={"name": name, "kind": "dict"},
            )
        try:
            return await self._request("POST", "/v1/dicts", json=self._create_with)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._request("GET", f"/v1/dicts/{exc.existing_id}")

    async def _url(self, suffix: str = "") -> str:
        """This dict's route; a reference by name is looked up (or created) first."""
        if not self._known("id"):
            await self._ensure()
        return f"/v1/dicts/{self._known('id')}{suffix}"

    async def _item_url(self, key: str, suffix: str = "") -> str:
        return await self._url(f"/items/{quote(_key(key), safe='')}{suffix}")

    # --- Python's dict protocol ------------------------------------------

    def __bool__(self) -> bool:
        return True

    def __getitem__(self, key: str) -> Any:
        """Read a key; a missing (or expired) one raises ``KeyError``.

        Returns:
            The value, as the JSON it was stored as.

        Usage::

            flags = noclick.Dict.from_name("feature-flags")
            if flags["new-checkout"]:
                print("New checkout is on")
        """
        value = run_sync(self.get.aio(key, _MISSING))
        if value is _MISSING:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        run_sync(self.put.aio(key, value))

    def __delitem__(self, key: str) -> None:
        if not run_sync(self.remove.aio(key)):
            raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and run_sync(self.get.aio(key, _MISSING)) is not _MISSING

    def __len__(self) -> int:
        self._raw = run_sync(self._load())
        return int(self._raw.get("key_count") or 0)

    def __iter__(self) -> Iterator[str]:
        return _iterate_sync(self._walk(prefix=None, keys_only=True, limit=None))

    # --- reads -----------------------------------------------------------

    @synced
    async def get(self, key: str, default: Any = None) -> Any:
        """Read a key, or ``default`` when it's missing or expired.

        Returns:
            The value as the JSON it was stored as, or ``default``.

        Usage::

            flags = noclick.Dict.from_name("feature-flags")
            if flags.get("new-checkout", default=False):
                print("New checkout is on")
        """
        try:
            raw = await self._request("GET", await self._item_url(key)) or {}
        except NotFound as exc:
            if _missing_key(exc, key):
                return default
            raise
        return raw.get("value")

    async def _walk(self, *, prefix: Optional[str], keys_only: bool, limit: Optional[int]) -> AsyncIterator[Any]:
        """Each key (or ``DictItem``) in key order, page by page."""
        params = compact(prefix=prefix, view="keys" if keys_only else None)
        path, cursor, count = await self._url("/items"), None, 0
        while True:
            size = None if limit is None else min(limit - count, 100)
            page = await fetch_page(self._api, path, params=params, user=self._call_scope(), cursor=cursor, limit=size)
            for row in page.data:
                yield row.get("key") if keys_only else DictItem._from(row)
                count += 1
                if limit is not None and count >= limit:
                    return
            if not page.next_cursor:
                return
            cursor = page.next_cursor

    @synced
    async def keys(self, prefix: Optional[str] = None, *, limit: Optional[int] = None) -> List[str]:
        """The keys, in order, or those that start with ``prefix``.

        Returns:
            Every matching key (or the first ``limit``), fetched page by page.

        Usage::

            seen = noclick.Dict.from_name("processed-orders")
            for key in seen.keys(prefix="lock:"):
                print(key)
        """
        return [key async for key in self._walk(prefix=prefix, keys_only=True, limit=limit)]

    @synced
    async def items(self, prefix: Optional[str] = None, *, limit: Optional[int] = None) -> List[DictItem]:
        """The keys and their values, in key order, or those whose key starts with ``prefix``.

        Returns:
            A ``DictItem`` per key (or for the first ``limit``): it unpacks as ``key, value`` and
            also carries ``expires_at``, ``updated_at`` and ``size_bytes``.

        Usage:
            Read them like a Python dict's items::

                seen = noclick.Dict.from_name("processed-orders")
                for key, value in seen.items(prefix="o_", limit=100):
                    print(key, value)

            See what's about to expire::

                seen = noclick.Dict.from_name("processed-orders")
                for item in seen.items(prefix="lock:"):
                    print(item.key, item.expires_at)
        """
        return [item async for item in self._walk(prefix=prefix, keys_only=False, limit=limit)]

    @synced
    async def items_page(
        self, prefix: Optional[str] = None, *, cursor: Optional[str] = None, limit: Optional[int] = None,
    ) -> Page:
        """One page of items in key order; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds ``DictItem``s and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            seen = noclick.Dict.from_name("processed-orders")
            page = seen.items_page(prefix="o_", limit=50)
            for key, value in page.data:
                print(key, value)
        """
        page = await fetch_page(
            self._api, await self._url("/items"), params=compact(prefix=prefix), user=self._call_scope(),
            cursor=cursor, limit=limit,
        )
        return Page([DictItem._from(row) for row in page.data], page.next_cursor)

    # --- writes ----------------------------------------------------------

    @synced
    async def put(self, key: str, value: Any, *, ttl_s: Optional[int] = None) -> None:
        """Write a key. With ``ttl_s`` it expires that many seconds from now;
        without, it stays until it's removed (and loses any expiry it had).
        ``d[key] = value`` does the same with no expiry.

        Usage:
            Remember an order you've handled::

                seen = noclick.Dict.from_name("processed-orders", create_if_missing=True)
                seen.put("o_1841", {"status": "refunded", "by": "support-bot"})

            A cache entry for a day::

                cache = noclick.Dict.from_name("rates-cache", create_if_missing=True)
                cache.put("usd:eur", 0.92, ttl_s=86400)
        """
        await self._request("PUT", await self._item_url(key), json={"value": _json(value), **compact(ttl_s=ttl_s)})

    @synced
    async def put_if_absent(self, key: str, value: Any, *, ttl_s: Optional[int] = None) -> bool:
        """Write a key only if it isn't there (an expired key counts as absent), in
        one atomic step: of any number of callers racing, exactly one wins. That
        makes it a lock (with ``ttl_s``, so a crashed holder's lock frees itself)
        or a check that something runs once.

        Returns:
            ``True`` if this call wrote it, ``False`` if the key was already there.

        Usage:
            Only one worker runs the nightly job; the lock frees itself after five minutes::

                locks = noclick.Dict.from_name("locks", create_if_missing=True)
                if locks.put_if_absent("nightly-report", "worker-3", ttl_s=300):
                    print("This worker runs it")

            Handle each webhook delivery once, however often it's retried::

                seen = noclick.Dict.from_name("processed-orders", create_if_missing=True)
                if seen.put_if_absent("evt_9f2c", True, ttl_s=7 * 86400):
                    print("First time: handle it")
        """
        body = {"value": _json(value), "if_absent": True, **compact(ttl_s=ttl_s)}
        raw = await self._request("PUT", await self._item_url(key), json=body) or {}
        return bool(raw.get("written"))

    @synced
    async def increment(self, key: str, by: int = 1, *, ttl_s: Optional[int] = None) -> int:
        """Add ``by`` (which may be negative) to a counter, atomically: concurrent
        increments never lose a count. A missing key starts at 0; ``ttl_s`` sets
        its expiry only when this call creates it, so a counter per window
        (``visits:2026-09-28``) cleans itself up. A key holding anything but an
        integer raises ``noclick.InvalidRequest``.

        Returns:
            The counter's value after this increment.

        Usage:
            Count, and read the total in the same call::

                stats = noclick.Dict.from_name("stats", create_if_missing=True)
                total = stats.increment("refunds-today")

            A rate limit: at most 100 calls per customer per hour::

                limits = noclick.Dict.from_name("rate-limits", create_if_missing=True)
                if limits.increment("calls:acme:2026-09-28T14", ttl_s=3600) > 100:
                    print("Over the limit; try again next hour")
        """
        if isinstance(by, bool) or not isinstance(by, int):
            raise TypeError(f"increment adds an int, not {by!r}.")
        raw = await self._request("POST", await self._item_url(key, "/increment"), json=compact(by=by, ttl_s=ttl_s)) or {}
        return int(raw["value"])

    @synced
    async def update(self, items: Mapping[str, Any], *, ttl_s: Optional[int] = None) -> None:
        """Write up to 1,000 keys in one call, all of them or none; ``ttl_s``
        applies to each.

        Usage::

            flags = noclick.Dict.from_name("feature-flags", create_if_missing=True)
            flags.update({"new-checkout": True, "beta-search": False, "max-upload-mb": 50})
        """
        wire = [{"key": _key(k), "value": _json(v), **compact(ttl_s=ttl_s)} for k, v in items.items()]
        await self._request("POST", await self._url("/items"), json={"items": wire})

    @synced
    async def pop(self, key: str, default: Any = _MISSING) -> Any:
        """Remove a key and return its value. A missing key returns ``default``,
        or raises ``KeyError`` when you gave none, like a Python dict's ``pop``.

        Returns:
            The value the key held, or ``default``.

        Usage::

            jobs = noclick.Dict.from_name("pending-exports", create_if_missing=True)
            job = jobs.pop("acme", None)
            if job is not None:
                print("Exporting", job)
        """
        try:
            raw = await self._request("DELETE", await self._item_url(key)) or {}
        except NotFound as exc:
            if not _missing_key(exc, key):
                raise
            if default is _MISSING:
                raise KeyError(key) from None
            return default
        return raw.get("value")

    @synced
    async def remove(self, key: str) -> bool:
        """Remove a key if it's there. ``del d[key]`` does the same and raises
        ``KeyError`` on a missing key; this is its form that doesn't, with an
        ``.aio`` for async code.

        Returns:
            Whether the key was there to remove.

        Usage::

            locks = noclick.Dict.from_name("locks")
            locks.remove("nightly-report")   # done: let the next run take it
        """
        try:
            await self._request("DELETE", await self._item_url(key))
        except NotFound as exc:
            if _missing_key(exc, key):
                return False
            raise
        return True

    @synced
    async def clear(self) -> Operation:
        """Remove every key. The dict itself stays, empty.

        Returns:
            The clear's operation: ``undo()`` puts back every key it removed that nothing has written since.

        Usage::

            cache = noclick.Dict.from_name("rates-cache")
            cleared = cache.clear()
            cleared.undo()   # the keys are back
        """
        raw = await self._request("POST", await self._url("/clear"))
        return Operation.from_id(raw["operation_id"], client=self._client)

    @synced
    async def history(self, key: Optional[str] = None, *, limit: Optional[int] = None) -> List[DictChange]:
        """Its writes of the last 30 days, newest first, each with the value it replaced; ``key`` keeps one key's.

        Returns:
            Each change.

        Usage::

            prefs = noclick.Dict.from_name("prefs")
            for change in prefs.history("theme"):
                print(change.at, change.op, change.previous)
        """
        rows = await paginate(self._api, await self._url("/history"), params={"key": key},
                              user=self._call_scope(), limit=limit)
        return [DictChange._from(row) for row in rows]

    @synced
    async def restore_change(self, change: Any) -> None:
        """Put the key back as ``change`` found it: the value it replaced, or gone, when the change created
        the key. A value that has expired since raises ``noclick.Conflict``.

        Usage:
            Undo a bad write::

                prefs = noclick.Dict.from_name("prefs")
                prefs["theme"] = "neon"
                prefs.restore_change(prefs.history("theme")[0])
        """
        change_id = change.id if isinstance(change, DictChange) else change
        await self._request("POST", await self._url(f"/history/{change_id}/restore"))

    # --- lifecycle -------------------------------------------------------

    @synced
    async def export(self) -> Operation:
        """Export every key as it stands at one moment, as JSON Lines: one
        ``{"key", "value", "expires_at"}`` per line, in key order.

        Returns:
            An operation whose ``wait()`` gives an ``ExportBundle``: a zip at ``url`` holding the file.

        Usage::

            seen = noclick.Dict.from_name("processed-orders")
            bundle = seen.export().wait()
            print(bundle.url)
        """
        payload = await self._request("POST", await self._url("/export"))
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="dict.export", reader=_read_export,
        )

    @synced
    async def delete(self) -> TrashItem:
        """Delete the dict and every key in it: it goes to the trash, restorable for 30 days. One an app
        binds goes to the trash too: the app keeps its binding, reaching nothing until you restore the dict.

        Returns:
            Its ``TrashItem``: ``restore()`` puts it back, keys and all.

        Usage::

            cache = noclick.Dict.from_name("rates-cache")
            item = cache.delete()
            item.restore()   # it's back
        """
        raw = await self._request("DELETE", await self._url())
        return trashed(raw, client=self._client, user=self._call_scope())
