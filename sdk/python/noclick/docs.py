"""NoClick's docs as Markdown: the guides, skills (task playbooks), SDK reference, examples and API operations,
searched and read with no key, as ``noclick docs`` and ``noclick skill`` print them."""

from __future__ import annotations

import os
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

import httpx

from ._client import API_URL_ENV, DEFAULT_BASE_URL, Client


def _get(path: str, params: Optional[Dict[str, Any]], base_url: Optional[str]) -> Any:
    api_url = (base_url or os.environ.get(API_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
    return Client._decode(httpx.get(f"{api_url}{path}", params={k: v for k, v in (params or {}).items()
                                                                  if v is not None}, timeout=30))


@dataclass(frozen=True)
class DocHit:
    """A doc a search found, or one a listing names: its ``id`` (``guide:apps``, ``skill:ship-an-app``) reads it
    whole with ``Docs.read``."""

    id: str
    kind: str
    title: str
    url: Optional[str]
    snippet: str
    #: ``built``, or ``designed`` for an API call that doesn't work yet.
    status: str
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "DocHit":
        return cls(raw.get("id") or "", raw.get("kind") or "", raw.get("title") or "", raw.get("url"),
                   raw.get("snippet") or "", raw.get("status") or "built", raw)


@dataclass(frozen=True)
class Doc:
    """One guide page or section, skill, reference entry, example or API operation, whole: ``text`` is Markdown,
    and ``sections`` names a page's sections by id."""

    id: str
    kind: str
    title: str
    summary: str
    url: Optional[str]
    status: str
    text: str
    sections: List[str]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "Doc":
        return cls(raw.get("id") or "", raw.get("kind") or "", raw.get("title") or "", raw.get("summary") or "",
                   raw.get("url"), raw.get("status") or "built", raw.get("text") or "",
                   list(raw.get("sections") or []), raw)


class Docs:
    """NoClick's docs, for code and coding agents: no key needed."""

    @staticmethod
    def search(query: Optional[str] = None, *, kind: Optional[str] = None, limit: int = 20,
               base_url: Optional[str] = None) -> List[DocHit]:
        """Search the docs, best first; with no ``query``, list every guide page and skill (or ``kind``'s:
        ``guide``, ``skill``, ``reference``, ``example``, ``event``, ``api``).

        Returns:
            Up to ``limit`` hits (at most 50 with a query).

        Usage::

            for hit in noclick.Docs.search("send email from an agent", limit=5):
                print(hit.id, hit.title)
        """
        body = _get("/v1/docs", {"q": query, "kind": kind, "limit": limit if query else None}, base_url) or {}
        return [DocHit._from(row) for row in body.get("data") or []]

    @staticmethod
    def read(doc_id: str, *, base_url: Optional[str] = None) -> Doc:
        """Read one doc whole: a hit's ``id``, or a bare name (``apps``), which reads the guide, else the skill, so
        named. One nobody has raises ``noclick.NotFound``.

        Returns:
            The doc, its ``text`` as Markdown.

        Usage::

            print(noclick.Docs.read("skill:ship-an-app").text)
        """
        return Doc._from(_get(f"/v1/docs/{doc_id}", None, base_url) or {})
