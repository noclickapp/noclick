"""Buckets: files by key, private by default, with signed links and an S3-compatible escape hatch.

    bucket = noclick.Bucket.from_name("uploads", create_if_missing=True)
    bucket.put("invoices/0042.pdf", pdf_bytes, content_type="application/pdf")
    link = bucket.signed_url("invoices/0042.pdf", expires_in=3600)

A key is a path-like name (``invoices/0042.pdf``); ``/`` separates folders only
by convention, so listing with ``delimiter="/"`` shows them as folders.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from typing import Any, BinaryIO, Dict, Iterable, List, Literal, Mapping, Optional, Union
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import (
    Page, _Object, bound_arguments, compact, fetch_page, field, list_all, list_page, paginate, parse_time,
    ref_id, tool_entries,
)
from ._sync import synced
from .trash import TrashItem, trashed
from ._scope import AMBIENT, resolve_scope
from .exceptions import Conflict, NotAvailable, NotFound
from .export import ExportBundle
from .operation import Operation, register_result

Data = Union[bytes, bytearray, memoryview, str, BinaryIO]


@dataclass(frozen=True)
class BucketObject:
    """A file in a bucket: its ``key``, ``size`` in bytes, ``content_type``, ``etag``
    (it changes whenever the content does), the ``metadata`` you gave it and
    ``updated_at``. In a listing with a ``delimiter``, an entry whose ``is_folder``
    is true stands for every key under that prefix, and only its ``key`` is set."""

    key: str
    size: Optional[int]
    content_type: Optional[str]
    etag: Optional[str]
    metadata: Dict[str, str]
    updated_at: Any
    is_folder: bool = False
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "BucketObject":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            key=raw.get("key") or "",
            size=raw.get("size"),
            content_type=raw.get("content_type"),
            etag=raw.get("etag"),
            metadata=dict(raw.get("metadata") or {}),
            updated_at=parse_time(raw.get("updated_at")),
            is_folder=bool(raw.get("folder")),
            raw=raw,
        )


@dataclass(frozen=True)
class ObjectVersion:
    """What a file held before a write through NoClick replaced it (``op`` ``changed``) or removed it
    (``deleted``), kept 30 days. An upload through a signed link or S3 credentials keeps none."""

    id: str
    key: str
    op: str
    size: Optional[int]
    replaced_at: Any
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ObjectVersion":
        return cls(id=raw["id"], key=raw["key"], op=raw["op"], size=raw.get("size"),
                   replaced_at=parse_time(raw.get("replaced_at")), raw=raw)


@dataclass(frozen=True)
class BucketUpload:
    """A file being uploaded in parts (``Bucket.start_upload``): its ``key`` and
    ``upload_id``, which the other upload calls take, its ``content_type``, and
    the parts it takes: each ``min_part_bytes`` (5 MiB) to ``max_part_bytes``
    (5 GiB), every part but the last the same size, up to ``max_parts``
    (10,000)."""

    key: str
    upload_id: str
    content_type: Optional[str]
    min_part_bytes: int
    max_part_bytes: int
    max_parts: int
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "BucketUpload":
        raw = raw if isinstance(raw, dict) else {}
        return cls(key=raw.get("key") or "", upload_id=raw.get("upload_id") or "",
                   content_type=raw.get("content_type"), min_part_bytes=int(raw.get("min_part_bytes") or 0),
                   max_part_bytes=int(raw.get("max_part_bytes") or 0), max_parts=int(raw.get("max_parts") or 0),
                   raw=raw)


#: Part links signed in one request; ``upload_part_urls`` sends as many requests as it needs.
_PART_LINKS_PER_CALL = 1000


@dataclass(frozen=True)
class S3Credentials:
    """Short-lived keys for the bucket's S3-compatible endpoint, for tools that
    speak S3 (rclone, the AWS CLI, boto3). They reach this bucket only (read-only
    if you asked) and stop working at ``expires_at``. Give the tool all of
    ``endpoint``, ``access_key_id``, ``secret_access_key`` and ``session_token``,
    with ``region``; ``bucket`` is the bucket's name on that endpoint, which isn't
    its NoClick name. Keys are a person's: an app's deployed code gets none, and
    uploads a file of any size in parts (``Bucket.start_upload``) instead."""

    endpoint: str
    bucket: str
    access_key_id: str
    secret_access_key: str = dc_field(repr=False)
    session_token: Optional[str] = dc_field(repr=False)
    region: str
    read_only: bool
    expires_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "S3Credentials":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            endpoint=raw.get("endpoint") or "",
            bucket=raw.get("bucket") or "",
            access_key_id=raw.get("access_key_id") or "",
            secret_access_key=raw.get("secret_access_key") or "",
            session_token=raw.get("session_token"),
            region=raw.get("region") or "auto",
            read_only=bool(raw.get("read_only")),
            expires_at=parse_time(raw.get("expires_at")),
            raw=raw,
        )


def _read_export(result: Any, op: Operation) -> ExportBundle:
    return ExportBundle._from(result)


register_result("bucket.export", _read_export)

#: What an agent, a toolkit or a hosted MCP server may do with a bucket, each a tool of its own.
BUCKET_TOOLS = ("objects", "head", "put", "signed_url", "remove")


@dataclass(frozen=True)
class BucketOperations:
    """Some of a bucket's operations as tools (``bucket.only(...)``), with the
    arguments ``bind(...)`` fixed."""

    bucket: "Bucket"
    operations: List[str]
    #: The arguments NoClick fills on every call, out of the model's reach.
    bindings: Dict[str, Any] = dc_field(default_factory=dict)

    def bind(self, **arguments: Any) -> "BucketOperations":
        """Fix arguments of these operations, as ``ConnectionOperations.bind`` does:
        a bound parameter leaves the tool's schema and NoClick fills it on every call.
        ``prefix`` is the one to bind here: every key the tools take and return is
        then under it, so one bucket can hold a folder per user
        (``prefix="users/{{user.id}}/"``). Sends nothing.

        Returns:
            A new ref with these arguments bound on top of any bound before.

        Usage::

            uploads = noclick.Bucket.from_name("uploads")
            assistant = noclick.Agent.from_name(
                "assistant",
                create_if_missing=True,
                instructions="You file what the user sends you and share links to it.",
                tools=[uploads.only("objects", "put", "signed_url").bind(prefix="users/{{user.id}}/")],
            )
        """
        return BucketOperations(self.bucket, list(self.operations), {**self.bindings, **bound_arguments(arguments)})

    async def _tool_refs(self, scope: Any) -> List[Any]:
        return tool_entries(f"bucket:{await ref_id(self.bucket)}", self.operations, self.bindings)


def _content(data: Data) -> bytes:
    if isinstance(data, str):
        return data.encode()
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    if hasattr(data, "read"):
        return bytes(data.read())
    raise TypeError(f"put() takes bytes, text or a binary file, not {type(data).__name__}.")


class Bucket(_Object):
    """A bucket of files by key. Private by default: files are reached through
    this client, a ``signed_url`` or S3 credentials. A public bucket also serves
    every file at ``url(key)``."""

    _repr_keys = ("id", "name", "public")

    id: str = field("id")
    name: str = field("name")
    public: bool = field("public", doc="Whether every file is readable at ``url(key)`` without a link.")
    size_bytes: Optional[int] = field("size_bytes")
    object_count: Optional[int] = field("object_count")
    public_base_url: Optional[str] = field(
        "public_base_url", doc="Where a public bucket serves its files (None while it's private).",
    )
    used_by: List[Dict[str, Any]] = field(
        "used_by",
        doc="Who uses it: apps that bind it (``kind`` ``project``, with the ``binding`` name) and agents with it "
        "in their tools (``kind`` ``agent``), each with its ``id`` and ``name``.",
    )
    notifications: List[Dict[str, Any]] = field(
        "notifications",
        doc="Where it tells about new files (``notify``): each with the ``queue`` (its name) and ``prefix`` (None "
            "for every file).",
    )
    region: Optional[str] = field(
        "region", doc="The region it keeps its files in (``noclick.regions()``), fixed when it was created.",
    )
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    @property
    def console_url(self) -> Optional[str]:
        """This bucket in the developer console (None off the hosted API)."""
        base = self._api.console_url("resources", "storage")
        return f"{base}?bucket={quote(str(self._known('id')), safe='')}" if base and self._known("id") else base

    def only(self, *operations: str) -> BucketOperations:
        """A tool ref to some of its operations, for ``tools=``: ``"objects"`` (list
        keys under a prefix), ``"head"`` (one file's size, type and metadata),
        ``"put"`` (store a file from a ``url`` or from ``text``, with a content type and
        metadata; the model never handles bytes), ``"signed_url"`` (a link that reads a
        file, to hand a person) and ``"remove"``. The bucket itself in an agent's
        ``tools=`` gives all five, as ``{name}__objects`` and so on. Its calls follow
        your policy as ``bucket.objects``, ``bucket.put`` and the rest (``bucket.*``). A
        file the agent's browser downloads comes back to it as a signed URL, which
        ``put`` stores from ``url``. An agent may use its own scope's buckets and the
        account's. In a toolkit or a hosted MCP server, a bucket is in invite-only
        beta.

        Returns:
            A ref to just those operations, to list in ``tools=``; ``bind(...)`` fixes arguments.

        Usage::

            reports = noclick.Bucket.from_name("reports")
            analyst = noclick.Agent.from_name(
                "analyst",
                create_if_missing=True,
                instructions="You write the weekly report, save it, and share a link to it.",
                tools=[reports.only("put", "signed_url"), "search"],
            )
        """
        unknown = [op for op in operations if op not in BUCKET_TOOLS]
        if not operations or unknown:
            raise ValueError(f"only() takes some of {', '.join(BUCKET_TOOLS)}, not {', '.join(unknown) or 'nothing'}")
        return BucketOperations(self, list(operations))

    async def _tool_refs(self, scope: Any) -> List[Any]:
        return [f"bucket:{await ref_id(self)}"]

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls, name: str, *, public: bool = False, region: Optional[str] = None, allow_existing: bool = False,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> "Bucket":
        """Create a bucket called ``name``, unique to its user (a taken name raises
        ``noclick.Conflict`` with ``existing_id``, or with ``allow_existing=True`` returns
        the bucket already there, as it is). ``public=True`` serves every
        file at a plain URL. ``region`` (``noclick.regions()``) is where its files
        are kept, for good; without one, your account's default region, else
        ``us-east``. Object storage takes it as a location hint: the bucket is
        made there when the store has room there, which is a placement, not a
        legal promise of residency. A name is 1-64 letters, digits and ``. _ -``.

        Returns:
            The new, empty bucket.

        Usage:
            Private files your app hands out by signed link::

                uploads = noclick.Bucket.create("uploads")

            Public assets, such as images on a site::

                assets = noclick.Bucket.create("public-assets", public=True)
                print(assets.public_base_url)

            Files that stay in Europe::

                records = noclick.Bucket.create("patient-records", region="eu")
        """
        scope = resolve_scope(user)
        raw = await cls._create_named("/v1/buckets", {"name": name, "public": public, **compact(region=region)},
                                      allow_existing=allow_existing, user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls, name: str, *, create_if_missing: bool = False, public: bool = False, region: Optional[str] = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> "Bucket":
        """A lazy reference to the bucket called ``name`` in the current (or given)
        user. With ``create_if_missing=True`` it's created on first use (in ``region``,
        as ``create``); one that exists is used as it is (change it with ``update``).

        Inside a deployed app (signed in by its deployment) the name is looked up in the app's own
        namespace for the environment the code runs in, and one made there is the app's: a name bound to
        the app by hand wins, and in a preview of an app whose ``preview_resources`` is ``branch`` the
        branch gets an overlay at its first write: what it writes is its own, and it reads
        production's files through it, so a preview never changes production's data.

        Returns:
            A bucket that loads (or is created) the first time it's used. Nothing is sent yet.

        Usage:
            Name it in your code; the first run creates it::

                bucket = noclick.Bucket.from_name("uploads", create_if_missing=True)
                bucket.put("hello.txt", "hi")

            A bucket per user, for what their agent saves::

                with noclick.as_user("user_42"):
                    files = noclick.Bucket.from_name("assistant-files", create_if_missing=True)
                    print(files.objects(prefix="receipts/"))
        """
        bucket = cls._new(hints={"name": name}, client=client, user=user)
        if create_if_missing:
            bucket._create_with = {"name": name, "public": public, **compact(region=region)}
        return bucket

    @classmethod
    def from_id(cls, bucket_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Bucket":
        """A lazy reference to a bucket by id.

        Returns:
            A bucket that loads the first time you read a field. Nothing is sent yet.

        Usage::

            bucket = noclick.Bucket.from_id("8d1f3b27-5a6e-4c09-b2d8-9e4a7c1f0b35")
            data = bucket.read("invoices/0042.pdf")
        """
        return cls._new(hints={"id": bucket_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, bucket_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Bucket":
        """Load a bucket by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The bucket, loaded: whether it's public, how many files it holds and their total size.

        Usage::

            bucket = noclick.Bucket.get("8d1f3b27-5a6e-4c09-b2d8-9e4a7c1f0b35")
            print(bucket.name, bucket.public, bucket.object_count, bucket.size_bytes)
        """
        bucket = cls.from_id(bucket_id, client=client, user=user)
        await bucket._ensure()
        return bucket

    @synced
    @classmethod
    async def list(
        cls, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Bucket"]:
        """The current user's buckets (the account's own outside ``as_user``, or those ``user_filter`` covers).

        Returns:
            Every matching bucket, newest first, fetched page by page.

        Usage::

            for bucket in noclick.Bucket.list():
                print(bucket.name, bucket.public, bucket.size_bytes)

            everyone = noclick.Bucket.list(user_filter=noclick.ALL_USERS)   # every user's, plus your account's
        """
        return await list_all(
            "/v1/buckets", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of buckets; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the buckets and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Bucket.list_page(limit=50)
            while True:
                for bucket in page.data:
                    print(bucket.name, bucket.object_count)
                if page.next_cursor is None:
                    break
                page = noclick.Bucket.list_page(limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/buckets", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        bucket_id = self._known("id")
        if bucket_id:
            return await self._request("GET", f"/v1/buckets/{bucket_id}")
        name = self._hints["name"]
        found = await self._in_app("bucket", name, self._create_with)
        if found is not None:
            return found
        page = await self._request("GET", "/v1/buckets", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        if rows:
            return rows[0]
        if self._create_with is None:
            raise NotFound(
                f"No bucket is named {name!r}.",
                next_step="Create it with noclick.Bucket.create(...) or pass create_if_missing=True.",
                details={"name": name},
            )
        try:
            return await self._request("POST", "/v1/buckets", json=self._create_with)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._request("GET", f"/v1/buckets/{exc.existing_id}")

    async def _url(self, suffix: str = "") -> str:
        """This bucket's route; a reference by name is looked up (or created) first."""
        if not self._known("id"):
            await self._ensure()
        return f"/v1/buckets/{self._known('id')}{suffix}"

    # --- files -----------------------------------------------------------

    @synced
    async def put(
        self, key: str, data: Data, *, content_type: Optional[str] = None, metadata: Optional[Mapping[str, str]] = None,
    ) -> BucketObject:
        """Store ``data`` (bytes, text as UTF-8, or a binary file) at ``key``,
        replacing what was there. ``content_type`` is guessed from the key's
        extension when omitted; ``metadata`` is up to 2 KB of your own ASCII
        string pairs (names come back lowercased), returned with the file. One
        ``put`` carries up to 100 MB; send
        larger files straight from where they are with a ``PUT`` signed link.

        Returns:
            The file as stored, with its ``size`` and ``etag``.

        Usage:
            Store what your code made::

                bucket = noclick.Bucket.from_name("uploads", create_if_missing=True)
                stored = bucket.put("invoices/0042.pdf", b"%PDF-1.7 ...", content_type="application/pdf")
                print(stored.size, stored.etag)

            Upload a file from disk, with metadata your app reads back later::

                bucket = noclick.Bucket.from_name("uploads")
                with open("report.csv", "rb") as f:
                    bucket.put("reports/2026-09.csv", f, metadata={"user": "acme", "source": "nightly"})
        """
        params = compact(
            key=key, content_type=content_type, metadata=json.dumps(dict(metadata)) if metadata else None,
        )
        raw = await self._request("PUT", await self._url("/objects"), params=params, content=_content(data))
        return BucketObject._from(raw)

    @synced
    async def read(self, key: str) -> bytes:
        """Read the file at ``key``; a missing key raises ``noclick.NotFound``.

        Returns:
            The file's bytes, exactly as stored; decode text yourself.

        Usage::

            bucket = noclick.Bucket.from_name("uploads")
            pdf = bucket.read("invoices/0042.pdf")
            with open("0042.pdf", "wb") as f:
                f.write(pdf)
        """
        return await self._request("GET", await self._url("/objects"), params={"key": key}, binary=True)

    @synced
    async def head(self, key: str) -> BucketObject:
        """Look a file up without downloading it; a missing key raises ``noclick.NotFound``.

        Returns:
            The file's size, content type, etag, metadata and when it last changed.

        Usage::

            bucket = noclick.Bucket.from_name("uploads")
            info = bucket.head("invoices/0042.pdf")
            print(info.size, info.content_type, info.metadata)
        """
        raw = await self._request("GET", await self._url("/objects"), params={"key": key, "view": "metadata"})
        return BucketObject._from(raw)

    @synced
    async def objects(
        self, prefix: Optional[str] = None, *, delimiter: Optional[str] = None, limit: Optional[int] = None,
    ) -> List[BucketObject]:
        """The files whose keys start with ``prefix``, in key order. With
        ``delimiter="/"``, keys below the next ``/`` are rolled up into one folder
        entry each (``is_folder``), so you can walk the bucket a level at a time.

        Returns:
            Every matching file (or the first ``limit``), fetched page by page.

        Usage:
            Everything under a prefix::

                bucket = noclick.Bucket.from_name("uploads")
                for obj in bucket.objects(prefix="invoices/"):
                    print(obj.key, obj.size, obj.updated_at)

            One level at a time, like a file browser::

                bucket = noclick.Bucket.from_name("uploads")
                for entry in bucket.objects(prefix="invoices/", delimiter="/"):
                    print(entry.key + (" (folder)" if entry.is_folder else f" {entry.size} bytes"))
        """
        rows = await paginate(
            self._api, await self._url("/objects"), params={"prefix": prefix, "delimiter": delimiter},
            user=self._call_scope(), limit=limit,
        )
        return [BucketObject._from(row) for row in rows]

    @synced
    async def objects_page(
        self, prefix: Optional[str] = None, *, delimiter: Optional[str] = None, cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Page:
        """One page of ``objects``; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds ``BucketObject``s and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            bucket = noclick.Bucket.from_name("uploads")
            page = bucket.objects_page(prefix="invoices/", limit=100)
            while True:
                for obj in page.data:
                    print(obj.key, obj.size)
                if page.next_cursor is None:
                    break
                page = bucket.objects_page(prefix="invoices/", limit=100, cursor=page.next_cursor)
        """
        page = await fetch_page(
            self._api, await self._url("/objects"), params={"prefix": prefix, "delimiter": delimiter},
            user=self._call_scope(), cursor=cursor, limit=limit,
        )
        return Page([BucketObject._from(row) for row in page.data], page.next_cursor)

    @synced
    async def remove(self, key: str) -> None:
        """Delete the file at ``key``. Removing a key that isn't there does nothing.

        Usage::

            bucket = noclick.Bucket.from_name("uploads")
            bucket.remove("invoices/0042.pdf")
        """
        await self._request("DELETE", await self._url("/objects"), params={"key": key})

    @synced
    async def versions(self, key: str) -> List[ObjectVersion]:
        """What ``key`` held before each write through NoClick of the last 30 days, newest first.

        Returns:
            Each earlier version.

        Usage::

            bucket = noclick.Bucket.from_name("uploads")
            for version in bucket.versions("menu.pdf"):
                print(version.replaced_at, version.op, version.size)
        """
        raw = await self._request("GET", await self._url("/objects/versions"), params={"key": key})
        return [ObjectVersion._from(row) for row in (raw or {}).get("data") or []]

    @synced
    async def restore_version(self, key: str, version: Any) -> BucketObject:
        """Put ``key`` back as ``version`` held it; what it holds now is kept as a version in turn.

        Returns:
            The file, as it's stored again.

        Usage:
            Undo an overwrite::

                bucket = noclick.Bucket.from_name("uploads")
                bucket.restore_version("menu.pdf", bucket.versions("menu.pdf")[0])
        """
        version_id = version.id if isinstance(version, ObjectVersion) else version
        raw = await self._request("POST", await self._url("/objects/versions/restore"),
                                  json={"key": key, "version_id": version_id})
        return BucketObject._from(raw)

    # --- links -----------------------------------------------------------

    @synced
    async def signed_url(
        self, key: str, *, method: Literal["GET", "PUT"] = "GET", expires_in: int = 3600,
        content_type: Optional[str] = None,
    ) -> str:
        """A link that reads (``GET``) or uploads (``PUT``) the file at ``key``
        without a NoClick key, for ``expires_in`` seconds (60 to 604,800, a week).
        A ``PUT`` link takes up to 5 GB; with ``content_type`` the upload must send
        that type.

        Returns:
            The link. Anyone who has it can use it until it expires, so hand it only to whoever needs it.

        Usage:
            Let a user download a private file::

                bucket = noclick.Bucket.from_name("uploads")
                link = bucket.signed_url("invoices/0042.pdf", expires_in=3600)

            Let a browser upload straight to the bucket, so the file never passes through your server::

                bucket = noclick.Bucket.from_name("uploads")
                upload = bucket.signed_url("avatars/u42.png", method="PUT", expires_in=600, content_type="image/png")
                # the browser runs: fetch(upload, {method: "PUT", body: file, headers: {"Content-Type": "image/png"}})
        """
        body = compact(key=key, method=method, expires_in=expires_in, content_type=content_type)
        response = await self._request("POST", await self._url("/signed_urls"), json=body) or {}
        return response["url"]

    # --- uploads in parts ------------------------------------------------

    @synced
    async def start_upload(
        self, key: str, *, content_type: Optional[str] = None, metadata: Optional[Mapping[str, str]] = None,
    ) -> BucketUpload:
        """Begin uploading the file at ``key`` in parts: for a file bigger than a ``PUT``
        link carries (5 GB), or one a page sends a piece at a time. Sign a link per part
        with ``upload_part_urls``, ``PUT`` each part's bytes to its link (a browser can,
        straight from a page: each answers with an ``ETag`` header), then join them with
        ``complete_upload``, or drop them with ``abort_upload``. Each part is 5 MiB to
        5 GiB, every part but the last the same size, up to 10,000 parts. Nothing is at
        ``key`` until the upload completes, and one left unfinished is dropped after 7
        days. ``content_type`` and ``metadata`` are as ``put`` takes them. An app's own
        code uploads this way, since S3 credentials stay with a person.

        Returns:
            The upload: its ``upload_id`` and the part sizes it takes.

        Usage:
            Upload a big file from disk, 64 MB at a time::

                import os

                import httpx

                part = 64 * 1024 * 1024
                bucket = noclick.Bucket.from_name("recordings", create_if_missing=True)
                upload = bucket.start_upload("calls/all-hands.mp4", content_type="video/mp4")
                count = -(-os.path.getsize("all-hands.mp4") // part)
                links = bucket.upload_part_urls("calls/all-hands.mp4", upload.upload_id, range(1, count + 1))
                etags = {}
                with open("all-hands.mp4", "rb") as f:
                    for number in range(1, count + 1):
                        sent = httpx.put(links[number], content=f.read(part))
                        sent.raise_for_status()
                        etags[number] = sent.headers["ETag"]
                stored = bucket.complete_upload("calls/all-hands.mp4", upload.upload_id, etags)
                print(stored.size)
        """
        body = compact(key=key, content_type=content_type, metadata=dict(metadata) if metadata else None)
        return BucketUpload._from(await self._request("POST", await self._url("/uploads"), json=body))

    @synced
    async def upload_part_urls(
        self, key: str, upload_id: str, part_numbers: Iterable[int], *, expires_in: int = 3600,
    ) -> Dict[int, str]:
        """A ``PUT`` link for each of ``part_numbers`` (1 to 10,000) of the upload, for
        ``expires_in`` seconds (60 to 604,800). ``PUT`` a part's bytes to its link: the
        answer's ``ETag`` header names the part for ``complete_upload``. A part
        uploaded again replaces it, so a failed part is simply sent again.

        Returns:
            Each part number's link.

        Usage:
            Hand a page the links for a 1 GB file in 16 MiB parts::

                bucket = noclick.Bucket.from_name("manuals")
                links = bucket.upload_part_urls("b737/fcom.pdf", upload_id, range(1, 65), expires_in=3600)
        """
        numbers = list(part_numbers)
        links: Dict[int, str] = {}
        for start in range(0, len(numbers), _PART_LINKS_PER_CALL):
            body = {"key": key, "upload_id": upload_id, "part_numbers": numbers[start:start + _PART_LINKS_PER_CALL],
                    "expires_in": expires_in}
            page = await self._request("POST", await self._url("/uploads/part_urls"), json=body) or {}
            links.update({int(row["part_number"]): row["url"] for row in page.get("data") or []})
        return links

    @synced
    async def complete_upload(self, key: str, upload_id: str, parts: Mapping[int, str]) -> BucketObject:
        """Join the uploaded parts into the file at ``key``, in part number order:
        ``parts`` maps each part's number to the ``ETag`` its upload answered with (as
        a page sends them back, numbers as text are fine). What ``key`` held is kept
        as an earlier version, as ``put`` keeps it. Parts that can't be joined raise
        ``noclick.InvalidRequest`` saying why (a wrong ETag, a part but the last under
        5 MiB, or parts but the last of different sizes); an upload already completed,
        aborted or over 7 days old raises ``noclick.NotFound``.

        Returns:
            The file as stored, with its ``size`` and ``etag``.

        Usage::

            bucket = noclick.Bucket.from_name("manuals")
            stored = bucket.complete_upload("b737/fcom.pdf", upload_id, {1: '"9b2c..."', 2: '"0e41..."'})
            print(stored.size)
        """
        body = {"key": key, "upload_id": upload_id,
                "parts": [{"part_number": int(n), "etag": etag} for n, etag in parts.items()]}
        return BucketObject._from(await self._request("POST", await self._url("/uploads/complete"), json=body))

    @synced
    async def abort_upload(self, key: str, upload_id: str) -> None:
        """Drop the upload and every part sent. One already completed or aborted is fine.

        Usage::

            bucket = noclick.Bucket.from_name("manuals")
            bucket.abort_upload("b737/fcom.pdf", upload_id)
        """
        await self._request("POST", await self._url("/uploads/abort"), json={"key": key, "upload_id": upload_id})

    @synced
    async def url(self, key: str) -> str:
        """The plain URL a public bucket serves ``key`` at. A private bucket raises
        ``noclick.NotAvailable``: use ``signed_url``, or ``update(public=True)``.

        Returns:
            ``public_base_url`` followed by the key; it works for as long as the bucket stays public.

        Usage::

            assets = noclick.Bucket.from_name("public-assets")
            print(assets.url("logo.png"))   # https://.../logo.png
        """
        raw = await self._ensure()
        base = raw.get("public_base_url")
        if not raw.get("public") or not base:
            raise NotAvailable(
                f"Bucket {raw.get('name')!r} is private, so its files have no public URL.",
                next_step="Use bucket.signed_url(key), or make it public with bucket.update(public=True).",
                details={"bucket_id": raw.get("id")},
            )
        return f"{base.rstrip('/')}/{quote(key, safe='/')}"

    # --- settings and access ---------------------------------------------

    @synced
    async def update(self, *, public: Optional[bool] = None) -> "Bucket":
        """Change the bucket's settings. Making it private stops every public URL
        at once; signed links keep working until they expire.

        Returns:
            This bucket, with the server's current fields.

        Usage::

            assets = noclick.Bucket.from_name("public-assets", create_if_missing=True)
            assets.update(public=True)
            print(assets.public_base_url)
        """
        self._raw = await self._request("PATCH", await self._url(), json=compact(public=public))
        return self

    @synced
    async def notify(self, queue: Any, *, prefix: Optional[str] = None, enabled: bool = True) -> "Bucket":
        """Put a message on ``queue`` (a ``Queue`` or its name, in the bucket's own user)
        for every file stored under ``prefix`` (the whole bucket when omitted), however it
        arrived: ``put``, a ``PUT`` signed link, or S3 credentials. The message is
        ``{"event": "put", "bucket", "key", "size", "content_type", "etag", "at"}``, so a
        worker or an agent with ``OnQueue`` picks each upload up. Asking again for the same
        queue and prefix changes nothing; ``enabled=False`` stops it. A bucket tells up to
        10 queues.

        Returns:
            This bucket, whose ``notifications`` list where it tells.

        Usage:
            Transcribe every call recording as it lands::

                recordings = noclick.Bucket.from_name("recordings", create_if_missing=True)
                calls = noclick.Queue.from_name("new-recordings", create_if_missing=True)
                recordings.notify(calls, prefix="calls/")
                for msg in calls.iterate():
                    link = recordings.signed_url(msg.body["key"])
                    print(noclick.AI.transcribe(link).text)
                    msg.ack()

            Stop::

                recordings = noclick.Bucket.from_name("recordings")
                recordings.notify("new-recordings", prefix="calls/", enabled=False)
        """
        name = queue if isinstance(queue, str) else (await queue._ensure())["name"]
        body = {"queue": name, **compact(prefix=prefix)}
        if enabled:
            self._raw = await self._request("POST", await self._url("/notifications"), json=body)
        else:
            self._raw = await self._request("POST", await self._url("/notifications/remove"), json=body)
        return self

    @synced
    async def s3_credentials(self, *, read_only: bool = False, ttl_s: int = 3600) -> S3Credentials:
        """Keys for the bucket's S3-compatible endpoint, for rclone, the AWS CLI or
        an S3 library, valid ``ttl_s`` seconds (900 to 43,200). They reach this
        bucket only; ``read_only=True`` for keys that can't change anything. They're
        for you and your own code: an app's deployed code is refused them
        (``noclick.PermissionDenied``) and uploads big files in parts
        (``start_upload``) instead.

        Returns:
            The endpoint, bucket name, keys and ``expires_at``. The secret is shown once; mint new ones when they expire.

        Usage::

            import boto3

            bucket = noclick.Bucket.from_name("uploads")
            creds = bucket.s3_credentials(read_only=True, ttl_s=3600)
            s3 = boto3.client(
                "s3",
                endpoint_url=creds.endpoint,
                region_name=creds.region,
                aws_access_key_id=creds.access_key_id,
                aws_secret_access_key=creds.secret_access_key,
                aws_session_token=creds.session_token,
            )
            print(s3.list_objects_v2(Bucket=creds.bucket, Prefix="invoices/")["KeyCount"])
        """
        body = {"ttl_s": ttl_s, **({"read_only": True} if read_only else {})}
        return S3Credentials._from(await self._request("POST", await self._url("/s3_credentials"), json=body))

    @synced
    async def export(self) -> Operation:
        """Export every file, to take anywhere: a zip holding each one at its key
        (under ``buckets/<name>/files/``), with ``index.jsonl`` listing each key's
        content type and metadata. A key that can't be a path in a zip (an empty,
        ``.`` or ``..`` part) is kept under ``renamed/``, and the index says which.

        Returns:
            An operation whose ``wait()`` gives an ``ExportBundle``: the zip at ``url``, valid 7 days.

        Usage::

            bucket = noclick.Bucket.from_name("uploads")
            bundle = bucket.export().wait()
            print(bundle.url, bundle.size_bytes)
        """
        payload = await self._request("POST", await self._url("/export"))
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="bucket.export", reader=_read_export,
        )

    @synced
    async def delete(self, *, force: bool = False) -> TrashItem:
        """Delete the bucket: it goes to the trash, restorable for 30 days. It must be empty unless
        ``force=True``, which takes every file in it too (a non-empty bucket otherwise raises
        ``noclick.Conflict``); its files are stored, and billed, until it's purged.
        A bucket in an agent's tools (``used_by``) raises ``noclick.Conflict`` until
        you take it out; so will one an app binds, when apps ship.

        Returns:
            Its ``TrashItem``: ``restore()`` puts it back, files and all.

        Usage::

            bucket = noclick.Bucket.from_name("scratch")
            bucket.delete(force=True)
        """
        raw = await self._request("DELETE", await self._url(), params={"force": "true"} if force else None)
        return trashed(raw, client=self._client, user=self._call_scope())
