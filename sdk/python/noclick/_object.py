"""Live API objects: ``User``, ``Agent``, ``Operation`` and the rest.

An object can exist before the server has been asked about it
(``User.from_id(...)``, ``Agent.from_name(...)``,
``Operation.from_id(...)``). It hydrates on first need: a method call, or a
property the local hints can't answer. ``hydrate()`` does it explicitly.
An object you got while acting for a user keeps acting for that user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Generic, List, Optional, Sequence, Tuple, TypeVar, Union

from ._client import Client, resolve_client
from ._sync import run_sync, synced
from ._scope import AMBIENT, resolve_scope, user_filter_param
from .exceptions import Conflict, Error, NotFound

T = TypeVar("T", bound="_Object")
R = TypeVar("R")


def parse_time(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return value


def required_number(obj: Dict[str, Any], key: str) -> Union[int, float]:
    """A number the API always sends; its absence is a malformed response, never a zero."""
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Error(f"The response is missing the number `{key}`.", details={"field": key, "value": value})
    return value


def compact(**fields: Any) -> Dict[str, Any]:
    return {k: v for k, v in fields.items() if v is not None}


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()


def field(key: str, convert: Optional[Callable[[Any], Any]] = None, doc: Optional[str] = None) -> property:
    def getter(self: "_Object") -> Any:
        if self._raw is not None and key in self._raw:
            value = self._raw[key]
        elif key in self._hints:
            value = self._hints[key]
        else:
            value = self._sync_raw().get(key)
        return convert(value) if convert is not None and value is not None else value

    return property(getter, doc=doc or f"The object's ``{key}``.")


class _Object:
    _raw: Optional[Dict[str, Any]]
    _hints: Dict[str, Any]
    _client: Optional[Client]
    _scope: Any

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError(
            f"{type(self).__name__} objects come from its classmethods "
            f"(create, get, list, from_...), not the constructor."
        )

    @classmethod
    def _new(
        cls: type[T],
        *,
        raw: Optional[Dict[str, Any]] = None,
        hints: Optional[Dict[str, Any]] = None,
        client: Optional[Client] = None,
        user: Any = AMBIENT,
    ) -> T:
        obj = cls.__new__(cls)
        obj._init(raw=raw, hints=hints, client=client, user=user)
        return obj

    def _init(
        self,
        *,
        raw: Optional[Dict[str, Any]] = None,
        hints: Optional[Dict[str, Any]] = None,
        client: Optional[Client] = None,
        user: Any = AMBIENT,
    ) -> None:
        self._raw = raw
        self._hints = dict(hints or {})
        self._client = client
        self._scope = resolve_scope(user)
        # Whether ``from_name`` creates the object when it's missing (``create_if_missing``).
        self._creates = False

    def _define(self, definition: Dict[str, Any], *, create_if_missing: bool, key: str = "name") -> None:
        """What ``from_name`` was given: the fields it sets on the object it finds, every time, and with
        ``create_if_missing`` what it creates one from when there's none. A ``definition`` holding only
        ``key`` sets nothing: without ``create_if_missing`` that's a plain lookup."""
        self._creates = create_if_missing
        if create_if_missing or set(definition) - {key}:
            self._create_with = definition

    # --- transport -------------------------------------------------------

    @property
    def _api(self) -> Client:
        return resolve_client(self._client)

    def _owner_scope(self, owner: Any) -> Optional[str]:
        """The user ``owner`` (a ``user_id`` the API sent) names for this object's calls to carry. None from a
        deployed app's own code: its credential acts for the app's own user without naming one."""
        return owner if owner and not self._api.in_app else None

    def _call_scope(self) -> Any:
        owner = self._owner_scope((self._raw or {}).get("user_id"))
        return owner if owner else self._scope

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        kwargs.setdefault("user", self._call_scope())
        return await self._api.request(method, path, **kwargs)

    async def _in_app(self, kind: str, name: str, create_with: Optional[Dict[str, Any]],
                      **resolving: Any) -> Optional[Dict[str, Any]]:
        """Inside a deployed app, the ``kind`` called ``name`` for the environment its code runs in (a preview
        branch's own, when its app gives branches their own), made on first use when ``create_with`` says how,
        with what else the lookup takes (``resolving``, a database's ``branch_data``); None outside one."""
        if not self._api.in_app:
            return None
        made = {k: v for k, v in (create_with or {}).items() if k != "name"}
        return await self._request("POST", "/v1/projects/current/resources", json={
            "kind": kind, "name": name, "create_if_missing": create_with is not None, **made, **compact(**resolving)})

    @classmethod
    async def _create_named(
        cls, path: str, body: Dict[str, Any], *, allow_existing: bool, user: Any, client: Optional[Client] = None,
        key: str = "name", existing_path: Optional[Callable[[str], str]] = None, **request: Any,
    ) -> Dict[str, Any]:
        """``create``: POST ``body`` to ``path``. With ``allow_existing``, a ``key`` already taken (the API's
        ``Conflict`` naming ``existing_id``) answers that object as it is, unchanged."""
        api = resolve_client(client)
        try:
            return await api.request("POST", path, json=body, user=user, **request)
        except Conflict as exc:
            if not allow_existing or not exc.existing_id:
                raise
            taken = exc
        # Another conflict than the name being taken (its existing_id names something else) stays one.
        try:
            found = await api.request(
                "GET", existing_path(taken.existing_id) if existing_path else f"{path}/{taken.existing_id}", user=user,
            )
        except NotFound:
            raise taken from None
        if found.get(key) != body.get(key):
            raise taken
        return found

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        """Fetch this object's current view (subclasses implement)."""
        raise NotImplementedError

    async def _ensure(self) -> Dict[str, Any]:
        if self._raw is None:
            self._raw = await self._load()
        return self._raw

    def _sync_raw(self) -> Dict[str, Any]:
        return self._raw if self._raw is not None else run_sync(self._ensure())

    @property
    def is_hydrated(self) -> bool:
        """Whether the server's view has been loaded."""
        return self._raw is not None

    @property
    def raw(self) -> Dict[str, Any]:
        """The server's JSON for this object (hydrates if needed)."""
        return self._sync_raw()

    @synced
    async def hydrate(self: T) -> T:
        """Load the object from the server if it hasn't been yet.

        Returns:
            This object, loaded. It sends nothing if it already was.

        Usage:
            Load an object now, so a missing one fails here rather than at first use::

                agent = noclick.Agent.from_name("support").hydrate()
                print(agent.model)

            In async code, load it before reading its properties, so the first read doesn't
            block your event loop::

                agent = noclick.Agent.from_name("support")
                await agent.hydrate.aio()
                print(agent.model)
        """
        await self._ensure()
        return self

    @synced
    async def refresh(self: T) -> T:
        """Re-fetch the object's current state.

        Returns:
            This object, with the server's current fields.

        Usage::

            op = noclick.Operation.from_id("3b9d6f2e-1c4a-4e8b-9f7d-2a6c5e8b1d40").hydrate()
            print(op.status)   # running
            op.refresh()
            print(op.status)   # succeeded, once it has finished
        """
        self._raw = await self._load()
        return self

    # --- presentation ----------------------------------------------------

    def _known(self, key: str) -> Any:
        if self._raw is not None and key in self._raw:
            return self._raw[key]
        return self._hints.get(key)

    _repr_keys: tuple = ("id",)

    def _repr_parts(self) -> list:
        parts = [f"{k}={self._known(k)!r}" for k in self._repr_keys if self._known(k) is not None]
        if self._raw is None:
            parts.append("hydrated=False")
        return parts

    def __repr__(self) -> str:
        return f"{type(self).__name__}({', '.join(self._repr_parts())})"

    def __eq__(self, other: Any) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        mine, theirs = self._known("id"), other._known("id")
        return mine is not None and mine == theirs

    def __hash__(self) -> int:
        return hash((type(self).__name__, self._known("id") or id(self)))


def check_unchanged(kind: str, raw: Dict[str, Any], given: Dict[str, Any], *,
                    next_step: Optional[str] = None) -> None:
    """``from_name`` on an existing object: each argument it can't set (``given``, keyed as the API's view
    names the field) must match what the object has, so none is ever ignored."""
    for key, wanted in given.items():
        have = raw.get(key)
        if have != wanted:
            label = raw.get("name") or raw.get("id")
            raise Conflict(
                f"The {kind} {label!r} already exists with {key} {have!r}, which from_name can't change to "
                f"{wanted!r}.",
                next_step=next_step or f"Leave {key} out to use it as it is, or use another name.",
                details={"existing_id": raw.get("id"), "field": key, key: have},
            )


async def ref_id(ref: Any) -> Optional[str]:
    """The id of an object (hydrating a lazy one) or an id string."""
    if ref is None or isinstance(ref, str):
        return ref
    if isinstance(ref, _Object):
        return ref._known("id") or (await ref._ensure())["id"]
    raise TypeError(f"Expected an object or an id, not {type(ref).__name__}")


def csv(value: Union[None, str, Sequence[str]]) -> Optional[str]:
    """A comma list from one value or several."""
    if value is None or isinstance(value, str):
        return value
    return ",".join(value)


def iso_time(value: Union[None, str, datetime]) -> Optional[str]:
    """An ISO timestamp from an aware ``datetime`` or a string already in that form."""
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        raise ValueError("Pass a timezone-aware datetime (e.g. datetime.now(timezone.utc)).")
    return value.isoformat()


# The largest page the /v1 list routes serve.
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class Page(Generic[R]):
    """One page of a listing; pass ``next_cursor`` back as ``cursor`` for the
    next (None = the last page)."""

    data: List[R]
    next_cursor: Optional[str]


async def read_scope(user: Any, user_filter: Any) -> Tuple[Any, Optional[str]]:
    """What a read carries: a filtered read is account-level (no user header)
    and names its users in ``user_id``; otherwise it acts for its user."""
    if user_filter is None:
        return resolve_scope(user), None
    if user is not AMBIENT:
        raise TypeError("Pass user= (who the call acts as) or user_filter= (which users a read covers), not both.")
    return None, await user_filter_param(user_filter)


async def fetch_page(
    client: Client, path: str, *, params: Optional[Dict[str, Any]] = None, user: Any,
    cursor: Optional[str] = None, limit: Optional[int] = None,
) -> Page:
    """One page of a ``{"object": "list", "data", "next_cursor"}`` listing."""
    query = {**(params or {}), "cursor": cursor, "limit": limit}
    page = await client.request("GET", path, params=query, user=user) or {}
    return Page(list(page.get("data") or []), page.get("next_cursor") or None)


async def paginate(
    client: Client, path: str, *, params: Optional[Dict[str, Any]] = None, user: Any, limit: Optional[int] = None,
) -> list:
    """Every item of a listing, or the first ``limit``, in pages of at most ``MAX_PAGE_SIZE``."""
    items: list = []
    cursor = None
    while True:
        size = None if limit is None else min(limit - len(items), MAX_PAGE_SIZE)
        page = await fetch_page(client, path, params=params, user=user, cursor=cursor, limit=size)
        items.extend(page.data)
        if limit is not None and len(items) >= limit:
            return items[:limit]
        if not page.next_cursor:
            return items
        cursor = page.next_cursor


Build = Callable[[Dict[str, Any], Any], Any]


async def list_all(
    path: str, build: Build, *, params: Optional[Dict[str, Any]] = None, user: Any = AMBIENT,
    user_filter: Any = None, limit: Optional[int] = None, client: Optional[Client] = None,
) -> list:
    """``X.list()``: every row (or the first ``limit``) built into objects."""
    scope, user_id = await read_scope(user, user_filter)
    rows = await paginate(
        resolve_client(client), path, params={**(params or {}), "user_id": user_id}, user=scope, limit=limit,
    )
    return [build(row, scope) for row in rows]


async def list_page(
    path: str, build: Build, *, params: Optional[Dict[str, Any]] = None, user: Any = AMBIENT,
    user_filter: Any = None, cursor: Optional[str] = None, limit: Optional[int] = None,
    client: Optional[Client] = None,
) -> Page:
    """``X.list_page()``: one page built into objects. ``limit`` must be at most
    ``MAX_PAGE_SIZE`` (200 on tool calls, requests and message listings); the
    server refuses a larger one, never caps it."""
    scope, user_id = await read_scope(user, user_filter)
    page = await fetch_page(
        resolve_client(client), path, params={**(params or {}), "user_id": user_id}, user=scope,
        cursor=cursor, limit=limit,
    )
    return Page([build(row, scope) for row in page.data], page.next_cursor)


_TEMPLATE = re.compile(r"\{\{(.*?)\}\}")
_USER_TEMPLATE = re.compile(r"\s*user\.(id|email|name|metadata\.[A-Za-z0-9_-]+)\s*")


def bound_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """``bind(**arguments)`` checked: every ``{{...}}`` in a value names the user's
    ``id``, ``email``, ``name`` or one ``metadata`` key."""
    if not arguments:
        raise ValueError("bind() takes at least one argument: bind(to='{{user.email}}')")

    def check(value: Any) -> None:
        if isinstance(value, str):
            for template in _TEMPLATE.findall(value):
                if not _USER_TEMPLATE.fullmatch(template):
                    raise ValueError(
                        f"{{{{{template}}}}} isn't something NoClick fills in; use {{{{user.id}}}}, "
                        "{{user.email}}, {{user.name}} or {{user.metadata.<key>}}"
                    )
        elif isinstance(value, dict):
            for item in value.values():
                check(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                check(item)

    for value in arguments.values():
        check(value)
    return dict(arguments)


def tool_entries(base: str, operations: Sequence[str], bindings: Dict[str, Any]) -> List[Any]:
    """``tools`` on the wire for some operations of one ref: ``"<base>.<op>"``, or
    ``{"tool": ..., "bind": ...}`` when arguments are bound."""
    if not bindings:
        return [f"{base}.{op}" for op in operations]
    return [{"tool": f"{base}.{op}", "bind": dict(bindings)} for op in operations]
