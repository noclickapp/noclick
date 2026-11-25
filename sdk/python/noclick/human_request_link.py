"""HumanRequestLink: a human request's page, as the person its link reached reads and answers it. The link is the
capability, so it takes no key: a page of your own reads and answers a request with the link alone."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import quote

from ._client import Client
from ._object import parse_time
from ._sync import synced


@dataclass(frozen=True)
class HumanRequestPage:
    """A human request as its page shows it (``HumanRequestLink.read``): its ``kind`` (``ask``, ``approve``,
    ``notify``, ``hand_off``, ``setup``, ...), its ``status`` (``pending`` until it's answered), its message, when it
    expires, and in ``raw`` everything the page shows (its options, its brand, a held call's approval, a step
    question, a hand-off)."""

    id: str
    kind: str
    status: str
    message: Optional[str]
    expires_at: Optional[datetime]
    raw: Dict[str, Any] = dc_field(default_factory=dict)


class HumanRequestLink:
    """A human request's page (``/h/{id}``), as the person its link reached reads and answers it. The id is the
    capability; the link NoClick sends its person carries a key beside it (``?k=``), which a request asked of the
    account's owner, one only its person answers and a held call's approval need: pass it as ``key``. Who may answer
    is NoClick's to judge, as on its own page: a request the link can't open raises ``noclick.NotFound``, and an
    answer it doesn't take raises with its reason.

    Usage::

        link = noclick.HumanRequestLink(request_id, key=key_from_the_link)
        if link.read().kind == "approve":
            link.answer({"decision": "approve"})
    """

    def __init__(self, request_id: str, *, key: Optional[str] = None, base_url: Optional[str] = None,
                 timeout: float = 60.0, max_retries: int = 3) -> None:
        self.id = request_id
        self.key = key
        self._client = Client(api_key="", base_url=base_url, timeout=timeout, max_retries=max_retries)

    def __repr__(self) -> str:
        return f"noclick.HumanRequestLink(id={self.id!r})"

    def _path(self, suffix: str = "") -> str:
        return f"/v1/public/human_requests/{quote(self.id, safe='')}{suffix}"

    def _params(self) -> Optional[Dict[str, str]]:
        return {"k": self.key} if self.key else None

    async def _post(self, suffix: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return await self._client.request("POST", self._path(suffix), json=body, params=self._params(), user=None,
                                          anonymous=True)

    @synced
    async def read(self) -> HumanRequestPage:
        """The request as its page shows it.

        Returns:
            The ``HumanRequestPage``.

        Usage::

            page = noclick.HumanRequestLink(request_id, key=key).read()
            print(page.kind, page.message)
        """
        raw = await self._client.request("GET", self._path(), params=self._params(), user=None, anonymous=True)
        return HumanRequestPage(id=str(raw.get("id") or self.id), kind=str(raw.get("kind") or ""),
                                status=str(raw.get("status") or ""), message=raw.get("message"),
                                expires_at=parse_time(raw.get("expires_at")), raw=raw)

    @synced
    async def answer(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Answer it, once: a question's ``choice`` (or ``choices``) and ``text``, an approval's ``decision``
        (``approve`` or ``deny``); a held call's ``approved``, ``note`` and each of its terms accepted; a step
        question's ``connection`` or ``values``. Raises with the reason an answer isn't taken (already answered,
        expired, not this link's to give).

        Returns:
            The request as it stands once answered.

        Usage::

            noclick.HumanRequestLink(request_id, key=key).answer({"choice": "Yes"})
        """
        return await self._post("/answer", body)

    @synced
    async def connect(self, *, credential_type: Optional[str] = None) -> str:
        """A connect question's other account: the provider's sign-in link, which comes back to the request's page and
        whose account answers the question. ``credential_type``: which of its ways to sign in.

        Returns:
            The sign-in link to open.

        Usage::

            url = noclick.HumanRequestLink(request_id, key=key).connect()
        """
        raw = await self._post("/connect", {"credential_type": credential_type} if credential_type else {})
        return str(raw["url"])

    @synced
    async def reply(self, text: str) -> Dict[str, Any]:
        """Reply in the conversation an agent handed this link's person.

        Returns:
            The request as it stands.

        Usage::

            noclick.HumanRequestLink(request_id, key=key).reply("I'll take it from here.")
        """
        return await self._post("/reply", {"text": text})

    @synced
    async def hand_back(self) -> Dict[str, Any]:
        """Give the handed-over conversation back to the agent, which answers from the next message.

        Returns:
            The request as it stands.

        Usage::

            noclick.HumanRequestLink(request_id, key=key).hand_back()
        """
        return await self._post("/hand_back", {})
