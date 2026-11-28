"""Skills: Agent Skills folders any agent of their scope can attach.

    check = noclick.Skill.from_dir("./skills/invoice-check")              # SKILL.md plus its scripts and files
    support = noclick.Agent.from_name("support", create_if_missing=True, instructions="...", skills=[check])

A skill is a folder: a ``SKILL.md`` whose frontmatter names it (``name``) and
says what it does and when to use it (``description``; ``always: true`` puts it
whole in every turn), plus any other files. Every save is a new version; an
agent follows the latest unless it holds one (``skill.pinned(3)``). A coding
harness finds its skills where it reads skills; an ``sdk`` agent sees each
one's name and description every turn and reads one with ``skill__read``.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from ._client import Client
from ._object import Page, _Object, compact, field, list_all, list_page, parse_time, ref_id
from ._scope import AMBIENT, resolve_scope
from ._sync import synced
from .exceptions import Conflict, NotFound
from .trash import TrashItem, trashed
from .volume import is_id

Files = Mapping[str, Union[str, bytes]]
# What a folder may hold (the API's own limits): read no further than this.
_MAX_FILES = 200


@dataclass(frozen=True)
class SkillLink:
    """A skill held at one version on an agent (``skill.pinned(n)``)."""

    skill: Any
    pin: int


@dataclass(frozen=True)
class SkillAttachment:
    """An agent that attaches a skill, and the version it holds (``None``: the latest)."""

    id: str
    name: str
    pin: Optional[int]


@dataclass(frozen=True)
class SkillFileInfo:
    """One file of a version, as its manifest lists it."""

    path: str
    size: int
    sha256: str

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "SkillFileInfo":
        return cls(raw.get("path") or "", int(raw.get("size") or 0), raw.get("sha256") or "")


@dataclass(frozen=True)
class SkillAuthor:
    """Who saved a version: a person in the app (``console``), a key (``api``), or an agent's turn."""

    type: Optional[str]
    agent_id: Optional[str]
    agent_name: Optional[str]


@dataclass(frozen=True)
class SkillVersion:
    """One version of a skill: its frontmatter as that version has it, and its files."""

    version: int
    digest: str
    name: str
    description: str
    always: bool
    files: List[SkillFileInfo]
    size: int
    created_by: SkillAuthor
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "SkillVersion":
        by = raw.get("created_by") or {}
        return cls(int(raw.get("version") or 0), raw.get("digest") or "", raw.get("name") or "",
                   raw.get("description") or "", raw.get("always") is True,
                   [SkillFileInfo._from(f) for f in raw.get("files") or []], int(raw.get("size") or 0),
                   SkillAuthor(by.get("type"), by.get("agent_id"), by.get("agent_name")),
                   parse_time(raw.get("created_at")), raw)


@dataclass(frozen=True)
class SkillFile:
    """One file's content: its text, or base64 when it isn't UTF-8 (``encoding``)."""

    path: str
    version: int
    size: int
    sha256: str
    content: str
    encoding: str


def _wire(files: Files) -> List[Dict[str, str]]:
    out = []
    for path, content in files.items():
        if isinstance(content, bytes):
            out.append({"path": path, "content": base64.b64encode(content).decode(), "encoding": "base64"})
        else:
            out.append({"path": path, "content": content, "encoding": "utf-8"})
    return out


def _folder(path: str) -> Dict[str, Union[str, bytes]]:
    """Every file under ``path`` by its path inside it, text as text."""
    files: Dict[str, Union[str, bytes]] = {}
    for root, dirs, names in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "__pycache__", "node_modules"))
        for name in sorted(names):
            full = os.path.join(root, name)
            with open(full, "rb") as fh:
                data = fh.read()
            try:
                files[os.path.relpath(full, path).replace(os.sep, "/")] = data.decode()
            except UnicodeDecodeError:
                files[os.path.relpath(full, path).replace(os.sep, "/")] = data
            if len(files) > _MAX_FILES:
                raise ValueError(f"{path} holds more than {_MAX_FILES} files, more than a skill takes")
    return files


class Skill(_Object):
    """An Agent Skills folder of the account's (every user's agents may use it)
    or one user's, versioned. Delete it and it goes to the trash, off every agent
    that attaches it; restoring puts it back on them."""

    _repr_keys = ("id", "name", "version")

    id: str = field("id")
    name: str = field("name", doc="Its name, from its latest ``SKILL.md``.")
    description: str = field("description")
    always: bool = field("always", doc="Whether it's put whole in every turn of the agents that attach it.")
    version: int = field("version", doc="Its latest version's number.")
    digest: str = field("digest", doc="Its latest version's content as a digest: what restarts a coding agent's "
                                      "warm sandbox when it changes.")
    file_count: int = field("file_count")
    size: int = field("size", doc="Its latest version's size in bytes.")
    attached_to: List[SkillAttachment] = field(
        "attached_to", lambda rows: [SkillAttachment(a["id"], a["name"], a.get("pin")) for a in rows],
        doc="The agents that attach it, and the version each holds (``None``: the latest).")
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)
    updated_at: Any = field("updated_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(cls, files: Files, *, allow_existing: bool = False, user: Any = AMBIENT,
                     client: Optional[Client] = None) -> "Skill":
        """A skill from its folder (path → text, or bytes for a file that isn't text), named by its ``SKILL.md``;
        unique by name to its user, or to the account outside ``as_user``. A taken name raises
        ``noclick.Conflict`` with ``existing_id``, or with ``allow_existing=True`` returns the skill already
        there as it is (``save_version`` to change it). Up to 200 files and 20 MB, ``SKILL.md`` up to 64 KB.

        Returns:
            The new skill at version 1.

        Usage::

            check = noclick.Skill.create({
                "SKILL.md": "---\\nname: invoice-check\\ndescription: Check an invoice against its purchase order.\\n---\\n1. ...",
                "scripts/match.py": open("match.py").read(),
            })
        """
        scope = resolve_scope(user)
        skill = cls._new(hints={}, client=client, user=scope)
        try:
            skill._raw = await skill._request("POST", "/v1/skills", json={"files": _wire(files)})
        except Conflict as exc:
            if not allow_existing or not exc.existing_id:
                raise
            skill._raw = await skill._request("GET", f"/v1/skills/{exc.existing_id}")
        return skill

    @synced
    @classmethod
    async def from_dir(cls, path: str, *, allow_existing: bool = False, user: Any = AMBIENT,
                       client: Optional[Client] = None) -> "Skill":
        """A skill from a folder on this machine: its ``SKILL.md`` and every other file under it (``.git``,
        ``__pycache__`` and ``node_modules`` left out). A name already taken: as ``create``.

        Returns:
            The new skill (or, with ``allow_existing=True``, the one already there).

        Usage::

            check = noclick.Skill.from_dir("./skills/invoice-check")
        """
        return await cls.create.aio(_folder(path), allow_existing=allow_existing, user=user, client=client)

    @classmethod
    def from_name(cls, name: str, *, create_if_missing: bool = False, files: Optional[Files] = None,
                  user: Any = AMBIENT, client: Optional[Client] = None) -> "Skill":
        """A lazy reference to the skill called ``name``. Acting for a user, that
        user's own skill is found first, then the account's. With
        ``create_if_missing=True`` it's created from ``files`` on first use.

        Returns:
            A skill that loads (or is created) the first time it's used. Nothing is sent yet.

        Usage::

            support = noclick.Agent.from_name("support", create_if_missing=True, instructions="...",
                                              skills=[noclick.Skill.from_name("invoice-check")])
        """
        skill = cls._new(hints={"name": name}, client=client, user=user)
        if create_if_missing:
            if files is None:
                raise TypeError("create_if_missing needs the skill's files: files={'SKILL.md': ...}")
            skill._create_with = {"files": _wire(files)}
        return skill

    @classmethod
    def from_id(cls, skill_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Skill":
        """A lazy reference to a skill by id.

        Returns:
            A skill that loads the first time you read a field. Nothing is sent yet.

        Usage::

            skill = noclick.Skill.from_id(support.skills[0]["id"])
        """
        return cls._new(hints={"id": skill_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, skill_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Skill":
        """Load a skill by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The skill, loaded: its latest version and the agents that attach it.

        Usage::

            print(noclick.Skill.get(skill_id).attached_to)
        """
        skill = cls.from_id(skill_id, client=client, user=user)
        await skill._ensure()
        return skill

    @synced
    @classmethod
    async def list(cls, *, agent: Any = None, limit: Optional[int] = None, user_filter: Any = None,
                   user: Any = AMBIENT, client: Optional[Client] = None) -> List["Skill"]:
        """The current user's skills and the account's (or those ``user_filter`` covers), newest first. With
        ``agent`` (an ``Agent`` or its id), the skills that agent attaches, in its order.

        Returns:
            Every matching skill, fetched page by page.

        Usage::

            for skill in noclick.Skill.list():
                print(skill.name, skill.version, [a.name for a in skill.attached_to])
        """
        return await list_all(
            "/v1/skills", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params=compact(agent_id=await ref_id(agent)), user=user, user_filter=user_filter, limit=limit,
            client=client,
        )

    @synced
    @classmethod
    async def list_page(cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
                        user: Any = AMBIENT, client: Optional[Client] = None) -> Page:
        """One page of skills; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the skills and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Skill.list_page(limit=50)
        """
        return await list_page(
            "/v1/skills", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        skill_id = self._known("id")
        if skill_id:
            return await self._request("GET", f"/v1/skills/{skill_id}")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/skills", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        own = [row for row in rows if bool(row.get("user_id")) == bool(self._scope)]
        rows = own if self._create_with is not None else own + [row for row in rows if row not in own]
        if rows:
            return rows[0]
        if self._create_with is None:
            raise NotFound(f"No skill is named {name!r}.",
                           next_step="Create it with noclick.Skill.create(files) or pass create_if_missing=True "
                                     "and files.", details={"name": name, "kind": "skill"})
        try:
            return await self._request("POST", "/v1/skills", json=self._create_with)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._request("GET", f"/v1/skills/{exc.existing_id}")

    async def _url(self, suffix: str = "") -> str:
        if not self._known("id"):
            await self._ensure()
        return f"/v1/skills/{self._known('id')}{suffix}"

    # --- the skill -------------------------------------------------------

    def pinned(self, version: int) -> SkillLink:
        """This skill held at one version, for an agent's ``skills=``.

        Returns:
            What ``skills=`` takes for a skill the agent holds at ``version``.

        Usage::

            noclick.Agent.from_name("support").update(skills=[noclick.Skill.from_name("invoice-check").pinned(3)])
        """
        return SkillLink(self, version)

    @synced
    async def save_version(self, files: Files, *, removed: Sequence[str] = (), replace: bool = False,
                   base_version: Optional[int] = None) -> "Skill":
        """Save a new version: ``files`` written over the latest (the whole folder with ``replace=True``),
        ``removed`` taken out. With ``base_version`` it saves only while the latest is still that version (else
        ``noclick.Conflict``). Agents following the latest get it in their next conversation; a running coding
        sandbox restarts with it.

        Returns:
            This skill, at its new version.

        Usage::

            check = noclick.Skill.from_name("invoice-check")
            check.save_version({"scripts/match.py": open("match.py").read()}, base_version=check.version)
        """
        self._raw = await self._request("POST", await self._url("/versions"), json=compact(
            files=_wire(files), removed=list(removed) or None, replace=replace or None, base_version=base_version))
        return self

    @synced
    async def update(self, *, name: Optional[str] = None, description: Optional[str] = None) -> "Skill":
        """Rename it or change its description: a new version with its ``SKILL.md`` frontmatter rewritten.

        Returns:
            This skill, as it is now.

        Usage::

            noclick.Skill.from_name("invoice-check").update(description="Check invoices and flag those over budget.")
        """
        self._raw = await self._request("PATCH", await self._url(), json=compact(name=name, description=description))
        return self

    @synced
    async def versions(self) -> List[SkillVersion]:
        """Every version, newest first.

        Returns:
            Each version's frontmatter, files, size and who saved it.

        Usage::

            for v in noclick.Skill.from_name("invoice-check").versions():
                print(v.version, v.created_by.type, v.created_at)
        """
        response = await self._request("GET", await self._url("/versions")) or {}
        return [SkillVersion._from(row) for row in response.get("data") or []]

    @synced
    async def get_version(self, version: int) -> SkillVersion:
        """One version, with its files.

        Returns:
            That version; an unknown one raises ``noclick.NotFound``.

        Usage::

            first = noclick.Skill.from_name("invoice-check").get_version(1)
        """
        return SkillVersion._from(await self._request("GET", await self._url(f"/versions/{version}")))

    @synced
    async def restore(self, version: int) -> "Skill":
        """A new version holding what ``version`` held.

        Returns:
            This skill, at its new version.

        Usage::

            noclick.Skill.from_name("invoice-check").restore(2)
        """
        self._raw = await self._request("POST", await self._url(f"/versions/{version}/restore"))
        return self

    @synced
    async def files(self, *, version: Optional[int] = None) -> List[SkillFileInfo]:
        """The files of a version (the latest unless ``version``), by path.

        Returns:
            Each file's path, size and hash.

        Usage::

            print([f.path for f in noclick.Skill.from_name("invoice-check").files()])
        """
        response = await self._request("GET", await self._url("/files"), params=compact(version=version)) or {}
        return [SkillFileInfo._from(row) for row in response.get("data") or []]

    @synced
    async def read(self, path: str, *, version: Optional[int] = None) -> SkillFile:
        """One file of a version (the latest unless ``version``): its text, or base64 when it isn't UTF-8.

        Returns:
            The file; a path the version doesn't hold raises ``noclick.NotFound``.

        Usage::

            print(noclick.Skill.from_name("invoice-check").read("SKILL.md").content)
        """
        raw = await self._request("GET", await self._url("/files"), params=compact(path=path, version=version))
        return SkillFile(raw["path"], int(raw["version"]), int(raw["size"]), raw["sha256"], raw["content"],
                         raw["encoding"])

    @synced
    async def delete(self) -> TrashItem:
        """Delete it: to the trash, restorable for 30 days, and off every agent that attaches it until it's
        restored.

        Returns:
            Its ``TrashItem``: ``restore()`` puts it back, on its agents too.

        Usage::

            noclick.Skill.from_name("old-checks").delete()
        """
        raw = await self._request("DELETE", await self._url())
        return trashed(raw, client=self._client, user=self._call_scope())


def skill_refs(skills: Optional[Sequence[Any]], *, user: Any, client: Optional[Client]) -> Optional[List[Any]]:
    """``skills=`` on an agent: ``Skill``s (``skill.pinned(n)`` to hold one version), or a skill's id or name,
    looked up lazily in ``user`` (its own, then the account's)."""
    if skills is None:
        return None
    if isinstance(skills, (str, Skill, SkillLink)):
        raise TypeError("skills= is a list: skills=[noclick.Skill.from_name('invoice-check')]")
    refs: List[Any] = []
    for skill in skills:
        if isinstance(skill, str):
            skill = (Skill.from_id(skill, user=user, client=client) if is_id(skill)
                     else Skill.from_name(skill, user=user, client=client))
        if not isinstance(skill, (Skill, SkillLink)):
            raise TypeError(f"skills= takes noclick.Skill, skill.pinned(n) or a skill's id or name, not "
                            f"{type(skill).__name__}")
        refs.append(skill)
    return refs


async def skill_links(refs: Sequence[Any]) -> List[Dict[str, Any]]:
    """``skills`` as the API takes and shows it: ``[{id, pin}]``, in order."""
    return [{"id": await ref_id(ref.skill if isinstance(ref, SkillLink) else ref),
             "pin": ref.pin if isinstance(ref, SkillLink) else None} for ref in refs]
