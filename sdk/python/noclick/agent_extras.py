"""An agent's memory, workspace files (``AgentWorkspace``), share link, live events and test runs.

    support = noclick.Agent.from_name("support")
    support.memory.save("refunds", "Refund within 30 days of purchase.", description="Our refund rules")
    files = support.workspace().files()
    link = support.share()
    for event in support.stream("Where's my refund?", conversation="ticket-1841"):
        print(event.type, event.text)
    run = support.rehearse("A customer asks for a refund on order 1841").wait()
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union
from urllib.parse import quote

from ._attachment import Attachment
from ._object import Page, _Object, compact, field, paginate, parse_time
from ._sync import synced
from ._scope import AMBIENT
from .exceptions import NotFound
from .operation import Operation, register_result
from .sandbox import ExecResult
from .volume import VolumeEntry

if TYPE_CHECKING:
    from .agent import Agent, AgentReply, ModelUsage


# --- memory ------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryWriter:
    """Who last wrote a memory entry: an agent's turn (``type`` ``agent``: which agent, and in which of its
    conversations), a person in the app (``console``) or a key (``api``)."""

    type: Optional[str]
    agent_id: Optional[str]
    agent_name: Optional[str]
    conversation: Optional[str]

    @classmethod
    def _from(cls, raw: Any) -> "MemoryWriter":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("type"), raw.get("agent_id"), raw.get("agent_name"), raw.get("conversation"))


@dataclass(frozen=True)
class MemoryEntry:
    """One named note in an agent's memory. ``version`` goes up with every
    save; pass the one you read back to ``save`` or ``delete`` so you never
    overwrite a change the agent made since. ``content`` is ``None`` in a
    listing (``read`` loads it). ``updated_by`` is ``agent``, ``api`` or
    ``console``.

    ``conversation`` is set on a conversation's checkpoint: a long
    conversation keeps its older history folded into one entry, named
    ``context.`` and a hash, which its turns read in place of that history.
    Read it to see what the agent carries forward; an edit wins over the next
    summary, and deleting it forgets that history for good. The agent never
    sees it outside that conversation."""

    name: str
    description: str
    content: Optional[str]
    version: int
    updated_at: Any
    updated_by: Optional[str]
    written_by: MemoryWriter
    user_id: Optional[str]
    conversation: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "MemoryEntry":
        return cls(
            raw["name"], raw.get("description") or "", raw.get("content"), int(raw.get("version") or 0),
            parse_time(raw.get("updated_at")), raw.get("updated_by"), MemoryWriter._from(raw.get("written_by")),
            raw.get("user_id"), raw.get("conversation"), raw,
        )


@dataclass(frozen=True)
class MemoryEntryVersion:
    """One version of a memory entry, as it was saved. Every save keeps the
    version it replaces, so an entry keeps its last 50 versions, the one it
    holds now (``current``) included; a conversation's checkpoint keeps none.
    ``content`` is ``None`` in a listing (``get_version`` loads it), and
    ``saved_at`` is when that version was saved."""

    name: str
    version: int
    current: bool
    description: str
    content: Optional[str]
    written_by: MemoryWriter
    user_id: Optional[str]
    saved_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "MemoryEntryVersion":
        return cls(
            raw["name"], int(raw.get("version") or 0), raw.get("current") is True, raw.get("description") or "",
            raw.get("content"), MemoryWriter._from(raw.get("written_by")), raw.get("user_id"),
            parse_time(raw.get("saved_at")), raw,
        )


class AgentMemory:
    """``agent.memory``: named notes the agent keeps across conversations.
    Every turn starts with each entry's name and description; the agent reads a
    body when it needs one, and saves what it learns. Your code can seed,
    read, correct and forget entries the same way.

    An account agent keeps two layers: entries saved outside ``as_user`` are
    the account's, read in every user's conversations (your refund policy),
    and what it learns while talking to a user is that user's alone. A
    user's own agent has one memory, the user's. The agent changes the
    account's entries only in conversations your code has with it outside
    ``as_user``, and only reads its memory when it answers someone outside
    your account (an inbox's sender, a caller, a visitor to its share link).
    A long conversation also keeps its checkpoint here, in that conversation's
    layer (``MemoryEntry.conversation``).

    It's a ``noclick.Memory`` (its id is ``agent.memory_id``) that goes with
    the agent: another agent of its scope can read it too, with
    ``memories=[agent.memory]``, and named memories (``noclick.Memory``) are
    attached the same way.

    Usage::

        support = noclick.Agent.from_name("support")
        support.memory.save("refunds", "Refund within 30 days of purchase.", description="Our refund rules")
        print([entry.name for entry in support.memory.list()])
    """

    _agent: "Agent"

    @classmethod
    def _of(cls, agent: "Agent") -> "AgentMemory":
        memory = cls.__new__(cls)
        memory._agent = agent
        return memory

    def __repr__(self) -> str:
        return f"AgentMemory(agent={self._agent._known('name') or self._agent._known('id')!r})"

    async def _call(self, method: str, suffix: str, user: Any, **kwargs: Any) -> Any:
        raw = await self._agent._ensure()
        return await self._agent._request(
            method, f"/v1/agents/{raw['id']}/memory{suffix}", user=self._agent._talk_scope(user), **kwargs,
        )

    @synced
    async def list(self, *, user: Any = AMBIENT) -> List[MemoryEntry]:
        """The entries of one layer: the account's outside ``as_user``, else the user's.

        Returns:
            Each entry's name, description, version and when it last changed, by name; ``content`` is
            ``None`` here, so ``read`` an entry for its body.

        Usage::

            support = noclick.Agent.from_name("support")
            for entry in support.memory.list():
                print(entry.name, entry.description, entry.updated_by)
        """
        response = await self._call("GET", "", user) or {}
        return [MemoryEntry._from(row) for row in response.get("data") or []]

    @synced
    async def search(self, query: str, *, limit: Optional[int] = None, user: Any = AMBIENT) -> List[MemoryEntry]:
        """Search what the agent remembers in a scope, the way the agent does: a
        user's entries and the account's. An entry matches when its name,
        description or content holds any of the query's words (a word also
        finds the longer words it starts: ``refund`` finds ``refunds``), or its
        name or description holds the query; the more words, the better.

        Returns:
            The best matches first (10 unless ``limit`` says otherwise, at most 100), each with its ``content``
            and ``user_id`` (``None`` for the account's entries).

        Usage::

            support = noclick.Agent.from_name("support")
            for entry in support.memory.search("refund policy", user="user_42"):
                print(entry.name, entry.content)
        """
        response = await self._call("GET", "", user, params={"q": query, "limit": limit}) or {}
        return [MemoryEntry._from(row) for row in response.get("data") or []]

    @synced
    async def read(self, name: str, *, user: Any = AMBIENT) -> MemoryEntry:
        """One entry in full; a name with no entry raises ``noclick.NotFound``.

        Returns:
            The entry with its ``content`` and the ``version`` to pass back when you change it.

        Usage::

            support = noclick.Agent.from_name("support")
            refunds = support.memory.read("refunds")
            print(refunds.version, refunds.content)
        """
        return MemoryEntry._from(await self._call("GET", f"/{quote(name, safe='')}", user))

    @synced
    async def save(
        self,
        name: str,
        content: str,
        *,
        description: Optional[str] = None,
        version: Optional[int] = None,
        user: Any = AMBIENT,
    ) -> MemoryEntry:
        """Write an entry, creating it if the name is new. ``description`` is the
        line the agent sees every turn (required for a new entry, kept when you
        leave it out). With ``version``, the save only lands if the entry is
        still at that version, else ``noclick.Conflict``; without it, it replaces
        whatever is there.

        Returns:
            The entry as saved, with its new ``version``.

        Usage:
            Seed what every conversation should know::

                support = noclick.Agent.from_name("support")
                support.memory.save(
                    "refunds", "Refund within 30 days of purchase, to the original card.",
                    description="Our refund rules",
                )

            Correct an entry without losing an edit the agent made meanwhile::

                support = noclick.Agent.from_name("support")
                entry = support.memory.read("refunds")
                try:
                    support.memory.save("refunds", entry.content + "\\nNo refunds on gift cards.", version=entry.version)
                except noclick.Conflict:
                    print("The agent changed it since; read it again.")
        """
        body = compact(content=content, description=description, version=version)
        return MemoryEntry._from(await self._call("PUT", f"/{quote(name, safe='')}", user, json=body))

    @synced
    async def delete(self, name: str, *, version: Optional[int] = None, user: Any = AMBIENT) -> None:
        """Forget an entry. With ``version``, only if it is still at that version
        (else ``noclick.Conflict``). The agent can save the name again later.

        Usage::

            support = noclick.Agent.from_name("support")
            entry = support.memory.read("old-pricing")
            support.memory.delete("old-pricing", version=entry.version)
        """
        await self._call("DELETE", f"/{quote(name, safe='')}", user, params={"version": version})

    @synced
    async def versions(self, name: str, *, user: Any = AMBIENT) -> List[MemoryEntryVersion]:
        """An entry's versions, newest first: the one it holds now, then those kept from earlier saves (its last
        50 in all). A name with no entry raises ``noclick.NotFound``.

        Returns:
            Each version's number, description, who wrote it and when, without its ``content``.

        Usage::

            support = noclick.Agent.from_name("support")
            for v in support.memory.versions("refunds"):
                print(v.version, v.current, v.written_by.type, v.saved_at)
        """
        response = await self._call("GET", f"/{quote(name, safe='')}/versions", user) or {}
        return [MemoryEntryVersion._from(row) for row in response.get("data") or []]

    @synced
    async def get_version(self, name: str, version: int, *, user: Any = AMBIENT) -> MemoryEntryVersion:
        """One version of an entry, with its content; one it no longer keeps raises ``noclick.NotFound``.

        Returns:
            That version in full.

        Usage::

            first = noclick.Agent.from_name("support").memory.get_version("refunds", 1)
            print(first.content)
        """
        return MemoryEntryVersion._from(await self._call("GET", f"/{quote(name, safe='')}/versions/{version}", user))

    @synced
    async def restore(self, name: str, version: int, *, user: Any = AMBIENT) -> MemoryEntry:
        """Put an entry back as it was at ``version``: a new version holding that one's content and description,
        so the one it replaces is kept too.

        Returns:
            The entry as restored, at its new ``version``.

        Usage::

            support = noclick.Agent.from_name("support")
            support.memory.restore("refunds", 1)
        """
        return MemoryEntry._from(await self._call("POST", f"/{quote(name, safe='')}/versions/{version}/restore", user))

    @synced
    async def entries(self, *, user: Any = AMBIENT) -> List[MemoryEntry]:
        """``list``, as ``noclick.Memory`` calls it, so code reads any memory the same way.

        Returns:
            Each entry's name, description and version, by name, without its ``content``.

        Usage::

            for memory in (noclick.Agent.from_name("support").memory, noclick.Memory.from_name("company")):
                print([entry.name for entry in memory.entries()])
        """
        return await self.list.aio(user=user)

    @synced
    async def forget(self, name: str, *, version: Optional[int] = None, user: Any = AMBIENT) -> None:
        """``delete``, as ``noclick.Memory`` calls it, so code changes any memory the same way.

        Usage::

            support = noclick.Agent.from_name("support")
            support.memory.forget("old-pricing")
        """
        await self.delete.aio(name, version=version, user=user)


# --- workspace -----------------------------------------------------------------


@dataclass(frozen=True)
class WorkspaceFile:
    """A file in an agent's workspace for one conversation (``AgentWorkspace``).
    ``url`` downloads it without a key for about an hour."""

    path: str
    size_bytes: int
    modified_at: Any
    url: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "WorkspaceFile":
        return cls(raw["path"], int(raw.get("size_bytes") or 0), parse_time(raw.get("modified_at")), raw.get("url"), raw)


class AgentWorkspace:
    """The files an agent works on: what it writes with its shell or its tools,
    and what you put there for it. An agent has one ``/workspace``, which every
    turn sees whoever it answers, and a clear or a resume leaves as it is; an
    account agent's user has their own. (A ``noclick.Workspace`` is something
    else: a home for channels and their members.)"""

    #: The conversation it was named by, if any: accepted and ignored, since an agent has one workspace.
    conversation: Optional[str]
    _agent: "Agent"
    _user: Any

    @classmethod
    def _of(cls, agent: "Agent", conversation: Optional[str], user: Any) -> "AgentWorkspace":
        workspace = cls.__new__(cls)
        workspace._agent, workspace.conversation, workspace._user = agent, conversation, user
        return workspace

    def __repr__(self) -> str:
        return f"AgentWorkspace(conversation={self.conversation!r})"

    async def _call(self, method: str, suffix: str, **kwargs: Any) -> Any:
        raw = await self._agent._ensure()
        params = {**({"conversation": self.conversation} if self.conversation else {}), **kwargs.pop("params", {})}
        return await self._agent._request(
            method, f"/v1/agents/{raw['id']}/workspace{suffix}", params=params,
            user=self._agent._talk_scope(self._user), **kwargs,
        )

    @synced
    async def files(self) -> List[WorkspaceFile]:
        """Every file in the workspace.

        Returns:
            Each file's ``path`` (relative to ``/workspace``), size, when it last changed and a download ``url``.
            An empty list for a conversation whose agent hasn't written anything.

        Usage::

            support = noclick.Agent.from_name("support")
            for file in support.workspace().files():
                print(file.path, file.size_bytes, file.url)
        """
        response = await self._call("GET", "") or {}
        return [WorkspaceFile._from(row) for row in response.get("data") or []]

    @synced
    async def read(self, path: str) -> bytes:
        """Read one file; a missing file raises ``noclick.NotFound``.

        Returns:
            The file's bytes, exactly as stored; decode text yourself.

        Usage::

            analyst = noclick.Agent.from_name("analyst")
            report = analyst.workspace().read("report.csv")
            print(report.decode()[:200])
        """
        return await self._call("GET", "/files", params={"path": path}, binary=True)

    @synced
    async def write(self, path: str, data: Union[bytes, str]) -> WorkspaceFile:
        """Put a file in the workspace (bytes, or text as UTF-8), replacing one at
        that path, so the agent finds it on its next turn. At most 100 MB. A
        coding harness's sandbox stays up between turns and sees the file once it
        starts again (it stops a few minutes after its last turn), so write there
        before the conversation's first turn or between its sessions.

        Returns:
            The file as stored, with its download ``url``.

        Usage::

            analyst = noclick.Agent.from_name("analyst")
            workspace = analyst.workspace()
            workspace.write("sales.csv", "region,total\\nnorth,1200\\nsouth,950\\n")
            reply = analyst.message("Chart sales.csv by region.", conversation="q3-review")
        """
        content = data.encode() if isinstance(data, str) else bytes(data)
        return WorkspaceFile._from(await self._call("PUT", "/files", params={"path": path}, content=content))

    @synced
    async def delete(self, path: str) -> None:
        """Delete one file from the workspace; a missing file does nothing.

        Usage::

            analyst = noclick.Agent.from_name("analyst")
            analyst.workspace().delete("draft.csv")
        """
        await self._call("DELETE", "/files", params={"path": path})

    @synced
    async def url(self, path: str, *, expires_in_s: Optional[int] = None) -> str:
        """A link that downloads one file without a key, for your user to click.

        Returns:
            The link; it works for ``expires_in_s`` seconds (an hour by default, a day at most).

        Usage::

            analyst = noclick.Agent.from_name("analyst")
            link = analyst.workspace().url("chart.png", expires_in_s=600)
            print(link)
        """
        response = await self._call("GET", "/url", params={"path": path, "expires_in_s": expires_in_s}) or {}
        return response["url"]


# --- sandbox ---------------------------------------------------------------------


@dataclass(frozen=True)
class ConversationSandbox:
    """The machine a conversation's agent works on, as it stands (``AgentSandbox.get``).

    ``place`` is ``sandbox`` (one of the conversation's own), ``machine`` or ``live`` (an app's live container);
    ``status`` is ``running`` or ``stopped``, since ``started_at``. A coding agent's sandbox starts with a turn and
    stops a minute after its last; an ``sdk`` agent's shell lives only during a turn, so it reads ``stopped``. ``cpu``
    and ``memory_mb`` are what it reserved (``None`` while stopped), ``usd_per_hour`` what an hour of it costs,
    ``spent_usd_today`` what its sandbox charged since midnight UTC (``None`` where the conversation has no sandbox of
    its own), and ``workspace`` the folder kept between its runs."""

    agent_id: str
    conversation: str
    harness: str
    place: str
    status: str
    started_at: Any
    cpu: Optional[float]
    memory_mb: Optional[int]
    region: Optional[str]
    usd_per_hour: Optional[float]
    spent_usd_today: Optional[float]
    machine_id: Optional[str]
    project_id: Optional[str]
    workspace: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ConversationSandbox":
        return cls(raw["agent_id"], raw["conversation"], raw["harness"], raw["place"], raw["status"],
                   parse_time(raw.get("started_at")), raw.get("cpu"), raw.get("memory_mb"), raw.get("region"),
                   raw.get("usd_per_hour"), raw.get("spent_usd_today"), raw.get("machine_id"), raw.get("project_id"),
                   raw.get("workspace"), raw)


@dataclass(frozen=True)
class SandboxFilesPage(Page):
    """One page of a sandbox's folder (``AgentSandbox.files_page``): ``data`` holds ``VolumeEntry``s, ``next_cursor``
    is ``None`` on the last page, and ``source`` says where it was read: the running ``sandbox``, or what its
    ``workspace`` kept."""

    source: str = "sandbox"


@dataclass(frozen=True)
class SandboxShell:
    """A shell on a conversation's sandbox (``AgentSandbox.shell``): hand ``url`` and the single-use ``token`` to your
    user's browser, which opens it within two minutes as a take-over's terminal is opened (the websocket's first
    message is ``{"type": "auth", "token": ..., "cols": ..., "rows": ...}``; the TypeScript SDK's
    ``SandboxShell.connect``). It closes as bash exits, after ``idle_limit_s`` with nothing typed, or when the
    websocket closes. A browser that says it renews (``"renew": true`` in its first message) is asked to every 15
    minutes (``{"type": "renew"}``) and answers ``{"type": "renew", "token": ...}`` with a new shell's token, and bash
    goes on."""

    agent_id: str
    conversation: str
    url: str
    token: str = dc_field(repr=False)  # opens the shell: never in a log line
    token_expires_at: Any = None
    idle_limit_s: Optional[int] = None
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "SandboxShell":
        return cls(raw["agent_id"], raw["conversation"], raw["url"], raw["token"],
                   parse_time(raw.get("token_expires_at")), raw.get("idle_limit_s"), raw)


class AgentSandbox:
    """The machine an agent works on (``agent.sandbox()``), one whoever it answers: what it is and costs, its files,
    and your own commands on it, beside the agent's work. While its sandbox runs, its files are read there with
    every secret it holds taken out; while it's stopped, from what its workspace kept. Files and commands need the
    account's secret key with the ``agents:terminal`` scope (they reach what the sandbox holds)."""

    #: The conversation it was named by; none reads it through the agent's session.
    conversation: Optional[str]
    _agent: "Agent"
    _user: Any

    @classmethod
    def _of(cls, agent: "Agent", conversation: Optional[str], user: Any) -> "AgentSandbox":
        sandbox = cls.__new__(cls)
        sandbox._agent, sandbox.conversation, sandbox._user = agent, conversation, user
        return sandbox

    def __repr__(self) -> str:
        return f"AgentSandbox(conversation={self.conversation!r})"

    async def _route(self, suffix: str = "") -> str:
        raw = await self._agent._ensure()
        conversation = self.conversation
        if conversation is None:
            session = await self._agent.session.aio(user=self._user)
            if session is None:
                raise NotFound("It has no session yet, so nothing has run on its sandbox: message it first.")
            conversation = session.conversation
        return f"/v1/agents/{raw['id']}/conversations/{quote(conversation, safe='')}/sandbox{suffix}"

    def _scope(self) -> Any:
        return self._agent._talk_scope(self._user)

    @synced
    async def get(self) -> ConversationSandbox:
        """Where it runs, whether it's running and since when, what it reserved and costs.

        Returns:
            A ``ConversationSandbox``.

        Usage::

            coder = noclick.Agent.from_name("coder")
            machine = coder.sandbox().get()
            print(machine.status, machine.cpu, machine.memory_mb, machine.spent_usd_today)
        """
        return ConversationSandbox._from(await self._agent._request("GET", await self._route(), user=self._scope()))

    @staticmethod
    def _list_params(path: str, recursive: bool) -> Dict[str, Any]:
        return compact(path=path, view="list", recursive="true" if recursive else None)

    @synced
    async def files(self, path: str = "/workspace", *, recursive: bool = False,
                    limit: Optional[int] = None) -> List[VolumeEntry]:
        """What's in the folder at ``path`` (absolute; its workspace by default), a folder before what's in it, or with
        ``recursive=True`` everything below it (git's objects left out unless listed by their path). A path that
        doesn't exist raises ``noclick.NotFound``.

        Returns:
            Every entry (or the first ``limit``), fetched page by page.

        Usage::

            coder = noclick.Agent.from_name("coder")
            for entry in coder.sandbox().files("/workspace/src"):
                print(entry.path, entry.type, entry.size)
        """
        rows = await paginate(self._agent._api, await self._route("/files"),
                              params=self._list_params(path, recursive), user=self._scope(), limit=limit)
        return [VolumeEntry._from(row) for row in rows]

    @synced
    async def files_page(self, path: str = "/workspace", *, recursive: bool = False, cursor: Optional[str] = None,
                         limit: Optional[int] = None) -> SandboxFilesPage:
        """One page of ``files``, and where it was read; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A ``SandboxFilesPage``.

        Usage::

            coder = noclick.Agent.from_name("coder")
            page = coder.sandbox().files_page(limit=100)
            print(page.source, [entry.path for entry in page.data])
        """
        raw = await self._agent._request(
            "GET", await self._route("/files"), user=self._scope(),
            params={**self._list_params(path, recursive), **compact(cursor=cursor, limit=limit)}) or {}
        return SandboxFilesPage([VolumeEntry._from(row) for row in raw.get("data") or []],
                                raw.get("next_cursor") or None, raw.get("source") or "workspace")

    @synced
    async def read(self, path: str) -> bytes:
        """One file's bytes (up to 16 MB), every secret the sandbox holds taken out; a missing file raises
        ``noclick.NotFound``.

        Returns:
            The file's bytes; decode text yourself.

        Usage::

            coder = noclick.Agent.from_name("coder")
            print(coder.sandbox().read("/workspace/README.md").decode())
        """
        return await self._agent._request("GET", await self._route("/files"), params={"path": path}, binary=True,
                                          user=self._scope())

    @synced
    async def exec(self, command: str, *, timeout_s: Optional[int] = None) -> ExecResult:
        """Run a bash command in its running sandbox, in the agent's working directory, beside its work: the agent
        isn't stopped, and the sandbox stays up while the command runs. A stopped conversation raises
        ``noclick.Conflict`` (its next turn starts its sandbox).

        Args:
            command: Run with bash.
            timeout_s: Seconds before it's stopped: 60 by default, at most 90.

        Returns:
            Its ``stdout``, ``stderr`` (the last 64 KiB of each) and ``exit_code``.

        Usage::

            coder = noclick.Agent.from_name("coder")
            print(coder.sandbox().exec("git status --short").stdout)
        """
        return ExecResult._from(await self._agent._request(
            "POST", await self._route("/exec"), json=compact(command=command, timeout_s=timeout_s),
            user=self._scope()))

    @synced
    async def shell(self) -> SandboxShell:
        """Your own shell (``bash -l``) on its running sandbox, in the agent's working directory, beside its work:
        the agent isn't stopped, and the sandbox stays up while you type. A stopped conversation raises
        ``noclick.Conflict`` (its next turn starts its sandbox).

        Returns:
            A ``SandboxShell`` whose ``url`` and single-use ``token`` your user's browser opens within two minutes.

        Usage::

            coder = noclick.Agent.from_name("coder")
            shell = coder.sandbox().shell()
            send_to_browser(shell.url, shell.token)
        """
        return SandboxShell._from(await self._agent._request("POST", await self._route("/shell"), user=self._scope()))


# --- coding agents -------------------------------------------------------------------


@dataclass(frozen=True)
class CodingPause:
    """Why a coding agent isn't doing anything: ``reason`` (``expired``, ``disconnected``, ``spending_paused``,
    ``spend_cap``, ``out_of_funds``, ``budget``, ``failed_start``, ``paused``) and its ``message``."""

    reason: str
    message: str

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "CodingPause":
        return cls(raw["reason"], raw.get("message") or "")


@dataclass(frozen=True)
class CodingCredential:
    """Whose model credential a coding agent thinks with: ``kind`` is ``key``, a person's ``plan``, NoClick's own
    (``noclick``), or ``pending`` until it's connected."""

    kind: str
    connection: Optional[str]
    credential_type: Optional[str]
    connected: Optional[bool]

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "CodingCredential":
        return cls(raw.get("kind") or "pending", raw.get("connection"), raw.get("credential_type"),
                   raw.get("connected"))


@dataclass(frozen=True)
class CodingJob:
    """A coding agent's turn in flight (or a ``lost`` one): ``title`` as whoever handed it over named it, ``text`` the
    start of what it was asked."""

    operation_id: str
    conversation: Optional[str]
    status: str
    step: Optional[str]
    since: Any
    title: Optional[str]
    text: str
    lost: bool
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "CodingJob":
        return cls(raw["operation_id"], raw.get("conversation"), raw["status"], raw.get("step"),
                   parse_time(raw.get("since")), raw.get("title"), raw.get("text") or "", bool(raw.get("lost")), raw)


@dataclass(frozen=True)
class CodingRun:
    """A coding agent's conversation with a place up now; a sandbox's ``cpu`` and ``memory_mb`` are what it
    reserved, an app's live container's ``daemon`` whether its harness runs there now."""

    conversation: Optional[str]
    place: str
    since: Any
    busy: bool
    project_id: Optional[str]
    daemon: Optional[bool]
    cpu: Optional[float]
    memory_mb: Optional[int]

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "CodingRun":
        return cls(raw.get("conversation"), raw["place"], parse_time(raw.get("since")), bool(raw.get("busy")),
                   raw.get("project_id"), raw.get("daemon"), raw.get("cpu"), raw.get("memory_mb"))


@dataclass(frozen=True)
class CodingApp:
    """The app a coding agent codes: ``name`` (what code finds it by), ``title`` (as a person reads it), and
    ``coder`` for the app's own coding agent."""

    project_id: str
    name: Optional[str]
    title: Optional[str]
    coder: bool

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "CodingApp":
        return cls(raw["project_id"], raw.get("name"), raw.get("title"), bool(raw.get("coder")))


@dataclass(frozen=True)
class CodingAgent:
    """One coding agent, as ``Agent.coding()`` reads it: its ``state``, its ``place``, whose model credential it
    thinks with, its current ``job`` and the conversations up now (``runs``)."""

    agent_id: str
    name: str
    user_id: Optional[str]
    app: Optional[CodingApp]
    harness: str
    model: Optional[str]
    credential: CodingCredential
    place: str
    state: str
    paused: Optional[CodingPause]
    pauses: List[CodingPause]
    job: Optional[CodingJob]
    runs: List[CodingRun]
    spent_usd_this_month: float
    model_usage_this_month: "ModelUsage"
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "CodingAgent":
        from .agent import ModelUsage

        return cls(
            raw["agent_id"], raw["name"], raw.get("user_id"), CodingApp._from(raw["app"]) if raw.get("app") else None,
            raw["harness"], raw.get("model"), CodingCredential._from(raw.get("credential") or {}), raw["place"],
            raw["state"], CodingPause._from(raw["paused"]) if raw.get("paused") else None,
            [CodingPause._from(p) for p in raw.get("pauses") or []],
            CodingJob._from(raw["job"]) if raw.get("job") else None, [CodingRun._from(r) for r in raw.get("runs") or []],
            float(raw.get("spent_usd_this_month") or 0), ModelUsage._from(raw.get("model_usage_this_month") or {}), raw,
        )


@dataclass(frozen=True)
class CodingCount:
    """How many coding agents run on one harness and model, in one state and place."""

    harness: str
    model: Optional[str]
    state: str
    place: str
    count: int

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "CodingCount":
        return cls(raw["harness"], raw.get("model"), raw["state"], raw["place"], int(raw.get("count") or 0))


@dataclass(frozen=True)
class CodingAgents:
    """Every coding agent (``Agent.coding()``): ``agents``, then ``counts`` by harness, model, state and place,
    ``by_state``, ``paused_by_reason``, and ``unread``: what couldn't be read (an app's container, the sandbox
    registry), whose runs are unknown, never shown down."""

    agents: List[CodingAgent]
    counts: List[CodingCount]
    by_state: Dict[str, int]
    paused_by_reason: Dict[str, int]
    read_at: Any
    unread: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "CodingAgents":
        return cls([CodingAgent._from(a) for a in raw.get("data") or []],
                   [CodingCount._from(c) for c in raw.get("counts") or []], dict(raw.get("by_state") or {}),
                   dict(raw.get("paused_by_reason") or {}), parse_time(raw.get("read_at")),
                   list(raw.get("unread") or []), raw)


# --- share link ------------------------------------------------------------------


class ShareLink(_Object):
    """An agent's public chat page. Anyone with ``url`` can talk to the agent,
    no sign-in: each visitor in conversations of their own, billed to you. Your
    brand dresses the page. ``created_at`` is when it was first shared."""

    _repr_keys = ("url", "enabled")

    url: str = field("url")
    enabled: bool = field("enabled")
    agent_id: str = field("agent_id")
    created_at: Any = field("created_at", parse_time)
    rotated_at: Any = field("rotated_at", parse_time, doc="When the URL last changed (None if it never has).")

    def _path(self) -> str:
        return f"/v1/agents/{self._known('agent_id')}/share"

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", self._path())

    @synced
    async def disable(self) -> "ShareLink":
        """Turn the page off: visitors see that the agent isn't available.
        ``agent.share()`` turns it back on at the same URL.

        Returns:
            This link, with ``enabled`` false.

        Usage::

            support = noclick.Agent.from_name("support")
            support.share().disable()
        """
        self._raw = await self._request("PATCH", self._path(), json={"enabled": False})
        return self

    @synced
    async def rotate(self) -> "ShareLink":
        """Give the page a new URL; the old one stops at once.

        Returns:
            This link, with its new ``url``.

        Usage::

            support = noclick.Agent.from_name("support")
            link = support.share().rotate()
            print(link.url)
        """
        self._raw = await self._request("POST", f"{self._path()}/rotate")
        return self


# --- live events -------------------------------------------------------------------


@dataclass(frozen=True)
class AgentEvent:
    """One moment of a streamed turn or a watched conversation. ``type`` is ``text``
    (``text`` is the next piece of the reply), ``tool_call`` (``tool``, its wire
    name like ``gmail__send_email_message``, and its ``arguments``; ``held`` when
    policy holds it for a person), ``tool_result`` (``tool``, its ``result``: the
    start of what it returned, up to 500 characters, or its error; and whether it
    ``is_error``), ``file`` (a ``file`` the message carried, ``role`` ``user``, or
    the turn made, ``assistant``), ``reasoning`` (``text`` is one short line of
    what the model is thinking, the title of a section of its reasoning, sent as
    it completes), ``status`` (``compacting`` while a long conversation's older
    history is summarized, then ``compacted``), ``approval`` (its ``"noclick"`` tools held a
    purchase or a deletion for the account's owner: the ``approval``), ``operation``
    (they started a long action: the ``operation``, which comes again with its
    ``progress`` each time the work reports some and once more when it ends) or
    ``done`` (``reply`` is the
    whole ``AgentReply``, as ``message`` returns it). ``agent.watch()`` also yields
    ``message`` (a whole message: its ``role``, ``text``, ``files``, ``via`` or ``trigger`` and, a reply, its
    ``tool_calls`` and ``reasoning``; a ``note``, its ``data``),
    ``status`` (the conversation's new ``status``) and ``turn_end`` once a turn of the conversation ends, however
    it started and whether or not it saved a reply (its ``status``: ``succeeded``, ``failed``, ``canceled`` or
    ``expired``; ``text``, its reply's words, empty when it said nothing). ``operation_id`` names the turn
    an event belongs to (``None`` for a message no turn sent, like a person's
    reply). ``history()`` reads messages in the same shape. The type ``call`` is
    reserved for a phone call's moments. A coding harness's turn (Codex, Claude Code and
    the like) also tells what its commands print as they run, ``output`` (``text``, its
    command's ``call_id``, and ``whole`` when it replaces what came before of that command),
    and each file it changes, ``diff`` (``path``, ``change`` and the ``diff``). Its own steps'
    ``tool_call`` and ``tool_result`` say ``source`` ``harness``, name their ``call_id`` and say
    what kind of step it is (``step_kind``), a ``tool_call`` what it's about (``command``, ``path``
    or ``query``), a command's result its ``exit_code`` and ``duration_ms``: the fields a finished
    turn's ``AgentStep`` keeps. A ``status`` of ``events_dropped`` says ``count`` moments its
    sandbox couldn't send. On a machine, a turn waiting for its harness's image says
    ``downloading`` while it downloads (``text``, like "Downloading OpenCode for this machine:
    450 MB of 1.31 GB", with ``downloaded_bytes`` and ``total_bytes`` in ``raw``), then
    ``downloaded``."""

    type: str
    text: Optional[str] = None
    tool: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None
    result: Any = None
    is_error: bool = False
    reply: Optional["AgentReply"] = None
    #: A ``message``'s sender: ``user``, ``assistant``, ``person`` (someone it was handed off to) or ``note`` (a
    #: line added with ``agent.note``).
    role: Optional[str] = None
    #: A held ``tool_call``: who ``approver`` is and, when the request is addressed to the scope you read as,
    #: the approval's ``request_id`` and its page ``url``.
    held: Optional[Dict[str, Any]] = None
    #: A ``status`` event's: the conversation's new status (``active``, ``awaiting_human`` or ``handed_off``), or a
    #: turn's own (``compacting``, then ``compacted``; on a machine, ``downloading``, then ``downloaded``). A
    #: ``turn_end``'s: how the turn ended (``succeeded``, ``failed``, ``canceled`` or ``expired``).
    status: Optional[str] = None
    operation_id: Optional[str] = None
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)
    #: A ``file`` event's file.
    file: Optional[Attachment] = None
    #: A ``message`` event's files.
    files: List[Attachment] = dc_field(default_factory=list)
    #: A ``message`` event's tool calls (a reply's): each ``{tool, arguments, result, is_error}``, as its turn's
    #: ``tool_call`` and ``tool_result`` events showed it.
    tool_calls: List[Dict[str, Any]] = dc_field(default_factory=list)
    #: An ``approval`` event's: its ``id``, ``summary``, exact ``price`` (a purchase), ``expires_at`` and
    #: ``sent_to``, the apps NoClick sent the account's owner its link on (never the link).
    approval: Optional[Dict[str, Any]] = None
    #: An ``operation`` event's: the long action's ``id`` (an ``Operation``'s), ``kind``, ``status`` and
    #: ``summary`` and, once the work reported some, its ``progress`` (``Operation.progress``, with its last 3
    #: ``lines``).
    operation: Optional[Dict[str, Any]] = None
    #: A ``user`` message's way in, when not the API: ``whatsapp``, ``imessage``, ``call`` or ``email``.
    via: Optional[str] = None
    #: A ``note`` message's data.
    data: Optional[Dict[str, Any]] = None
    #: A ``user`` message no person sent: what started its turn (``Message.trigger``).
    trigger: Optional[Dict[str, Any]] = None
    #: A ``message`` event's reasoning (a reply's): each ``{text, created_at}`` (``Message.reasoning``).
    reasoning: List[Dict[str, Any]] = dc_field(default_factory=list)
    #: A coding harness's step: the ``tool_call``, the ``output`` of its command, its ``tool_result`` and the
    #: ``diff`` of each file it changed share it.
    call_id: Optional[str] = None
    #: ``harness`` for a step a coding harness took itself (its own shell, its edits), not a tool NoClick gave it.
    source: Optional[str] = None
    #: A harness command's ``tool_result``: its exit code (``None`` when it never exited) and how long it ran.
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    #: An ``output`` that replaces what streamed of its command so far, rather than continuing it.
    whole: bool = False
    #: A ``diff``'s file (or the file, a page's URL, a harness step's ``tool_call`` edits or reads), what happened to
    #: it (``add``, ``update`` or ``delete``) and the change: a unified diff, or a new file's whole content.
    path: Optional[str] = None
    change: Optional[str] = None
    diff: Optional[str] = None
    #: A ``status`` ``events_dropped``'s: how many moments its sandbox couldn't send.
    count: Optional[int] = None
    #: A harness step's ``tool_call`` and ``tool_result``: ``command``, ``edit``, ``read``, ``search`` or ``tool``
    #: (``AgentStep.kind``).
    step_kind: Optional[str] = None
    #: A ``request`` event's: what a coding harness asks a person (an approval or a question), as it waits and as it
    #: ends, the shape ``Agent.requests`` lists (answer it with ``Agent.answer``).
    request: Optional[Dict[str, Any]] = None
    #: A harness command's ``tool_call``: the command it runs; a harness search's: what it looks for.
    command: Optional[str] = None
    query: Optional[str] = None
    #: A ``message``'s id in its thread (``Message.id``).
    message_id: Optional[str] = None
    #: Who sent a ``user`` ``message`` (``Message.author``).
    author: Optional[Dict[str, Any]] = None
    #: A ``message`` an agent sent its owner from another of its conversations (``Message.notification``).
    notification: bool = False
    #: A notification's space, when it passes on a space's news (``Message.space``).
    space: Optional[Dict[str, Any]] = None
    #: The coding harness's subagent a ``user`` ``message`` was written for (``Message.subagent``).
    subagent: Optional[Dict[str, str]] = None
    #: The chat a ``message`` of the agent's session came from, where it isn't the session's own (``Message.chat``).
    chat: Optional[str] = None


# --- test runs ---------------------------------------------------------------------


@dataclass(frozen=True)
class Rehearsal:
    """A test run: a real turn of the agent (its model, instructions and tools)
    where a simulated world answers every tool call, so nothing is sent and no
    account is touched. ``tool_calls`` are the calls it made, each with the
    ``tool`` (its tool name, like ``gmail__search_emails``), its ``arguments``
    and the ``result`` the world answered (``None`` if the world couldn't);
    ``transcript`` is the turn step by step: ``role`` ``assistant`` steps (its
    ``text`` between calls, then the reply) and ``tool`` steps. On a coding
    harness, its own shell and file steps are ``tool`` steps with ``source``
    ``harness``: they ran for real, in the run's own sandbox. ``cost_usd`` is
    what the run cost you."""

    reply: str
    tool_calls: List[Dict[str, Any]]
    transcript: List[Dict[str, Any]]
    scenario: Optional[str]
    cost_usd: Optional[float]
    operation_id: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)


def _read_rehearsal(result: Any, op: Operation) -> Rehearsal:
    result = result if isinstance(result, dict) else {}
    return Rehearsal(
        reply=result.get("reply") or "",
        tool_calls=list(result.get("tool_calls") or []),
        transcript=list(result.get("transcript") or []),
        scenario=result.get("scenario"),
        cost_usd=result.get("cost_usd"),
        operation_id=op._known("id"),
        raw=result,
    )


register_result("agent.rehearse", _read_rehearsal)
