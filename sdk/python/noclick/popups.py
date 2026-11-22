"""Popups: the popups and banners of the NoClick app your account's owner can turn off, and back on."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, Mapping, Optional

from ._client import Client, resolve_client
from ._sync import synced


@dataclass(frozen=True)
class Popups:
    """Which of the NoClick app's popups and banners your account's owner sees: ``popups`` maps each one
    (``run_results``, the outputs shown after a workflow runs; ``invite_banner``, the nudge to share a workflow's live
    invite link; ``publish_banner``, the nudge to publish an interface) to whether it shows. One never turned off
    shows. They're what Settings → Popups in the NoClick app shows, and a popup's own "Don't show again" turns it off
    too."""

    popups: Dict[str, bool]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "Popups":
        raw = raw if isinstance(raw, dict) else {}
        return cls({str(k): v is True for k, v in (raw.get("popups") or {}).items()}, raw)

    @synced
    @classmethod
    async def get(cls, *, client: Optional[Client] = None) -> "Popups":
        """Read which of the app's popups your account's owner sees. Any of your account's own keys may, but one held
        to one of your users, which raises ``noclick.PermissionDenied``: they're the owner's.

        Returns:
            Every popup, each ``True`` (it shows) or ``False`` (it's off).

        Usage::

            shown = noclick.Popups.get().popups
            print(shown["run_results"])   # True until it's turned off
        """
        return cls._from(await resolve_client(client).request("GET", "/v1/popups", user=None))

    @synced
    @classmethod
    async def update(cls, popups: Mapping[str, bool], *, client: Optional[Client] = None) -> "Popups":
        """Show (``True``) or stop showing (``False``) the app's popups to your account's owner, in one change; a popup
        you leave out stays as it is. A popup the app doesn't have, or a value that isn't ``True`` or ``False``,
        raises ``noclick.InvalidRequest`` and changes nothing.

        Returns:
            Every popup, as it stands after the change.

        Usage::

            noclick.Popups.update({"invite_banner": False})
        """
        body = {"popups": dict(popups)}
        return cls._from(await resolve_client(client).request("PATCH", "/v1/popups", json=body, user=None))
