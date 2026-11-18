"""Files on messages: an agent's and a channel's, uploaded first and sent once; sent, the account's files."""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass, field as dc_field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from ._client import Client, resolve_client
from ._object import compact
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
    account's files (``noclick.attachments()``) have their ``id``, to send again."""

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

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "Attachment":
        mime = raw.get("mime_type") or "application/octet-stream"
        return cls(raw.get("name") or "", raw.get("url") or "", mime, raw.get("id"), raw.get("size_bytes"),
                   raw.get("kind") or _kind(mime), bool(raw.get("voice")), raw.get("duration_ms"), raw.get("peaks"),
                   raw)


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
    and videos it made, its calls' recordings. A message to an agent sends any of
    them again in its ``files``. The account's alone: read as a user, it's refused.

    Args:
        query: Keeps the files whose names contain it (any case).
        limit: How many, 1 to 100.

    Returns:
        Each file as an ``Attachment`` with its ``id``, ``name``, ``url``, ``mime_type`` and ``kind``.

    Usage::

        [report] = noclick.attachments(query="q3")
        analyst.message("What changed since this?", files=[report])
    """
    page = await resolve_client(client).request("GET", "/v1/attachments", params=compact(query=query, limit=limit),
                                                user=None) or {}
    return [Attachment._from(f) for f in page.get("data") or []]
