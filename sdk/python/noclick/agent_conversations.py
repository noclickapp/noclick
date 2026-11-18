"""An agent's conversations as a chat drives them: one conversation's settings, forks, reverts, resume, context, usage
and commands (``agent.conversation(name)``), and every agent's state for a list of them (``Agent.states()``)."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union
from urllib.parse import quote

from ._object import compact, parse_time
from ._sync import synced
from .operation import Operation

if TYPE_CHECKING:
    from .agent import Agent, Conversation


@dataclass(frozen=True)
class ConversationSettings:
    """What a conversation's next turn runs on: the agent's ``model``, ``effort``, ``speed`` and ``model_connection``
    (an agent is one session, so every conversation runs on them); the ``efforts`` and ``speeds`` its harness takes on
    that model; what can pay for it (``accounts``); its permission mode (``permission_mode``,
    ``effective_permission_mode``: the strictest its harness enforces when it can't enforce the one set,
    ``permission_modes``, ``not_supported``); its ``title``, whether it's ``archived`` and what it was forked from."""

    permission_mode: str
    effective_permission_mode: str
    permission_modes: List[str]
    not_supported: Dict[str, str]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)
    conversation: Optional[str] = None
    title: Optional[str] = None
    archived: bool = False
    harness: Optional[str] = None
    model: Optional[str] = None
    #: How hard its model reasons (``None``: the model's own default, ``default_effort`` when the harness says it).
    effort: Optional[str] = None
    #: The efforts its harness takes on its model, weakest first, in the harness's own words.
    efforts: List[str] = dc_field(default_factory=list)
    default_effort: Optional[str] = None
    speed: str = "standard"
    #: ``["standard", "fast"]`` where its harness has a fast mode on its model; ``[]`` where it has none.
    speeds: List[str] = dc_field(default_factory=list)
    model_connection: Optional[str] = None
    #: What can pay for it: each ``{name, integration, kind (key, plan or noclick), connected, usable, why}``.
    accounts: List[Dict[str, Any]] = dc_field(default_factory=list)
    #: What the conversation sets itself: its ``permission_mode``.
    overridden: List[str] = dc_field(default_factory=list)
    #: ``{conversation, message, through}``: what it was forked from (``through``: its own last copied message).
    forked_from: Optional[Dict[str, Any]] = None

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ConversationSettings":
        return cls(raw.get("permission_mode") or "full-access", raw.get("effective_permission_mode") or "full-access",
                   list(raw.get("permission_modes") or []), dict(raw.get("not_supported") or {}), raw,
                   raw.get("conversation"), raw.get("title"), bool(raw.get("archived")), raw.get("harness"),
                   raw.get("model"), raw.get("effort"), list(raw.get("efforts") or []), raw.get("default_effort"),
                   raw.get("speed") or "standard", list(raw.get("speeds") or []), raw.get("model_connection"),
                   list(raw.get("accounts") or []), list(raw.get("overridden") or []), raw.get("forked_from"))


@dataclass(frozen=True)
class ConversationRevert:
    """A revert: the message it went back to before (its ``text``, to send again), how many turns left the thread,
    what the agent reads (``agent_reads``: ``native`` in its own history, ``context`` carried by its next turn), and the
    files: ``files["restored"]`` are put back before its next turn (in its sandbox, where they are), ``kept`` (with
    ``files=False``), ``not_restored`` (``{path, why}``: an edit too large to have been kept whole) and
    ``commands_not_undone``."""

    conversation: str
    message: str
    text: str
    dropped_turns: int
    files: Dict[str, Any]
    files_applied: Optional[str]
    agent_reads: str
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ConversationRevert":
        return cls(raw.get("conversation") or "", raw.get("message") or "", raw.get("text") or "",
                   int(raw.get("dropped_turns") or 0), dict(raw.get("files") or {}), raw.get("files_applied"),
                   raw.get("agent_reads") or "native", raw)


@dataclass(frozen=True)
class ConversationContext:
    """How full the model's context was at the conversation's last turn: ``used_tokens`` of ``window_tokens``
    (``percent``), as its coding harness reported them (``source`` ``harness``) or as NoClick's runtime sent its last
    call (``noclick``), and where it folds the thread by itself (``auto_compacts_at``, a share of the window). ``None``
    figures before a first turn."""

    model: Optional[str]
    used_tokens: Optional[int]
    window_tokens: Optional[int]
    percent: Optional[float]
    auto_compacts_at: Optional[float]
    source: Optional[str]
    as_of: Any
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ConversationContext":
        return cls(raw.get("model"), raw.get("used_tokens"), raw.get("window_tokens"), raw.get("percent"),
                   raw.get("auto_compacts_at"), raw.get("source"), parse_time(raw.get("as_of")), raw)


@dataclass(frozen=True)
class ToolServer:
    """One MCP server a conversation's coding harness reaches its tools on: ``status`` ``connected``, ``connecting``
    (its handshake hasn't finished) or ``failed`` (``error`` says why), and how many tools it offers the model where
    the harness says (``tool_count``)."""

    name: str
    status: str
    tool_count: Optional[int]
    error: Optional[str]


@dataclass(frozen=True)
class ToolServers:
    """A conversation's tool servers: read live from its running harness (``source`` ``live``), else as its last turn
    found them (``last_turn``), else none yet (``none``). ``reconnect`` is ``{available, scope, why}``: whether one
    server's handshake can be done again in place (``scope`` ``server``), only all of them at once (``all``), or not
    and why not."""

    servers: List[ToolServer]
    source: str
    checked_at: Any
    reconnect: Dict[str, Any]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ToolServers":
        servers = [ToolServer(str(s.get("name") or ""), s.get("status") or "failed", s.get("tool_count"), s.get("error"))
                   for s in raw.get("data") or [] if isinstance(s, dict)]
        reconnect = raw.get("reconnect") if isinstance(raw.get("reconnect"), dict) else {}
        return cls(servers, raw.get("source") or "none", parse_time(raw.get("checked_at")),
                   {"available": reconnect.get("available") is True, "scope": reconnect.get("scope"),
                    "why": reconnect.get("why")}, raw)


@dataclass(frozen=True)
class AgentToolServer:
    """An MCP server an agent has as tools: a step of its automation (``id``, what ``remove_tool_server`` takes),
    reached at its ``url`` over ``transport`` (``http`` or ``sse``), ``signed_in`` where a sign-in to it is set,
    sending the ``headers`` named (their values are never read back)."""

    id: str
    name: str
    url: Optional[str]
    transport: str
    signed_in: bool
    headers: List[str] = dc_field(default_factory=list)
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "AgentToolServer":
        return cls(str(raw.get("id") or ""), str(raw.get("name") or ""), raw.get("url"),
                   raw.get("transport") or "http", raw.get("signed_in") is True,
                   [str(h) for h in raw.get("headers") or []], raw)


@dataclass(frozen=True)
class ConversationUsage:
    """What a conversation cost: ``cost_usd`` (what its turns were charged), its model calls on your own key or plan
    (``model_usage``, ``None`` on NoClick's key), its ``turns``, what pays for its model (``pays_with``: ``noclick``,
    ``key`` or ``plan``) and, on a plan, its limits where its harness reported them (``plan_limits``, each ``{label,
    used_percent, resets_at}``)."""

    cost_usd: float
    model_usage: Optional[Dict[str, Any]]
    turns: int
    pays_with: str
    plan_limits: List[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ConversationUsage":
        return cls(float(raw.get("cost_usd") or 0.0), raw.get("model_usage"), int(raw.get("turns") or 0),
                   raw.get("pays_with") or "noclick", list(raw.get("plan_limits") or []), raw)


@dataclass(frozen=True)
class CommandResult:
    """What a command NoClick has a control for came to: its ``control`` (``model``, ``effort``, ``new``, ``context``,
    ``usage``, ``ask``…) and that control's answer (``result``: the conversation's settings, a new conversation, its
    context or usage, or an operation)."""

    control: str
    command: Dict[str, str]
    result: Dict[str, Any]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "CommandResult":
        return cls(raw.get("control") or "", dict(raw.get("command") or {}), dict(raw.get("result") or {}), raw)


@dataclass(frozen=True)
class AgentStateRow:
    """One agent as a list shows it (``Agent.states()``): its ``state`` (``needs_you``: something waits on a person,
    its harness's request included; ``working``; ``with_you``: a person has one of its conversations; ``waking``: a
    turn of its own is about to start; ``failed``: its last turn failed; ``idle``), the ``conversation`` that's in, the
    tool call it runs ``now`` (``{tool, kind, line, since, running}``), what ``waiting`` counts (``asks``,
    ``held_calls``, ``requests``, ``total``) and when."""

    agent_id: str
    name: str
    harness: str
    state: str
    conversation: Optional[str]
    now: Optional[Dict[str, Any]]
    waiting: Dict[str, int]
    turn_started_at: Any
    last_active_at: Any
    failed: Optional[Dict[str, Any]]
    waking: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "AgentStateRow":
        return cls(raw.get("agent_id") or "", raw.get("name") or "", raw.get("harness") or "", raw.get("state") or "idle",
                   raw.get("conversation"), raw.get("now"), dict(raw.get("waiting") or {}),
                   parse_time(raw.get("turn_started_at")), parse_time(raw.get("last_active_at")), raw.get("failed"),
                   raw.get("waking"), raw)


class AgentConversation:
    """One conversation with an agent, as a chat reads and changes it (``agent.conversation(name)``): its settings, a
    fork, a revert, resuming it as the agent's session, its context and usage, a command. Sends nothing until you call
    one."""

    #: The conversation's key.
    name: str
    _agent: "Agent"
    _user: Any

    @classmethod
    def _of(cls, agent: "Agent", name: str, user: Any) -> "AgentConversation":
        handle = cls.__new__(cls)
        handle._agent, handle.name, handle._user = agent, name, user
        return handle

    def __repr__(self) -> str:
        return f"AgentConversation(name={self.name!r})"

    async def _call(self, method: str, suffix: str = "", **kwargs: Any) -> Dict[str, Any]:
        raw = await self._agent._ensure()
        path = f"/v1/agents/{raw['id']}/conversations/{quote(self.name, safe='')}{suffix}"
        return await self._agent._request(method, path, user=self._agent._talk_scope(self._user), **kwargs) or {}

    @synced
    async def settings(self) -> ConversationSettings:
        """What its next turn runs on, and what its harness and accounts offer.

        Returns:
            A ``ConversationSettings``.

        Usage::

            chat = noclick.Agent.from_name("coder").conversation("main")
            settings = chat.settings()
            print(settings.model, settings.effort, settings.efforts)
        """
        return ConversationSettings._from(await self._call("GET", "/settings"))

    @synced
    async def update(self, **changes: Any) -> ConversationSettings:
        """Change it from its next message: ``permission_mode``, ``title`` (a rename) and ``archived``. ``model``,
        ``effort``, ``speed`` and ``model_connection`` change the agent itself, for every conversation, as
        ``Agent.update`` does (``None`` clears ``effort``, ``speed`` or ``model_connection``). Its harness stays the
        agent's.

        Returns:
            Its ``ConversationSettings`` after the change.

        Usage::

            chat = noclick.Agent.from_name("coder").conversation("main")
            chat.update(model="opus", effort="high")   # the agent's, for everyone
            chat.update(permission_mode="approval-required", title="Retries")
        """
        known = ("model", "effort", "speed", "model_connection", "permission_mode", "title", "archived")
        unknown = sorted(set(changes) - set(known))
        if unknown:
            raise TypeError(f"update() takes {', '.join(known)}, not {', '.join(unknown)}")
        return ConversationSettings._from(await self._call("PATCH", json=dict(changes)))

    @synced
    async def fork(self, *, message: Optional[str] = None, title: Optional[str] = None) -> "Conversation":
        """Copy it into a new conversation, up to and with a message's turn (a ``Message.id``; the whole thread when
        omitted), with the same permission mode. Its agent reads the copy in its own history (``agent_reads``
        ``native``), or, where it can't, as context its first turn carries.

        Returns:
            The new ``Conversation``, with ``forked_from``.

        Usage::

            coder = noclick.Agent.from_name("coder")
            last = coder.history("main")[-1]
            fork = coder.conversation("main").fork(message=last.id)
            coder.message("Try the other approach", conversation=fork.conversation)
        """
        from .agent import Conversation

        return Conversation._from(await self._call("POST", "/fork", json=compact(message=message, title=title)))

    @synced
    async def resume(self) -> "Conversation":
        """Make it the agent's session again, like ``claude --resume``: everyone talking to the agent shares it from
        now on, and a message without a ``conversation`` goes to it. The agent's files stay as they are. Raises
        ``noclick.Conflict`` while the agent is working on a turn, and ``noclick.NotFound`` for a conversation the
        agent never had.

        Returns:
            Its ``Conversation``, ``active``.

        Usage::

            coder = noclick.Agent.from_name("coder")
            earlier = [c for c in coder.conversations(limit=20) if not c.active][0]
            coder.conversation(earlier.conversation).resume()
        """
        from .agent import Conversation

        return Conversation._from(await self._call("POST", "/resume"))

    @synced
    async def revert(self, message: str, *, files: bool = False) -> ConversationRevert:
        """Go back to before a message you sent (a ``Message.id``): it and everything after it leave the thread and
        what the agent reads; ``files=True`` also puts the files its edits since changed back as they were, before its
        next turn. Raises ``noclick.Conflict`` while a turn runs or the agent waits on an answer there.

        Returns:
            A ``ConversationRevert``, whose ``text`` is the message's.

        Usage::

            coder = noclick.Agent.from_name("coder")
            mine = [m for m in coder.history("main") if m.role == "user"][-1]
            undone = coder.conversation("main").revert(mine.id, files=True)
            print(undone.files["restored"])
        """
        return ConversationRevert._from(await self._call("POST", "/revert", json={"message": message, "files": files}))

    @synced
    async def context(self) -> ConversationContext:
        """How full the model's context was at its last turn, against its window (a chat's ``/context``).

        Returns:
            A ``ConversationContext``.

        Usage::

            used = noclick.Agent.from_name("coder").conversation("main").context()
            print(f"{used.percent}% of {used.window_tokens}")
        """
        return ConversationContext._from(await self._call("GET", "/context"))

    @synced
    async def usage(self) -> ConversationUsage:
        """What it cost and what pays for its model (a chat's ``/usage``).

        Returns:
            A ``ConversationUsage``.

        Usage::

            spent = noclick.Agent.from_name("coder").conversation("main").usage()
            print(spent.cost_usd, spent.pays_with)
        """
        return ConversationUsage._from(await self._call("GET", "/usage"))

    @synced
    async def tool_servers(self) -> ToolServers:
        """The MCP servers its coding harness reaches its tools on: connected, connecting or failed, with their tools.

        Returns:
            A ``ToolServers``.

        Usage::

            for server in noclick.Agent.from_name("coder").conversation("main").tool_servers().servers:
                print(server.name, server.status, server.error)
        """
        return ToolServers._from(await self._call("GET", "/tool_servers"))

    @synced
    async def reconnect_tool_server(self, name: str) -> ToolServers:
        """Do one tool server's handshake again, where its harness can (``tool_servers().reconnect``): Claude Code and
        OpenCode reconnect that server, Codex reloads all of them. Hermes Agent and OpenClaw connect theirs at every
        turn, so this raises ``noclick.Conflict`` saying the next message reconnects them.

        Returns:
            A ``ToolServers``, as it stands after the reconnect started.

        Usage::

            noclick.Agent.from_name("coder").conversation("main").reconnect_tool_server("linear")
        """
        return ToolServers._from(await self._call("POST", f"/tool_servers/{quote(name, safe='')}/reconnect"))

    @synced
    async def message_subagent(self, call_id: str, text: str) -> Operation:
        """Tell one of its coding harness's own subagents something while it works: the ``Task`` (Claude Code) or
        ``task`` (OpenCode) call ``call_id`` in the conversation's running turn, as its events name it. No harness
        takes a message into its subagent, so it joins the main session's turn, which reads whom it's for and passes
        it on; the thread keeps it as yours, its ``subagent`` naming the call. Raises ``noclick.Conflict`` once that
        turn or the subagent has ended. A NoClick agent it started takes messages itself (``Agent.send``).

        Returns:
            Its ``agent.ask`` ``Operation``, answered with the reply of the turn it joined.

        Usage::

            chat = noclick.Agent.from_name("coder").conversation("main")
            chat.message_subagent("toolu_01", "Also check the admin routes.").wait()
        """
        scope = self._agent._talk_scope(self._user)
        response = await self._call("POST", f"/subagents/{quote(call_id, safe='')}/messages", json={"text": text})
        return Operation._from_payload(response, client=self._agent._client, user=scope, kind="agent.ask")

    @synced
    async def run_command(self, name: str, arguments: str = "", *,
                          delivery: Optional[str] = None) -> Union[CommandResult, Operation]:
        """Run a command typed in a chat. One NoClick has a control for (``/model opus``, ``/effort high``, ``/fast``,
        ``/new``, ``/context``, ``/usage``, ``/btw <question>``) comes back as that control's ``CommandResult``; any
        other runs as the harness's own command, its turn's ``Operation``.

        Returns:
            A ``CommandResult``, or the command's ``Operation``.

        Usage::

            chat = noclick.Agent.from_name("coder").conversation("main")
            chat.run_command("effort", "high")
            chat.run_command("compact").wait()
        """
        raw = await self._agent._ensure()
        scope = self._agent._talk_scope(self._user)
        response = await self._agent._request(
            "POST", f"/v1/agents/{raw['id']}/messages", user=scope,
            json=compact(command={"name": name, "arguments": arguments}, conversation=self.name, delivery=delivery),
        ) or {}
        if response.get("object") == "command_result":
            return CommandResult._from(response)
        return Operation._from_payload(response, client=self._agent._client, user=scope, kind="agent.message")
