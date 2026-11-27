"""Keys: one of your account's own keys makes another for your code, no wider than itself."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote

import httpx

from ._client import API_URL_ENV, DEFAULT_BASE_URL, Client, resolve_client
from ._object import UNSET, Page, fetch_page, paginate, parse_time
from ._sync import synced


@dataclass(frozen=True)
class SetupCode:
    """A setup code (``Key.setup_code``): the ``code``, the name of the key it becomes, and when it lapses."""

    code: str
    key_name: str
    expires_at: Optional[datetime]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)


def _public_access(public_endpoints: Any, per_visitor_limit_per_minute: Any, allowed_origins: Any) -> Dict[str, Any]:
    """What a publishable key may call, on the wire: each endpoint ``{"kind", "id"}``; only the fields given."""
    body: Dict[str, Any] = {}
    if public_endpoints is not UNSET:
        body["public_endpoints"] = [{"kind": e["kind"], "id": e["id"]} for e in public_endpoints]
    if per_visitor_limit_per_minute is not UNSET:
        body["per_visitor_limit_per_minute"] = per_visitor_limit_per_minute
    if allowed_origins is not UNSET:
        body["allowed_origins"] = list(allowed_origins)
    return body


@dataclass(frozen=True)
class Key:
    """A platform secret key of your account's: its ``id``, ``name``, ``scopes``, monthly cap, expiry, the user it's
    pinned to (``user_id``) and the key that made it (``minted_by``; ``None`` for one the owner made). ``secret`` is
    the key itself (``nk_live_...``): ``Key.create`` returns it once, and nothing shows it again."""

    id: str
    name: str
    scopes: List[str]
    spend_cap_usd_per_month: Optional[float]
    expires_at: Optional[datetime]
    user_id: Optional[str]
    minted_by: Optional[str]
    #: ``secret`` or ``publishable``.
    type: str = "secret"
    #: What shows of it everywhere: ``nk_live_ab12``.
    key_prefix: Optional[str] = None
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    secret: Optional[str] = dc_field(default=None, repr=False)
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "Key":
        raw = raw if isinstance(raw, dict) else {}
        cap = raw.get("spend_cap_usd_per_month")
        return cls(str(raw.get("id") or ""), str(raw.get("name") or ""), [str(s) for s in raw.get("scopes") or []],
                   float(cap) if cap is not None else None, parse_time(raw.get("expires_at")), raw.get("user_id"),
                   raw.get("minted_by"), raw.get("type") or "secret", raw.get("key_prefix"),
                   parse_time(raw.get("created_at")), parse_time(raw.get("last_used_at")),
                   parse_time(raw.get("revoked_at")), raw.get("raw_key"),
                   {k: v for k, v in raw.items() if k != "raw_key"})

    @synced
    @classmethod
    async def create(cls, name: str, scopes: Sequence[str], *, spend_cap_usd_per_month: Optional[float] = None,
                     expires_at: Optional[datetime] = None, user_id: Optional[str] = None,
                     type: Optional[str] = None, public_endpoints: Any = UNSET,
                     per_visitor_limit_per_minute: Any = UNSET, allowed_origins: Any = UNSET,
                     client: Optional[Client] = None) -> "Key":
        """Make a secret key from your server, with one of your account's own keys that names the ``keys:create``
        scope (a key with every scope, ``*``, holds it only when it's named too). The new key is no wider than the
        one making it: only scopes it holds itself (``*`` only from a key holding ``*``), a monthly cap when it has
        one, at most its own, an expiry when it has one, no later, and the approval settings it set for itself. It
        names the key that made it (``minted_by``) and never outlives it: revoking a key revokes every key it made,
        and theirs. ``user_id`` pins it to one of your users. Signed in, the account's owner makes any key, and alone
        makes a ``type="publishable"`` one (no scopes): it calls only its ``public_endpoints`` (each ``{"kind",
        "id"}``, from ``Account.public_endpoints()``), from a web page, at most ``per_visitor_limit_per_minute`` calls
        a visitor, from ``allowed_origins``.

        Returns:
            The key, its ``secret`` shown this once: store it where your code reads it.

        Raises:
            noclick.PermissionDenied: a key without ``keys:create``, one acting for a user, or a key wider than the
                one making it (``field`` names what: ``scopes``, ``spend_cap_usd_per_month``, ``expires_at``).

        Usage::

            worker = noclick.Key.create("queue worker", ["queues", "agents"], spend_cap_usd_per_month=20)
            os.environ["WORKER_KEY"] = worker.secret
        """
        body: Dict[str, Any] = {"name": name, "scopes": list(scopes)}
        if spend_cap_usd_per_month is not None:
            body["spend_cap_usd_per_month"] = spend_cap_usd_per_month
        if expires_at is not None:
            body["expires_at"] = expires_at.isoformat()
        if user_id is not None:
            body["user_id"] = user_id
        if type is not None:
            body["type"] = type
        body.update(_public_access(public_endpoints, per_visitor_limit_per_minute, allowed_origins))
        return cls._from(await resolve_client(client).request("POST", "/v1/keys", json=body, user=None))

    @synced
    @classmethod
    async def list(cls, *, status: Optional[str] = None, limit: Optional[int] = None,
                   client: Optional[Client] = None) -> List["Key"]:
        """Every key of the account, newest first (``status``: ``active``, ``revoked`` or ``all``, the default), each
        with what it spent this month (``raw["spent_usd_this_month"]``). The signed-in owner's alone.

        Returns:
            Each ``Key`` (never its secret).

        Usage::

            for key in noclick.Key.list(status="active"):
                print(key.name, key.key_prefix)
        """
        rows = await paginate(resolve_client(client), "/v1/keys", params={"status": status}, user=None, limit=limit)
        return [cls._from(row) for row in rows]

    @synced
    @classmethod
    async def list_page(cls, *, status: Optional[str] = None, cursor: Optional[str] = None,
                        limit: Optional[int] = None, client: Optional[Client] = None) -> Page:
        """One page of ``list()``; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the keys.

        Usage::

            page = noclick.Key.list_page(limit=20)
            print([key.name for key in page.data], page.next_cursor)
        """
        page = await fetch_page(resolve_client(client), "/v1/keys", params={"status": status}, user=None,
                                cursor=cursor, limit=limit)
        return Page([cls._from(row) for row in page.data], page.next_cursor)

    @synced
    @classmethod
    async def update(cls, key_id: str, *, name: Optional[str] = None, spend_cap_usd_per_month: Any = UNSET,
                     public_endpoints: Any = UNSET, per_visitor_limit_per_minute: Any = UNSET,
                     allowed_origins: Any = UNSET, client: Optional[Client] = None) -> "Key":
        """Change a key: its ``name``, its monthly cap (``None`` removes it) and a publishable key's endpoints, visitor
        limit and origins; only the fields given. The signed-in owner's alone (a key's own approval settings:
        ``ApprovalPolicy.set_for_key``).

        Returns:
            The key as it is now.

        Usage::

            noclick.Key.update(key.id, name="queue worker (prod)", spend_cap_usd_per_month=50)
        """
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if spend_cap_usd_per_month is not UNSET:
            body["spend_cap_usd_per_month"] = spend_cap_usd_per_month
        body.update(_public_access(public_endpoints, per_visitor_limit_per_minute, allowed_origins))
        return cls._from(await resolve_client(client).request(
            "PATCH", f"/v1/keys/{quote(key_id, safe='')}", json=body, user=None))

    @synced
    @classmethod
    async def revoke(cls, key_id: str, *, client: Optional[Client] = None) -> "Key":
        """Revoke a key: its next call fails, and every key it made is revoked with it. The signed-in owner's alone.

        Returns:
            The key, with ``revoked_at`` set.

        Usage::

            noclick.Key.revoke(key.id)
        """
        return cls._from(await resolve_client(client).request("DELETE", f"/v1/keys/{quote(key_id, safe='')}", user=None))

    @synced
    @staticmethod
    async def setup_code(*, scopes: Optional[Sequence[str]] = None, name: Optional[str] = None,
                         client: Optional[Client] = None) -> SetupCode:
        """A one-time setup code (``nc_setup_...``, 30 minutes) a coding agent redeems for a key of the account
        (``noclick setup <code>``, or ``POST /v1/setup``), so the key lands in its project, never in its context. Its
        key holds every scope but the ones a key holds only when they're named, and also ``scopes``, any of those the
        agent's work needs (``["machines:vetting"]``). The key takes ``name``, for the task the agent is handed
        (default ``Coding agent``); a code nobody redeems makes no key. The signed-in owner's alone.

        Returns:
            The code.

        Usage::

            print(noclick.Key.setup_code(name="Coding agent: build an agent").code)
        """
        body = {k: v for k, v in (("scopes", list(scopes) if scopes else None), ("name", name)) if v} or None
        raw = await resolve_client(client).request("POST", "/v1/cli/setup_codes", json=body, user=None) or {}
        return SetupCode(raw.get("code") or "", raw.get("key_name") or "", parse_time(raw.get("expires_at")), raw)
    @staticmethod
    async def revoke_current(*, client: Optional[Client] = None) -> None:
        """Revoke the key the client signs in with (a sign-out): every later call with it is refused.

        Usage::

            noclick.Key.revoke_current()
        """
        await resolve_client(client).request("DELETE", "/v1/keys/current", user=None)

    @staticmethod
    def redeem_setup_code(code: str, *, base_url: Optional[str] = None) -> "Key":
        """Redeem a one-time setup code (``nc_setup_...``, which the console's quickstart hands a coding agent) for a
        key of the account, once, with no key of your own. Keep it out of anything you print: ``noclick setup`` keeps
        it where ``noclick login`` would.

        Returns:
            The key, its ``secret`` shown this once, with its ``id`` and ``name`` (``raw["email"]`` is the
            account's).

        Usage::

            key = noclick.Key.redeem_setup_code("nc_setup_...")
            client = noclick.Client(api_key=key.secret)
        """
        import os

        api_url = (base_url or os.environ.get(API_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
        response = httpx.post(f"{api_url}/v1/setup", data={"code": code}, headers={"Accept": "application/json"},
                              timeout=30)
        body = Client._decode(response) or {}
        return Key._from({"id": body.get("key_id"), "name": body.get("key_name"), "raw_key": body.get("key"),
                          **{k: v for k, v in body.items() if k != "key"}})
