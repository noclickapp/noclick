"""Workspaces: a home for channels and their members, like a workspace in a team chat.

    billing = noclick.Agent.from_name("billing")
    ana = noclick.User.from_id("ana")
    acme = noclick.Workspace.from_name("Acme", create_if_missing=True, members=[billing, ana], budget_usd_per_month=200)
    room = noclick.Channel.create("billing", workspace=acme, members=[billing, ana])

A workspace lives in a scope that already exists, your account or one of your
users, so it adds no tenancy of its own.
"""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from ._client import Client, path_segment, resolve_client
from ._object import UNSET, Page, _Object, compact, field, list_all, list_page, parse_time, ref_id
from ._sync import synced
from .trash import TrashItem, trashed
from ._scope import AMBIENT, resolve_scope, user_ref
from .agent import Agent, agent_id
from .channel import Channel, ChannelMessage, Subscription, _message_id, subscription_body
from .exceptions import Conflict, NotFound
from .repo import Repo
from .session import Session
from .user import User

STATUSES = ("active", "archived")
ROLES = ("admin", "member", "guest")


def _check_role(role: Optional[str]) -> Optional[str]:
    if role is not None and role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, not {role!r}")
    return role


@dataclass(frozen=True)
class WorkspaceMember:
    """One member of a workspace: ``type`` is ``agent`` or ``user`` (a person: one of
    your users), with its ``agent_id`` or your ``user_id`` for them. Remove one by ``id``.
    A user's ``role`` is ``admin`` (invites and removes people), ``member`` (every channel)
    or ``guest`` (only its own channels); a ``person`` joined from their own NoClick
    sign-in (their ``user_id`` is that login's id), with their ``email`` and when they were
    last active in NoClick (``last_seen_at``)."""

    id: str
    type: str
    agent_id: Optional[str]
    user_id: Optional[str]
    name: Optional[str]
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)
    role: Optional[str] = None
    person: bool = False
    email: Optional[str] = None
    last_seen_at: Any = None
    joined_at: Any = None

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "WorkspaceMember":
        return cls(raw["id"], raw["type"], raw.get("agent_id"), raw.get("user_id"), raw.get("name"),
                   parse_time(raw.get("created_at")), raw, raw.get("role"), bool(raw.get("person")),
                   raw.get("email"), parse_time(raw.get("last_seen_at")),
                   parse_time(raw.get("joined_at") or raw.get("created_at")))


@dataclass(frozen=True)
class MyWorkspace:
    """A workspace as the signed-in person sees it (``Workspace.mine``): their account's
    (``own``, ``role`` ``owner``) or one they joined, whose it is (``account_name``) and
    their ``user_id`` there (their login id). ``personal``: a personal space, the one every
    account has, where what's made without naming a space goes."""

    id: str
    name: str
    logo_url: Optional[str]
    own: bool
    role: str
    status: Optional[str]
    account_name: Optional[str]
    user_id: Optional[str]
    member_id: Optional[str]
    joined_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)
    personal: bool = False

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "MyWorkspace":
        return cls(raw["id"], raw.get("name") or "", raw.get("logo_url"), bool(raw.get("own")), raw.get("role") or "",
                   raw.get("status"), raw.get("account_name"), raw.get("user_id"), raw.get("member_id"),
                   parse_time(raw.get("joined_at")), raw, bool(raw.get("personal")))


@dataclass(frozen=True)
class SpaceNoClick:
    """A space's own NoClick: the agent that answers in it (``agent_id``, put it in a channel by it), its ``name``,
    and its ``label`` as a person reads it (``NoClick · <space>``)."""

    workspace_id: str
    agent_id: str
    name: str
    label: str
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class SpaceQuestion:
    """A question your own NoClick asked a space's NoClick (``Workspace.questions``):
    ``waiting`` until it's answered once, then ``answered`` with its ``answer``, or
    ``unanswered`` when the space's NoClick couldn't."""

    id: str
    workspace_id: str
    question: str
    status: str
    answer: Optional[str]
    asked_at: Any
    answered_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "SpaceQuestion":
        return cls(raw["id"], raw["workspace_id"], raw.get("question") or "", raw.get("status") or "waiting",
                   raw.get("answer"), parse_time(raw.get("asked_at")), parse_time(raw.get("answered_at")), raw)


@dataclass(frozen=True)
class SpaceTemplate:
    """A space saved as a template (``Workspace.save_as_template``): the repository holding it (None on a dry run),
    what it holds, what it asks whoever adds it for, and what stayed behind."""

    name: str
    repo_name: str
    repo: Optional[Repo]
    #: Its parts by name: ``channels``, ``agents``, ``skills``, ``memories``, ``automations``, ``stores``, and
    #: whether it carries an ``app``.
    contains: Dict[str, Any]
    #: What it asks for: ``connections`` (``{integration, for}``), ``secrets`` (``{name, keys, for}``), and
    #: ``budget_usd_per_month``.
    asks: Dict[str, Any]
    #: Each ``{what, why}`` that stayed behind.
    left_out: List[Dict[str, str]]
    #: What a template never carries, in a person's words.
    never: List[str]
    files: int
    commit_sha: Optional[str]
    summary: str
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any], client: Any = None, user: Any = AMBIENT) -> "SpaceTemplate":
        repo = raw.get("repo")
        return cls(raw.get("name") or "", raw.get("repo_name") or "",
                   Repo._new(raw=repo, client=client, user=user) if repo else None, dict(raw.get("contains") or {}),
                   dict(raw.get("asks") or {}), list(raw.get("left_out") or []), list(raw.get("never") or []),
                   int(raw.get("files") or 0), (raw.get("commit") or {}).get("sha"), raw.get("summary") or "", raw)


@dataclass(frozen=True)
class WorkspaceInvite:
    """An invite into a workspace: a ``link`` anyone signed in to NoClick may use (up to
    ``max_uses``), or an ``email`` invite only that address accepts. ``url`` is where
    accepting it opens, while it can still be used; ``status`` is ``active``,
    ``accepted``, ``revoked``, ``expired`` or ``used_up``."""

    id: str
    workspace_id: str
    type: str
    role: str
    email: Optional[str]
    url: Optional[str]
    uses: int
    max_uses: Optional[int]
    uses_left: Optional[int]
    invited_by: Optional[str]
    status: str
    expires_at: Any
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)
    #: When an email invite was last sent (``None``: a link, or not sent).
    sent_at: Any = None
    _client: Any = dc_field(default=None, repr=False, compare=False)
    _user: Any = dc_field(default=AMBIENT, repr=False, compare=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any], client: Any = None, user: Any = AMBIENT) -> "WorkspaceInvite":
        return cls(raw["id"], raw["workspace_id"], raw["type"], raw["role"], raw.get("email"), raw.get("url"),
                   raw.get("uses") or 0, raw.get("max_uses"), raw.get("uses_left"), raw.get("invited_by"),
                   raw.get("status") or "active", parse_time(raw.get("expires_at")),
                   parse_time(raw.get("created_at")), raw, parse_time(raw.get("sent_at")), client, user)

    async def _call(self, method: str, suffix: str = "") -> "WorkspaceInvite":
        response = await resolve_client(self._client).request(
            method, f"/v1/workspaces/{self.workspace_id}/invites/{self.id}{suffix}", user=resolve_scope(self._user))
        return WorkspaceInvite._from(response or {}, self._client, self._user)

    @synced
    async def revoke(self) -> "WorkspaceInvite":
        """Turn it off: its link stops working at once (who joined with it stays).

        Returns:
            The invite, ``revoked``.

        Usage::

            for invite in acme.invites(status="active"):
                invite.revoke()
        """
        return await self._call("DELETE")

    @synced
    async def resend(self) -> "WorkspaceInvite":
        """Email an email invite again, good for another 7 days.

        Returns:
            The invite, with its new ``expires_at``.

        Usage::

            acme.invite("dee@example.com").resend()
        """
        return await self._call("POST", "/resend")

    @synced
    async def rotate(self) -> "WorkspaceInvite":
        """A link's new link: this one stops, the new one keeps its role, uses left and expiry.

        Returns:
            The new invite (its own ``url``).

        Usage::

            link = acme.invite_link()
            link = link.rotate()   # the old URL no longer works
        """
        return await self._call("POST", "/rotate")


RESOURCE_KINDS = ("connection", "app", "database", "files", "repo", "skill", "memory", "machine", "automation")


@dataclass(frozen=True)
class WorkspaceResource:
    """One of your account's resources shared with a workspace: every person in it reaches
    it at ``members_level`` (its admins and members) or ``guests_level`` (its guests);
    ``levels`` are its kind's, lowest first (``agents``: through its agents only), and
    ``level`` what you hold through it. A machine is shared for agents to run on: at
    ``run`` the workspace's agents run there and its people see it, at ``use`` they may
    also move its agents onto it and off it; its shell and files stay yours. An
    automation (one of your workflows) is seen with its runs at ``runs``, also run at
    ``run`` (members' default) and also changed at ``edit``, its runs billed to you."""

    id: str
    workspace_id: str
    kind: str
    ref: str
    name: Optional[str]
    members_level: str
    guests_level: str
    levels: List[str]
    level: Optional[str]
    added_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)
    _client: Any = dc_field(default=None, repr=False, compare=False)
    _user: Any = dc_field(default=AMBIENT, repr=False, compare=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any], client: Any = None, user: Any = AMBIENT) -> "WorkspaceResource":
        return cls(raw["id"], raw["workspace_id"], raw["kind"], raw["ref"], raw.get("name"), raw["members_level"],
                   raw["guests_level"], list(raw.get("levels") or []), raw.get("level"),
                   parse_time(raw.get("added_at")), raw, client, user)

    def _path(self) -> str:
        return f"/v1/workspaces/{self.workspace_id}/resources/{self.id}"

    @synced
    async def update(self, *, members_level: Optional[str] = None,
                     guests_level: Optional[str] = None) -> "WorkspaceResource":
        """Change what its members or guests get (an omitted one stays); the account's own.

        Returns:
            The shared resource with its new levels.

        Usage::

            [orders] = acme.resources(kind="database")
            orders.update(members_level="write")
        """
        response = await resolve_client(self._client).request(
            "PATCH", self._path(), json=compact(members_level=members_level, guests_level=guests_level),
            user=resolve_scope(self._user))
        return WorkspaceResource._from(response or {}, self._client, self._user)

    @synced
    async def remove(self) -> None:
        """Take it from the workspace's people; your account keeps it, and agents that hold
        it as their own keep it.

        Returns:
            ``None``.

        Usage::

            orders.remove()
        """
        await resolve_client(self._client).request("DELETE", self._path(), user=resolve_scope(self._user))


async def _member_spec(member: Any, role: Optional[str] = None) -> Dict[str, Any]:
    """A workspace member on the wire: ``{agent_id}`` or ``{user_id, role?}``."""
    if isinstance(member, Agent):
        if role is not None:
            raise ValueError("An agent in a workspace has no role; a role is a user's.")
        return {"agent_id": await agent_id(member)}
    if isinstance(member, User):
        return compact(user_id=await user_ref(member), role=_check_role(role))
    if isinstance(member, WorkspaceMember):
        return {"agent_id": member.agent_id} if member.type == "agent" else {"user_id": member.user_id}
    raise TypeError(f"A workspace member is a noclick.Agent or a noclick.User, not {member!r}")


def _matches(member: WorkspaceMember, spec: Dict[str, Any]) -> bool:
    if spec.get("agent_id"):
        return member.type == "agent" and member.agent_id == spec["agent_id"]
    return member.type == "user" and member.user_id == spec.get("user_id")


def _check_status(status: Optional[str]) -> None:
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, not {status!r}")


# What ``from_name`` sets on an existing workspace.
_CONVERGED = ("budget_usd_per_month", "logo_url")


class Workspace(_Object):
    """A home for channels and their members, like a workspace in a team chat: a
    company, a client or a team, with its people, its agents and its rooms. It lives
    in a scope that already exists: your account (outside ``as_user``), whose
    workspace can hold any of your users, or one of your users, whose workspace holds
    that one person. Its channels (``Channel.create(..., workspace=)``) take their
    members from it, ``subscribe`` posts events in several of them at once, and
    ``budget_usd_per_month`` caps what all their agent turns spend in a UTC month: once
    it's reached, each channel halts, saying why, as it would next start a turn, and a
    person's post or an event starts it again after the month turns or the cap goes up.
    ``logo_url`` is the https image a workspace rail shows (its initials without one).

    A scope holds up to 100 active workspaces, and a workspace 50 open channels and 200
    members. Every account also has its personal space (``personal``), made the first time
    it's read: a space like any other, where an agent or a channel made without naming a
    space goes, uncapped, never archived or deleted.
    """

    _repr_keys = ("id", "name", "status")

    id: str = field("id")
    name: str = field("name")
    logo_url: Optional[str] = field("logo_url", doc="The image that stands for it (``None``: its initials).")
    user_id: Optional[str] = field("user_id", doc="The user it belongs to (``None``: your account).")
    status: str = field("status", doc="``active``, or ``archived``: its channels closed, everything still readable.")
    personal: Optional[bool] = field(
        "personal", doc="The account's personal space: where what's made without naming a space goes.",
    )
    budget_usd_per_month: Optional[float] = field(
        "budget_usd_per_month", doc="What its channels' agent turns may spend in a month (``None``: no cap of its own).",
    )
    spent_usd: Optional[float] = field("spent_usd", doc="What its channels' agent turns have spent this month.")
    channel_count: Optional[int] = field("channel_count", doc="How many open channels it has.")
    role: Optional[str] = field(
        "role", doc="Your role in it: ``owner`` (your account's, or your user's own), else the role you joined with.",
    )
    people_count: Optional[int] = field("people_count", doc="How many people are in it, its account's owner included.")
    people_limit: Optional[int] = field(
        "people_limit", doc="The most people its account's plan lets it hold, its owner included (3 on Free, 50 on "
        "Member).",
    )
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    @property
    def members(self) -> List[WorkspaceMember]:
        """Its agents and people."""
        return [WorkspaceMember._from(m) for m in self._sync_raw().get("members") or []]

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls,
        name: str,
        *,
        members: Sequence[Any] = (),
        budget_usd_per_month: Optional[float] = None,
        logo_url: Optional[str] = None,
        allow_existing: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Workspace":
        """Make a workspace in the current (or given) user, or in your account outside
        ``as_user``. ``members`` are ``noclick.Agent``s and ``noclick.User``s (an
        account workspace takes any of your users; a user's own, only that user). A
        name is unique among a scope's workspaces: a taken one raises
        ``noclick.Conflict`` with ``existing_id``, or with ``allow_existing=True`` returns
        the workspace already there, as it is: its members and settings don't change.

        Returns:
            The new workspace, ``active``, with its ``members``.

        Usage::

            acme = noclick.Workspace.create(
                "Acme",
                members=[noclick.Agent.from_name("billing"), noclick.User.from_id("ana"), noclick.User.from_id("bo")],
                budget_usd_per_month=200,
                logo_url="https://cdn.acme.test/logo.png",
            )
            print(acme.id, [member.name for member in acme.members])
        """
        scope = resolve_scope(user)
        body = compact(name=name, members=[await _member_spec(m) for m in members],
                       budget_usd_per_month=budget_usd_per_month, logo_url=logo_url)
        raw = await cls._create_named("/v1/workspaces", body, allow_existing=allow_existing, user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        create_if_missing: bool = False,
        members: Optional[Sequence[Any]] = None,
        budget_usd_per_month: Any = UNSET,
        logo_url: Any = UNSET,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Workspace":
        """A lazy reference to the active workspace called ``name`` in the current (or
        given) user. Given fields, it gets the workspace and sets the ones you pass, on every run:
        on an existing one a member your code no longer lists is removed (and so taken out of its
        channels), a new one added, and ``budget_usd_per_month`` and ``logo_url`` set to yours.
        A field you leave out is never changed, and ``None`` clears the cap or the logo.
        ``create_if_missing=True`` makes it with the fields ``create`` takes when there's none;
        without it, a missing workspace raises ``noclick.NotFound``. Each run
        with fields is a write: set them at startup or in a setup script, and take the bare
        ``from_name`` in request handlers.

        Returns:
            A workspace that loads (or is made, or has your fields set) the first time it's used.
            Nothing is sent yet.

        Usage:
            One workspace per customer company, set on every deploy::

                billing = noclick.Agent.from_name("billing")
                acme = noclick.Workspace.from_name(
                    "Acme", create_if_missing=True, members=[billing, noclick.User.from_id("ana")],
                    budget_usd_per_month=200,
                )
                room = noclick.Channel.from_name("billing", workspace=acme, create_if_missing=True, members=[billing])
        """
        workspace = cls._new(hints={"name": name}, client=client, user=user)
        settings = dict(budget_usd_per_month=budget_usd_per_month, logo_url=logo_url)
        workspace._define({
            "name": name,
            **{k: v for k, v in settings.items() if v is not UNSET},
            **({} if members is None else {"members": list(members)}),
        }, create_if_missing=create_if_missing)
        return workspace

    @classmethod
    def from_id(cls, workspace_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Workspace":
        """A lazy reference to a workspace by id.

        Returns:
            A workspace that loads the first time you read a field. Nothing is sent yet.

        Usage::

            acme = noclick.Workspace.from_id("2f6c1a9e-4b7d-4c3e-9a8f-5d1e7b0c3a62")
            print([room.name for room in acme.channels()])
        """
        return cls._new(hints={"id": workspace_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, workspace_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Workspace":
        """Load a workspace by id now; an unknown id raises ``noclick.NotFound``, and so
        does a user's workspace loaded without that user.

        Returns:
            The workspace, loaded, with its ``members``.

        Usage::

            acme = noclick.Workspace.get("2f6c1a9e-4b7d-4c3e-9a8f-5d1e7b0c3a62")
            print(acme.name, acme.spent_usd, acme.budget_usd_per_month)
        """
        workspace = cls.from_id(workspace_id, client=client, user=user)
        await workspace._ensure()
        return workspace

    @synced
    @classmethod
    async def list(
        cls,
        *,
        status: Optional[str] = None,
        agent: Any = None,
        limit: Optional[int] = None,
        user_filter: Any = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Workspace"]:
        """The current user's workspaces (your account's outside ``as_user``, or those
        ``user_filter`` covers); ``status`` keeps ``active`` or ``archived`` ones, ``agent``
        (a ``noclick.Agent`` or its id) the ones that agent is a member of.

        Returns:
            Every matching workspace, newest first, fetched page by page.

        Usage::

            for workspace in noclick.Workspace.list(status="active"):
                print(workspace.name, workspace.channel_count, workspace.spent_usd)
        """
        _check_status(status)
        return await list_all(
            "/v1/workspaces", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"status": status, "agent_id": await agent_id(agent)}, user=user, user_filter=user_filter,
            limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, status: Optional[str] = None,
        agent: Any = None, user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of workspaces; pass ``next_cursor`` back as ``cursor``; ``agent`` is as in ``list``.

        Returns:
            A page whose ``data`` holds the workspaces and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Workspace.list_page(limit=50, user_filter=noclick.ALL_USERS)
            while True:
                for workspace in page.data:
                    print(workspace.user_id, workspace.name)
                if page.next_cursor is None:
                    break
                page = noclick.Workspace.list_page(limit=50, user_filter=noclick.ALL_USERS, cursor=page.next_cursor)
        """
        _check_status(status)
        return await list_page(
            "/v1/workspaces", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"status": status, "agent_id": await agent_id(agent)}, user=user, user_filter=user_filter,
            cursor=cursor, limit=limit, client=client,
        )

    # --- loading ---------------------------------------------------------

    async def _id_path(self) -> str:
        if not self._known("id"):
            await self._ensure()
        return f"/v1/workspaces/{self._known('id')}"

    async def _load(self) -> Dict[str, Any]:
        if self._known("id"):
            return await self._request("GET", f"/v1/workspaces/{self._known('id')}")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/workspaces", params={"name": name, "status": "active"}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name and row.get("status") != "archived"]
        if rows:
            return await self._converge(rows[0])
        if not self._creates:
            raise NotFound(
                f"No workspace is named {name!r}.",
                next_step="Make it with noclick.Workspace.create(...) or pass create_if_missing=True.",
                details={"name": name, "kind": "workspace"},
            )
        definition = self._create_with
        body = {
            **compact(**{k: v for k, v in definition.items() if k != "members"}),
            "members": [await _member_spec(m) for m in definition.get("members") or []],
        }
        try:
            return await self._request("POST", "/v1/workspaces", json=body)
        except Conflict as exc:  # made concurrently
            if not exc.existing_id:
                raise
            return await self._converge(await self._request("GET", f"/v1/workspaces/{exc.existing_id}"))

    async def _converge(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Set the fields ``from_name`` was given on an existing workspace."""
        definition = self._create_with
        if definition is None:
            return raw
        workspace_id = raw["id"]
        changes = {k: definition[k] for k in _CONVERGED if k in definition and raw.get(k) != definition[k]}
        if changes:
            raw = await self._request("PATCH", f"/v1/workspaces/{workspace_id}", json=changes)
        if "members" not in definition:
            return raw
        wanted = [await _member_spec(m) for m in definition["members"]]
        have = [WorkspaceMember._from(m) for m in raw.get("members") or []]
        changed = False
        for member in have:
            if not any(_matches(member, spec) for spec in wanted):
                await self._request("DELETE", f"/v1/workspaces/{workspace_id}/members/{member.id}")
                changed = True
        for spec in wanted:
            if not any(_matches(member, spec) for member in have):
                await self._request("POST", f"/v1/workspaces/{workspace_id}/members", json=spec)
                changed = True
        return await self._request("GET", f"/v1/workspaces/{workspace_id}") if changed else raw

    # --- changes -----------------------------------------------------------

    @synced
    async def update(self, *, name: Any = UNSET, logo_url: Any = UNSET, budget_usd_per_month: Any = UNSET) -> "Workspace":
        """Rename it, or change its logo or its monthly cap (``None`` clears either).

        Returns:
            This workspace, updated.

        Usage::

            acme = noclick.Workspace.from_name("Acme")
            acme.update(budget_usd_per_month=500, logo_url="https://cdn.acme.test/logo-dark.png")
        """
        changes = {k: v for k, v in dict(name=name, logo_url=logo_url, budget_usd_per_month=budget_usd_per_month).items()
                   if v is not UNSET}
        self._raw = await self._request("PATCH", await self._id_path(), json=changes)
        return self

    @synced
    async def set_logo(self, image: Any, *, mime_type: Optional[str] = None) -> "Workspace":
        """Upload its logo (a path, bytes or a binary file object): a JPEG, PNG,
        WebP or GIF of at most 2 MB, kept as an account file that ``logo_url``
        then points at. Bytes or a file object without a name need ``mime_type``.

        Returns:
            This workspace, with its new ``logo_url``.

        Usage::

            acme = noclick.Workspace.from_name("Acme")
            acme.set_logo("acme-logo.png")
            print(acme.logo_url)
        """
        if isinstance(image, (str, os.PathLike)):
            mime_type = mime_type or mimetypes.guess_type(os.fspath(image))[0]
            with open(image, "rb") as handle:
                data = handle.read()
        else:
            data = bytes(image.read()) if hasattr(image, "read") else bytes(image)
            mime_type = mime_type or mimetypes.guess_type(str(getattr(image, "name", "") or ""))[0]
        if not mime_type:
            raise TypeError("Say the image's type: mime_type='image/png'.")
        self._raw = await self._request("PUT", f"{await self._id_path()}/logo", params={"mime_type": mime_type},
                                        content=data)
        return self

    @synced
    async def archive(self) -> "Workspace":
        """Put it away: its channels close (their turns in flight are canceled) and its
        subscriptions stop, and everything in it stays readable. An archived workspace takes
        no changes (``noclick.Conflict``), and its name is free for a new one.

        Returns:
            This workspace, ``archived``.

        Usage::

            acme = noclick.Workspace.from_name("Acme")
            acme.archive()
            print(acme.status)   # archived
        """
        self._raw = await self._request("POST", f"{await self._id_path()}/archive")
        return self

    @synced
    async def delete(self) -> TrashItem:
        """Move it to the trash with its channels (their messages, DMs and files), its invites and its own NoClick,
        restorable for 30 days as it was. Its people lose it meanwhile; your agents and users stay.

        Returns:
            Its ``TrashItem``: ``restore()`` brings it all back.

        Usage::

            noclick.Workspace.from_name("Acme").delete()
        """
        raw = await self._request("DELETE", await self._id_path())
        return trashed(raw, client=self._client, user=self._call_scope())

    @synced
    async def unarchive(self) -> "Workspace":
        """Make an archived workspace active again: the channels its archiving closed open again, and its
        subscriptions hear again. Its name must be free among your active workspaces (``noclick.Conflict``).

        Returns:
            This workspace, ``active``.

        Usage::

            acme = noclick.Workspace.get(workspace_id)
            acme.unarchive()
        """
        self._raw = await self._request("POST", f"{await self._id_path()}/unarchive")
        return self

    # --- channels and members ------------------------------------------------

    @synced
    async def channels(self, *, status: Optional[str] = None) -> List[Channel]:
        """Its channels, newest first: ``Channel.list(workspace=...)``.

        Returns:
            Every channel in it (``status`` keeps ``open`` or ``closed`` ones).

        Usage::

            acme = noclick.Workspace.from_name("Acme")
            for room in acme.channels(status="open"):
                print(room.name, [member.name for member in room.members])
        """
        await self._ensure()
        return await Channel.list.aio(workspace=self._known("id"), status=status, user=self._call_scope(),
                                      client=self._client)

    @synced
    async def add(self, member: Any, *, role: Optional[str] = None) -> WorkspaceMember:
        """Add a ``noclick.Agent`` of its scope or a ``noclick.User`` (an account workspace
        takes any of your users; a user's own, only that user), a user with its ``role``
        (``member`` by default). Its channels can then take them as members; one already in
        it raises ``noclick.Conflict``.

        Returns:
            The member as the workspace now holds it.

        Usage::

            acme = noclick.Workspace.from_name("Acme")
            acme.add(noclick.Agent.from_name("onboarding"))
            acme.add(noclick.User.from_id("carla"))
        """
        spec = await _member_spec(member, role)
        response = await self._request("POST", f"{await self._id_path()}/members", json=spec) or {}
        added = WorkspaceMember._from(response)
        if self._raw is not None:
            self._raw = {**self._raw, "members": [*(self._raw.get("members") or []), response]}
        return added

    @synced
    async def set_role(self, member: Any, role: str) -> WorkspaceMember:
        """Change a person's role (``admin``, ``member`` or ``guest``): the workspace's owner,
        or an admin of it.

        Returns:
            The member with its new role.

        Usage::

            ana = next(m for m in acme.members if m.name == "Ana")
            acme.set_role(ana, "admin")
        """
        member_id = member.id if isinstance(member, WorkspaceMember) else member
        response = await self._request("PATCH", f"{await self._id_path()}/members/{member_id}",
                                       json={"role": _check_role(role)}) or {}
        return WorkspaceMember._from(response)

    @synced
    async def invite_link(self, *, role: Optional[str] = None, expires_in_days: Optional[int] = None,
                          max_uses: Optional[int] = None) -> WorkspaceInvite:
        """A link anyone signed in to NoClick may use to join (its ``url``), as ``role``
        (``member`` by default), at most ``max_uses`` times, for ``expires_in_days`` (30 by
        default, at most 90). People who join become users of your account, and what they do
        in the workspace bills it. Its owner or an admin; 50 invites a day.

        Returns:
            The invite, with its ``url`` to share.

        Usage::

            link = acme.invite_link(role="guest", max_uses=5)
            print(link.url)
        """
        response = await self._request("POST", f"{await self._id_path()}/invite_links", json=compact(
            role=_check_role(role), expires_in_days=expires_in_days, max_uses=max_uses)) or {}
        return WorkspaceInvite._from(response, self._client, self._call_scope())

    @synced
    async def invite(self, email: str, *, role: Optional[str] = None) -> WorkspaceInvite:
        """Email ``email`` an invite, good for 7 days, that only a NoClick sign-in with that
        email accepts; inviting an address already invited sends that invite again.

        Returns:
            The invite.

        Usage::

            acme.invite("dee@example.com", role="member")
        """
        response = await self._request("POST", f"{await self._id_path()}/invites",
                                       json=compact(email=email, role=_check_role(role))) or {}
        return WorkspaceInvite._from(response, self._client, self._call_scope())

    @synced
    async def invites(self, *, status: Optional[str] = None) -> List[WorkspaceInvite]:
        """Its invites, newest first; ``status`` keeps one (``active``, ``accepted``,
        ``revoked``, ``expired``, ``used_up``).

        Returns:
            Its invites.

        Usage::

            pending = acme.invites(status="active")
        """
        response = await self._request("GET", f"{await self._id_path()}/invites", params={"status": status}) or {}
        return [WorkspaceInvite._from(r, self._client, self._call_scope()) for r in response.get("data") or []]

    @synced
    async def resources(self, *, kind: Optional[str] = None) -> List[WorkspaceResource]:
        """What your account shares with it (``kind`` keeps one); a person in it reads what
        reaches them, with their ``level``.

        Returns:
            The shared resources, oldest first.

        Usage::

            for shared in acme.resources():
                print(shared.kind, shared.name, shared.members_level)
        """
        response = await self._request("GET", f"{await self._id_path()}/resources", params={"kind": kind}) or {}
        return [WorkspaceResource._from(r, self._client, self._call_scope()) for r in response.get("data") or []]

    @synced
    async def share(self, kind: str, ref: Any, *, members_level: Optional[str] = None,
                    guests_level: Optional[str] = None) -> WorkspaceResource:
        """Share one of your account's resources with it (its id, or the object): every
        person in it gets it at ``members_level`` (the kind's default when left out) or, a
        guest, ``guests_level`` (``none``), and anyone who joins later. ``kind`` is one of
        ``connection``, ``app``, ``database``, ``files``, ``repo``, ``skill``, ``memory``,
        ``machine``, ``automation`` (a workflow); a connection is shared by its id.

        Returns:
            The shared resource.

        Usage::

            acme.share("database", orders_db, members_level="read")
            acme.share("machine", dev_box, members_level="use")   # its people place agents there
            acme.share("automation", monday_plan)                  # its people see and run it
        """
        if kind not in RESOURCE_KINDS:
            raise ValueError(f"kind must be one of {RESOURCE_KINDS}, not {kind!r}")
        response = await self._request("POST", f"{await self._id_path()}/resources", json=compact(
            kind=kind, ref=await ref_id(ref), members_level=members_level, guests_level=guests_level)) or {}
        return WorkspaceResource._from(response, self._client, self._call_scope())

    @synced
    async def messages(self, *, since: Any = None, after: Any = None,
                       limit: Optional[int] = None) -> List[ChannelMessage]:
        """What was said across its open channels since ``since`` (a ``datetime`` with its
        timezone, or an ISO time; the last 24 hours when left out), in one read: each message
        of a channel's main timeline posted since then, or whose thread had a reply since
        (``reply_count``; read the replies with the channel's ``replies``), with its
        ``channel_name``. Only the channels you see in it, never a DM.

        Returns:
            Up to ``limit`` (50 by default) messages, oldest first: pass the last one as
            ``after`` to read on.

        Usage::

            from datetime import datetime

            today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
            for message in acme.messages(since=today):
                print(f"#{message.channel_name} {message.author.name}: {message.text}")
        """
        when = since.isoformat() if isinstance(since, datetime) else since
        response = await self._request("GET", f"{await self._id_path()}/messages", params=compact(
            since=when, cursor=_message_id(after), limit=limit)) or {}
        return [ChannelMessage._from(m) for m in response.get("data") or []]

    @synced
    async def summary(self) -> Dict[str, Any]:
        """Its Resources tab in one read: ``{workspace_id, kinds}``, ``kinds`` holding
        ``agents`` (``working``, ``waiting``, ``idle``), ``machines`` (``up``, and ``shared``:
        the machines shared with it, each with the agents here placed on it), ``channels``,
        ``numbers``, ``email`` and each shareable kind as the tab names it (``connections``,
        ``websites``, ``databases``, ``files``, ``code``, ``skills``, ``memories``), each
        ``{count, items}``.

        Returns:
            The summary.

        Usage::

            print(acme.summary()["kinds"]["agents"]["working"])
        """
        return await self._request("GET", f"{await self._id_path()}/summary") or {}

    @synced
    async def save_as_template(self, *, repo_name: Optional[str] = None, description: Optional[str] = None,
                               app: Any = None, include_app: bool = True, dry_run: bool = False) -> SpaceTemplate:
        """Save the space as a template: a new repository of yours holding its ``space.json`` (its channels, agents
        and their instructions, the skills and memories they use, the automations it shares), those parts' files,
        and the code of the app it shares. Wherever one of your connections is named, the template names its
        integration and asks for it. Never its messages, data, people, accounts or secrets' values (``never``);
        ``left_out`` names what else stayed behind and why. The repository is private until you make it public
        (``template.repo.make_public()``). Only one of the account's own spaces, never the personal space.

        Args:
            repo_name: The new repository's name (the space's name with ``-template`` unless set).
            description: What the template does, in a line.
            app: The app (or its id) whose code it carries, when the space shares several.
            include_app: ``False`` carries no app's code.
            dry_run: Say what would go in, making nothing.

        Returns:
            Its ``SpaceTemplate``: ``repo`` (None on a dry run), what it ``contains`` and ``asks`` for.

        Usage::

            saved = noclick.Workspace.from_name("Social media").save_as_template(description="Posts for Lumen.")
            print(saved.contains["agents"], saved.asks.get("connections"))
            print(saved.repo.make_public().origin_url)
        """
        raw = await self._request("POST", f"{await self._id_path()}/template", json=compact(
            repo_name=repo_name, description=description, app_id=await ref_id(app) if app is not None else None,
            include_app=None if include_app else False, dry_run=dry_run or None)) or {}
        return SpaceTemplate._from(raw, client=self._client, user=self._call_scope())

    @synced
    @classmethod
    async def from_template(cls, source: Any, *, name: Optional[str] = None,
                            leave_out: Optional[Sequence[Dict[str, Any]]] = None,
                            cap_usd_per_month: Optional[float] = None, connections: Optional[Dict[str, str]] = None,
                            secrets: Optional[Dict[str, Dict[str, str]]] = None,
                            app_secrets: Optional[Dict[str, str]] = None, dry_run: bool = False,
                            client: Optional[Client] = None) -> Any:
        """Add a space template as a new space of yours: its channels, agents (with their instructions, skills and
        memories), automations, data stores and app, each made in your account, all of it or none. Each account it
        uses is one you have (never asked again) or waits for you to connect, and the space's ``#noclick`` opens on a
        welcome post saying what arrived, a row to connect each account left and a first task to tap. Only the
        account adds one.

        Args:
            source: The template's address (its origin URL, or a ``noclick.com/deploy?repo=`` link naming it), or one
                of your repos holding a ``space.json`` (a ``Repo``, its id or its name).
            name: The new space's name (the template's own, numbered past one you have, when left out).
            leave_out: Parts that stay out, each ``{"kind": "agent", "name": "Designer"}`` (``{"kind": "app"}`` for
                its app): leave out every channel to bring just the agents.
            cap_usd_per_month: What its agents may spend together in a month, shared out as their budgets (the
                template's own when left out).
            connections: Which of your connected accounts each integration uses, by integration (the newest of its
                kind when left out).
            secrets: Values for the secrets it asks for, by name: ``{"unsplash": {"UNSPLASH_ACCESS_KEY": "..."}}``.
            app_secrets: Values for the secrets its app's ``noclick.json`` asks you to set.
            dry_run: Say what it would make and ask, making nothing.

        Returns:
            A ``TemplateAdd`` operation whose ``wait()`` gives a ``TemplateAdded``; with ``dry_run``, its
            ``TemplatePlan``.

        Usage::

            plan = noclick.Workspace.from_template(address, dry_run=True)
            print(plan.summary, plan.cap["usd_per_month"])
            added = noclick.Workspace.from_template(address, secrets={"unsplash": {"UNSPLASH_ACCESS_KEY": key}}).wait()
            print(added.workspace_name, added.waiting)
        """
        from .space_template import template_answer, template_body

        raw = await resolve_client(client).request("POST", "/v1/workspaces/from_template", json=template_body(
            source, leave_out=leave_out, cap_usd_per_month=cap_usd_per_month, connections=connections,
            secrets=secrets, app_secrets=app_secrets, dry_run=dry_run, name=name), user=None) or {}
        return template_answer(raw, client=client, user=None)

    @synced
    async def add_template(self, source: Any, *, leave_out: Optional[Sequence[Dict[str, Any]]] = None,
                           cap_usd_per_month: Optional[float] = None, connections: Optional[Dict[str, str]] = None,
                           secrets: Optional[Dict[str, Dict[str, str]]] = None,
                           app_secrets: Optional[Dict[str, str]] = None, dry_run: bool = False) -> Any:
        """Add a space template to this space, beside what's there: its channels carry the template's word
        (``#social-ideas``), an agent whose name you have already carries it too (``Social Writer``); nothing you
        have is reused or merged. ``leave_out`` names the parts that stay out. Otherwise as
        ``Workspace.from_template``.

        Returns:
            A ``TemplateAdd`` operation whose ``wait()`` gives a ``TemplateAdded``; with ``dry_run``, its
            ``TemplatePlan``.

        Usage::

            lumen = noclick.Workspace.from_name("Lumen Coffee")
            plan = lumen.add_template(address, leave_out=[{"kind": "app"}], dry_run=True)
            print([(p.name, p.named) for p in plan.parts if p.included])
            lumen.add_template(address, leave_out=[{"kind": "app"}]).wait()
        """
        from .space_template import template_answer, template_body

        raw = await self._request("POST", f"{await self._id_path()}/template/add", json=template_body(
            source, leave_out=leave_out, cap_usd_per_month=cap_usd_per_month, connections=connections,
            secrets=secrets, app_secrets=app_secrets, dry_run=dry_run)) or {}
        return template_answer(raw, client=self._client, user=self._call_scope())

    @synced
    async def noclick_agent(self) -> SpaceNoClick:
        """The space's own NoClick (an account's own spaces have one; the personal space's is the account's own
        NoClick), made the first time it's asked for: put it in a channel by its ``agent_id``.

        Returns:
            Its ``agent_id``, ``name`` and ``label`` (``NoClick · <space>``).

        Usage::

            helper = noclick.Workspace.from_name("Support").noclick_agent()
            channel.add_member(helper.agent_id)
        """
        raw = await self._request("GET", f"{await self._id_path()}/noclick", user=None) or {}
        return SpaceNoClick(raw.get("workspace_id") or "", raw.get("agent_id") or "", raw.get("name") or "",
                            raw.get("label") or "", raw)

    @synced
    @classmethod
    async def personal_space(cls, *, client: Optional[Client] = None) -> MyWorkspace:
        """Your personal space: the space every account has, made the first time it's read, where an agent or a
        channel made without naming a space goes. Invite people to it as to any space; they never see your own chat
        with NoClick there. Signed in to NoClick; ``mine()`` lists it too, first.

        Returns:
            It, as ``mine()`` lists it.

        Usage::

            personal = noclick.Workspace.personal_space()
            print(personal.id, personal.name)
        """
        response = await resolve_client(client).request("POST", "/v1/me/personal_space", user=None) or {}
        return MyWorkspace._from(response)

    @synced
    @classmethod
    async def mine(cls, *, client: Optional[Client] = None) -> List[MyWorkspace]:
        """The workspaces you see, signed in to NoClick: your personal space first (``personal``),
        your account's other active ones (``own``, role ``owner``), then the active ones you joined
        in other accounts, with your role and whose each is, then your account's archived ones
        (``status`` archived), which ``unarchive`` brings back. One of the account's own secret
        keys reads the account's own ones, never those you joined.

        Returns:
            Each workspace as you see it.

        Usage::

            for space in noclick.Workspace.mine():
                print(space.name, space.role, space.account_name)
        """
        response = await resolve_client(client).request("GET", "/v1/me/workspaces", user=None) or {}
        return [MyWorkspace._from(r) for r in response.get("data") or []]

    @synced
    @classmethod
    async def session(cls, workspace: Any, *, ttl_s: Optional[int] = None,
                      client: Optional[Client] = None) -> Session:
        """A session acting as you in a workspace you joined: ``session.client()`` reads and
        posts in its channels and talks to its agents, as your user in its account. It lasts
        ``ttl_s`` (an hour by default, at most a day): mint another before it lapses.

        Returns:
            The session, its ``token`` your page's key for that workspace.

        Usage::

            space = noclick.Workspace.mine()[1]
            as_me = noclick.Workspace.session(space).client()
            noclick.Channel.list(client=as_me)
        """
        workspace_id = workspace.id if isinstance(workspace, MyWorkspace) else workspace
        api = resolve_client(client)
        response = await api.request("POST", f"/v1/me/workspaces/{workspace_id}/sessions",
                                     json=compact(ttl_s=ttl_s), user=None) or {}
        return Session(token=response.get("token"), id=response.get("id"), user_id=response.get("user_id"),
                       scopes=list(response.get("scopes") or []), expires_at=parse_time(response.get("expires_at")),
                       raw=response, base_url=api.base_url)

    @synced
    @classmethod
    async def questions(cls, workspace: Any, *, client: Optional[Client] = None) -> List[SpaceQuestion]:
        """What your own NoClick asked a space's NoClick (a space you own or joined), newest
        first, each with its answer once it came: read with your own key, or a ``session``
        in the space.

        Returns:
            Each question: ``waiting`` until it's answered once, then ``answered`` with its
            ``answer``, or ``unanswered`` when the space's NoClick couldn't.

        Usage::

            for asked in noclick.Workspace.questions(space):
                print(asked.question, asked.status, asked.answer)
        """
        workspace_id = workspace.id if isinstance(workspace, MyWorkspace) else workspace
        response = await resolve_client(client).request("GET", f"/v1/workspaces/{workspace_id}/questions",
                                                        user=None) or {}
        return [SpaceQuestion._from(r) for r in response.get("data") or []]

    @synced
    @classmethod
    async def leave(cls, workspace: Any, *, client: Optional[Client] = None) -> None:
        """Leave a workspace you joined, and each of its channels.

        Returns:
            ``None``; it's gone from ``mine()`` at once.

        Usage::

            noclick.Workspace.leave(space)
        """
        workspace_id = workspace.id if isinstance(workspace, MyWorkspace) else workspace
        await resolve_client(client).request("DELETE", f"/v1/me/workspaces/{workspace_id}", user=None)

    @synced
    @classmethod
    async def invitation(cls, token: str, *, client: Optional[Client] = None) -> Dict[str, Any]:
        """What an invite is for, read without joining (signed in): ``{workspace: {id, name,
        logo_url}, account_name, invited_by, role, type, email, status, already_member}``.

        Returns:
            The invite as its page shows it.

        Usage::

            print(noclick.Workspace.invitation(token)["workspace"]["name"])
        """
        return await resolve_client(client).request("GET", f"/v1/invites/{path_segment(token)}", user=None) or {}

    @synced
    @classmethod
    async def accept_invite(cls, token: str, *, client: Optional[Client] = None) -> MyWorkspace:
        """Join an invite's workspace as yourself (signed in): you become a user of its
        account, your id there your login id.

        Returns:
            The workspace as ``mine()`` lists it.

        Usage::

            space = noclick.Workspace.accept_invite(token)
            noclick.Workspace.session(space)
        """
        response = await resolve_client(client).request(
            "POST", f"/v1/invites/{path_segment(token)}/accept", user=None) or {}
        return MyWorkspace._from(response)

    @synced
    async def remove(self, member: Any) -> None:
        """Take a member out of the workspace and every one of its channels: a
        ``WorkspaceMember``, its id, or the ``noclick.Agent`` or ``noclick.User`` you added.

        Usage::

            acme = noclick.Workspace.from_name("Acme")
            acme.remove(noclick.User.from_id("bo"))
        """
        if isinstance(member, WorkspaceMember):
            member_id = member.id
        elif isinstance(member, str):
            member_id = member
        else:
            spec = await _member_spec(member)
            self._raw = await self._load()
            found = next((m for m in self.members if _matches(m, spec)), None)
            if found is None:
                raise ValueError(f"{member!r} is not a member of workspace {self._known('name') or self._known('id')}")
            member_id = found.id
        await self._request("DELETE", f"{await self._id_path()}/members/{member_id}")
        if self._raw is not None:
            self._raw = {**self._raw, "members": [m for m in self._raw.get("members") or [] if m.get("id") != member_id]}

    # --- subscriptions ---------------------------------------------------

    @synced
    async def subscribe(
        self, source: Any, *, channels: Any, wake: Any = None, filters: Optional[Dict[str, Any]] = None,
    ) -> Subscription:
        """One subscription posting in several of its channels: ``channels`` is ``"all"``
        (every channel, ones made later too) or a list of its ``Channel``s (or ids).
        ``source``, ``wake`` and ``filters`` are as in ``channel.subscribe``, ``wake``
        applying in each channel (``"all"``: every agent in each). A workspace holds up to
        20 subscriptions.

        Returns:
            The subscription, ``active``.

        Usage:
            Every room in the workspace hears when one of its connections breaks::

                acme = noclick.Workspace.from_name("Acme")
                acme.subscribe("connection.disconnected", channels="all")

            Two rooms, and every agent in them, hear each failed payment::

                stripe = noclick.Connection.from_name("stripe", integration="stripe")
                acme = noclick.Workspace.from_name("Acme")
                rooms = [room for room in acme.channels() if room.name in ("billing", "support")]
                acme.subscribe(noclick.OnEvent(stripe, "invoice_payment_failed"), channels=rooms, wake="all")
        """
        if channels == "all":
            channel_ids: Any = "all"
        elif isinstance(channels, (list, tuple)):
            channel_ids = [await ref_id(channel) for channel in channels]
        else:
            raise TypeError(f"channels= is 'all' or a list of the workspace's channels, not {channels!r}")
        body = {**await subscription_body(source, wake, filters), "channels": channel_ids}
        response = await self._request("POST", f"{await self._id_path()}/subscriptions", json=body)
        return Subscription._new(raw=response, client=self._client, user=self._call_scope())

    @synced
    async def subscriptions(self) -> List[Subscription]:
        """The workspace's own subscriptions (each channel's are on ``channel.subscriptions()``).

        Returns:
            Each subscription with its ``source``, the ``channels`` it posts in, ``wake`` and ``status``.

        Usage::

            acme = noclick.Workspace.from_name("Acme")
            for subscription in acme.subscriptions():
                print(subscription.source, subscription.channels, subscription.status)
        """
        response = await self._request("GET", f"{await self._id_path()}/subscriptions") or {}
        return [Subscription._new(raw=row, client=self._client, user=self._call_scope())
                for row in response.get("data") or []]
