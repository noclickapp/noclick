"""Files on messages: an agent's and a channel's, uploaded first and sent once; sent, the account's files."""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import Page, compact, fetch_page, parse_time
from ._sync import synced
from .exceptions import InvalidRequest

# A message's files at most, as the API caps them.
MAX_FILES = 100


@dataclass(frozen=True)
class Attachment:
    """A file on a message, kept as an account file at ``url``. ``kind`` is
    ``image``, ``audio``, ``video`` or ``file``; a ``voice`` clip has its
    ``duration_ms`` and its waveform's ``peaks`` (loudness from 0 to 1). Audio
    is kept as transcription reads it (a browser's WebM recording as MP3). A
    file an agent's conversation shows (in ``history``, or a ``file`` event)
    has its ``name``, ``url`` and ``mime_type``, and no ``id``: it was sent. The
    account's files (``noclick.attachments()``) have their ``id``, to send again,
    and when each was made (``created_at``) and last changed (``updated_at``)."""

    name: str
    url: str
    mime_type: str
    id: Optional[str] = None
    size_bytes: Optional[int] = None
    kind: str = "file"
    voice: bool = False
    duration_ms: Optional[int] = None
    peaks: Optional[List[float]] = None
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "Attachment":
        mime = raw.get("mime_type") or "application/octet-stream"
        return cls(raw.get("name") or "", raw.get("url") or "", mime, raw.get("id"), raw.get("size_bytes"),
                   raw.get("kind") or _kind(mime), bool(raw.get("voice")), raw.get("duration_ms"), raw.get("peaks"),
                   raw, parse_time(raw.get("created_at")), parse_time(raw.get("updated_at")))


def _kind(mime: str) -> str:
    top = mime.split("/", 1)[0]
    return top if top in ("image", "audio", "video") else "file"


def file_bytes(file: Any, name: Optional[str]) -> tuple:
    """``(bytes, name)`` of a path, bytes or a binary file object."""
    if isinstance(file, (str, os.PathLike)):
        with open(file, "rb") as handle:
            return handle.read(), name or os.path.basename(os.fspath(file))
    if isinstance(file, (bytes, bytearray, memoryview)):
        if not name:
            raise TypeError("Name a file you upload as bytes: name='report.pdf'.")
        return bytes(file), name
    if hasattr(file, "read"):
        found = name or os.path.basename(str(getattr(file, "name", "") or ""))
        if not found:
            raise TypeError("Name a file object without one: name='report.pdf'.")
        return bytes(file.read()), found
    raise TypeError(f"A file is a path, bytes or a binary file object, not {type(file).__name__}.")


async def upload(request: Callable[..., Awaitable[Any]], path: str, file: Any, *, name: Optional[str],
                 mime_type: Optional[str], voice: bool, peaks: Optional[Sequence[float]]) -> Attachment:
    """POST ``file`` to an ``attachments`` route."""
    data, name = file_bytes(file, name)
    params = compact(name=name, mime_type=mime_type or mimetypes.guess_type(name)[0],
                     voice="true" if voice else None, peaks=",".join(f"{p:g}" for p in peaks) if peaks else None)
    return Attachment._from(await request("POST", path, params=params, content=data) or {})


async def attachment_ids(files: Sequence[Any], upload_one: Callable[[Any], Awaitable[Attachment]]) -> List[str]:
    """``files`` as the ids a message sends: an uploaded ``Attachment`` as it is, anything else (a path, bytes, a
    binary file object) uploaded first. More than ``MAX_FILES`` is refused before anything is uploaded, as the
    API would refuse the message, so no file is left uploaded and never sent."""
    if len(files) > MAX_FILES:
        raise InvalidRequest(f"A message carries at most {MAX_FILES} files.", details={"field": "attachments"},
                             next_step="Send the rest in another message.")
    ids = []
    for f in files:
        if isinstance(f, Attachment) and f.id:
            ids.append(f.id)
        else:
            ids.append((await upload_one(f)).id)
    return ids


@synced
async def attachments(*, query: Optional[str] = None, limit: int = 30,
                      client: Optional[Client] = None) -> List[Attachment]:
    """The account's files, newest first: what its messages carried, the images
    and videos it made, its calls' recordings, what its browsers downloaded and the
    pages they stopped on. A message to an agent sends any of them again in its
    ``files``. The account's alone: read as a user, it's refused.

    Args:
        query: Keeps the files whose names contain it (any case).
        limit: How many, 1 to 100.

    Returns:
        Each file as an ``Attachment`` with its ``id``, ``name``, ``url`` (a link that reads it for an hour),
        ``mime_type`` and ``kind``.

    Usage::

        [report] = noclick.attachments(query="q3")
        analyst.message("What changed since this?", files=[report])
    """
    page = await resolve_client(client).request("GET", "/v1/attachments", params=compact(query=query, limit=limit),
                                                user=None) or {}
    return [Attachment._from(f) for f in page.get("data") or []]


@synced
async def attachments_page(*, query: Optional[str] = None, cursor: Optional[str] = None, limit: Optional[int] = None,
                           client: Optional[Client] = None) -> Page:
    """One page of the account's files, newest first; pass ``next_cursor`` back as ``cursor``.

    Returns:
        A page whose ``data`` holds each ``Attachment`` and whose ``next_cursor`` is ``None`` on the last page.

    Usage::

        page = noclick.attachments_page(limit=50)
        while True:
            for file in page.data:
                print(file.name, file.size_bytes)
            if page.next_cursor is None:
                break
            page = noclick.attachments_page(limit=50, cursor=page.next_cursor)
    """
    page = await fetch_page(resolve_client(client), "/v1/attachments", params=compact(query=query), user=None,
                            cursor=cursor, limit=limit)
    return Page([Attachment._from(f) for f in page.data], page.next_cursor)


@synced
async def delete_attachment(attachment: Any, *, client: Optional[Client] = None) -> None:
    """Delete one of the account's files for good (an ``Attachment`` or its id):
    its record and what it stored, with no trash to restore it from. A message
    that carried it keeps its name, and its link stops working. The account's
    own to do: acting for one of your users, or from an app's code, it's refused.

    Usage::

        for file in noclick.attachments(query="draft"):
            noclick.delete_attachment(file)
    """
    attachment_id = attachment.id if isinstance(attachment, Attachment) else attachment
    if not attachment_id:
        raise TypeError("Pass one of the account's files (from noclick.attachments()) or its id.")
    await resolve_client(client).request("DELETE", f"/v1/attachments/{quote(str(attachment_id), safe='')}",
                                         user=None)
