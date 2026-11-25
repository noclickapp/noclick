"""Keys: one of your account's own keys makes another for your code, no wider than itself."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import httpx

from ._client import API_URL_ENV, DEFAULT_BASE_URL, Client, resolve_client
from ._object import parse_time
from ._sync import synced


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
    secret: Optional[str] = dc_field(default=None, repr=False)
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "Key":
        raw = raw if isinstance(raw, dict) else {}
        cap = raw.get("spend_cap_usd_per_month")
        return cls(str(raw.get("id") or ""), str(raw.get("name") or ""), [str(s) for s in raw.get("scopes") or []],
                   float(cap) if cap is not None else None, parse_time(raw.get("expires_at")), raw.get("user_id"),
                   raw.get("minted_by"), raw.get("raw_key"), {k: v for k, v in raw.items() if k != "raw_key"})

    @synced
    @classmethod
    async def create(cls, name: str, scopes: Sequence[str], *, spend_cap_usd_per_month: Optional[float] = None,
                     expires_at: Optional[datetime] = None, user_id: Optional[str] = None,
                     client: Optional[Client] = None) -> "Key":
        """Make a secret key from your server, with one of your account's own keys that names the ``keys:create``
        scope (a key with every scope, ``*``, holds it only when it's named too). The new key is no wider than the
        one making it: only scopes it holds itself (``*`` only from a key holding ``*``), a monthly cap when it has
        one, at most its own, an expiry when it has one, no later, and the approval settings it set for itself. It
        names the key that made it (``minted_by``) and never outlives it: revoking a key revokes every key it made,
        and theirs. ``user_id`` pins it to one of your users. Signed in, the account's owner makes any key.

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
        return cls._from(await resolve_client(client).request("POST", "/v1/keys", json=body, user=None))

    @synced
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
