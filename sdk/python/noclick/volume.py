"""Volumes: a persistent filesystem you mount into sandboxes and agents.

    vol = noclick.Volume.from_name("datasets", create_if_missing=True)
    vol.write("/raw/orders.csv", csv_bytes)
    with noclick.Sandbox.create(volumes={"/data": vol}) as sb:
        sb.exec("python train.py --data /data/raw")

Paths start at the volume's root (``/raw/orders.csv``). Folders are real folders,
made as files are written into them. What a sandbox or an agent's turn writes is
saved every few seconds while it runs, and all of it when it ends; two writers to one
file at once: the last one to finish wins.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field as dc_field
from typing import Any, BinaryIO, Dict, List, Mapping, Optional, Union
from urllib.parse import quote

from ._client import Client, resolve_client
from ._designed import designed_params
from ._object import (
    Page, _Object, compact, fetch_page, field, list_all, list_page, paginate, parse_time, ref_id,
)
from ._sync import synced
from .trash import TrashItem, trashed
from ._scope import AMBIENT, resolve_scope
from .exceptions import Conflict, NotFound
from .export import ExportBundle
from .operation import Operation, register_result

Data = Union[bytes, bytearray, memoryview, str, BinaryIO]


@dataclass(frozen=True)
class VolumeEntry:
    """A file or folder in a volume: its ``path`` from the volume's root, its
    ``type`` (``file`` or ``directory``), a file's ``size`` in bytes (None for a
    folder) and when it last changed (``updated_at``)."""

    path: str
    type: str
    size: Optional[int]
    updated_at: Any
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "VolumeEntry":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            path=raw.get("path") or "",
            type=raw.get("type") or "file",
            size=raw.get("size"),
            updated_at=parse_time(raw.get("updated_at")),
            raw=raw,
        )


def _read_export(result: Any, op: Operation) -> ExportBundle:
    return ExportBundle._from(result)


register_result("volume.export", _read_export)


def _content(data: Data) -> bytes:
    if isinstance(data, str):
        return data.encode()
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    if hasattr(data, "read"):
        return bytes(data.read())
    raise TypeError(f"write() takes bytes, text or a binary file, not {type(data).__name__}.")


def is_id(value: str) -> bool:
    """Whether a string is shaped like a NoClick id (a UUID) rather than a name."""
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def volume_refs(volumes: Any, *, user: Any, client: Optional[Client]) -> Optional[Dict[str, Any]]:
    """``volumes=`` on a sandbox or agent: ``{mount path: Volume, id or name}``. A name is
    looked up lazily in ``user`` (its own volume first, then the account's)."""
    if volumes is None:
        return None
    if not isinstance(volumes, Mapping):
        raise TypeError('volumes= maps a mount path to a volume: {"/data": noclick.Volume.from_name("datasets")}')
    refs: Dict[str, Any] = {}
    for path, volume in volumes.items():
        if isinstance(volume, Volume) or (isinstance(volume, str) and is_id(volume)):
            refs[path] = volume
        elif isinstance(volume, str):
            refs[path] = Volume.from_name(volume, user=user, client=client)
        else:
            raise TypeError(f"Mount a noclick.Volume, a volume id or its name at {path!r}, not {type(volume).__name__}")
    return refs


async def volume_ids(refs: Mapping[str, Any]) -> Dict[str, str]:
    """``{mount path: volume id}``, as the API takes it."""
    return {path: await ref_id(volume) for path, volume in sorted(refs.items())}


class Volume(_Object):
    """A persistent filesystem: files by path, in folders, that outlive the
    sandbox or agent turn that wrote them. Mount it with
    ``Sandbox.create(volumes={"/data": vol})`` or ``Agent.from_name(..., volumes=...)``,
    or read and write it from your own code."""

    _repr_keys = ("id", "name")

    id: str = field("id")
    name: str = field("name")
    size_bytes: Optional[int] = field("size_bytes")
    file_count: Optional[int] = field("file_count")
    mounted_by: List[Dict[str, Any]] = field(
        "mounted_by",
        doc="The running sandboxes, the agents and the machines that mount it: ``kind`` (``sandbox``, "
            "``agent`` or ``machine``), ``id``, ``name`` (an agent's or a machine's) and the mount ``path``.",
    )
    region: Optional[str] = field(
        "region", doc="Always ``None`` for now: volumes aren't placed by region yet (``region=`` is in invite-only beta).",
    )
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    @property
    def console_url(self) -> Optional[str]:
        """This volume in the developer console (None off the hosted API)."""
        base = self._api.console_url("resources", "volumes")
        return f"{base}?volume={quote(str(self._known('id')), safe='')}" if base and self._known("id") else base

    # --- construction ----------------------------------------------------

    @designed_params("region")
    @synced
    @classmethod
    async def create(
        cls, name: str, *, region: Optional[str] = None, allow_existing: bool = False, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Volume":
        """Create an empty volume called ``name`` (1-64 letters, digits and
        ``. _ -``), unique to its user (a taken name raises ``noclick.Conflict``
        with ``existing_id``, or with ``allow_existing=True`` returns the volume already there,
        files and all).

        Invite-only beta: ``region`` (``noclick.regions()``), where its
        files are kept. The sandbox provider's volumes take no location yet, so
        passing one raises ``noclick.NotAvailable``; a sandbox or agent in any
        region mounts a volume.

        Returns:
            The new, empty volume.

        Usage:
            An empty volume::

                cache = noclick.Volume.create("build-cache")
                print(cache.id, cache.size_bytes)   # ... 0

            One per user, for what their sandboxes build::

                with noclick.as_user("user_42"):
                    work = noclick.Volume.create("workbench")
                    print(work.user_id)   # user_42
        """
        scope = resolve_scope(user)
        raw = await cls._create_named("/v1/volumes", compact(name=name, region=region), allow_existing=allow_existing,
                                      user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @designed_params("region")
    @classmethod
    def from_name(
        cls, name: str, *, create_if_missing: bool = False, region: Optional[str] = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Volume":
        """A lazy reference to the volume called ``name``. Acting for a user, that
        user's own volume is found first, then the account's (every user's
        sandboxes and agents can mount those). With ``create_if_missing=True`` the
        current (or given) user's is created on first use.
        Invite-only beta: ``region`` (see ``create``).

        Returns:
            A volume that loads (or is created) the first time it's used. Nothing is sent yet.

        Usage:
            Name it in your code; the first run creates it::

                vol = noclick.Volume.from_name("datasets", create_if_missing=True)
                vol.write("/raw/orders.csv", b"id,total\\no_1,42\\n")

            A volume per user, for what their sandboxes build::

                with noclick.as_user("user_42"):
                    work = noclick.Volume.from_name("workbench", create_if_missing=True)
                    print(work.listdir("/"))
        """
        volume = cls._new(hints={"name": name}, client=client, user=user)
        if create_if_missing:
            volume._create_with = compact(name=name, region=region)
        return volume

    @classmethod
    def from_id(cls, volume_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Volume":
        """A lazy reference to a volume by id.

        Returns:
            A volume that loads the first time you read a field. Nothing is sent yet.

        Usage::

            vol = noclick.Volume.from_id("4c8e1f0a-6b3d-4a92-9e57-1d2f8b0c7a36")
            data = vol.read("/raw/orders.csv")
        """
        return cls._new(hints={"id": volume_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, volume_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Volume":
        """Load a volume by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The volume, loaded: its size, how many files it holds, and who mounts it.

        Usage::

            vol = noclick.Volume.get("4c8e1f0a-6b3d-4a92-9e57-1d2f8b0c7a36")
            print(vol.name, vol.size_bytes, vol.file_count, vol.mounted_by)
        """
        volume = cls.from_id(volume_id, client=client, user=user)
        await volume._ensure()
        return volume

    @synced
    @classmethod
    async def list(
        cls, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Volume"]:
        """The current user's volumes and the account's (or those ``user_filter`` covers).

        Returns:
            Every matching volume, newest first, fetched page by page.

        Usage::

            for vol in noclick.Volume.list():
                print(vol.name, vol.size_bytes, vol.user_id)   # user_id is None for the account's

            everyone = noclick.Volume.list(user_filter=noclick.ALL_USERS)   # every user's, plus your account's
        """
        return await list_all(
            "/v1/volumes", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of volumes; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the volumes and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Volume.list_page(limit=50)
            while True:
                for vol in page.data:
                    print(vol.name, vol.file_count)
                if page.next_cursor is None:
                    break
                page = noclick.Volume.list_page(limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/volumes", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        volume_id = self._known("id")
        if volume_id:
            return await self._request("GET", f"/v1/volumes/{volume_id}")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/volumes", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        # This scope's own volume first; a definition is only ever for its own.
        own = [row for row in rows if bool(row.get("user_id")) == bool(self._scope)]
        rows = own if self._create_with is not None else own + [row for row in rows if row not in own]
        if rows:
            return rows[0]
        if self._create_with is None:
            raise NotFound(
                f"No volume is named {name!r}.",
                next_step="Create it with noclick.Volume.create(...) or pass create_if_missing=True.",
                details={"name": name},
            )
        try:
            return await self._request("POST", "/v1/volumes", json=self._create_with)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._request("GET", f"/v1/volumes/{exc.existing_id}")

    async def _url(self, suffix: str = "") -> str:
        """This volume's route; a reference by name is looked up (or created) first."""
        if not self._known("id"):
            await self._ensure()
        return f"/v1/volumes/{self._known('id')}{suffix}"

    # --- files -----------------------------------------------------------

    @synced
    async def write(self, path: str, data: Data) -> VolumeEntry:
        """Write ``data`` (bytes, text as UTF-8, or a binary file) to ``path``,
        replacing the file there and making any folders it needs. It's saved at
        once: a sandbox or agent that mounts the volume after this sees it. One
        ``write`` carries up to 100 MB; make bigger files inside a sandbox that
        mounts the volume.

        Returns:
            The file as written, with its ``size``.

        Usage:
            Put a dataset where your sandboxes will read it::

                vol = noclick.Volume.from_name("datasets", create_if_missing=True)
                entry = vol.write("/raw/orders.csv", b"id,total\\no_1,42\\n")
                print(entry.path, entry.size)

            Upload a file from disk::

                vol = noclick.Volume.from_name("datasets")
                with open("model.bin", "rb") as f:
                    vol.write("/models/model.bin", f)
        """
        raw = await self._request("PUT", await self._url("/files"), params={"path": path}, content=_content(data))
        return VolumeEntry._from(raw)

    @synced
    async def read(self, path: str) -> bytes:
        """Read the file at ``path``, as the volume last saved it, up to 100 MB; a
        missing file raises ``noclick.NotFound``, a folder or a bigger file
        ``noclick.InvalidRequest``.

        Returns:
            The file's bytes, exactly as stored; decode text yourself.

        Usage::

            vol = noclick.Volume.from_name("datasets")
            report = vol.read("/out/report.csv").decode()
            print(report.splitlines()[0])
        """
        return await self._request("GET", await self._url("/files"), params={"path": path}, binary=True)

    @synced
    async def listdir(self, path: str = "/", *, recursive: bool = False, limit: Optional[int] = None) -> List[VolumeEntry]:
        """What's in the folder at ``path``, in path order: its files and folders,
        or with ``recursive=True`` everything below it. A path that doesn't exist
        raises ``noclick.NotFound``.

        Returns:
            Every entry (or the first ``limit``), fetched page by page.

        Usage:
            One folder, like ``ls``::

                vol = noclick.Volume.from_name("datasets")
                for entry in vol.listdir("/raw"):
                    print(entry.path, entry.type, entry.size)

            Every file under a folder::

                vol = noclick.Volume.from_name("datasets")
                files = [e for e in vol.listdir("/", recursive=True) if e.type == "file"]
                print(len(files), sum(e.size or 0 for e in files))
        """
        rows = await paginate(
            self._api, await self._url("/files"), params=self._list_params(path, recursive),
            user=self._call_scope(), limit=limit,
        )
        return [VolumeEntry._from(row) for row in rows]

    @synced
    async def listdir_page(
        self, path: str = "/", *, recursive: bool = False, cursor: Optional[str] = None, limit: Optional[int] = None,
    ) -> Page:
        """One page of ``listdir``; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds ``VolumeEntry``s and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            vol = noclick.Volume.from_name("datasets")
            page = vol.listdir_page("/raw", limit=100)
            while True:
                for entry in page.data:
                    print(entry.path, entry.size)
                if page.next_cursor is None:
                    break
                page = vol.listdir_page("/raw", limit=100, cursor=page.next_cursor)
        """
        page = await fetch_page(
            self._api, await self._url("/files"), params=self._list_params(path, recursive),
            user=self._call_scope(), cursor=cursor, limit=limit,
        )
        return Page([VolumeEntry._from(row) for row in page.data], page.next_cursor)

    @staticmethod
    def _list_params(path: str, recursive: bool) -> Dict[str, Any]:
        return compact(path=path, view="list", recursive="true" if recursive else None)

    @synced
    async def remove(self, path: str, *, recursive: bool = False) -> None:
        """Delete the file or folder at ``path``. A folder that isn't empty needs
        ``recursive=True`` (otherwise ``noclick.Conflict``); a path that isn't
        there does nothing.

        Usage::

            vol = noclick.Volume.from_name("datasets")
            vol.remove("/raw/orders.csv")
            vol.remove("/tmp", recursive=True)
        """
        params = {"path": path, **({"recursive": "true"} if recursive else {})}
        await self._request("DELETE", await self._url("/files"), params=params)

    @synced
    async def copy(self, src: str, dst: str) -> VolumeEntry:
        """Copy the file or folder at ``src`` to ``dst`` in this volume (a folder
        with everything in it), replacing what ``dst`` held.

        Returns:
            The copy at ``dst``.

        Usage::

            vol = noclick.Volume.from_name("datasets")
            vol.copy("/raw/orders.csv", "/archive/2026-09/orders.csv")
        """
        return VolumeEntry._from(await self._request("POST", await self._url("/copy"), json={"src": src, "dst": dst}))

    # --- export and delete -----------------------------------------------

    @synced
    async def export(self) -> Operation:
        """Export every file, so the volume can move anywhere: a zip holding them
        in their folders (under ``volumes/<name>/files/``), with ``index.jsonl``
        listing each path, its size and when it last changed.

        Returns:
            An operation whose ``wait()`` gives an ``ExportBundle``: the zip at ``url``, valid 7 days.

        Usage::

            vol = noclick.Volume.from_name("datasets")
            bundle = vol.export().wait()
            print(bundle.url, bundle.expires_at)
        """
        payload = await self._request("POST", await self._url("/export"))
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="volume.export", reader=_read_export,
        )

    @synced
    async def delete(self) -> TrashItem:
        """Delete the volume and every file in it: it goes to the trash, restorable for 30 days (its files
        stored, and billed, until it's purged). While a running sandbox, an
        agent or a machine mounts it (``mounted_by``), this raises ``noclick.Conflict``:
        take it out of the agent's or machine's ``volumes`` and let the sandboxes end first. A user
        can't delete the account's volumes (``noclick.PermissionDenied``).

        Returns:
            Its ``TrashItem``: ``restore()`` puts it back.

        Usage::

            noclick.Volume.from_name("build-cache").delete()
        """
        raw = await self._request("DELETE", await self._url())
        return trashed(raw, client=self._client, user=self._call_scope())
