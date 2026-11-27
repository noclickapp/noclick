"""AccountPush: the browsers that show the signed-in person NoClick's notifications (Web Push)."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import parse_time
from ._sync import synced


@dataclass(frozen=True)
class PushDevice:
    """One browser that shows the person's notifications, as its push service names it (``endpoint``)."""

    id: str
    device: Optional[str]
    endpoint: str
    created_at: Optional[datetime]
    last_sent_at: Optional[datetime]

    @classmethod
    def _from(cls, raw: Any) -> "PushDevice":
        raw = raw if isinstance(raw, dict) else {}
        return cls(str(raw.get("id") or ""), raw.get("device"), str(raw.get("endpoint") or ""),
                   parse_time(raw.get("created_at")), parse_time(raw.get("last_sent_at")))


@dataclass(frozen=True)
class AccountPush:
    """The browsers that show the signed-in person NoClick's notifications: a DM or @mention of them in a space, a
    question or approval that needs them, and work that finished while they weren't watching. Turned on in a browser
    from the person's own tap, and off there. The signed-in person's alone, in their own browser: any other caller
    raises ``noclick.PermissionDenied``."""

    configured: bool
    public_key: Optional[str]
    devices: List[PushDevice]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "AccountPush":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("configured") is True, raw.get("public_key"),
                   [PushDevice._from(d) for d in raw.get("devices") or []], raw)

    @synced
    @classmethod
    async def get(cls, *, client: Optional[Client] = None) -> "AccountPush":
        """Read the browsers that show the person's notifications.

        Returns:
            The browsers (``devices``), whether this NoClick sends notifications to browsers (``configured``) and the
            key a new one subscribes with (``public_key``).

        Usage::

            push = noclick.AccountPush.get()
            print([d.device for d in push.devices])
        """
        return cls._from(await resolve_client(client).request("GET", "/v1/account/push", user=None))

    @synced
    @classmethod
    async def add(cls, subscription: Mapping[str, Any], *, device: Optional[str] = None,
                  client: Optional[Client] = None) -> PushDevice:
        """Turn notifications on in a browser, with its push subscription (``endpoint`` and ``keys``, as the browser's
        ``PushSubscription.toJSON()`` gives them): the same browser again is updated, never added twice.

        Returns:
            The browser, as it's kept.

        Usage::

            added = noclick.AccountPush.add(subscription, device="iPhone")
        """
        raw = await resolve_client(client).request("POST", "/v1/account/push", user=None, json={
            "endpoint": subscription.get("endpoint"), "keys": subscription.get("keys"), "device": device})
        return PushDevice._from(raw)

    @synced
    @classmethod
    async def remove(cls, device_id: str, *, client: Optional[Client] = None) -> None:
        """Turn notifications off in one browser.

        Returns:
            Nothing.

        Usage::

            noclick.AccountPush.remove(added.id)
        """
        await resolve_client(client).request("DELETE", f"/v1/account/push/{quote(device_id, safe='')}", user=None)
