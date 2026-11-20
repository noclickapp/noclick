"""Notifications: the email alerts NoClick sends your account's owner, one switch for each kind."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, Mapping, Optional

from ._client import Client, resolve_client
from ._sync import synced


@dataclass(frozen=True)
class Notifications:
    """Which kinds of email alert NoClick sends your account's owner: ``categories`` maps each kind
    (``run_failure``, ``credits``, ``spend_cap``, ``digest``, ...) to whether it's on. A kind never
    turned off is on. They're what Settings → Notifications in the NoClick app shows, and every alert
    email carries a one-click link that turns its own kind off."""

    categories: Dict[str, bool]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "Notifications":
        raw = raw if isinstance(raw, dict) else {}
        return cls({str(k): v is True for k, v in (raw.get("categories") or {}).items()}, raw)

    @synced
    @classmethod
    async def get(cls, *, client: Optional[Client] = None) -> "Notifications":
        """Read which kinds of email alert your account's owner gets. Any of your account's own keys may,
        but one held to one of your users, which raises ``noclick.PermissionDenied``: they're the owner's.

        Returns:
            Every kind NoClick sends, each ``True`` (on) or ``False`` (off).

        Usage::

            alerts = noclick.Notifications.get()
            print(alerts.categories["digest"])   # True until it's turned off
            off = [kind for kind, on in alerts.categories.items() if not on]
        """
        return cls._from(await resolve_client(client).request("GET", "/v1/notifications", user=None))

    @synced
    @classmethod
    async def update(cls, categories: Mapping[str, bool], *, client: Optional[Client] = None) -> "Notifications":
        """Turn kinds of email alert to your account's owner on (``True``) or off (``False``), in one
        change; a kind you leave out stays as it is. A kind NoClick doesn't send, or a value that isn't
        ``True`` or ``False``, raises ``noclick.InvalidRequest`` and changes nothing.

        Returns:
            Every kind, as it stands after the change.

        Usage::

            noclick.Notifications.update({"digest": False, "run_failure": True})
        """
        body = {"categories": dict(categories)}
        return cls._from(await resolve_client(client).request("PATCH", "/v1/notifications", json=body, user=None))
