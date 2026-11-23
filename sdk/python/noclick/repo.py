"""Repos: git repositories for the code your agents and apps write.

    repo = noclick.Repo.from_name("agent-tools", create_if_missing=True)
    repo.commit({"src/index.ts": source}, message="Add the lookup route")
    repo.commit({"index.html": {"url": "https://example.com/page.html"}}, message="Publish the page")
    print(repo.read("src/index.ts").decode())
    print(repo.clone_url())   # plain git over HTTPS, a short-lived token inside

    site = noclick.Repo.create("site", from_url="https://github.com/acme/site").wait()   # a copy, history and all

A repo is plain git: clone it, push to it, copy one in from a public URL, or move it to GitHub whole.
A project (``noclick.Project``) deploys one to a URL.
"""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import os
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union, overload
from urllib.parse import quote

from ._attachment import Attachment
from ._client import Client, resolve_client
from ._object import (
    Page, _Object, compact, fetch_page, field, list_all, list_page, paginate, parse_time, ref_id,
)
from ._sync import synced
from .trash import TrashItem, trashed
from ._scope import AMBIENT, resolve_scope
from .exceptions import Conflict, NotFound
from .export import ExportBundle
from .operation import Operation, register_result


@dataclass(frozen=True)
class Commit:
    """One commit: its ``sha``, ``message`` and ``author``, the ``branch`` it was
    made on, and ``files_changed``, how many files it added, changed or deleted.
    A branch's history (``commits()``) names that branch and counts no files
    (``files_changed`` is None); ``diff()`` counts them and names no branch."""

    sha: str
    message: str
    author: Optional[str]
    branch: Optional[str]
    created_at: Any
    files_changed: Optional[int]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "Commit":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            raw.get("sha") or "", raw.get("message") or "", raw.get("author"), raw.get("branch"),
            parse_time(raw.get("created_at")), raw.get("files_changed"), raw,
        )


@dataclass(frozen=True)
class FileChange:
    """One file a commit changed: its ``path`` (and ``old_path`` when it was renamed), its ``status``
    (``added``, ``modified``, ``deleted``, ``renamed``, ``copied`` or ``type_changed``), the lines it added
    and deleted, its ``size`` in bytes, and ``patch``, its unified diff in git's format. ``patch`` (and the
    line counts) are None for a file that isn't shown: one that isn't text, or is too large."""

    path: str
    status: str
    additions: Optional[int]
    deletions: Optional[int]
    size: Optional[int]
    patch: Optional[str]
    old_path: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "FileChange":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("path") or "", raw.get("status") or "modified", raw.get("additions"),
                   raw.get("deletions"), raw.get("size"), raw.get("patch"), raw.get("old_path"), raw)


@dataclass(frozen=True)
class CommitDiff:
    """What one commit changed against its first parent: the ``commit``, its ``parents`` (none for the
    first commit), the lines it added and deleted in all, and each file it changed."""

    commit: Commit
    parents: List[str]
    additions: int
    deletions: int
    files: List[FileChange]

    @classmethod
    def _from(cls, raw: Any) -> "CommitDiff":
        raw = raw if isinstance(raw, dict) else {}
        return cls(Commit._from(raw), list(raw.get("parents") or []), raw.get("additions") or 0,
                   raw.get("deletions") or 0, [FileChange._from(f) for f in raw.get("files") or []])


@dataclass(frozen=True)
class Branch:
    """A branch: its ``name``, the sha of its ``head`` commit, and when it last moved."""

    name: str
    head: Optional[str]
    updated_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "Branch":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("name") or "", raw.get("head"), parse_time(raw.get("updated_at")), raw)


@dataclass(frozen=True)
class RepoBackup:
    """A branch's old head NoClick kept before an agent's push rewrote it (``reason`` ``"rewritten"``: a
    force-push) or deleted it (``"deleted"``): the ``branch``, the commit ``sha`` it was at, the platform agent
    whose push it was (``agent_id``, else None), and when it was kept. It's kept 30 days, until
    ``expires_at``, out of the branch list and clones; ``Repo.restore_backup`` makes the branch again."""

    id: str
    branch: str
    sha: str
    reason: str
    agent_id: Optional[str]
    created_at: Any
    expires_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "RepoBackup":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("id") or "", raw.get("branch") or "", raw.get("sha") or "", raw.get("reason") or "",
                   raw.get("agent_id"), parse_time(raw.get("created_at")), parse_time(raw.get("expires_at")), raw)


@dataclass(frozen=True)
class RepoFile:
    """An entry in a repo's tree: its ``path`` from the root, its ``type``
    (``file``, ``dir`` or ``link``) and, for a file, its ``size`` in bytes and ``sha``,
    git's blob id for its content (it changes whenever the content does). A ``link``
    is a symbolic link someone committed: listed as the entry it is, with no size
    or sha, and never followed."""

    path: str
    type: str
    size: Optional[int]
    sha: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "RepoFile":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("path") or "", raw.get("type") or "file", raw.get("size"), raw.get("sha"), raw)


def _pushable(push: Union[None, str, Sequence[str]]) -> Optional[List[str]]:
    """``push=`` as branch patterns: exact names or a prefix ending in ``/*``, the one
    glob a git endpoint enforces; None (read-only) stays None."""
    if push is None:
        return None
    globs = [push] if isinstance(push, str) else list(push)
    if not globs or not all(isinstance(g, str) and g for g in globs):
        raise ValueError("push takes branch globs like 'noclick/*'; leave it out for a read-only checkout")
    for glob in globs:
        if "*" in (glob[:-2] if glob.endswith("/*") else glob):
            raise ValueError(f"{glob!r} isn't a push pattern: name a branch exactly ('main'), or a prefix ending "
                             "in '/*' ('noclick/*')")
    return globs


def _folder(path: Optional[str]) -> Optional[str]:
    """``path=`` as a folder under ``/workspace``: relative, no ``..``."""
    if path is None:
        return None
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts or path.startswith("/") or any(p in (".", "..") for p in parts):
        raise ValueError(f"path is a folder under /workspace, like 'docs' or 'repos/docs', not {path!r}")
    return "/".join(parts)


@dataclass(frozen=True)
class RepoCheckout:
    """A git repository an agent works in, for ``Agent(repos=[...])``: a
    connection's repository (``connection.checkout("acme/docs")``) or a NoClick
    repo of the agent's scope (``repo.checkout()``). NoClick clones it into
    ``/workspace/<path>`` (the repository's name when ``path`` is omitted) at a
    conversation's first turn, and the agent's git reaches that repository only,
    through NoClick, with a key made for its sandbox; the connection's own token
    never enters it. ``push`` lists the branches it may push to: exact names, or a
    prefix ending in ``/*`` (``"noclick/*"`` reaches ``noclick/fix`` and
    ``noclick/a/b``); NoClick's git endpoint refuses any other push, and with no
    ``push`` the checkout is read-only. Whatever ``push`` allows, the agent can't
    force-push or delete the repository's default branch, and before its push
    rewrites or deletes any other branch NoClick keeps the old head as a backup
    for 30 days (on a git host, ``refs/noclick/backups/<branch>/<time>`` in the
    repository, which you push back to restore; on a NoClick repo, ``repo.backups()``
    and ``repo.restore_backup()``). A policy can't do this job: a coding
    harness runs ``git push`` in its own shell, which is no tool call for a
    policy to judge. ``gh`` only reads the repository there."""

    #: ``owner/name`` on the connection's service (None for a NoClick repo).
    repository: Optional[str] = None
    connection: Any = dc_field(default=None, repr=False)
    repo: Any = dc_field(default=None, repr=False)
    #: The branch it checks out (the repository's default when None).
    branch: Optional[str] = None
    #: The folder under ``/workspace`` it's cloned into.
    path: Optional[str] = None
    #: Branches it may push to, exact or ``prefix/*`` (None: read-only).
    push: Optional[List[str]] = None

    async def _wire(self, scope: Any) -> Dict[str, Any]:
        """The ``repos=`` entry for an agent in ``scope`` (a connection from another scope goes by id)."""
        extra = compact(branch=self.branch, path=self.path, push=self.push)
        if self.repo is not None:
            return {"repo_id": await ref_id(self.repo), **extra}
        from .connection import _connection_ref  # connection imports this module

        return {"connection": await _connection_ref(self.connection, resolve_scope(scope)),
                "repository": self.repository, **extra}


def _read_export(result: Any, op: Operation) -> ExportBundle:
    return ExportBundle._from(result)


def _read_github(result: Any, op: Operation) -> Optional[str]:
    return result.get("url") if isinstance(result, dict) else None


def _read_import(result: Any, op: Operation) -> "Repo":
    raw = result.get("repo") if isinstance(result, dict) else None
    return Repo._new(raw=raw if isinstance(raw, dict) else None, hints={"id": op._known("repo_id")},
                     client=op._client, user=op._call_scope())


register_result("repo.export", _read_export)
register_result("repo.export_to_github", _read_github)
register_result("repo.import", _read_import)


class RepoImport(Operation):
    """A public git repository being copied, history and all, into a new repo: the operation
    ``Repo.create(..., from_url=...)`` returns. The repo is listed at once (``repo``) but takes no
    commits or pushes until the copy succeeds. ``wait()`` gives the ``Repo`` then: its
    ``default_branch`` is the source's own (or the one you named) and its ``last_commit`` that branch's
    head. A copy that can't finish (no repository at the URL, one that asks for a sign-in, over 5 GiB
    of history as git transfers it, which isn't the repo's ``size_bytes`` afterwards, longer than 15
    minutes) raises from ``wait()`` saying why, and the repo is deleted; so is one you ``cancel()``.
    ``progress`` shows how far it got."""

    repo_id: Optional[str] = field("repo_id", doc="The new repo's id.")

    @property
    def repo(self) -> "Repo":
        """The new repo: it reads while the copy runs, and takes writes once ``wait()`` returns."""
        return Repo._new(hints={"id": self.repo_id}, client=self._client, user=self._call_scope())


def _blob_sha(data: bytes) -> str:
    """Git's blob id for ``data``, to tell an unchanged file without sending it."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _excluded(path: str, exclude: Sequence[str]) -> bool:
    """Whether a path (or a folder above it) matches one of the ``exclude`` globs."""
    parts = path.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    return any(fnmatch.fnmatchcase(p, glob) for glob in exclude for p in prefixes)


def _read_folder(folder: Union[str, "os.PathLike[str]"], exclude: Sequence[str]) -> Dict[str, bytes]:
    """Every file under ``folder`` by its path from there, ``.git`` and ``exclude`` left out."""
    root = Path(folder)
    if not root.is_dir():
        raise NotADirectoryError(f"{str(folder)!r} isn't a folder")
    found: Dict[str, bytes] = {}
    for directory, subdirs, names in os.walk(root):
        subdirs[:] = [d for d in subdirs if d != ".git"]
        for name in names:
            path = (Path(directory) / name).relative_to(root).as_posix()
            if not _excluded(path, exclude):
                found[path] = (Path(directory) / name).read_bytes()
    return found


async def _change(path: str, content: Union[None, str, bytes, Attachment, Mapping[str, Any]]) -> Dict[str, Any]:
    """One file of a commit on the wire: text as UTF-8, bytes as base64, None deletes; one of the account's files,
    or a mapping of where NoClick reads it, goes by reference (a ``Bucket`` stands for its id)."""
    if content is None:
        return {"path": path, "delete": True}
    if isinstance(content, str):
        return {"path": path, "content": content, "encoding": "utf-8"}
    if isinstance(content, Attachment):
        if not content.id:
            raise ValueError(f"{path}: a file a conversation shows has no id to commit by; use one of "
                             "noclick.attachments(), or its url.")
        return {"path": path, "attachment_id": content.id}
    if isinstance(content, Mapping):
        return {"path": path, **{k: await ref_id(v) if k.endswith("_id") else v for k, v in content.items()}}
    return {"path": path, "content": base64.b64encode(bytes(content)).decode("ascii"), "encoding": "base64"}


class Repo(_Object):
    """A git repository NoClick hosts. ``Repo.from_name("agent-tools",
    create_if_missing=True)`` is lazy; commit to it from code, or clone it and
    push with plain git."""

    _repr_keys = ("id", "name", "default_branch")

    id: str = field("id")
    name: str = field("name")
    default_branch: str = field("default_branch", doc="The branch a project deploys to production (``main`` unless set).")
    size_bytes: Optional[int] = field("size_bytes")
    last_commit: Optional[Commit] = field(
        "last_commit", Commit._from, doc="The newest commit on the default branch (None in an empty repo).",
    )
    used_by: List[Dict[str, Any]] = field(
        "used_by", doc="The apps that deploy it: ``kind`` (``project``), ``id`` and ``name``.",
    )
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)
    forked_from: Optional[Dict[str, Any]] = field(
        "forked_from", doc="Copied from someone's public work on NoClick: ``{\"address\": ...}``, the address it was "
        "copied from; None for a repo of your own.")

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    # --- construction ----------------------------------------------------

    @overload
    @classmethod
    async def create(
        cls, name: str, *, default_branch: Optional[str] = None, from_url: None = None, ref: None = None,
        allow_existing: bool = False, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> "Repo": ...

    @overload
    @classmethod
    async def create(
        cls, name: str, *, from_url: str, ref: Optional[str] = None, default_branch: Optional[str] = None,
        allow_existing: bool = False, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> RepoImport: ...

    @synced
    @classmethod
    async def create(
        cls,
        name: str,
        *,
        default_branch: Optional[str] = None,
        from_url: Optional[str] = None,
        ref: Optional[str] = None,
        allow_existing: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> Union["Repo", RepoImport]:
        """Create a repo called ``name`` (unique per user; a duplicate raises
        ``noclick.Conflict`` with ``existing_id``, or with ``allow_existing=True``
        returns the repo already there, commits and all): empty, or with
        ``from_url`` a copy of a public git repository, history and all.

        ``from_url`` is the https URL you'd ``git clone``, with no login in it.
        Every branch and tag is copied, and the repo's default branch is the
        source's own unless ``default_branch`` names another of its branches.
        ``ref`` copies one branch, tag or commit (its full sha) instead, with its
        history, as the repo's one branch: named ``default_branch``, else the
        branch's own name, else ``main``. Submodules and LFS files aren't copied
        (their pointers are, as committed). The copy takes up to 5 GiB of history
        and 15 minutes. That size is measured as git transfers the history
        (compressed), which isn't the same figure as the repo's ``size_bytes``
        afterwards. The copy is charged what it uses: its seconds of compute and the
        bytes it stores, at NoClick's vendors' prices. An import always makes a new
        repo, so ``allow_existing`` doesn't apply to it.

        ``from_url`` may also be an app's address whose owner made its code public on NoClick
        (``pilot-hub.noclick.site``, with or without ``https://``, or a custom domain it serves): its published code
        is copied inside NoClick, as a fork, and the repo's ``forked_from`` names that address; the operation's
        result says what a deploy of it asks for. An address with no public work raises ``noclick.InvalidRequest``
        (reason ``not_public``).

        Returns:
            The new repo, loaded, with no commits yet; with ``from_url``, a
            ``RepoImport``: the operation doing the copy, whose ``wait()`` gives
            the repo once it's copied.

        Usage:
            Create one for your account's own code::

                repo = noclick.Repo.create("agent-tools")
                print(repo.name, repo.default_branch)   # agent-tools main

            Inside ``as_user`` it's that user's, and bills to them::

                with noclick.as_user("user_42"):
                    site = noclick.Repo.create("portfolio", default_branch="production")

            Copy a public repository, then deploy it::

                copy = noclick.Repo.create("blog", from_url="https://github.com/acme/blog")
                repo = copy.wait()
                print(repo.default_branch, repo.last_commit.sha)
                app = noclick.Project.create("blog", repo=repo)

            Fork an app someone made public, from its address alone::

                repo = noclick.Repo.create("my-pilot-hub", from_url="pilot-hub.noclick.site").wait()
                print(repo.forked_from)   # {'address': 'pilot-hub.noclick.site'}

            Copy one release of it, as the branch ``main``::

                repo = noclick.Repo.create("blog-v2", from_url="https://github.com/acme/blog", ref="v2.0.0").wait()

            A source NoClick can't copy raises from ``wait()``, and the repo is deleted::

                try:
                    noclick.Repo.create("private", from_url="https://github.com/acme/private").wait()
                except noclick.InvalidRequest as refused:
                    print(refused.message)   # ... asked for a sign-in: NoClick copies public repositories only.
        """
        scope = resolve_scope(user)
        if from_url is None:
            if ref is not None:
                raise ValueError("ref names what to copy from from_url: pass from_url too")
            raw = await cls._create_named("/v1/repos", compact(name=name, default_branch=default_branch),
                                          allow_existing=allow_existing, user=scope, client=client)
            return cls._new(raw=raw, client=client, user=scope)
        if allow_existing:
            raise ValueError("an import always makes a new repo, so allow_existing doesn't apply to it")
        raw = await cls._create_named("/v1/repos", compact(name=name, default_branch=default_branch,
                                                           source=compact(url=from_url, ref=ref)),
                                      allow_existing=False, user=scope, client=client)
        return RepoImport._from_payload(raw.get("operation"), client=client, user=scope, kind="repo.import",
                                        reader=_read_import)

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        create_if_missing: bool = False,
        default_branch: Optional[str] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Repo":
        """A lazy reference to the repo called ``name`` in the current (or
        given) user. With ``create_if_missing=True`` it's created, empty, on
        first use; an existing repo is used as it is.

        Returns:
            A repo that loads, or is created, the first time it's used. Nothing is sent yet.

        Usage:
            The same line works on the first run and every run after::

                repo = noclick.Repo.from_name("agent-tools", create_if_missing=True)
                repo.commit({"README.md": "# Agent tools\\n"}, message="Start the repo")

            Without ``create_if_missing`` a missing repo raises ``noclick.NotFound`` at first use::

                repo = noclick.Repo.from_name("booking", user="acme")
                print(repo.last_commit)
        """
        repo = cls._new(hints={"name": name}, client=client, user=user)
        if create_if_missing:
            repo._create_with = compact(name=name, default_branch=default_branch)
        return repo

    @classmethod
    def from_id(cls, repo_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Repo":
        """A lazy reference to a repo by id.

        Returns:
            A repo that loads the first time you read a field. Nothing is sent yet.

        Usage::

            repo = noclick.Repo.from_id("c4e1a7b2-5d3f-4a8e-9b6c-1f2d3e4a5b60")
            for branch in repo.branches():
                print(branch.name, branch.head)
        """
        return cls._new(hints={"id": repo_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, repo_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Repo":
        """Load a repo by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The repo, loaded.

        Usage::

            repo = noclick.Repo.get("c4e1a7b2-5d3f-4a8e-9b6c-1f2d3e4a5b60")
            print(repo.name, repo.size_bytes, repo.last_commit)
        """
        repo = cls.from_id(repo_id, client=client, user=user)
        await repo._ensure()
        return repo

    @synced
    @classmethod
    async def list(
        cls, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Repo"]:
        """The current user's repos (the account's own outside ``as_user``, or those ``user_filter`` covers).

        Returns:
            Every matching repo, newest first, fetched page by page.

        Usage::

            for repo in noclick.Repo.list():
                print(repo.name, repo.default_branch, repo.size_bytes)

            everyone = noclick.Repo.list(user_filter=noclick.ALL_USERS)   # every user's, plus your account's
        """
        return await list_all(
            "/v1/repos", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of repos; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the repos and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Repo.list_page(limit=50)
            while True:
                for repo in page.data:
                    print(repo.name)
                if page.next_cursor is None:
                    break
                page = noclick.Repo.list_page(limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/repos", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        repo_id = self._known("id")
        if repo_id:
            return await self._request("GET", f"/v1/repos/{repo_id}")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/repos", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        if rows:
            return rows[0]
        if self._create_with is None:
            raise NotFound(
                f"No repo is named {name!r}.",
                next_step="Create it with noclick.Repo.create(...) or pass create_if_missing=True.",
                details={"name": name},
            )
        try:
            return await self._request("POST", "/v1/repos", json=self._create_with)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._request("GET", f"/v1/repos/{exc.existing_id}")

    async def _repo_path(self) -> str:
        return f"/v1/repos/{await ref_id(self)}"

    # --- git -------------------------------------------------------------

    @synced
    async def clone_url(self, *, write: bool = False, ttl_s: Optional[int] = None) -> str:
        """A git URL with a short-lived token inside, for ``git clone``,
        ``fetch`` and, with ``write=True``, ``push``. ``ttl_s`` is 3,600 by
        default, at most 86,400; the token stops working after it. The token
        reaches this repo only. Clones and pushes cost nothing extra, within fair
        use. An agent's writing URL (asked for through NoClick's MCP server, by
        the coordinator or by a platform agent) goes through NoClick, which never
        lets it force-push or delete the default branch, and keeps the old head of
        any other branch its push rewrites or deletes (``backups``).

        Returns:
            An ``https://`` URL that plain git accepts as it is. Treat it as a secret until it expires.

        Usage:
            Clone the repo on a build machine::

                import subprocess

                repo = noclick.Repo.from_name("agent-tools")
                subprocess.run(["git", "clone", repo.clone_url(), "agent-tools"], check=True)

            Let a sandbox push for the next ten minutes::

                repo = noclick.Repo.from_name("agent-tools")
                url = repo.clone_url(write=True, ttl_s=600)
                with noclick.Sandbox.create(network=True) as sb:
                    sb.exec(["git", "clone", url, "/workspace/agent-tools"])
        """
        response = await self._request(
            "POST", f"{await self._repo_path()}/clone_url", json=compact(write=write, ttl_s=ttl_s),
        ) or {}
        return response["url"]

    def checkout(
        self,
        *,
        branch: Optional[str] = None,
        path: Optional[str] = None,
        push: Union[None, str, Sequence[str]] = None,
    ) -> RepoCheckout:
        """This repo checked out in an agent's workspace, for ``Agent(repos=[...])``:
        cloned into ``/workspace/<path>`` (the repo's name when omitted) at a
        conversation's first turn, on ``branch`` (the default branch when omitted).
        ``push`` is the branches the agent may push to, exact or ``prefix/*``;
        without it the checkout is read-only. The repo must be in the agent's own
        scope (the account's for an account agent, a user's for that user's), and
        the agent's commits name it as their author. Sends nothing.

        Returns:
            A ``RepoCheckout`` to list in an agent's ``repos``.

        Usage:
            Let an agent change the site on branches of its own, for review::

                site = noclick.Repo.from_name("booking")
                builder = noclick.Agent.from_name(
                    "site-builder",
                    create_if_missing=True,
                    instructions="You make the changes asked for in /workspace/booking, on a new branch, and push it.",
                    repos=[site.checkout(push="agent/*")],
                )
        """
        return RepoCheckout(repo=self, branch=branch, path=_folder(path), push=_pushable(push))

    @synced
    async def commit(
        self,
        files: Union[Mapping[str, Union[None, str, bytes, Attachment, Mapping[str, Any]]], str, "os.PathLike[str]"],
        *,
        message: str,
        branch: Optional[str] = None,
        author: Optional[str] = None,
        exclude: Sequence[str] = (),
    ) -> Optional[Commit]:
        """Commit ``files`` in one commit: each path maps to its new content
        (text, or bytes for binary files) or to ``None`` to delete it. The commit
        goes on ``branch`` (the default branch when omitted), which is created
        from the default branch's head if it doesn't exist yet. At most 1,000
        files and 50 MB in one commit.

        A file NoClick can reach goes by reference instead, and NoClick reads it
        byte for byte, so it never passes through your code: one of the account's
        files (an ``Attachment`` from ``noclick.attachments()``, or
        ``{"attachment_id": ...}``, which also names a file this key uploaded to an
        agent or a channel before a message sends it), ``{"url": "https://..."}``,
        or a bucket's file, ``{"bucket_id": bucket, "key": "fonts/a.woff2"}``. Those
        bytes count toward the 50 MB too.

        ``files`` may instead be a folder on disk: the branch's tree is made to match
        it, and only what changed is sent (new and changed files written, files the
        folder no longer has deleted), so running it again after no change commits
        nothing. ``.git`` is skipped, and so is any path matching one of the
        ``exclude`` globs (``["node_modules", "*.log"]``), which also keeps the repo's
        own copies of those paths.

        Returns:
            The new commit, with its ``sha``; for a folder with nothing changed, ``None``. Files
            given that change nothing (each already holds what it's given) raise ``noclick.Conflict``
            (409), naming the commit that holds them.

        Usage:
            Write two files and delete one, as one commit::

                repo = noclick.Repo.from_name("agent-tools", create_if_missing=True)
                commit = repo.commit(
                    {"src/index.ts": "export const lookup = () => 42;\\n", "package.json": '{"name": "agent-tools"}', "old.txt": None},
                    message="Add the lookup route",
                )
                print(commit.sha, commit.files_changed)

            Commit to a branch of its own, for a preview deployment, and name the author::

                repo = noclick.Repo.from_name("booking")
                repo.commit(
                    {"app/routes/book.tsx": "export default function Book() { return null; }\\n"},
                    message="Try the new booking form",
                    branch="new-form",
                    author="support-bot <support-bot@agents.noclick.app>",
                )

            Publish a page someone sent the account as it is, without reading it::

                [page] = noclick.attachments(query="game.html")
                site = noclick.Repo.from_name("game", create_if_missing=True)
                commit = site.commit({"index.html": page, "logo.png": {"url": "https://example.com/logo.png"}},
                                     message="Publish the game")

            Commit a folder a build wrote, sending only what changed since the last run::

                site = noclick.Repo.from_name("marketing-site", create_if_missing=True)
                commit = site.commit("./dist", message="Rebuild the site", exclude=["*.map"])
                print(commit.sha if commit else "nothing changed")
        """
        if not isinstance(files, Mapping):
            files = await self._folder_changes(files, branch, exclude)
            if not files:
                return None
        body = compact(
            message=message, branch=branch, author=author,
            files=[await _change(path, content) for path, content in files.items()],
        )
        return Commit._from(await self._request("POST", f"{await self._repo_path()}/commits", json=body))

    async def _folder_changes(
        self, folder: Union[str, "os.PathLike[str]"], branch: Optional[str], exclude: Sequence[str],
    ) -> Dict[str, Optional[bytes]]:
        """What a commit of ``folder`` must send: changed and new files, and ``None`` for the repo's
        files the folder no longer has. A branch that doesn't exist yet starts from the default one."""
        local = _read_folder(folder, exclude)
        ref = branch if branch and branch in {b.name for b in await self.branches.aio()} else None
        # A link in the repo is left as it is: a commit through the API writes files, so it can't put one back.
        remote = {f.path: f.sha for f in await self.files.aio("", ref=ref, recursive=True) if f.type == "file"}
        changes: Dict[str, Optional[bytes]] = {
            path: data for path, data in local.items() if remote.get(path) != _blob_sha(data)
        }
        changes.update({path: None for path in remote if path not in local and not _excluded(path, exclude)})
        return changes

    @synced
    async def read(self, path: str, *, ref: Optional[str] = None) -> bytes:
        """Read one file at ``ref`` (a branch, tag or commit sha; the default
        branch's head when omitted). A missing path raises ``noclick.NotFound``.
        A link is never followed: its path reads as the path it points to.

        Returns:
            The file's bytes exactly as committed; decode text yourself.

        Usage::

            repo = noclick.Repo.from_name("booking")
            manifest = repo.read("package.json", ref="main").decode()
            print(manifest)
        """
        return await self._request(
            "GET", f"{await self._repo_path()}/files", params={"path": path, "ref": ref}, binary=True,
        )

    @synced
    async def files(self, prefix: str = "", *, ref: Optional[str] = None, recursive: bool = False) -> List[RepoFile]:
        """What's in the directory ``prefix`` (the root when empty) at ``ref``.
        ``recursive=True`` lists every file below it instead, without the directories.
        A symbolic link is one entry of ``type`` ``link``, whatever it points to.

        Returns:
            Its files and directories, directories first, each by path from the repo's root.

        Usage:
            Walk the tree one level at a time::

                repo = noclick.Repo.from_name("booking")
                for entry in repo.files("app/", ref="main"):
                    print(entry.type, entry.path, entry.size)

            Or read every file under a directory::

                repo = noclick.Repo.from_name("booking")
                for entry in repo.files("app/routes/", recursive=True):
                    print(entry.path, len(repo.read(entry.path)))
        """
        response = await self._request(
            "GET", f"{await self._repo_path()}/files",
            params={"prefix": prefix, "ref": ref, "recursive": "true" if recursive else None},
        ) or {}
        return [RepoFile._from(row) for row in response.get("data") or []]

    @synced
    async def branches(self) -> List[Branch]:
        """The repo's branches, the default one first.

        Returns:
            Each branch with its ``head`` sha and when it last moved.

        Usage::

            repo = noclick.Repo.from_name("booking")
            for branch in repo.branches():
                print(branch.name, branch.head, branch.updated_at)
        """
        rows = await paginate(self._api, f"{await self._repo_path()}/branches", user=self._call_scope())
        return [Branch._from(row) for row in rows]

    @synced
    async def backups(self, *, branch: Optional[str] = None, limit: Optional[int] = 50) -> List[RepoBackup]:
        """The branches agents' pushes rewrote or deleted, as NoClick kept them first: newest first, each for
        30 days. Through NoClick an agent never force-pushes or deletes the default branch at all.

        Returns:
            Up to ``limit`` backups (``None`` for all of them), of ``branch`` alone when it's given.

        Usage::

            repo = noclick.Repo.from_name("booking")
            for backup in repo.backups(branch="agent/new-form"):
                print(backup.reason, backup.sha[:7], backup.created_at)
        """
        rows = await paginate(self._api, f"{await self._repo_path()}/backups", params={"branch": branch},
                              user=self._call_scope(), limit=limit)
        return [RepoBackup._from(row) for row in rows]

    @synced
    async def restore_backup(self, backup: Union[RepoBackup, str]) -> Branch:
        """Make a backup's branch again at the commit it was kept at (``backup``: a ``RepoBackup`` or its id).
        When the repo has a branch by that name again, the backup comes back as ``<branch>-restored-<time>``
        instead; nothing that's there moves.

        Returns:
            The branch made, with its ``head``.

        Usage::

            repo = noclick.Repo.from_name("booking")
            [latest] = repo.backups(branch="agent/new-form", limit=1)
            print(repo.restore_backup(latest).name)
        """
        backup_id = quote(str(backup.id if isinstance(backup, RepoBackup) else backup), safe="")
        made = await self._request("POST", f"{await self._repo_path()}/backups/{backup_id}/restore", json={})
        return Branch._from(made or {})

    @synced
    async def commits(self, *, branch: Optional[str] = None, limit: Optional[int] = 20) -> List[Commit]:
        """The history of ``branch`` (the default branch when omitted), newest first.

        Returns:
            Up to ``limit`` commits (20 by default; ``None`` for the whole history), fetched page by page.

        Usage::

            repo = noclick.Repo.from_name("booking")
            for commit in repo.commits(branch="main", limit=5):
                print(commit.sha[:7], commit.author, commit.message)
        """
        rows = await paginate(
            self._api, f"{await self._repo_path()}/commits", params={"branch": branch},
            user=self._call_scope(), limit=limit,
        )
        return [Commit._from(row) for row in rows]

    @synced
    async def commits_page(self, *, branch: Optional[str] = None, cursor: Optional[str] = None,
                           limit: Optional[int] = None) -> Page:
        """One page of ``commits``, newest first; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds ``Commit``s and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            repo = noclick.Repo.from_name("booking")
            page = repo.commits_page(branch="main", limit=50)
            while True:
                for commit in page.data:
                    print(commit.sha[:7], commit.message)
                if page.next_cursor is None:
                    break
                page = repo.commits_page(branch="main", limit=50, cursor=page.next_cursor)
        """
        page = await fetch_page(self._api, f"{await self._repo_path()}/commits", params={"branch": branch},
                                user=self._call_scope(), cursor=cursor, limit=limit)
        return Page([Commit._from(row) for row in page.data], page.next_cursor)

    @synced
    async def diff(self, sha: str) -> CommitDiff:
        """What the commit ``sha`` (full or short) changed against its first parent. An unknown commit
        raises ``noclick.NotFound``.

        Returns:
            The commit with each file it changed, the file's status, the lines it added and deleted and
            its patch in git's unified format.

        Usage::

            repo = noclick.Repo.from_name("booking")
            [latest] = repo.commits(limit=1)
            changes = repo.diff(latest.sha)
            print(f"+{changes.additions} -{changes.deletions}")
            for file in changes.files:
                print(file.status, file.path)
                print(file.patch or "(not shown)")
        """
        path = f"{await self._repo_path()}/commits/{quote(sha, safe='')}"
        return CommitDiff._from(await self._request("GET", path))

    # --- leaving ---------------------------------------------------------

    @synced
    async def export(self) -> Operation:
        """Package the repo to take elsewhere: every branch and its history as a git bundle.

        Returns:
            An operation whose ``.wait()`` gives an ``noclick.ExportBundle``: a zip at ``url``
            (a link that expires) holding the bundle, which ``git clone`` reads as it is.

        Usage::

            repo = noclick.Repo.from_name("agent-tools")
            bundle = repo.export().wait()
            print(bundle.url, bundle.expires_at)
        """
        payload = await self._request("POST", f"{await self._repo_path()}/export", json={})
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="repo.export", reader=_read_export,
        )

    @synced
    async def export_to_github(self, *, connection: Any, owner: str, name: Optional[str] = None,
                               private: bool = True) -> Operation:
        """Copy the repo, every branch and tag with its history, into a new
        GitHub repository ``owner/name`` (``name`` defaults to this repo's),
        through ``connection``: a GitHub connection (a ``Connection`` or its
        name) of the repo's user, or of the account. ``owner`` is the connected
        account's own login or an organization it may create repositories in.
        The NoClick repo stays as it was.

        A connection with no GitHub account connected yet raises
        ``noclick.NeedsConnection``, whose ``connect_url`` connects it. The
        operation fails with ``noclick.Conflict`` when GitHub already has
        ``owner/name``, and ``noclick.PermissionDenied`` when the connected
        account can't create repositories there.

        Returns:
            An operation whose ``.wait()`` gives the new GitHub repository's URL.

        Usage:
            Hand a repo to its owner's GitHub organization::

                repo = noclick.Repo.from_name("agent-tools")
                try:
                    url = repo.export_to_github(connection="github", owner="acme").wait()
                    print(url)   # https://github.com/acme/agent-tools
                except noclick.NeedsConnection as needed:
                    print("Connect GitHub first:", needed.connect_url)
        """
        ref = connection if isinstance(connection, str) else await ref_id(connection)
        payload = await self._request(
            "POST", f"{await self._repo_path()}/export",
            json=compact(to="github", connection=ref, owner=owner, name=name, private=private),
        )
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="repo.export_to_github",
            reader=_read_github,
        )

    @synced
    async def delete(self) -> TrashItem:
        """Delete the repo and its history: it goes to the trash, restorable for 30 days. A repo an app deploys
        from (see ``used_by``) is refused with ``noclick.Conflict``; delete that app first.

        Returns:
            Its ``TrashItem``: ``restore()`` puts it back, history and all.

        Usage::

            repo = noclick.Repo.from_name("scratch")
            repo.delete()
        """
        raw = await self._request("DELETE", await self._repo_path())
        return trashed(raw, client=self._client, user=self._call_scope())
