"""AccountPhones: the phone numbers your account's owner messages and calls NoClick from, each proven theirs."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import parse_time
from ._sync import synced


@dataclass(frozen=True)
class LinkedPhone:
    """One number linked to the account: how it was proven (``verify``, a code texted to it; ``whatsapp`` or
    ``imessage``, it texted NoClick) and when."""

    phone: str
    source: str
    verified_at: Optional[datetime]

    @classmethod
    def _from(cls, raw: Any) -> "LinkedPhone":
        raw = raw if isinstance(raw, dict) else {}
        return cls(str(raw.get("phone") or ""), str(raw.get("source") or "verify"), parse_time(raw.get("verified_at")))


@dataclass(frozen=True)
class PhoneChallenge:
    """A code texted to a number to link it: check it with ``AccountPhones.verify`` before ``expires_at``."""

    id: str
    phone: str
    expires_at: Optional[datetime]
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class PhoneLinkCode:
    """A one-time code that links whichever phone texts it to NoClick, and how many seconds it has left."""

    code: str
    expires_in: int


@dataclass(frozen=True)
class AccountPhones:
    """The numbers linked to your account. A linked number reaches the account: texts and calls from it go to its
    owner's NoClick, and the web's phone sign-in signs in to the account with it. So these are the signed-in owner's,
    or a key of your account's own that names the ``account:phones`` scope (a key with ``*`` doesn't hold it unless
    it's named too); any other caller raises ``noclick.PermissionDenied``. Refusals carry their kind in
    ``error.details["reason"]`` (``invalid_code``, ``expired``, ``already_linked``, ``linked_elsewhere``,
    ``last_way_in``, ...)."""

    configured: bool
    max_phones: int
    phones: List[LinkedPhone]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "AccountPhones":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("configured") is True, int(raw.get("max_phones") or 0),
                   [LinkedPhone._from(p) for p in raw.get("phones") or []], raw)

    @synced
    @classmethod
    async def get(cls, *, client: Optional[Client] = None) -> "AccountPhones":
        """Read the numbers linked to the account.

        Returns:
            The linked numbers (``phones``), whether this NoClick sends codes to link one (``configured``) and how
            many an account may link (``max_phones``).

        Usage::

            linked = noclick.AccountPhones.get()
            print([p.phone for p in linked.phones])
        """
        return cls._from(await resolve_client(client).request("GET", "/v1/account/phones", user=None))

    @synced
    @classmethod
    async def link(cls, phone: str, *, client: Optional[Client] = None) -> PhoneChallenge:
        """Text a code to ``phone`` (with its country code, like ``+14155550123``) to link it.

        Returns:
            The challenge the code is checked against with ``AccountPhones.verify``, within ten minutes.

        Usage::

            challenge = noclick.AccountPhones.link("+14155550123")
        """
        raw = await resolve_client(client).request("POST", "/v1/account/phones", json={"phone": phone}, user=None)
        raw = raw if isinstance(raw, dict) else {}
        return PhoneChallenge(str(raw.get("id") or ""), str(raw.get("phone") or phone),
                              parse_time(raw.get("expires_at")), raw)

    @synced
    @classmethod
    async def verify(cls, challenge_id: str, code: str, *, client: Optional[Client] = None) -> LinkedPhone:
        """Link the challenge's number with the code texted to it. A wrong code raises ``noclick.InvalidRequest``
        (``reason`` ``invalid_code``) and can be tried again; an expired challenge (``noclick.Expired``) or too many
        tries (``noclick.RateLimited``) needs a new code.

        Returns:
            The number, linked: proven by a code (``source`` ``verify``), and when.

        Usage::

            noclick.AccountPhones.verify(challenge.id, "123456")
        """
        body = {"challenge_id": challenge_id, "code": code}
        return LinkedPhone._from(await resolve_client(client).request(
            "POST", "/v1/account/phones/verify", json=body, user=None))

    @synced
    @classmethod
    async def link_code(cls, *, client: Optional[Client] = None) -> PhoneLinkCode:
        """A one-time code that links the phone it's texted from: sent to NoClick on WhatsApp or iMessage, it links
        that number to the account. ``expires_in`` counts seconds from now; asked again while it has minutes left,
        the same code. Raises ``noclick.NotAvailable`` (``reason`` ``codes_unavailable``) where this NoClick keeps no
        codes, and ``noclick.Conflict`` (``too_many_phones``) for an account with ``max_phones`` numbers.

        Returns:
            The code and the seconds it has left.

        Usage::

            code = noclick.AccountPhones.link_code()
            print(f"Text {code.code} to NoClick on WhatsApp")
        """
        raw = await resolve_client(client).request("POST", "/v1/account/phones/link_code", user=None)
        raw = raw if isinstance(raw, dict) else {}
        return PhoneLinkCode(str(raw.get("code") or ""), int(raw.get("expires_in") or 0))

    @synced
    @classmethod
    async def unlink(cls, phone: str, *, client: Optional[Client] = None) -> None:
        """Unlink a number: texts and calls from it no longer reach the account, at once. The only number of an
        account with no email raises ``noclick.Conflict`` (``reason`` ``last_way_in``).

        Usage::

            noclick.AccountPhones.unlink("+14155550123")
        """
        await resolve_client(client).request("DELETE", f"/v1/account/phones/{quote(phone, safe='')}", user=None)
