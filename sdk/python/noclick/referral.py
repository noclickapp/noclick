"""Your account's invite link: each person who joins NoClick through it, and starts using it, adds ``reward_usd`` to
your balance. A user of your account has none of its own."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, Optional

from ._client import Client, resolve_client
from ._object import parse_time
from ._sync import synced


@dataclass(frozen=True)
class Referral:
    """Your account's invite link and what it has earned."""

    code: str
    url: str
    #: What a friend reads, then the link.
    share_text: str
    #: What each friend who starts using NoClick adds to your balance.
    reward_usd: float
    #: How many joined through it.
    joined: int
    #: How many of them earned the reward, and what it came to.
    earned: int
    earned_usd: float
    #: Whose link your account joined through (``{"name", "channel"}``), if it did.
    joined_through: Optional[Dict[str, Any]]
    #: Until when your account can still apply an invite code (a day after it joined, once); ``None`` once it can't.
    can_apply_until: Any
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "Referral":
        return cls(str(raw.get("code") or ""), str(raw.get("url") or ""), str(raw.get("share_text") or ""),
                   float(raw.get("reward_usd") or 0), int(raw.get("joined") or 0), int(raw.get("earned") or 0),
                   float(raw.get("earned_usd") or 0), raw.get("joined_through"),
                   parse_time(raw.get("can_apply_until")), raw)

    @synced
    @staticmethod
    async def get(*, client: Optional[Client] = None) -> "Referral":
        """Your account's invite link, how many joined and earned through it, and whose link your account joined
        through.

        Returns:
            The link (``url``), the line to send it with (``share_text``) and what it has earned.

        Usage::

            referral = noclick.Referral.get()
            print(referral.share_text, referral.joined, referral.earned_usd)
        """
        return Referral._from(await resolve_client(client).request("GET", "/v1/referral", user=None) or {})

    @synced
    @staticmethod
    async def apply(code: str, *, client: Optional[Client] = None) -> "Referral":
        """Apply a friend's invite ``code`` (or their join link) to your account, as the person they invited: only
        within a day of your account's creation, and once. An unknown code raises ``noclick.NotFound``; a second one
        ``noclick.Conflict``.

        Returns:
            Your account's invite link, now naming whose link it joined through.

        Usage::

            noclick.Referral.apply("ana-k3x9")
        """
        return Referral._from(await resolve_client(client).request(
            "POST", "/v1/referral/apply", json={"code": code}, user=None) or {})
