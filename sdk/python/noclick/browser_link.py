"""BrowserLink: a person's page for a browser, as the person its link reached uses it. The link is the capability, so
it takes no key: a page of your own reads the link and acts on it with the link alone."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import quote

from ._client import Client
from ._object import parse_time
from ._sync import synced


@dataclass(frozen=True)
class BrowserLinkBrand:
    """The account's brand, as a link's page wears it."""

    name: Optional[str]
    logo_url: Optional[str]
    color: Optional[str]
    support_url: Optional[str]


@dataclass(frozen=True)
class BrowserLinkPage:
    """A browser link as its page shows it (``BrowserLink.read``), never the account, its user or the browser: its
    ``purpose`` (``live``, a browser's live view; ``login``, a link to sign in to a site once; ``ask``, a step a model
    asked a person to finish), its ``status`` (``open``, a sign-in nobody started yet; ``live`` while its browser
    works; then ``done``, ``expired`` or ``closed``), the site it's for, what it's for in the sender's words, when it
    expires and the account's brand."""

    id: str
    purpose: str
    status: str
    domain: Optional[str]
    reason: Optional[str]
    expires_at: Optional[datetime]
    brand: BrowserLinkBrand
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)


def _page(raw: Dict[str, Any], link_id: str) -> BrowserLinkPage:
    brand = raw.get("brand") or {}
    return BrowserLinkPage(
        id=str(raw.get("id") or link_id), purpose=str(raw.get("purpose") or "live"),
        status=str(raw.get("status") or "closed"), domain=raw.get("domain"), reason=raw.get("reason"),
        expires_at=parse_time(raw.get("expires_at")),
        brand=BrowserLinkBrand(name=brand.get("name"), logo_url=brand.get("logo_url"), color=brand.get("color"),
                               support_url=brand.get("support_url")),
        raw=raw)


class BrowserLink:
    """A person's page for a browser (``/live/{id}``): a browser's live view, a link to sign in to a site once, or a
    step a model asked a person to finish, as the person its link reached uses it. The id is the capability: it works
    until it's done, revoked (its browser closed, its work settled) or expired, and then every call raises
    (``noclick.NotFound`` for a link that never was, ``noclick.NotAvailable`` or ``noclick.Expired`` for one that
    stopped working). The browser itself is shown in the person's own browser (``BrowserLink.view`` in TypeScript).

    Usage::

        link = noclick.BrowserLink(link_id)
        if link.read().status == "open":
            link.start()
        link.type(text="482913")
        link.done()
    """

    def __init__(self, link_id: str, *, base_url: Optional[str] = None, timeout: float = 60.0,
                 max_retries: int = 3) -> None:
        self.id = link_id
        self._client = Client(api_key="", base_url=base_url, timeout=timeout, max_retries=max_retries)

    def __repr__(self) -> str:
        return f"noclick.BrowserLink(id={self.id!r})"

    def _path(self, suffix: str = "") -> str:
        return f"/v1/public/browser_links/{quote(self.id, safe='')}{suffix}"

    async def _post(self, suffix: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._client.request("POST", self._path(suffix), json=body or {}, user=None, anonymous=True)

    @synced
    async def read(self) -> BrowserLinkPage:
        """The link as its page shows it: what it's for, whether its browser works, and the account's brand.

        Returns:
            The ``BrowserLinkPage``.

        Usage::

            page = noclick.BrowserLink(link_id).read()
            print(page.purpose, page.status)
        """
        raw = await self._client.request("GET", self._path(), user=None, anonymous=True)
        return _page(raw, self.id)

    @synced
    async def start(self) -> BrowserLinkPage:
        """Open a sign-in link: its browser starts now on the site (once; opening it again shows the same one).

        Returns:
            The ``BrowserLinkPage``, ``live`` once its browser works.

        Usage::

            noclick.BrowserLink(link_id).start()
        """
        return _page(await self._post("/start"), self.id)

    @synced
    async def type(self, *, text: Optional[str] = None, key: Optional[str] = None) -> None:
        """Type ``text`` where the page has focus, or press ``key`` (``Enter``, ``Backspace``, ``Tab``, ...): one of
        the two. A phone's way in.

        Usage::

            link = noclick.BrowserLink(link_id)
            link.type(text="482913")
            link.type(key="Enter")
        """
        await self._post("/type", {"text": text} if text is not None else {"key": key})

    @synced
    async def done(self) -> BrowserLinkPage:
        """The person has finished: a sign-in is saved, the step a model asked for carries on. A live view has nothing
        to finish (its browser closes instead).

        Returns:
            The ``BrowserLinkPage``, ``done``.

        Usage::

            noclick.BrowserLink(link_id).done()
        """
        return _page(await self._post("/done"), self.id)
