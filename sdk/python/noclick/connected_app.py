"""Connected apps: the MCP clients your account's owner allowed to connect, and NoClick's own connections (its
assistant's), each a caller of its own with the bounds set for it. Only the owner, signed in, lists, revokes and
restores them."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import Page, fetch_page, paginate, parse_time
from ._sync import synced


@dataclass(frozen=True)
class ConnectedApp:
    """One connection, revoked or not: the client (``client_name``, and ``client_id``, ``noclick:`` for one NoClick
    makes itself), the capability groups it holds (``read``, ``build``, ``deploy``, ``spend``, ``delete``), its monthly
    cap and the amount under which a purchase it makes goes through unasked (``None``: none of its own, and it asks
    before every one), what it spent this month, and the user it acts for (``None``: your account). ``restorable``:
    once revoked, the owner may turn it back on as it was (a connection NoClick makes); a client a person connected
    connects again instead."""

    id: str
    client_name: str
    client_id: str
    client_uri: Optional[str]
    capabilities: List[str]
    spend_cap_usd_per_month: Optional[float]
    auto_approve_under_usd: Optional[float]
    spent_usd_this_month: float
    user_id: Optional[str]
    restorable: bool
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None

    @classmethod
    def _from(cls, raw: Any) -> "ConnectedApp":
        raw = raw if isinstance(raw, dict) else {}
        client = raw.get("client") or {}
        return cls(str(raw.get("id") or ""), client.get("name") or "", client.get("id") or "", client.get("uri"),
                   list(raw.get("capabilities") or []), raw.get("spend_cap_usd_per_month"),
                   raw.get("auto_approve_under_usd"), raw.get("spent_usd_this_month") or 0.0, raw.get("user_id"),
                   raw.get("restorable") is True, parse_time(raw.get("created_at")),
                   parse_time(raw.get("last_used_at")), parse_time(raw.get("revoked_at")), raw)

    @synced
    @classmethod
    async def list(cls, *, limit: Optional[int] = None, client: Optional[Client] = None) -> List["ConnectedApp"]:
        """Every connection, newest first, revoked ones too (or the first ``limit``). The account's signed-in owner's
        alone: a key, a user's session, an app's code or an MCP connection gets ``noclick.PermissionDenied``.

        Returns:
            Each ``ConnectedApp``.

        Usage::

            for app in noclick.ConnectedApp.list():
                print(app.client_name, app.capabilities, "revoked" if app.revoked else "live")
        """
        rows = await paginate(resolve_client(client), "/v1/connected_apps", user=None, limit=limit)
        return [cls._from(row) for row in rows]

    @synced
    @classmethod
    async def list_page(cls, *, cursor: Optional[str] = None, limit: Optional[int] = None,
                        client: Optional[Client] = None) -> Page:
        """One page of ``list()``, newest first; pass ``next_cursor`` back as ``cursor``. The signed-in owner's alone.

        Returns:
            A page whose ``data`` holds the connections.

        Usage::

            page = noclick.ConnectedApp.list_page(limit=20)
            print([app.client_name for app in page.data], page.next_cursor)
        """
        page = await fetch_page(resolve_client(client), "/v1/connected_apps", user=None, cursor=cursor, limit=limit)
        return Page([cls._from(row) for row in page.data], page.next_cursor)

    @synced
    @classmethod
    async def revoke(cls, connected_app_id: str, *, client: Optional[Client] = None) -> "ConnectedApp":
        """End a connection: its next call fails. Revoking one again changes nothing. The signed-in owner's alone.

        Returns:
            It, with ``revoked_at`` set.

        Usage::

            noclick.ConnectedApp.revoke(app.id)
        """
        return cls._from(await resolve_client(client).request(
            "DELETE", f"/v1/connected_apps/{quote(connected_app_id, safe='')}", user=None))

    @synced
    @classmethod
    async def restore(cls, connected_app_id: str, *, client: Optional[Client] = None) -> "ConnectedApp":
        """Turn a revoked connection NoClick makes (``restorable``: its assistant's) back on, as it was when revoked:
        its groups, cap, auto-approve amount and own approval settings, never wider. Its next call works; restoring a
        live one changes nothing. A client a person connected raises ``noclick.Conflict`` (it connects again, as a new
        connection). The signed-in owner's alone: a key, an app's code, an MCP connection or an agent gets
        ``noclick.PermissionDenied``.

        Returns:
            It, live (``revoked_at`` is ``None``).

        Usage::

            [assistant] = [a for a in noclick.ConnectedApp.list() if a.restorable and a.revoked]
            noclick.ConnectedApp.restore(assistant.id)
        """
        return cls._from(await resolve_client(client).request(
            "POST", f"/v1/connected_apps/{quote(connected_app_id, safe='')}/restore", user=None))
