"""Secrets: named environment values for sandboxes, agents and apps.

    openai = noclick.Secret.from_name("openai", values={"OPENAI_API_KEY": "sk-..."}, create_if_missing=True)
    with noclick.Sandbox.create(secrets=[openai]) as sb:
        sb.exec("python summarize.py")   # reads os.environ["OPENAI_API_KEY"]

A ``Connection`` is an account at a service NoClick calls for you, with tokens it
keeps fresh; a ``Secret`` is raw values for code you run. Values are write-only:
``keys`` names them, and nothing reads one back.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import Page, _Object, compact, field, list_all, list_page, parse_time, ref_id
from ._sync import synced
from ._scope import AMBIENT, resolve_scope
from .exceptions import Conflict, NotFound
from .versions import Version, version_id, versions_of
from .volume import is_id


def _values(values: Optional[Mapping[str, Any]], *, removable: bool = False) -> Optional[Dict[str, Any]]:
    """Values as sent: strings (``None`` removes a key in a merge)."""
    if values is None:
        return None
    if not isinstance(values, Mapping):
        raise TypeError('values= maps each name to its value: {"OPENAI_API_KEY": "sk-..."}')
    for key, value in values.items():
        if not isinstance(value, str) and not (removable and value is None):
            raise TypeError(f"The value of {key!r} must be a string, not {type(value).__name__}.")
    return dict(values)


def secret_refs(secrets: Any, *, user: Any, client: Optional[Client]) -> Optional[List[Any]]:
    """``secrets=`` on a sandbox or agent: ``Secret`` objects, ids and names. A name is
    looked up lazily in ``user`` (its own secret first, then the account's)."""
    if secrets is None:
        return None
    if isinstance(secrets, (str, Secret)):
        secrets = [secrets]
    refs: List[Any] = []
    for secret in secrets:
        if isinstance(secret, Secret) or (isinstance(secret, str) and is_id(secret)):
            refs.append(secret)
        elif isinstance(secret, str):
            refs.append(Secret.from_name(secret, user=user, client=client))
        else:
            raise TypeError(f"A secret is a noclick.Secret, its id or its name, not {type(secret).__name__}")
    return refs


async def secret_ids(refs: List[Any]) -> List[str]:
    """The ids, in order (a later secret's key wins a clash), as the API takes them."""
    return [await ref_id(secret) for secret in refs]


class Secret(_Object):
    """Named values, such as API keys, that the code you run reads from its
    environment: a sandbox's commands, an agent's shell, an app. Each key
    becomes an environment variable of that name. Values are write-only."""

    _repr_keys = ("id", "name", "keys")

    id: str = field("id")
    name: str = field("name")
    keys: List[str] = field("keys", doc="The names it holds, in order; never their values.")
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)
    updated_at: Any = field("updated_at", parse_time, doc="When its values last changed.")
    used_by: List[Dict[str, Any]] = field(
        "used_by",
        doc="Who reads it: ``kind`` (``agent``, a running ``sandbox`` or a ``project``), ``id``, ``name`` "
            "(None for a sandbox) and, for an app, the ``binding`` name.",
    )

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    @property
    def console_url(self) -> Optional[str]:
        """This secret in the developer console (None off the hosted API)."""
        base = self._api.console_url("resources", "secrets")
        return f"{base}?secret={quote(str(self._known('id')), safe='')}" if base and self._known("id") else base

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls, name: str, values: Optional[Mapping[str, str]] = None, *, allow_existing: bool = False,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> "Secret":
        """Create a secret called ``name`` (1-64 letters, digits and ``. _ -``),
        unique to its user (a taken name raises ``noclick.Conflict`` with
        ``existing_id``, or with ``allow_existing=True`` returns the secret already there, its
        values untouched), holding ``values``: up to 100 keys, each an environment
        variable name (letters, digits and ``_``, not starting with a digit; not
        ``PATH``, ``HOME`` or another the process sets, nor one starting ``LD_``,
        ``NC_`` or ``NOCLICK_``), each value a non-empty string of up to 32,768 characters.
        Without ``values`` it starts empty, for someone to fill in from the console.

        Returns:
            The new secret; its ``keys`` name what it holds.

        Usage:
            Store a key from your environment::

                import os

                shipping = noclick.Secret.create("shipping", {"SHIPPING_API_KEY": os.environ["SHIPPING_API_KEY"]})
                print(shipping.keys)   # ['SHIPPING_API_KEY']

            Store it the first time, and keep whatever someone pasted in the console after::

                import os

                shipping = noclick.Secret.create(
                    "shipping", {"SHIPPING_API_KEY": os.environ["SHIPPING_API_KEY"]}, allow_existing=True,
                )
        """
        scope = resolve_scope(user)
        body = compact(name=name, values=_values(values))
        raw = await cls._create_named("/v1/secrets", body, allow_existing=allow_existing, user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls, name: str, *, values: Optional[Mapping[str, str]] = None, create_if_missing: bool = False,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> "Secret":
        """A lazy reference to the secret called ``name``. Acting for a user, that
        user's own secret is found first, then the account's. Given ``values``, it gets the
        current (or given) user's own and sets the keys in ``values`` on every run (NoClick
        compares them, so unchanged values change nothing). Keys it doesn't name are kept: remove
        one with ``update``. ``create_if_missing=True`` creates it, holding ``values``, when
        there's none; without it, a missing secret raises ``noclick.NotFound``.

        Returns:
            A secret that loads (or is created) the first time it's used. Nothing is sent yet.

        Usage:
            Create it from your environment on the first run, and pick up a rotated key on the next::

                import os

                openai = noclick.Secret.from_name(
                    "openai", values={"OPENAI_API_KEY": os.environ["OPENAI_API_KEY"]}, create_if_missing=True,
                )
                with noclick.Sandbox.create(secrets=[openai]) as sb:
                    sb.exec("python summarize.py")   # reads os.environ["OPENAI_API_KEY"]

            Or declare it empty and paste the values in the console::

                erp = noclick.Secret.from_name("acme-erp", create_if_missing=True, user="acme")
                print(erp.console_url)
        """
        secret = cls._new(hints={"name": name}, client=client, user=user)
        secret._define(compact(name=name, values=_values(values)), create_if_missing=create_if_missing)
        return secret

    @classmethod
    def from_id(cls, secret_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Secret":
        """A lazy reference to a secret by id.

        Returns:
            A secret that loads the first time you read a field. Nothing is sent yet.

        Usage::

            openai = noclick.Secret.from_id("2a7f0c3e-9d1b-4e6a-8c5f-3b0e7d2a9c14")
            print(openai.keys)
        """
        return cls._new(hints={"id": secret_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, secret_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Secret":
        """Load a secret by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The secret, loaded: its key names, when they last changed, and who uses it. Never its values.

        Usage::

            openai = noclick.Secret.get("2a7f0c3e-9d1b-4e6a-8c5f-3b0e7d2a9c14")
            print(openai.name, openai.keys, openai.updated_at)
        """
        secret = cls.from_id(secret_id, client=client, user=user)
        await secret._ensure()
        return secret

    @synced
    @classmethod
    async def list(
        cls, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Secret"]:
        """The current user's secrets and the account's (or those ``user_filter`` covers).

        Returns:
            Every matching secret, newest first, fetched page by page, with key names and never values.

        Usage::

            for secret in noclick.Secret.list():
                print(secret.name, secret.keys, secret.user_id)   # user_id is None for the account's

            everyone = noclick.Secret.list(user_filter=noclick.ALL_USERS)   # every user's, plus your account's
        """
        return await list_all(
            "/v1/secrets", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of secrets; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the secrets and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Secret.list_page(limit=50)
            while True:
                for secret in page.data:
                    print(secret.name, secret.keys)
                if page.next_cursor is None:
                    break
                page = noclick.Secret.list_page(limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/secrets", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        secret_id = self._known("id")
        if secret_id:
            return await self._request("GET", f"/v1/secrets/{secret_id}")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/secrets", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        # This scope's own secret first; values are only ever set on its own.
        own = [row for row in rows if bool(row.get("user_id")) == bool(self._scope)]
        rows = own if self._create_with is not None else own + [row for row in rows if row not in own]
        if rows:
            return await self._converge(rows[0])
        if not self._creates:
            raise NotFound(
                f"No secret is named {name!r}.",
                next_step="Create it with noclick.Secret.create(...) or pass create_if_missing=True.",
                details={"name": name},
            )
        try:
            return await self._request("POST", "/v1/secrets", json=self._create_with)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._converge(await self._request("GET", f"/v1/secrets/{exc.existing_id}"))

    async def _converge(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Set the values ``from_name`` was given on an existing secret (merged; the server
        compares them, so the same values write nothing)."""
        values = (self._create_with or {}).get("values")
        if not values:
            return raw
        return await self._request("PATCH", f"/v1/secrets/{raw['id']}", json={"values": values})

    async def _url(self) -> str:
        """This secret's route; a reference by name is looked up (or created) first."""
        if not self._known("id"):
            await self._ensure()
        return f"/v1/secrets/{self._known('id')}"

    # --- values ----------------------------------------------------------

    @synced
    async def update(self, values: Mapping[str, Optional[str]], *, replace: bool = False) -> "Secret":
        """Set values. By default they merge: the keys you pass are set, a key
        set to ``None`` is removed, and the rest are kept. ``replace=True`` makes
        the secret hold exactly ``values``. New sandboxes see the change at once,
        agents from their next turn, and apps at their next deployment.

        Returns:
            This secret, with its new ``keys`` and ``updated_at``.

        Usage:
            Rotate one key and keep the rest::

                import os

                openai = noclick.Secret.from_name("openai")
                openai.update({"OPENAI_API_KEY": os.environ["NEW_OPENAI_API_KEY"]})

            Remove a key, or replace every value at once::

                erp = noclick.Secret.from_name("acme-erp", user="acme")
                erp.update({"ERP_TOKEN": None})
                erp.update({"ERP_USER": "svc-noclick", "ERP_PASSWORD": "..."}, replace=True)
                print(erp.keys)   # ['ERP_PASSWORD', 'ERP_USER']
        """
        body: Dict[str, Any] = {"values": _values(values, removable=not replace)}
        if replace:
            body["replace"] = True
        self._raw = await self._request("PATCH", await self._url(), json=body)
        return self

    @synced
    async def versions(self) -> List[Version]:
        """What it held before each change of the last 30 days, newest first: when each was replaced and the
        keys it held, never the values.

        Returns:
            Each earlier version.

        Usage::

            stripe = noclick.Secret.from_name("stripe")
            for version in stripe.versions():
                print(version.replaced_at, version.keys)
        """
        return versions_of(await self._request("GET", await self._url() + "/versions"))

    @synced
    async def restore_version(self, version: Any) -> "Secret":
        """Hold ``version``'s keys and values again (the values it holds now are kept as a version in turn).
        Nothing is shown or sent: the earlier values come back sealed.

        Returns:
            This secret, holding them.

        Usage:
            Roll back a key that was rotated by mistake::

                stripe = noclick.Secret.from_name("stripe")
                stripe.restore_version(stripe.versions()[0])
        """
        self._raw = await self._request("POST", await self._url() + f"/versions/{version_id(version)}/restore")
        return self

    @synced
    async def delete(self) -> None:
        """Delete the secret and its values, for good (its earlier versions go with it).
        While an agent lists it or an app binds it (``used_by``), this raises
        ``noclick.Conflict``; sandboxes already running keep their environment until they end.

        Usage::

            noclick.Secret.from_name("old-provider").delete()
        """
        await self._request("DELETE", await self._url())
