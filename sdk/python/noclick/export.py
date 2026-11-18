"""Exports: everything a user or an app holds, in formats that work elsewhere."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from ._object import parse_time


@dataclass(frozen=True)
class ExportItem:
    """One thing in an export and the form it leaves in: ``kind`` (``agent``,
    ``conversations``, ``memory``, ``database``, ``files``, ``dict``, ``queue``,
    ``code``, ``app``, ``credentials``, ``phone_number``, ``domain``), its
    ``name``, and ``detail``, a sentence saying where it is in the zip and what
    to do with it."""

    kind: str
    name: str
    detail: str


@dataclass(frozen=True)
class ExportBundle:
    """What an export produced: a zip at ``url`` (a link that works until
    ``expires_at``, 7 days) of ``size_bytes``, what's in it, and
    ``remaining_dependencies``, what keeps needing NoClick while the account
    exists (``the agent runtime``, ``channels``, ``people's pending asks``,
    ``app hosting``, ``connections``). The zip's ``README.md`` says the same for
    a person, its ``manifest.json`` for code."""

    url: Optional[str]
    expires_at: Any
    size_bytes: int
    contents: List[ExportItem]
    remaining_dependencies: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "ExportBundle":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            url=raw.get("url"),
            expires_at=parse_time(raw.get("expires_at")),
            size_bytes=int(raw.get("size_bytes") or 0),
            contents=[ExportItem(i.get("kind") or "", i.get("name") or "", i.get("detail") or "")
                      for i in raw.get("contents") or [] if isinstance(i, dict)],
            remaining_dependencies=list(raw.get("remaining_dependencies") or []),
            raw=raw,
        )
