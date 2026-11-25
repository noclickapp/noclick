"""Agents: hosted agents you message by name."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import quote

from ._attachment import Attachment, attachment_ids, upload
from ._client import Client, path_segment, resolve_client
from ._designed import designed, designed_params
from ._object import (
    UNSET, Page, _Object, check_unchanged, compact, csv, field, iso_time, list_all, list_page, paginate,
    parse_time, read_scope, ref_id,
)
from ._sync import synced
from .trash import TrashItem, trashed
from ._scope import AMBIENT, resolve_scope
from .agent_conversations import AgentConversation, AgentStateRow, AgentToolServer, ConversationSettings
from .agent_extras import AgentEvent, AgentMemory, AgentSandbox, AgentWorkspace, CodingAgents, ShareLink
from .approval import settings_wire
from .connection import model_connection_ref, tool_refs
from .cron import Cron
from .coordination import WAKEUP_STATUSES, Job, Wakeup, check_note, job_kinds, updates_wire, wake_condition
from .exceptions import Conflict, NotFound
from .operation import Operation, register_result
from .sandbox import network_wire
from .secret import secret_ids, secret_refs
from .terminal import Terminal
from .trigger import DEFINED_KINDS, AgentTrigger, named_by, spec_key, trigger_wire
from .volume import volume_ids, volume_refs
from .memory import memory_links, memory_refs
from .skill import skill_links, skill_refs

if TYPE_CHECKING:
    from .inbox import Inbox


@dataclass(frozen=True)
class ModelUsage:
    """What an agent's model calls on your own key or plan (its ``model_connection``) used:
    tokens in (``cached_tokens`` of them read from the provider's cache), tokens out, and what
    they come to in US dollars at the provider's list price. NoClick doesn't bill these calls (the
    key or plan pays); this is how you see them. A coding harness on a plan counts what it reports,
    priced as if it ran on a key."""

    input_tokens: int
    output_tokens: int
    cached_tokens: int
    usd: float
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> Optional["ModelUsage"]:
        if not isinstance(raw, dict):
            return None
        return cls(int(raw.get("input_tokens") or 0), int(raw.get("output_tokens") or 0),
                   int(raw.get("cached_tokens") or 0), float(raw.get("usd") or 0), raw)


@dataclass(frozen=True)
class AgentStepDiff:
    """One file a step changed: a unified diff, or a new file's whole content (``change`` ``add``), at most 16,384
    characters."""

    path: str
    change: Optional[str]
    diff: str


_STEP_KINDS = ("command", "edit", "read", "search", "tool")


@dataclass(frozen=True)
class StepLabel:
    """What a coding harness's step did, in words, in its tense: running as it runs (``Reading attachments.py``),
    done once it ended (``Read attachments.py lines 55-110``). ``text`` is the whole line; ``verb``, ``object`` and
    ``detail`` its parts."""

    text: str
    verb: Optional[str] = None
    object: Optional[str] = None
    detail: Optional[str] = None

    @classmethod
    def _from(cls, raw: Any) -> Optional["StepLabel"]:
        if not isinstance(raw, dict) or not raw.get("text"):
            return None
        return cls(str(raw["text"]), raw.get("verb"), raw.get("object"), raw.get("detail"))


@dataclass(frozen=True)
class StepTests:
    """A test run's counts, read from what it printed (pytest, vitest, jest, node's runner, cargo): as it streams
    (``done`` False; ``total`` once it's known) and at its end, and in words (``label``: ``161 passed``, ``2 of 43
    failed``, ``64 of 161``)."""

    passed: int
    failed: int
    skipped: int
    total: Optional[int]
    done: bool
    label: str

    @classmethod
    def _from(cls, raw: Any) -> Optional["StepTests"]:
        if not isinstance(raw, dict):
            return None
        return cls(int(raw.get("passed") or 0), int(raw.get("failed") or 0), int(raw.get("skipped") or 0),
                   raw.get("total"), raw.get("done") is True, str(raw.get("label") or ""))


@dataclass(frozen=True)
class StepProgress:
    """How far a step is, where it reported a count (a test run whose total is known, ``[64/161]``): ``done`` of
    ``total``. A step that names no total has none."""

    done: int
    total: int

    @classmethod
    def _from(cls, raw: Any) -> Optional["StepProgress"]:
        if not isinstance(raw, dict) or not raw.get("total"):
            return None
        return cls(int(raw.get("done") or 0), int(raw["total"]))


@dataclass(frozen=True)
class DiffStat:
    """The lines an edit's diffs added and removed."""

    added: int
    removed: int

    @classmethod
    def _from(cls, raw: Any) -> Optional["DiffStat"]:
        return cls(int(raw.get("added") or 0), int(raw.get("removed") or 0)) if isinstance(raw, dict) else None


@dataclass(frozen=True)
class StepGroup:
    """Reads, searches and listings a coding harness made in a row, folded into one line as Claude Code folds them
    (never a failed step): ``label`` (``Read 6 files, searched for 3 patterns``; ``Reading …`` while one runs), the
    ``counts`` (``read``: files, ``search``, ``list``), its steps (``step_ids``) and ``parent``, the subagent call
    whose steps they are. A group no longer standing (a step left it) has no ``step_ids``."""

    id: str
    label: Optional[str]
    counts: Dict[str, int]
    step_ids: List[str]
    running: bool
    parent: Optional[str] = None

    @classmethod
    def _from(cls, raw: Any) -> Optional["StepGroup"]:
        if not isinstance(raw, dict) or not raw.get("id"):
            return None
        return cls(str(raw["id"]), raw.get("label"), dict(raw.get("counts") or {}),
                   [str(i) for i in raw.get("step_ids") or []], raw.get("running") is True, raw.get("parent"))


def _groups(raw: Any) -> List[StepGroup]:
    return [g for g in (StepGroup._from(r) for r in raw or []) if g is not None]


@dataclass(frozen=True)
class ChangedFile:
    """A file a turn changed: the lines its edits added and removed, and ``how`` where not by an edit tool
    (``sed``, ``script``, ``a command``): such a change carries no counts."""

    path: str
    added: int
    removed: int
    how: List[str]


@dataclass(frozen=True)
class TurnChanges:
    """The files a turn changed: ``label`` (``Changed 5 files``), each file, the lines added and removed, and how
    many were changed only by a script or a command (``by_script``)."""

    label: str
    files: List[ChangedFile]
    added: int
    removed: int
    by_script: int


@dataclass(frozen=True)
class TurnSummary:
    """What a coding harness's turn did: ``label`` (``Read 9 files, searched 7 times``), its steps' ``counts`` by
    category (read, search, list, edit, test, install, run, tool), how many ``failed``, what it ``changed`` and its
    last test run's counts (``tests``)."""

    label: Optional[str]
    counts: Dict[str, int]
    failed: int
    changed: Optional[TurnChanges]
    tests: Optional[StepTests]

    @classmethod
    def _from(cls, raw: Any) -> Optional["TurnSummary"]:
        if not isinstance(raw, dict):
            return None
        changed = raw.get("changed") if isinstance(raw.get("changed"), dict) else None
        return cls(raw.get("label"), dict(raw.get("counts") or {}), int(raw.get("failed") or 0),
                   TurnChanges(str(changed.get("label") or ""), [
                       ChangedFile(str(f.get("path") or ""), int(f.get("added") or 0), int(f.get("removed") or 0),
                                   [str(h) for h in f.get("how") or []])
                       for f in changed.get("files") or [] if isinstance(f, dict)],
                       int(changed.get("added") or 0), int(changed.get("removed") or 0),
                       int(changed.get("by_script") or 0)) if changed else None,
                   StepTests._from(raw.get("tests")))


@dataclass(frozen=True)
class AgentStep:
    """One step of a turn as its reply keeps it (``Message.steps``, ``AgentReply.steps``). ``kind`` is a coding
    harness's shell ``command``, file ``edit``, ``read`` or ``search``, or any other ``tool`` (NoClick's own among
    them). A coding harness's own step (``source`` ``harness``) has the fields its live events showed as it ran, under
    its ``call_id``: its ``tool_call`` (``kind``, ``tool``, ``arguments``, ``command``, ``path``, ``query``), its
    command's ``output`` (the last 4,096 characters; what came before reads ``[… N characters not shown …]``), its
    ``tool_result`` (``exit_code``, ``duration_ms``, ``is_error``, ``result``) and each ``diff`` (``diffs``). A turn keeps
    at most 200 such steps and 256,000 characters of their output and diffs, the newest steps' first. NoClick's own tool
    calls are ``kind`` ``tool``, with no ``call_id``.

    What a harness's step did, in words, judged once by NoClick as it ran: its ``category`` (``read``, ``search``,
    ``list``, ``edit``, ``test``, ``install``, ``run`` or ``tool``), its ``label`` (``StepLabel``) and where that came
    from (``label_source``: the harness's own ``description``, Codex's ``actions``, or ``derived`` from the command),
    the command as shown (``display_command``: no ``cd`` into where it runs, heredocs shortened), a read's ``lines``
    (``{from, to}``), the files a read or an edit named (``paths``), how many lines it printed (``output_lines``), a test run's ``tests``, a count it reported
    (``progress``), an edit's ``diff_stat``, whether it ``failed`` (a search that found nothing didn't) and the
    ``group`` it folds into (``StepGroup.id``)."""

    kind: str
    tool: str
    call_id: Optional[str]
    source: Optional[str]
    arguments: Dict[str, Any]
    command: Optional[str]
    path: Optional[str]
    query: Optional[str]
    output: Optional[str]
    exit_code: Optional[int]
    duration_ms: Optional[int]
    is_error: bool
    result: Any
    diffs: List[AgentStepDiff]
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)
    category: Optional[str] = None
    label: Optional[StepLabel] = None
    label_source: Optional[str] = None
    display_command: Optional[str] = None
    lines: Optional[Dict[str, Any]] = None
    output_lines: Optional[int] = None
    tests: Optional[StepTests] = None
    progress: Optional[StepProgress] = None
    diff_stat: Optional[DiffStat] = None
    failed: Optional[bool] = None
    group: Optional[str] = None
    #: The files a read or an edit named, as it named them.
    paths: List[str] = dc_field(default_factory=list)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "AgentStep":
        diffs = [AgentStepDiff(d.get("path") or "", d.get("kind"), d.get("diff") or "")
                 for d in raw.get("diffs") or [] if isinstance(d, dict)]
        return cls(raw.get("kind") if raw.get("kind") in _STEP_KINDS else "tool", raw.get("tool") or "", raw.get("id"),
                   raw.get("source"), dict(raw.get("arguments") or {}), raw.get("command"), raw.get("path"),
                   raw.get("query"), raw.get("output"), raw.get("exit_code"), raw.get("duration_ms"),
                   raw.get("is_error") is True, raw.get("result"), diffs, parse_time(raw.get("created_at")), raw,
                   raw.get("category"), StepLabel._from(raw.get("label")), raw.get("label_source"),
                   raw.get("display_command"), raw.get("lines") if isinstance(raw.get("lines"), dict) else None,
                   raw.get("output_lines"), StepTests._from(raw.get("tests")), StepProgress._from(raw.get("progress")),
                   DiffStat._from(raw.get("diff_stat")),
                   raw.get("failed") if isinstance(raw.get("failed"), bool) else None, raw.get("group"),
                   [str(p) for p in raw.get("paths") or []])


def _steps(tool_calls: List[Dict[str, Any]]) -> List[AgentStep]:
    return [AgentStep._from(call) for call in tool_calls if isinstance(call, dict)]


@dataclass(frozen=True)
class AgentReply:
    """The agent's answer to one message."""

    text: str
    conversation: Optional[str]
    #: The turn's tool calls, each ``{tool, arguments, result, is_error, created_at}`` as ``history()`` shows a
    #: reply's (a failed call's ``result`` is its error); a coding harness's own steps add ``source: "harness"`` and
    #: the rest of an ``AgentStep`` (its ``id``, ``kind``, ``command``, ``path``, ``output``, ``exit_code``,
    #: ``duration_ms``, ``diffs``), in the order they happened.
    tool_calls: List[Dict[str, Any]]
    operation_id: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)
    #: The turn's model calls on your own key or plan (``None`` on NoClick's key, whose cost is its ``cost_usd``).
    model_usage: Optional[ModelUsage] = None
    #: The limit that ended the turn before it finished (``"steps"``, ``"spend"`` or ``"time"``: its
    #: ``turn_limits``), its text then saying where the work stands; ``None`` when the agent answered.
    ended_by: Optional[str] = None
    #: What a coding harness's turn did (``None`` for a turn with no harness steps).
    summary: Optional[TurnSummary] = None
    #: Its harness steps' folds, in order.
    groups: List[StepGroup] = dc_field(default_factory=list)

    @property
    def steps(self) -> List[AgentStep]:
        """``tool_calls`` as ``AgentStep``s."""
        return _steps(self.tool_calls)

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True)
class Conversation:
    """One thread with an agent; pass ``conversation`` back to continue it or to ``history()``."""

    conversation: str
    user_id: Optional[str]
    title: Optional[str]
    preview: Optional[str]
    turns: Optional[int]
    cost_usd: Optional[float]
    last_activity: Any
    raw: Dict[str, Any] = dc_field(repr=False)
    #: ``active``; ``awaiting_human`` while a turn waits on a person (an ``ask``, a held call, a sign-in);
    #: ``handed_off`` while a person has it.
    status: Optional[str] = None
    #: Who a ``handed_off`` conversation is with: the person's email or phone.
    handed_off_to: Optional[str] = None
    #: Its model calls on your own key or plan, all turns together (``None`` on NoClick's key).
    model_usage: Optional[ModelUsage] = None
    #: Its newest message: ``{role, text, created_at}`` (``None`` before any).
    last_message: Optional[Dict[str, Any]] = None
    #: Who is in it: each ``{type, id, name}``, the thread's own person first, then whoever else wrote in it.
    people: List[Dict[str, Any]] = dc_field(default_factory=list)
    archived: bool = False
    #: ``{conversation, message, through}``: the conversation it was forked from.
    forked_from: Optional[Dict[str, Any]] = None
    #: A fork's: ``native`` when the agent reads the copy in its own history, ``context`` when carried as context.
    agent_reads: Optional[str] = None
    #: Whether it's the agent's session now, the one conversation everyone talking to it shares; the others can be
    #: resumed.
    active: bool = False

    @classmethod
    def _from(cls, raw: Dict[str, Any], _scope: Any = None) -> "Conversation":
        return cls(
            raw.get("conversation"), raw.get("user_id"), raw.get("title"), raw.get("preview"),
            raw.get("turns"), raw.get("cost_usd"), parse_time(raw.get("last_activity")), raw,
            raw.get("status"), raw.get("handed_off_to"), ModelUsage._from(raw.get("model_usage")),
            raw.get("last_message"), list(raw.get("people") or []), bool(raw.get("archived")),
            raw.get("forked_from"), raw.get("agent_reads"), bool(raw.get("active")),
        )


@dataclass(frozen=True)
class AgentGrant:
    """A connection the agent's user gave it at run time (it asked with its
    ``request_connection`` tool, within ``can_request``). ``status`` is
    ``requested`` until the user connects, then ``active``; ``operations`` None
    means every operation."""

    id: str
    connection: str
    integration: str
    operations: Optional[List[str]]
    status: str
    reason: Optional[str]
    conversation: Optional[str]
    created_at: Any
    granted_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "AgentGrant":
        return cls(raw["id"], raw["connection"], raw["integration"], raw.get("operations"), raw["status"],
                   raw.get("reason"), raw.get("conversation"), parse_time(raw.get("created_at")),
                   parse_time(raw.get("granted_at")), raw)


@dataclass(frozen=True)
class AgentToolAction:
    """One action of an app in ``agent.tool_access()``: its rule ``key``, what its rules say of it
    (``verdict``: ``allow``, ``ask`` or ``off``) and how often it ran. ``group`` is its integration's own
    grouping of it (``Message``, ``Invoices``); ``kind`` what it does, from its name (``read``, ``send``,
    ``change``, ``delete`` or ``money``: a hint, never a rule); ``can_ask`` False where ``ask`` can't hold it
    (reading never waits for a person)."""

    key: str
    action: str
    title: str
    group: Optional[str]
    kind: str
    verdict: str
    can_ask: bool
    calls: int

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "AgentToolAction":
        return cls(raw["key"], raw["action"], raw["title"], raw.get("group"), raw["kind"], raw["verdict"],
                   raw.get("can_ask") is not False, int(raw.get("calls") or 0))


@dataclass(frozen=True)
class AgentToolApp:
    """One app in ``agent.tool_access()``: a connection of its scope, an integration its rules name, NoClick or
    the web (``kind``). ``key`` is its rule key (None for the web, whose actions ``search`` and ``fetch`` are keys of
    their own); ``account`` the account it's connected as (else its name); ``on`` whether anything of it may run."""

    key: Optional[str]
    app: str
    kind: str
    integration: Optional[str]
    credential_type: Optional[str]
    label: str
    account: Optional[str]
    status: Optional[str]
    on: bool
    calls: int
    actions: List[AgentToolAction]

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "AgentToolApp":
        return cls(raw.get("key"), raw["app"], raw["kind"], raw.get("integration"), raw.get("credential_type"),
                   raw["label"], raw.get("account"), raw.get("status"), bool(raw.get("on")), int(raw.get("calls") or 0),
                   [AgentToolAction._from(a) for a in raw.get("actions") or []])


@dataclass(frozen=True)
class AgentToolAccess:
    """What an agent may do with each app it reaches (``agent.tool_access()``). ``mode`` is ``restricted`` when
    it's kept to the apps its rules turn on, else ``everything``; ``listed`` when its ``tools`` are a list rather
    than everything, whose ``rules`` are what that list amounts to; ``since`` when the ``calls`` counted start."""

    mode: str
    listed: bool
    rules: Dict[str, str]
    since: Any
    apps: List[AgentToolApp]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "AgentToolAccess":
        return cls(raw.get("mode") or "everything", bool(raw.get("listed")), dict(raw.get("rules") or {}),
                   parse_time(raw.get("since")), [AgentToolApp._from(a) for a in raw.get("apps") or []], raw)


@dataclass(frozen=True)
class HarnessModel:
    """A model a harness offers, by the ``id`` its ``model=`` takes. One model reached
    several ways is a row per way, each with its ``route`` (``maker``, ``openrouter``,
    ``opencode`` or ``opencode-go``) and the same ``canonical``, the model as its maker
    names it (``anthropic/claude-sonnet-5-5``); a model reached one way is its own
    ``canonical``."""

    id: str
    label: Optional[str]
    canonical: str = ""
    route: str = "maker"
    #: What it costs on NoClick's own key: ``output_usd_per_million`` (``None`` for a router priced as the model it
    #: picks for each call) and ``needs_funds_usd``, the funds your account must have added (not its plan's included
    #: usage) to put an agent on it there: set for a model over $2 a million output tokens, else ``None``. ``None``
    #: where the key doesn't run it on this harness, or its price can't be read now.
    noclick_key: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class HarnessInfo:
    """What can run an agent: one of ``Agent.harnesses()``. ``sdk`` is NoClick's own
    agent loop; the others are coding agents that run in a sandbox of their own, with
    a shell and files, and think with the key or plan of a ``model_connection``.
    ``models()`` searches the models it offers."""

    #: What ``harness=`` takes: ``sdk``, ``claude_code``, ``codex``, ``opencode``, ``hermes`` or ``openclaw``.
    name: str
    label: Optional[str]
    #: The version NoClick runs (``None`` for ``sdk``).
    version: Optional[str]
    #: The ``model`` an agent on it gets when you give none.
    default_model: str
    #: Whether ``model=`` also takes models ``models()`` doesn't offer.
    custom_models: bool
    #: ``"required"`` for every CLI harness, ``"optional"`` for ``sdk``.
    model_connection: str
    #: The model providers (``kind="model"`` integrations) whose connection it can think with.
    integrations: List[str]
    #: ``"tokens"`` when the reply streams as it's written, ``"final"`` when it arrives whole.
    streaming: str
    #: ``"built_in"`` when it has its own shell and file tools, ``"code_capability"`` when its shell is the ``code`` tool.
    shell: str
    #: What to know before choosing it (a model that needs a particular key, say).
    notes: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)
    _client: Optional[Client] = dc_field(default=None, repr=False, compare=False)
    #: The reasoning efforts it takes on its default model, weakest first (``[]``: none).
    efforts: List[str] = dc_field(default_factory=list)
    #: The effort it runs at when none is set (``None``: the model's own).
    default_effort: Optional[str] = None
    #: ``["standard", "fast"]`` where it has a fast mode on its default model, else ``[]``.
    speeds: List[str] = dc_field(default_factory=list)
    #: Whether a coding agent on it may run on NoClick's own key (``model_connection="noclick"``, at the model's
    #: cost): ``{runs, models}`` (models to suggest there), or ``{runs: False, why}``.
    noclick_key: Dict[str, Any] = dc_field(default_factory=dict)
    #: The permission modes it enforces (``[]``: none, as on ``sdk``), and why it runs the others as another.
    permission_modes: List[str] = dc_field(default_factory=list)
    not_supported: Dict[str, str] = dc_field(default_factory=dict)

    @classmethod
    def _from(cls, raw: Dict[str, Any], client: Optional[Client]) -> "HarnessInfo":
        return cls(
            raw["name"], raw.get("label"), raw.get("version"), raw["default_model"], bool(raw["custom_models"]),
            raw["model_connection"], list(raw["integrations"]), raw["streaming"], raw["shell"],
            list(raw.get("notes") or []), raw, client, list(raw.get("efforts") or []), raw.get("default_effort"),
            list(raw.get("speeds") or []), dict(raw.get("noclick_key") or {}),
            list(raw.get("permission_modes") or []), dict(raw.get("not_supported") or {}),
        )

    @synced
    async def models(self, search: Optional[str] = None, *, limit: int = 50) -> List[HarnessModel]:
        """The models it offers, its default first: the first ``limit`` (at most 200), or
        those whose id or label contains ``search`` (ignoring case). A search after a
        few quiet minutes reads the providers' lists afresh, so it can take seconds.

        Returns:
            Each model's ``id`` (what ``model=`` takes) and ``label``. A harness whose
            ``custom_models`` is True also runs ids it doesn't list.

        Usage:
            Find a Claude model for an agent on OpenCode::

                [opencode] = [h for h in noclick.Agent.harnesses() if h.name == "opencode"]
                for model in opencode.models(search="claude", limit=10):
                    print(model.id, model.label)

            Check that a model is one Claude Code offers before creating the agent::

                [claude_code] = [h for h in noclick.Agent.harnesses() if h.name == "claude_code"]
                offered = [m.id for m in claude_code.models(search="opus")]
                print("opus" in offered)
        """
        page = await resolve_client(self._client).request(
            "GET", f"/v1/harnesses/{path_segment(self.name)}/models", params={"q": search, "limit": limit}, user=None,
        )
        return [HarnessModel(m["id"], m.get("label"), m.get("canonical") or m["id"], m.get("route") or "maker",
                             m.get("noclick_key")) for m in page["data"]]


def _author(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict) or value.get("type") not in ("account", "user", "agent", "app"):
        return None
    return {"type": value["type"], "id": value.get("id"), "name": value.get("name")}


def _channel(value: Any) -> Optional[Dict[str, Any]]:
    return value if isinstance(value, dict) and isinstance(value.get("posts"), list) else None


@dataclass(frozen=True)
class HistoryPage(Page):
    """A page of ``history``, with the agent's ``session``: the one conversation everyone talking to it shares now
    (a read of a conversation nobody wrote in yet names the one it makes)."""

    session: Optional[str] = None


@dataclass(frozen=True)
class ActivityChat:
    """The chat an activity item happened in, and who it's with: ``key`` the conversation, ``kind`` ``direct``,
    ``group`` or ``self`` (the owner's own chat), ``number`` E.164, ``avatar`` its picture where one was kept,
    ``node_type`` the trigger's node, which names the app the chat is on."""

    key: str
    name: Optional[str]
    kind: Optional[str]
    number: Optional[str]
    avatar: Optional[str]
    node_type: Optional[str]


@dataclass(frozen=True)
class ActivityMessage:
    """A message that came in, as its trigger's node reads it. ``media`` is ``{kind, url, duration, transcript}`` (a
    voice note, an image, a file), the transcript once the turn read it."""

    sender_name: Optional[str]
    sender_id: Optional[str]
    sender_number: Optional[str]
    sender_avatar: Optional[str]
    text: str
    media: Optional[Dict[str, Any]]
    quoted_text: Optional[str]
    at: Any
    message_id: Optional[str]

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ActivityMessage":
        media = raw.get("media")
        return cls(raw.get("sender_name"), raw.get("sender_id"), raw.get("sender_number"), raw.get("sender_avatar"),
                   raw.get("text") or "", media if isinstance(media, dict) else None, raw.get("quoted_text"),
                   parse_time(raw.get("at")), raw.get("message_id"))


@dataclass(frozen=True)
class ActivityAction:
    """One thing the agent did on a turn, in order. ``kind``: ``reply`` (with ``media`` ``{kind, url}`` for a file it
    sent; ``edited`` once it edited it), ``reaction`` (``emoji``), ``note``, ``reminder`` (``when``), ``found``,
    ``held`` (``held_request_id``, the request its owner answers), ``failed`` or ``quiet``."""

    kind: str
    text: Optional[str]
    emoji: Optional[str]
    at: Any
    held_request_id: Optional[str]
    message_id: Optional[str]
    tool: Optional[str]
    media: Optional[Dict[str, Any]]
    when: Optional[str]
    name: Optional[str]
    edited: bool


@dataclass(frozen=True)
class ActivityTurn:
    """The turn an activity item is: its ``agent.message`` operation (``id``) and thread (``conversation_id``).
    ``status`` is ``running`` (its actions fill as its calls complete), ``done`` or ``failed``; ``started_by`` the
    trigger (``{kind, id, title}``) or the wake-up that started it; ``steps`` every call, ``{tool, at, error}``."""

    id: str
    conversation_id: str
    status: str
    started_at: Any
    worked_s: Optional[float]
    started_by: Optional[Dict[str, Any]]
    steps: List[Dict[str, Any]]


@dataclass(frozen=True)
class AgentActivity:
    """A turn a trigger's event or a wake-up started where no one watched: the ``chat`` it happened in, what came in
    (``inbound``, None for a wake-up's; ``also_inbound``, the messages it answered too), what the agent ``did``, and
    the ``turn``."""

    chat: ActivityChat
    inbound: Optional[ActivityMessage]
    also_inbound: List[ActivityMessage]
    did: List[ActivityAction]
    turn: ActivityTurn
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "AgentActivity":
        chat, turn = raw.get("chat") or {}, raw.get("turn") or {}
        did = []
        for row in raw.get("did") or []:
            media = row.get("media")
            did.append(ActivityAction(
                row.get("kind") or "", row.get("text"), row.get("emoji"), parse_time(row.get("at")),
                row.get("held_request_id"), row.get("message_id"), row.get("tool"),
                media if isinstance(media, dict) else None, row.get("when"), row.get("name"), row.get("edited") is True))
        started_by = turn.get("started_by")
        return cls(
            ActivityChat(chat.get("key") or "", chat.get("name"), chat.get("kind"), chat.get("number"),
                         chat.get("avatar"), chat.get("node_type")),
            ActivityMessage._from(raw["inbound"]) if isinstance(raw.get("inbound"), dict) else None,
            [ActivityMessage._from(m) for m in raw.get("also_inbound") or [] if isinstance(m, dict)],
            did,
            ActivityTurn(turn.get("id") or "", turn.get("conversation_id") or "", turn.get("status") or "done",
                         parse_time(turn.get("started_at")), turn.get("worked_s"),
                         started_by if isinstance(started_by, dict) else None, list(turn.get("steps") or [])),
            raw,
        )


@dataclass(frozen=True)
class Message:
    """One message of a conversation: its ``role`` is ``user``, ``assistant``,
    ``person`` (someone it was handed off to) or ``note`` (a line added with
    ``agent.note``, with its ``data``)."""

    role: str
    text: str
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)
    #: The files it carried (a ``user`` message's, sent with ``files=``).
    files: List[Attachment] = dc_field(default_factory=list)
    #: A reply's tool calls: each ``{tool, arguments, result, is_error, created_at}``, as its turn's ``tool_call``
    #: and ``tool_result`` events showed it (``arguments`` cut short are ``{"_truncated": True}``); a coding harness's
    #: reply has its own steps among them, in the order they happened (``AgentStep``).
    tool_calls: List[Dict[str, Any]] = dc_field(default_factory=list)
    #: How a ``user`` message reached the agent when not through the API: ``whatsapp``, ``imessage`` (a text to
    #: NoClick's number), ``call`` (said on a phone call) or ``email`` (mail to one of its inboxes).
    via: Optional[str] = None
    #: A ``note``'s data, as ``agent.note`` added it.
    data: Optional[Dict[str, Any]] = None
    #: What started the turn of a ``user`` message no person sent: ``{kind, id, title}``, ``kind`` a trigger's
    #: (``webhook``, ``event``, ``cron``, ``platform``, ``queue``), ``wakeup``, or ``app_testing`` (NoClick carrying
    #: on once app testing changed); a NoClick event's has its ``event`` (``{id, type, data}``). None for a message
    #: someone sent.
    trigger: Optional[Dict[str, Any]] = None
    #: A reply's reasoning: each ``{text, created_at}``, a short line of what its model was thinking, as its
    #: turn's ``reasoning`` events showed it.
    reasoning: List[Dict[str, Any]] = dc_field(default_factory=list)
    #: The turn it belongs to (an ``agent.message`` operation's id; ``None`` for a message no turn sent, like a
    #: person's).
    operation_id: Optional[str] = None
    #: The harness command a ``user`` message ran in place of text: ``{name, arguments}``. None for a message.
    command: Optional[Dict[str, str]] = None
    #: Its place in the thread, which stays (a revert marks, never removes): what ``fork`` and ``revert`` take.
    id: Optional[str] = None
    #: Who sent a ``user`` message: ``{type, id, name}``, ``type`` ``account`` (the account itself, its owner or a
    #: key), ``user`` (one of your users, or you in a workspace you joined: ``id`` is that user's id), ``agent`` or
    #: ``app`` (an app's code). None where nobody's named (a trigger's event, an older message).
    author: Optional[Dict[str, Any]] = None
    #: An agent's message to its owner from another of its conversations (a ``human__notify`` that joined this thread).
    notification: bool = False
    #: A ``notification`` passing on a space's news (a space's NoClick alerted the person, or answered a question
    #: their NoClick asked it): ``{workspace_id, name, label}``, ``label`` what that NoClick goes by outside its space
    #: ("NoClick · Launch"). None otherwise.
    space: Optional[Dict[str, Any]] = None
    #: A ``user`` message written for one of its coding harness's subagents (``message_subagent``): ``{id, title}``,
    #: ``id`` the harness's call that runs it. None otherwise.
    subagent: Optional[Dict[str, str]] = None
    #: The chat a message of the agent's session came from, where it isn't the session's own: the ``conversation`` it
    #: was sent to (a WhatsApp chat's id, ``channel:<id>``, ``owner``, a shared page's visitor), which its reply goes
    #: back to. None otherwise.
    chat: Optional[str] = None
    #: What a coding harness's reply's turn did (``None`` where it says nothing).
    summary: Optional[TurnSummary] = None
    #: Its harness steps' folds, in order.
    groups: List[StepGroup] = dc_field(default_factory=list)
    #: A channel's turn's ``user`` message: what it delivered, as the channel has it: ``{id, name, space, thread,
    #: posts}``, ``space`` ``{id, name}`` or None, ``thread`` the one its reply posts in (``{id, author, text}``, None
    #: in the channel itself), each post ``{id, author, text, created_at, thread_id, files}`` with ``author``
    #: ``{type, id, name}`` as the channel names it and ``files`` each ``{name, mime_type}``. Its ``text`` is what the
    #: agent read. None otherwise.
    channel: Optional[Dict[str, Any]] = None

    @property
    def steps(self) -> List[AgentStep]:
        """``tool_calls`` as ``AgentStep``s."""
        return _steps(self.tool_calls)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "Message":
        command = raw.get("command")
        return cls(raw.get("role", ""), raw.get("text") or "", parse_time(raw.get("created_at")), raw,
                   [Attachment._from(f) for f in raw.get("files") or []], list(raw.get("tool_calls") or []),
                   raw.get("via"), raw.get("data"), raw.get("trigger"), list(raw.get("reasoning") or []),
                   raw.get("operation_id"),
                   {"name": command.get("name", ""), "arguments": command.get("arguments") or ""}
                   if isinstance(command, dict) else None, raw.get("id"), _author(raw.get("author")),
                   raw.get("notification") is True, raw.get("space") or None, raw.get("subagent") or None,
                   raw.get("chat"), TurnSummary._from(raw.get("summary")), _groups(raw.get("groups")),
                   _channel(raw.get("channel")))


@dataclass(frozen=True)
class HarnessRequest:
    """What a coding harness asks a person mid-turn: an ``approval`` (``action``: ``command``, ``edit``, ``plan``
    (leaving Claude Code's plan mode, its ``plan`` text), ``read``, ``fetch`` or ``tool``; ``title`` in a line,
    ``detail`` the command or the files) or a ``question`` (``questions``, each ``{id, header, question, options,
    multi_select}``). ``options`` are ACP's (``allow_once``, ``allow_always``, ``reject_once``); ``status`` is
    ``pending`` until it's ``answered``, ``expired`` (nobody answered in time: declined) or ``canceled`` (its turn
    stopped). Answer it with ``Agent.answer``."""

    id: str
    kind: str
    status: str
    action: Optional[str] = None
    title: Optional[str] = None
    detail: Optional[str] = None
    plan: Optional[str] = None
    questions: List[Dict[str, Any]] = dc_field(default_factory=list)
    options: List[Dict[str, str]] = dc_field(default_factory=list)
    answer: Optional[Dict[str, Any]] = None
    operation_id: Optional[str] = None
    created_at: Any = None
    expires_at: Any = None
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)
    #: What it was answered with (``allow_once``, ``reject_once``, …) and when; None until it's answered.
    decision: Optional[str] = None
    answered_at: Any = None
    #: Why it was closed unanswered: its turn ended first (failed, stopped, timed out).
    canceled_reason: Optional[str] = None

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "HarnessRequest":
        return cls(raw.get("id") or "", raw.get("kind") or "", raw.get("status") or "", raw.get("action"),
                   raw.get("title"), raw.get("detail"), raw.get("plan"), list(raw.get("questions") or []),
                   list(raw.get("options") or []), raw.get("answer"), raw.get("operation_id"),
                   parse_time(raw.get("created_at")), parse_time(raw.get("expires_at")), raw, raw.get("decision"),
                   parse_time(raw.get("answered_at")), raw.get("canceled_reason"))


@dataclass(frozen=True)
class AgentCommand:
    """One command a conversation's harness offers: its ``name`` (without the slash), what it does, what its
    arguments look like (``argument_hint``), where it comes from (``source``: ``harness``, ``custom``, ``skill`` or
    ``mcp``) and the other names it answers to."""

    name: str
    description: str = ""
    argument_hint: str = ""
    source: str = "custom"
    aliases: List[str] = dc_field(default_factory=list)


@dataclass(frozen=True)
class AgentCommands:
    """What a conversation's harness offers a person to run, read from the harness itself: its ``commands`` and
    ``skills`` (each ``{name, description}``); ``capabilities`` (``commands``, ``skills``, ``compact``, ``review``,
    ``goal``, ``init``, ``steer``, ``queue``); ``not_supported``, what NoClick can't run there and why; ``withheld``,
    the commands NoClick never runs from a chat (those that change what NoClick sets up and guards for the agent: its
    MCP servers, permissions, credentials, model provider, process or settings files); ``mapped``, the harness's
    commands NoClick has a control of its own for, each ``{name, to}`` (``to``: ``model``, ``effort``, ``new``,
    ``usage``, ``context``, ``plan``, ``delivery`` or ``ask``), which a page offers in their place; and how fresh the
    list is: ``as_of`` (when it was
    read) and ``read_from`` (``this_conversation`` or ``another_conversation``: it's kept per agent and harness, so a
    stopped sandbox's last list still answers), both None before its sandbox ever started."""

    harness: str
    commands: List[AgentCommand]
    skills: List[Dict[str, str]]
    capabilities: Dict[str, bool]
    not_supported: Dict[str, str]
    withheld: List[str]
    mapped: List[Dict[str, str]]
    as_of: Any
    read_from: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "AgentCommands":
        return cls(
            raw.get("harness") or "",
            [AgentCommand(c["name"], c.get("description") or "", c.get("argument_hint") or "",
                          c.get("source") or "custom", list(c.get("aliases") or [])) for c in raw.get("commands") or []],
            [{"name": s["name"], "description": s.get("description") or ""} for s in raw.get("skills") or []],
            {k: v is True for k, v in (raw.get("capabilities") or {}).items()},
            {k: str(v) for k, v in (raw.get("not_supported") or {}).items()},
            [str(n) for n in raw.get("withheld") or []],
            [{"name": str(m["name"]), "to": str(m["to"])} for m in raw.get("mapped") or []],
            parse_time(raw.get("as_of")), raw.get("read_from"), raw,
        )


def _read_reply(result: Any, op: Operation) -> AgentReply:
    result = result if isinstance(result, dict) else {"text": result}
    return AgentReply(
        text=result.get("text") or "",
        conversation=result.get("conversation"),
        tool_calls=list(result.get("tool_calls") or []),
        operation_id=op._known("id"),
        raw=result,
        model_usage=ModelUsage._from(result.get("model_usage")),
        ended_by=result.get("ended_by"),
        summary=TurnSummary._from(result.get("summary")),
        groups=_groups(result.get("groups")),
    )


def _agent_event(kind: str, data: Dict[str, Any]) -> AgentEvent:
    """One server-sent event of a streamed turn or a watched conversation."""
    if kind == "done":
        reply = AgentReply(
            data.get("text") or "", data.get("conversation"), list(data.get("tool_calls") or []),
            data.get("operation_id"), data, ModelUsage._from(data.get("model_usage")), data.get("ended_by"),
            TurnSummary._from(data.get("summary")), _groups(data.get("groups")),
        )
        return AgentEvent("done", text=reply.text, reply=reply, operation_id=reply.operation_id, raw=data)
    return AgentEvent(
        kind, text=data.get("text"), tool=data.get("tool"), arguments=data.get("arguments"),
        result=data.get("result"), is_error=bool(data.get("is_error")), role=data.get("role"),
        held=data.get("held"), status=data.get("status"), operation_id=data.get("operation_id"), raw=data,
        file=Attachment._from(data["file"]) if data.get("file") else None,
        files=[Attachment._from(f) for f in data.get("files") or []],
        tool_calls=list(data.get("tool_calls") or []),
        approval=data.get("approval"), operation=data.get("operation"), via=data.get("via"), data=data.get("data"),
        trigger=data.get("trigger"), reasoning=list(data.get("reasoning") or []),
        call_id=data.get("id"), source=data.get("source"), exit_code=data.get("exit_code"),
        duration_ms=data.get("duration_ms"), whole=bool(data.get("whole")), path=data.get("path"),
        change=data.get("kind") if kind == "diff" else None, diff=data.get("diff"), count=data.get("count"),
        step_kind=data.get("kind") if kind in ("tool_call", "tool_result") else None, command=data.get("command"),
        query=data.get("query"), request=data.get("request") if kind == "request" else None,
        message_id=data.get("id") if kind == "message" else None,
        author=_author(data.get("author")) if kind == "message" else None,
        notification=data.get("notification") is True, space=data.get("space") or None,
        subagent=(data.get("subagent") or None) if kind == "message" else None,
        chat=data.get("chat") if kind == "message" else None,
        channel=_channel(data.get("channel")) if kind == "message" else None,
        category=data.get("category"), label=StepLabel._from(data.get("label")),
        display_command=data.get("display_command"),
        group=data.get("group") if kind in ("tool_call", "tool_result") else None,
        step_group=StepGroup._from(data) if kind == "group" else None,
        tests=StepTests._from(data.get("tests")), progress=StepProgress._from(data.get("progress")),
        output_lines=data.get("output_lines"), diff_stat=DiffStat._from(data.get("diff_stat")),
        failed=data.get("failed") if isinstance(data.get("failed"), bool) else None,
        summary=TurnSummary._from(data.get("summary")),
    )


register_result("agent.message", _read_reply)
# A spawned task and an ``ask`` settle with a reply too.
register_result("agent.task", _read_reply)
register_result("agent.ask", _read_reply)
# A message to an agent built in the app.
register_result("workflow.agent_message", _read_reply)


def _integration_refs(entries: Any) -> Optional[List[str]]:
    """``can_request`` on the wire: integration names (or ``IntegrationInfo``s), ``"integration.operation"``, ``"*"``."""
    if entries is None:
        return None
    if isinstance(entries, str):
        return [entries]
    return [e if isinstance(e, str) else e.name for e in entries]


# What ``from_name`` sets on an existing agent (``triggers`` too, through the
# triggers sub-resource).
_CONVERGED = (
    "instructions", "model", "harness", "model_connection", "tools", "tool_rules", "can_request", "budget_usd_per_month",
    "browser_profile_id", "card_id", "volumes", "memories", "skills", "secret_ids", "timezone", "repos", "network", "shell",
    "region", "machine_id", "turn_limits", "effort", "speed", "permission_mode", "setup", "docker", "sandbox_size",
    "app_testing", "model_switching",
)
# Set when an agent is created, for good: ``from_name`` checks them on an existing one.
_FIXED = ("ttl_s", "parent_id")


def _drifted(key: str, have: Any, want: Any) -> bool:
    """Whether ``from_name`` sets ``key``: ``model_switching`` is sent as only its given parts, so only those count."""
    if key == "model_switching" and isinstance(want, dict):
        return any((have or {}).get(k) != v for k, v in want.items())
    return have != want


@dataclass(frozen=True)
class ModelSwitching:
    """How an agent moves to another of its owner's model connections when its plan runs out, or when it's told to.

    ``mode="switch"`` (a new agent's default): it moves by itself, to any of the owner's own Claude or ChatGPT plans
    freely, and to a paid key (an API key, NoClick's key at cost) only on the owner's say-so. ``mode="stay"``: it
    never leaves its connection, and at a limit waits for the reset. ``allowed``: the connections (``Connection`` or
    names) it moves between freely, paid keys included; None for the default rule. Only what's given is sent: an
    update changes only those (``allowed`` alone never changes its mode).

    Usage::

        atlas = noclick.Agent.from_name("atlas")
        atlas.update(model_switching=noclick.ModelSwitching(mode="stay"))
    """

    mode: Any = UNSET
    allowed: Any = UNSET


async def switching_wire(value: Any, *, scope: Any = AMBIENT) -> Optional[Dict[str, Any]]:
    """``model_switching=`` on the wire: a ``ModelSwitching`` or its dict, only what's given, each allowed connection
    by the ref its scope names it (``model_connection_ref``)."""
    if value is None:
        return None
    if isinstance(value, ModelSwitching):
        value = {k: v for k, v in (("mode", value.mode), ("allowed", value.allowed)) if v is not UNSET}
    wire: Dict[str, Any] = {}
    if "mode" in value:
        wire["mode"] = value["mode"]
    if "allowed" in value:
        allowed = value["allowed"]
        wire["allowed"] = None if allowed is None else [
            await model_connection_ref(a, scope=scope) for a in allowed]
    return wire


@dataclass(frozen=True)
class ModelSwitchGrant:
    """The owner's say-so for an agent's paid keys: which (``connections``, None for any), ``once`` or ``standing``,
    and how they gave it (``source``: ``cited``, words of theirs the agent cited, with ``evidence`` saying where and
    when, the quote and a link; ``asked``, their tap; ``owner``, their own call)."""

    id: str
    connections: Optional[List[str]]
    scope: str
    source: str
    evidence: Dict[str, Any]
    granted_by: Dict[str, Any]
    used_at: Optional[str]
    revoked_at: Optional[str]
    created_at: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False, compare=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ModelSwitchGrant":
        return cls(id=raw["id"], connections=raw.get("connections"), scope=raw["scope"], source=raw["source"],
                   evidence=raw.get("evidence") or {}, granted_by=raw.get("granted_by") or {},
                   used_at=raw.get("used_at"), revoked_at=raw.get("revoked_at"), created_at=raw.get("created_at"),
                   raw=raw)


def _limits_wire(limits: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """``turn_limits=`` on the wire: the limits given, as the agent keeps them (None: the defaults)."""
    given = {k: v for k, v in (limits or {}).items() if v is not None}
    return given or None


async def _repo_wires(repos: Sequence[Any], scope: Any) -> List[Dict[str, Any]]:
    """``repos=`` on the wire: each ``connection.checkout(...)`` or ``repo.checkout(...)`` says its own."""
    wires = []
    for checkout in repos:
        if not hasattr(checkout, "_wire"):
            raise TypeError(f"repos takes connection.checkout(...) or repo.checkout(...), not {checkout!r}")
        wires.append(await checkout._wire(scope))
    return wires


AGENT_STATUSES = ("working", "waiting", "idle", "expired")
LIST_ORDERS = ("created", "last_active")
ORIGINS = ("api", "app")


async def _list_params(name: Optional[str], status: Optional[str], active_since: Any, parent: Any,
                       temporary: Optional[bool], harness: Optional[str], order: Optional[str],
                       origin: Optional[str]) -> Dict[str, Any]:
    """``Agent.list``'s filters on the wire."""
    if status is not None and status not in AGENT_STATUSES:
        raise ValueError(f"status is one of {AGENT_STATUSES}, not {status!r}")
    if order is not None and order not in LIST_ORDERS:
        raise ValueError(f"order is one of {LIST_ORDERS}, not {order!r}")
    if origin is not None and origin not in ORIGINS:
        raise ValueError(f"origin is one of {ORIGINS}, not {origin!r}")
    return {
        "name": name, "status": status, "active_since": iso_time(active_since), "parent_id": await agent_id(parent),
        "temporary": None if temporary is None else ("true" if temporary else "false"), "harness": harness,
        "order": order, "origin": origin,
    }


async def agent_id(agent: Any) -> Optional[str]:
    """The id of an ``Agent`` (hydrating a lazy one) or an id string."""
    if agent is not None and not isinstance(agent, (str, Agent)):
        raise TypeError(f"Expected an noclick.Agent or an agent id, not {type(agent).__name__}")
    return await ref_id(agent)


class Agent(_Object):
    """A hosted agent. ``Agent.from_name("host", create_if_missing=True,
    instructions=...)`` is lazy; ``agent.message("hi").text`` talks to it.

    An account-level agent is shared: each user that messages it (via
    ``as_user`` or ``user=``) gets its own conversations. A user's own
    agent always acts for that user.

    The agents built in the NoClick app are listed and messaged here too
    (``origin`` ``app``, an id like ``node:<workflow>:<node>``): ``send`` and
    ``message`` reach them, and what they are is changed in the app.
    """

    _repr_keys = ("id", "name", "model")

    id: str = field("id")
    origin: Optional[str] = field(
        "origin", doc="``api`` for an agent made through the API, ``app`` for one built in the NoClick app.",
    )
    name: str = field("name")
    model: Optional[str] = field("model", doc="The model it runs, as its harness names it (``sonnet``, ``openrouter/...``).")
    harness: Optional[str] = field(
        "harness", doc="What runs it: ``sdk``, ``claude_code``, ``codex``, ``opencode``, ``hermes`` or ``openclaw``.",
    )
    model_connection: Optional[str] = field(
        "model_connection",
        doc="The connection whose key or plan it thinks with, by name (``None`` on ``sdk`` without one). "
        "Hidden, like ``instructions``, from a user's session reading an account agent.",
    )
    instructions: Optional[str] = field("instructions")
    tools: List[Any] = field(
        "tools", doc="What it can use, as listed: refs, ``{tool, bind}`` for an operation with arguments bound "
        "and ``{human, tools}`` for a person.",
    )
    tool_rules: Dict[str, str] = field(
        "tool_rules", doc="What it may do with each app it reaches, ``{key: 'allow' | 'ask' | 'off'}`` (empty: "
        "everything its tools give is allowed). See ``create``.",
    )
    can_request: List[str] = field("can_request", doc="What it may ask its user to connect at run time.")
    user_id: Optional[str] = field("user_id")
    workflow_id: Optional[str] = field("workflow_id")
    node_id: Optional[str] = field("node_id", doc="An app agent's step in its workflow (None for an API agent).")
    workflow_name: Optional[str] = field("workflow_name", doc="An app agent's workflow, by name.")
    access: Optional[str] = field(
        "access", doc="An app agent's workflow as you hold it: ``owner``, or ``editor`` or ``viewer`` when it was "
        "shared with you (only an owner's or an editor's takes messages).",
    )
    enabled: Optional[bool] = field("enabled", doc="Whether an app agent is switched on; a disabled one takes no messages.")
    app_url: Optional[str] = field("app_url", doc="Where an app agent is changed: its workflow in the NoClick app.")
    parent_id: Optional[str] = field("parent_id")
    ttl_s: Optional[int] = field(
        "ttl_s", doc="Its time to live, in seconds (None if it isn't temporary); ``expires_at`` is when it runs "
        "out, sooner for a temporary parent's child.",
    )
    expires_at: Any = field(
        "expires_at", parse_time,
        doc="When a temporary agent's ``ttl_s`` runs out (None if it isn't temporary): then ``expired``, taking no "
        "turns, readable for 30 days.",
    )
    budget_usd_per_month: Optional[float] = field("budget_usd_per_month")
    budget_restore: Optional[Dict[str, Any]] = field(
        "budget_restore", doc="While a budget set for one run holds (``update(budget_for_run=True)``), the budget that "
        "comes back as that run ends and after which run: ``{budget_usd_per_month, operation_id}`` (``operation_id`` "
        "None: its next turn). None otherwise.",
    )
    region: Optional[str] = field(
        "region", doc="The region its sandboxes run in (``noclick.regions()``), fixed when it was created; ``None``: "
        "wherever NoClick has capacity.",
    )
    machine_id: Optional[str] = field(
        "machine_id", doc="The ``Machine`` its harness runs on (None: a sandbox of its own; invite-only beta).",
    )
    created_at: Any = field("created_at", parse_time)
    browser_profile_id: Optional[str] = field(
        "browser_profile_id",
        doc="The browser profile its ``browser`` tool signs in with, of its own scope.",
    )
    card_id: Optional[str] = field(
        "card_id", doc="The ``Card`` it holds and pays with (None: none of its own; a spawned child may pay with its "
                       "parent's; invite-only beta).",
    )
    volumes: Optional[Dict[str, str]] = field(
        "volumes", doc="The volumes its shell mounts, by mount path: ``{path: volume id}``.",
    )
    memory_id: Optional[str] = field(
        "memory_id", doc="Its own memory (``agent.memory``) as a ``Memory`` id, to attach to other agents.",
    )
    skills: Optional[List[Dict[str, Any]]] = field("skills", doc="Its skills: each ``{id, pin}``.")
    memories: Optional[List[Dict[str, Any]]] = field(
        "memories", doc="The memories it reads besides its own, in order: each ``{id, writes}`` (None for a user's "
                        "session reading an account agent).",
    )
    secret_ids: Optional[List[str]] = field(
        "secret_ids", doc="The secrets in its shell's environment, in order (a later one's key wins).",
    )
    timezone: Optional[str] = field(
        "timezone",
        doc="The IANA timezone each turn is told the date and time in (``None``: the acting user's, else UTC).",
    )
    repos: Optional[List[Dict[str, Any]]] = field(
        "repos",
        doc="Repositories cloned into its workspace at a conversation's first turn: a ``connection`` and "
        "``repository``, a NoClick ``repo_id`` or a git ``url`` (signed in with a secret's ``secret_key``), each "
        "with its ``branch``, ``path`` and the branch globs it may ``push`` to.",
    )
    setup: List[str] = field(
        "setup", lambda v: list(v or []),
        doc="Commands its sandbox (its container, on a machine) runs as it starts (a coding harness only).",
    )
    docker: bool = field(
        "docker", bool,
        doc="Whether Docker runs in its sandbox, a VM of ``sandbox_size`` (a coding harness only).",
    )
    sandbox_size: Optional[str] = field(
        "sandbox_size",
        doc="The VM a Docker agent works in: ``small`` (2 CPUs, 4 GB), ``medium`` (4 CPUs, 8 GB) or ``large`` "
        "(8 CPUs, 16 GB); None without Docker.",
    )
    app_testing: str = field(
        "app_testing",
        doc="How a coding agent may turn app testing on (Docker in its sandbox for a task that needs it): "
        "``by_itself``, ``ask_first`` or ``never``.",
    )
    app_testing_usd_per_hour: Optional[float] = field(
        "app_testing_usd_per_hour",
        doc="What an hour of app testing costs where its sandbox runs; None without a sandbox of its own (an ``sdk`` "
        "agent, one on a machine).",
    )
    model_switching: Dict[str, Any] = field(
        "model_switching",
        doc="Its owner's rule for moving to another model connection when its plan runs out or it's told to: "
        "``{\"mode\": \"switch\"|\"stay\", \"allowed\": [names]|None}`` (``ModelSwitching``). In ``switch`` "
        "(the default) any of the owner's own plans is free and a paid key needs their say-so; ``stay`` keeps it on "
        "its connection; ``allowed`` names the ones it moves between freely.",
    )
    switched_from: Optional[Dict[str, Any]] = field(
        "switched_from",
        doc="While a plan's limit has it on another connection, the one it left (``connection``, ``name``, "
        "``window``, ``resets_at``): its first turn after that goes back there. None otherwise.",
    )
    moved_from: Optional[Dict[str, Any]] = field(
        "moved_from",
        doc="Where a move from a laptop made it (``move_id``, ``host``, ``folder``, ``at``); else None.",
    )
    network: Any = field(
        "network",
        doc="What its shell and code reach: ``True`` (anywhere), ``False`` (only what it needs to work) or the "
        "hosts it may reach besides, as sent.",
    )
    shell: Optional[bool] = field(
        "shell", doc="Whether it has a shell, the ``code`` capability (``False`` only on ``sdk``).",
    )
    turn_limits: Optional[Dict[str, Any]] = field(
        "turn_limits",
        doc="How far one of its turns goes, as set: ``steps``, ``usd`` and ``minutes`` (``None``, or a limit "
        "left out: 200 steps, $1 and 30 minutes).",
    )
    effort: Optional[str] = field(
        "effort", doc="Its conversations' reasoning effort (``None``: the model's own).",
    )
    speed: Optional[str] = field(
        "speed", doc="``fast``: its conversations run in fast mode.",
    )
    permission_mode: Optional[str] = field(
        "permission_mode", doc="Its conversations' permission mode unless one sets its own.",
    )
    approvals: Dict[str, Dict[str, Any]] = field(
        "approvals", lambda raw: dict(raw or {}),
        doc="What its own calls wait for a person on in place of the account's, by kind of hold (``disposition``, "
        "``under_usd``, ``until``, ``effective_at``, ``pending``), and ``routing``: who answers its held calls first "
        "(``approver``, ``on_timeout``, ``expires_in_s``); empty where it sets none (a child follows its parent's).",
    )
    status: Optional[str] = field(
        "status",
        doc="``working`` (a turn queued or running), ``waiting`` (its turns wait on a person: a question, a held "
        "call), ``idle``, or ``expired`` (past its ``ttl_s``: no turns, readable for 30 days). Pausing stops "
        "triggers, not work, so a paused agent can be "
        "``working``; ``paused`` says it's paused. None, like the activity fields below, for a user's session "
        "reading an account agent.",
    )
    last_active_at: Any = field(
        "last_active_at", parse_time,
        doc="When one of its turns last started or ended (``None``: it never ran, or hidden like ``status``).",
    )
    running_turns: Optional[int] = field(
        "running_turns",
        doc="How many of its turns are queued, running or waiting on a person, any conversation (hidden like ``status``).",
    )
    child_count: Optional[int] = field(
        "child_count",
        doc="How many live (not expired) children it has; ``children()`` lists them (hidden like ``status``).",
    )
    job_id: Optional[str] = field(
        "job_id", doc="The task it was spawned with, an ``agent.task`` operation (``None`` if ``spawn`` didn't make it).",
    )
    used_by: List[Dict[str, Any]] = field(
        "used_by",
        doc="The apps that bind it: ``kind`` (``project``), ``id``, ``name`` and the ``binding`` name (None for a "
        "user's session reading an account agent).",
    )

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    @staticmethod
    def _body(name: str, instructions: Optional[str], model: Optional[str], harness: Optional[str],
              tools: Optional[Sequence[Any]], ttl_s: Optional[int] = None, parent: Any = None,
              budget_usd_per_month: Optional[float] = None,
              can_request: Optional[Sequence[Any]] = None, triggers: Optional[Sequence[Any]] = None,
              browser_profile: Any = None, card: Any = None, volumes: Any = None, secrets: Any = None,
              model_connection: Any = None, timezone: Optional[str] = None, repos: Optional[Sequence[Any]] = None,
              network: Any = None, shell: Optional[bool] = None, region: Optional[str] = None,
              machine: Any = None, memories: Optional[Sequence[Any]] = None,
              skills: Optional[Sequence[Any]] = None,
              turn_limits: Optional[Mapping[str, Any]] = None, effort: Optional[str] = None,
              speed: Optional[str] = None, permission_mode: Optional[str] = None,
              setup: Optional[Sequence[str]] = None, tool_rules: Optional[Mapping[str, str]] = None,
              docker: Optional[bool] = None, sandbox_size: Optional[str] = None,
              app_testing: Optional[str] = None, model_switching: Any = None,
              user: Any = AMBIENT, client: Optional[Client] = None) -> Dict[str, Any]:
        # ``parent_id``, ``browser_profile_id`` and ``card_id`` may still be lazy objects, ``tools`` and
        # ``model_connection`` lazy Connections, ``triggers`` definitions, ``repos`` checkouts and
        # ``volumes``/``secret_ids`` lazy refs here; ``_wire`` resolves them. A volume or secret named by a
        # string is looked up in ``user``.
        return compact(
            name=name, instructions=instructions, model=model, harness=harness, model_connection=model_connection,
            tools=tools, tool_rules=None if tool_rules is None else dict(tool_rules), ttl_s=ttl_s, parent_id=parent,
            budget_usd_per_month=budget_usd_per_month, can_request=_integration_refs(can_request),
            triggers=None if triggers is None else list(triggers),
            browser_profile_id=browser_profile, card_id=card,
            volumes=volume_refs(volumes, user=user, client=client),
            memories=memory_refs(memories, user=user, client=client),
            skills=skill_refs(skills, user=user, client=client),
            secret_ids=secret_refs(secrets, user=user, client=client),
            timezone=timezone, repos=None if repos is None else list(repos), network=network_wire(network), shell=shell,
            region=region, machine_id=machine, turn_limits=_limits_wire(turn_limits), effort=effort, speed=speed,
            permission_mode=permission_mode, setup=None if setup is None else list(setup), docker=docker,
            sandbox_size=sandbox_size, app_testing=app_testing, model_switching=model_switching,
        )

    @staticmethod
    async def _wire(body: Dict[str, Any], *, scope: Any) -> Dict[str, Any]:
        """``scope`` is the agent's user (None for the account): a connection from another scope is sent by id."""
        if "parent_id" in body:
            body = {**body, "parent_id": await agent_id(body["parent_id"])}
        if "tools" in body:
            body = {**body, "tools": await tool_refs(body["tools"], scope=scope)}
        if "model_connection" in body:
            body = {**body, "model_connection": await model_connection_ref(body["model_connection"], scope=scope)}
        if "model_switching" in body:
            body = {**body, "model_switching": await switching_wire(body["model_switching"], scope=scope)}
        if "triggers" in body:
            body = {**body, "triggers": [await trigger_wire(t) for t in body["triggers"]]}
        for key in ("browser_profile_id", "card_id", "machine_id"):
            if key in body:
                body = {**body, key: await ref_id(body[key])}
        if "volumes" in body:
            body = {**body, "volumes": await volume_ids(body["volumes"])}
        if "memories" in body:
            body = {**body, "memories": await memory_links(body["memories"])}
        if "skills" in body:
            body = {**body, "skills": await skill_links(body["skills"])}
        if "secret_ids" in body:
            body = {**body, "secret_ids": await secret_ids(body["secret_ids"])}
        if "repos" in body:
            body = {**body, "repos": await _repo_wires(body["repos"], scope)}
        return body

    @designed_params(
        "card", "machine",
    )
    @synced
    @classmethod
    async def create(
        cls,
        name: str,
        *,
        instructions: str,
        model: Optional[str] = None,
        harness: Optional[str] = None,
        model_connection: Any = None,
        tools: Optional[Sequence[Any]] = None,
        tool_rules: Optional[Mapping[str, str]] = None,
        ttl_s: Optional[int] = None,
        parent_id: Any = None,
        budget_usd_per_month: Optional[float] = None,
        can_request: Optional[Sequence[Any]] = None,
        triggers: Optional[Sequence[Any]] = None,
        browser_profile: Any = None,
        card: Any = None,
        volumes: Optional[Mapping[str, Any]] = None,
        secrets: Optional[Sequence[Any]] = None,
        timezone: Optional[str] = None,
        repos: Optional[Sequence[Any]] = None,
        network: Union[None, bool, Sequence[str]] = None,
        shell: Optional[bool] = None,
        region: Optional[str] = None,
        machine: Any = None,
        memories: Optional[Sequence[Any]] = None,
        skills: Optional[Sequence[Any]] = None,
        turn_limits: Optional[Mapping[str, Any]] = None,
        effort: Optional[str] = None,
        speed: Optional[str] = None,
        permission_mode: Optional[str] = None,
        setup: Optional[Sequence[str]] = None,
        docker: Optional[bool] = None,
        sandbox_size: Optional[str] = None,
        app_testing: Optional[str] = None,
        model_switching: Any = None,
        approvals: Optional[Mapping[str, Any]] = None,
        allow_existing: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Agent":
        """Create an agent (names are unique per account and user; a
        duplicate raises ``noclick.Conflict`` with ``existing_id``). With
        ``allow_existing=True`` a taken name returns the agent already there, as it is:
        nothing about it changes, so it's made once and left alone after.

        ``harness`` is what runs it: ``"sdk"`` (the default), NoClick's own agent
        loop, or a coding agent in a sandbox of its own with a shell and files:
        ``"claude_code"``, ``"codex"``, ``"opencode"``, ``"hermes"`` or ``"openclaw"``
        (``Agent.harnesses()`` lists them). ``model`` is the harness's own: an
        OpenRouter id with the ``openrouter/`` prefix on ``sdk``, an alias such as
        ``"sonnet"`` on ``claude_code``, a ``provider/model`` on ``opencode``, ``hermes``
        and ``openclaw``; omitted, the harness's default. ``model_connection`` is the
        connection whose key or plan it thinks with (a ``Connection`` of a
        ``kind="model"`` integration such as ``anthropic``, or its name, in the
        agent's own scope; a lazy ``create_if_missing`` one is created first): every
        CLI harness needs one, and it may still be pending. On ``sdk`` it's optional,
        and lets ``model`` name ``anthropic/...`` or ``openai/...`` on your own key.
        A ``Connection`` object from another scope, such as your account's key for a
        user's agent, stays that connection (invite-only beta): only a key
        acting for the whole account may set one, and it must hold a key, since a
        person's Claude or ChatGPT plan is never shared. ``model_connection="noclick"`` runs a ``codex`` or
        ``opencode`` agent on NoClick's own key, at the model's cost (``HarnessInfo.noclick_key``).

        ``effort`` is how hard its model reasons in every conversation (one of its harness's
        ``efforts``); ``speed="fast"`` runs its model in its harness's fast mode where it has one (``speeds``).
        ``permission_mode`` is how far its coding harness goes before asking a person in a conversation that sets
        none (one of its harness's ``permission_modes``; a conversation's ``set_permission_mode`` wins).
        ``setup`` is commands a coding agent's sandbox (its container, on a machine) runs as it starts, in order, after
        its ``repos`` and with its ``secrets`` in the environment (a CLI installed, a config file written).
        ``docker=True`` runs Docker in a coding agent's sandbox, which is then a VM of ``sandbox_size`` (``"small"``,
        2 CPUs and 4 GB, unless it says ``"medium"`` or ``"large"``), with dockerd running before its first turn:
        ``docker``, ``docker compose`` and testcontainers work as on any Linux machine. The VM is billed at its cost
        for all of its size while it's up.
        ``app_testing`` is how a coding agent may turn Docker on for a task that needs it, without ``docker``:
        ``"by_itself"`` (the default) turns it on when a task does and off once it's done, saying each in its chat;
        ``"ask_first"`` asks the account's owner in the chat each time; ``"never"``.
        ``model_switching`` is how it moves to another of the owner's model connections when its plan runs out or
        it's told to (``ModelSwitching``, or ``{"mode": ..., "allowed": [...]}``): left out, it switches by itself
        to any of the owner's own plans and asks before a paid key.

        ``tools`` left out gives it everything in its scope (``"everything"``): every connection,
        ones connected later too, operations that need no account, the web and NoClick itself,
        plus the account's owner to notify and ask for an account agent. A list narrows it to
        connections (a ``Connection``, or its name: every operation), one
        operation of one (``"gmail.send_email_message"``), the capabilities ``"search"`` and
        ``"fetch"``, a ``Toolkit``, or a ``Database`` (its ``query``, ``execute`` and
        ``schema``, or ``db.only(...)``; invite-only beta), or a browser (``"browser"``, or
        ``"browser.act"`` and the like), or a person (a ``Human``, or ``human.only(...)``:
        tools that notify them, ask them and wait for the answer, or hand them the
        conversation), or the ``agents`` capability (``"agents"``, or ``noclick.Agents.only(...)``:
        tools to spawn, message, ask and keep track of other agents), or NoClick itself (``"noclick"``, or
        ``noclick.Platform.only(...)``: your account's API as tools, a purchase or a deletion waiting for
        your approval): at most 64 tools in all. A string names
        a connection in the agent's own user (the account for an account agent, whose
        ``"credential:<id>"`` names an account connected in the NoClick app), else an
        integration's operations that need no account (on NoClick's key), so
        ``tools=["exa.search"]`` (or ``"exa"``, all of them) needs no connection. A
        ``Connection`` object from another scope, another user's or the
        account's, stays that connection (a key acting for the whole account only).
        A lazy ``create_if_missing`` connection is created first. Every agent can also
        run shell commands (the ``code`` capability; a policy that denies
        ``code`` refuses them, and ``shell=False`` removes it). ``ttl_s`` makes it temporary:
        once that many seconds have passed it's ``expired``, taking no turns (its pending
        wake-ups are canceled) and readable for 30 days, then deleted; ``parent_id`` (an ``Agent`` or id) makes it a
        child of that agent, with nothing started (``parent.spawn`` also starts a task);
        ``budget_usd_per_month`` caps its spend: a child's is held out of what its parent
        has left, and a child without one draws on its parent's budget as it spends.

        ``tool_rules`` says what it may do with each app it reaches, ``{key: "allow" | "ask" | "off"}``: a key is
        an app as ``tools`` names it (a connection's name, ``"credential:<id>"``, an integration's, ``"noclick"``,
        ``"search"``, ``"fetch"``), one action of it (``"work-gmail.delete_email_message"``; NoClick's are its
        groups, ``"noclick.spend"``), or ``"*"`` for whatever the rest don't name. The most specific key naming a
        call decides it: ``allow`` runs it, ``ask`` holds it for the owner's yes, ``off`` refuses it; with none, it's
        allowed. With everything, ``{"*": "off", ...}`` keeps it to the apps the rules turn on, so an account
        connected later starts off. ``tool_access()`` shows them app by app. ``"noclick.spend": "allow"`` and
        ``"noclick.delete": "allow"`` also set its ``approvals`` for ``purchase`` and ``delete`` to allow.

        ``approvals`` are what its own calls wait for a person on, in place of the account's, by kind of hold
        (``noclick.ApprovalPolicy.get()`` lists the settable ones): ``"allow"``, ``"ask"``, ``"deny"``, or a dict
        with ``disposition`` (a purchase also takes ``under_usd``: allowed at or under it, asked above; any kind
        ``until``). Never looser than the account's ceiling for the kind (raise it with
        ``ApprovalPolicy.set(ceilings=...)``), a child's never looser than its parent's (which it follows where it
        sets none), and a purchase or a deletion past the default needs a monthly cap on the account. Loosening is
        the owner's: signed in, their own message to one of their agents, or a key naming ``approvals:policy``
        (after a 10-minute undo window); an agent acting on its own waits for the owner's yes. ``"routing"`` among
        them names who answers its held calls first, in place of its parent's or the account's approver (finally the
        owner), as ``ApprovalPolicy.set``'s ``routing`` takes it: its parent may approve its calls, never the agent
        itself nor one of its children.

        ``can_request`` lets it ask its user to connect accounts at run time
        (a ``request_connection`` tool): integration names, single
        ``"integration.operation"``s, or ``"*"``. What the user connects is a
        grant (``grants()``), kept apart from the agent's fields.

        ``triggers`` wake it without a message: ``noclick.OnWebhook``, ``OnEvent``, ``OnPlatformEvent``,
        ``Cron`` and ``OnQueue`` (see ``triggers()``).

        ``timezone`` (an IANA name) is the zone every turn is told the date and time in;
        without one, the acting user's ``timezone``, else UTC. An account's own agent made
        without one starts in its owner's, where their NoClick assistant tells the time.

        ``region`` (``noclick.regions()``) is where its sandboxes run, for good: a coding
        harness runs there whole, and an ``sdk`` agent's shell does while its loop runs in
        NoClick's own service. Without one it takes its parent's, else your account's
        default region, else runs wherever NoClick has capacity. ``region=db.region`` keeps
        an agent beside its data. ``machine`` (a ``Machine`` or id; invite-only
        beta) runs its harness on an always-on machine instead: no sandbox per
        conversation, nothing reaped when it's quiet, no per-minute sandbox charge,
        and it runs in the machine's region. A coding harness there reaches its model
        through NoClick's credential proxy, so its ``model_connection`` holds a
        Claude, ChatGPT or OpenRouter key, or your account's own plan: a Claude plan
        on ``claude_code`` or a ChatGPT plan on ``codex``, its sign-in kept in that
        agent's own container (the answer's ``notes`` say so). Anyone else's plan
        raises ``noclick.NotAvailable``; a machine runs at most 50 agents.

        ``volumes`` mounts ``Volume``s (or their ids or names: its user's own,
        then the account's) read-write in its shell at absolute paths
        (``{"/data": vol}``), in every conversation, up to 5; not at
        ``/workspace``, ``/root`` or a system folder. An ``sdk`` agent's shell
        sees each as it was when the turn started and saves its writes when the
        turn ends; a coding harness's sandbox, from when it starts until it stops.

        ``memories`` are the ``Memory``s it reads besides its own (``agent.memory``), in order, up to 10:
        a ``Memory``, its id or name (its user's own, then the account's), or another agent's ``memory``.
        Each is read-only to it unless given as ``memory.writable()``; a user's agent reads the account's
        memories but never writes them, and never another user's. Every turn starts with each entry's name
        and description, its own memory's first.

        ``skills`` are the ``Skill``s it uses, in order, up to 20: a ``Skill`` (``skill.pinned(n)`` to hold
        one version), its id or name (its user's own, then the account's). A coding harness finds them where
        it reads skills; an ``sdk`` agent sees each one's name and description every turn and reads one with
        ``skill__read``.

        ``repos`` clones repositories into its workspace, ``/workspace/<name>``, at a
        conversation's first turn: ``connection.checkout(...)`` for one a ``github``
        connection of its own scope reaches, or ``repo.checkout(...)`` for a NoClick ``Repo`` of
        its own scope, up to 10 (none with ``shell=False``). Its ``git`` reaches those
        repositories only, through NoClick, with a key made for its sandbox; the
        connection's token never enters it. A push goes through only to the branches
        the checkout's ``push`` globs name (none: read-only): NoClick judges each push
        on its way to the git host, because a harness's own ``git push`` is no tool
        call your policy could judge. ``gh`` only reads a git host's there; pull requests and
        issues are the connection's operations, in ``tools``.

        ``secrets`` (``Secret``s, ids or names; up to 20) become environment
        variables in its shell on every turn, a later secret's key winning a clash
        (a change reaches its next turn): its user's and the account's, an account
        agent's the account's only. Its shell takes no model provider's key
        (``OPENAI_API_KEY`` and the like belong on ``model_connection``): a secret
        holding one raises ``noclick.InvalidRequest``.

        ``shell=False`` takes the shell (the ``code`` capability) away from an ``sdk``
        agent, and from the children it spawns; a CLI harness refuses it with
        ``noclick.InvalidRequest``, since its shell is the harness.

        ``turn_limits`` is how far one turn of an ``sdk`` agent goes before it wraps up:
        ``{"steps": 100, "usd": 2, "minutes": 45}``, each left out at its default ($1 of
        model calls and 30 minutes, with 200 model calls as a backstop; at most 200, $25
        and 60). A turn its steps end stops there saying nothing and carries on by itself
        in a follow-up turn on the same conversation, up to 3 in a row, unless a message
        comes first; one its spend or minutes end says where the work stands and waits
        to be asked (``reply.ended_by`` names the limit). A coding harness ends its own
        turns, and refuses it with ``noclick.InvalidRequest``.

        ``network`` says what its shell and code may reach: ``True`` (the default:
        anywhere), ``False``, or up to 50 hosts (``"pypi.org"``, or ``"*.example.com"``
        for a domain and its subdomains), over HTTPS on port 443 only. What it needs
        to work stays reachable, and ``False`` leaves only that: an ``sdk`` agent's
        shell reaches NoClick's git proxy when it has ``repos`` (its model and tools run
        on NoClick); a coding harness reaches NoClick's API, NoClick's proxy for its
        model on a key and for git, and on a Claude or ChatGPT plan that provider's own
        hosts. Its tools run on NoClick, outside the limit. Without one it takes its
        parent's, else anywhere, and the children it spawns take its. Where NoClick
        can't keep to a limited network (a coding harness on a key other than
        Claude, ChatGPT or OpenRouter, say), it raises ``noclick.NotAvailable``
        rather than widen it.

        ``browser_profile`` (a ``BrowserProfile`` or id of its own user's, or your
        account's for an account agent) signs its ``browser`` tool in with that
        person's logins: each conversation gets a browser of its own for a turn, a
        step only a person can do holds the turn ``awaiting_human``, and its calls
        follow policy as ``browser.*``.

        Invite-only beta: ``card`` (a ``Card`` or id of its own scope: a
        user's agent pays with that user's cards, an account agent with your account's;
        giving one takes the key's ``cards`` scope) is what it pays with: it holds the card
        (a card has one agent at a time) and gets the tools ``card__status`` (what it can
        spend now) and ``card__purchase`` (approve before paying: above the card's threshold
        the turn waits for a person, and their answer is its next turn), which policy names
        ``card.status`` and ``card.purchase``. It never sees the number, and a turn answering
        someone outside its scope, or a test run, can't buy anything. A child it spawns pays
        with the same card only when given ``"card"`` (or one of the tools) in its ``tools``.

        Returns:
            The new agent, loaded.

        Usage:
            Outside ``as_user`` the agent is your account's, shared by every user that messages it::

                support = noclick.Agent.create(
                    "support",
                    instructions="You answer questions about our product. Search the docs before answering.",
                    tools=["search", "fetch"],
                    budget_usd_per_month=50,
                )

            Inside ``as_user`` it's that user's own, and uses the user's connections::

                with noclick.as_user("user_42"):
                    gmail = noclick.Connection.from_name("gmail", integration="gmail", create_if_missing=True)
                    assistant = noclick.Agent.create("assistant", instructions="You help the user with their email.", tools=[gmail])

            An operation that needs no account needs no connection, for any agent, a user's included::

                with noclick.as_user("user_42"):
                    scout = noclick.Agent.create("scout", instructions="You research companies for the user.", tools=["exa.search"])

            Run it on Claude Code, thinking with your Claude key. Its reply arrives whole, and a
            conversation's first turn starts its sandbox::

                claude = noclick.Connection.from_name("claude", integration="anthropic", create_if_missing=True)
                coder = noclick.Agent.create(
                    "coder",
                    instructions="You maintain our docs repo.",
                    harness="claude_code",
                    model="sonnet",
                    model_connection=claude,
                    tools=["github", "search"],
                )
                if not claude.connected:
                    print(claude.connect_url)   # where someone pastes a Claude key

            Make it once, and leave it alone after: a run that finds it returns it untouched, so an edit
            someone made in the app stays::

                support = noclick.Agent.create(
                    "support", instructions="You answer questions about our product.", allow_existing=True,
                )

            Give a coding agent a repository to work in, branches of its own to push to, and a
            clock in your team's timezone::

                github = noclick.Connection.from_name("github", integration="github", create_if_missing=True)
                fixer = noclick.Agent.create(
                    "fixer",
                    instructions="You fix failing tests in acme/web, push the fix to a branch and open a pull request.",
                    harness="claude_code",
                    model_connection="claude",
                    timezone="Europe/Berlin",
                    tools=[github.only("create_pull_request")],
                    repos=[github.checkout("acme/web", push=["agent/*"])],
                )

            Keep a coding agent's sandbox in Europe, with everything it works on::

                reviewer = noclick.Agent.create(
                    "reviewer",
                    instructions="You review pull requests for our EU customers' code.",
                    harness="codex",
                    model_connection="openai",
                    region="eu",
                )

            An agent that builds whole sites in one go, with room for more steps a turn::

                builder = noclick.Agent.create(
                    "builder",
                    instructions="You build and ship the sites you're asked for.",
                    tools=["noclick"],
                    turn_limits={"steps": 100},
                )

            An agent that only answers from its tools, with no shell::

                faq = noclick.Agent.create("faq", instructions="You answer from our help center.", tools=["search"], shell=False)

            Keep its shell to the package index it installs from, beside its data::

                analyst = noclick.Agent.create(
                    "analyst",
                    instructions="You answer questions about our orders with pandas, from the data in /data.",
                    volumes={"/data": noclick.Volume.from_name("orders", create_if_missing=True)},
                    network=["pypi.org", "files.pythonhosted.org"],
                )
        """
        scope = resolve_scope(user)
        body = await cls._wire(cls._body(
            name, instructions, model, harness, tools, ttl_s, parent_id, budget_usd_per_month, can_request,
            triggers, browser_profile, card, volumes, secrets, model_connection=model_connection,
            timezone=timezone, repos=repos, network=network, shell=shell, region=region, machine=machine,
            memories=memories, skills=skills, turn_limits=turn_limits, effort=effort, speed=speed,
            permission_mode=permission_mode, setup=setup, tool_rules=tool_rules, docker=docker,
            sandbox_size=sandbox_size, app_testing=app_testing, model_switching=model_switching, user=scope,
            client=client,
        ), scope=scope)
        if approvals is not None:
            body = {**body, "approvals": settings_wire(dict(approvals))}
        raw = await cls._create_named("/v1/agents", body, allow_existing=allow_existing, user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @designed_params(
        "card", "machine",
    )
    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        create_if_missing: bool = False,
        instructions: Optional[str] = None,
        model: Optional[str] = None,
        harness: Optional[str] = None,
        model_connection: Any = UNSET,
        tools: Optional[Sequence[Any]] = None,
        tool_rules: Optional[Mapping[str, str]] = None,
        ttl_s: Optional[int] = None,
        parent_id: Any = None,
        budget_usd_per_month: Any = UNSET,
        can_request: Optional[Sequence[Any]] = None,
        triggers: Optional[Sequence[Any]] = None,
        browser_profile: Any = UNSET,
        card: Any = UNSET,
        volumes: Optional[Mapping[str, Any]] = None,
        secrets: Optional[Sequence[Any]] = None,
        timezone: Any = UNSET,
        repos: Optional[Sequence[Any]] = None,
        network: Union[None, bool, Sequence[str]] = None,
        shell: Optional[bool] = None,
        region: Optional[str] = None,
        machine: Any = None,
        memories: Optional[Sequence[Any]] = None,
        skills: Optional[Sequence[Any]] = None,
        turn_limits: Any = UNSET,
        effort: Any = UNSET,
        speed: Any = UNSET,
        permission_mode: Any = UNSET,
        setup: Optional[Sequence[str]] = None,
        docker: Optional[bool] = None,
        sandbox_size: Optional[str] = None,
        app_testing: Optional[str] = None,
        model_switching: Any = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Agent":
        """A lazy reference to the agent called ``name`` in the current (or given) user:
        inside ``as_user`` only their own, never an account agent of that name (reach that
        outside ``as_user`` and message it for them). Given fields, it's two steps, taken the first time the reference is used: get the
        agent, then set the fields you pass. ``create_if_missing`` only decides what happens when
        there's none: ``True`` creates it with the fields ``Agent.create`` takes (``instructions``
        is required then), else it raises ``noclick.NotFound``. So every run of your code sets
        them: on an existing agent, instructions, model, harness, ``model_connection``, tools,
        ``tool_rules``, ``can_request``, budget, ``timezone``, ``volumes``, ``memories``, ``secrets``, ``repos``,
        ``network``, ``shell``, ``turn_limits``, ``effort`` or ``speed`` that differ are set to yours (the grants its user gave it are kept; a new ``harness`` without a
        ``model`` takes that harness's default model, and its conversations carry on
        on the new harness). So are its ``triggers``: a trigger
        your code no longer lists is removed and a new one added, while one that
        stays keeps its webhook URL; mail and call triggers are never touched. So are its
        ``browser_profile``, and its ``card`` (invite-only beta). A field you leave
        out is never changed, and ``None`` clears ``model_connection``, ``budget_usd_per_month``,
        ``browser_profile``, ``card``, ``timezone``, ``turn_limits``, ``effort`` or ``speed``, as in ``update()``: moving an agent back to ``sdk`` takes
        ``harness="sdk", model_connection=None``. ``region``, ``ttl_s`` and ``parent_id`` are set when
        it's created, for good: an existing agent with another raises ``noclick.Conflict`` naming
        the field and its value.

        Setting fields is a write, every time it runs: do it at startup or in a setup script, and
        take the bare ``Agent.from_name("support")`` in request handlers, or two versions of your
        server would keep overwriting each other's values. To make an agent once and leave it alone
        after, use ``Agent.create(..., allow_existing=True)``.

        Returns:
            An agent that loads (or is created, or has your fields set) the first time it's used.
            Nothing is sent yet.

        Usage:
            Refer to an agent by name without a request::

                support = noclick.Agent.from_name("support")
                print(support.model)   # loads it now; noclick.NotFound if there's none

            Set new instructions on the agent that's there (``noclick.NotFound`` if there's none)::

                support = noclick.Agent.from_name("support", instructions="You answer billing questions too.")
                support.hydrate()

            Or get it, creating it if it's missing, and set its fields. ``instructions`` is
            required then, and a field you leave out is never changed on an agent that already exists::

                with noclick.as_user("user_42"):
                    assistant = noclick.Agent.from_name(
                        "assistant",
                        create_if_missing=True,
                        instructions="You help the user run their day. Ask for access to an account when you need it.",
                        tools=["search"],
                        can_request=["google_calendar", "gmail"],
                    )
                    reply = assistant.message("Put lunch with Bo on my calendar for Friday at noon")

            An automation is an agent with a schedule among its triggers::

                digest = noclick.Agent.from_name(
                    "digest",
                    create_if_missing=True,
                    instructions="You summarize yesterday's support tickets for the team.",
                    tools=["search", "slack.send_message_to_channel"],
                    triggers=[noclick.Cron("0 8 * * 1-5", tz="Europe/London", message="Post the overnight summary in #support")],
                )

            Give its shell a dataset and an API key::

                analyst = noclick.Agent.from_name(
                    "analyst",
                    create_if_missing=True,
                    instructions="You answer questions about our orders. The data is in /data; call the warehouse "
                                 "API with $WAREHOUSE_TOKEN for stock levels.",
                    volumes={"/data": noclick.Volume.from_name("datasets", create_if_missing=True)},
                    secrets=["warehouse"],
                )
        """
        agent = cls._new(hints={"name": name}, client=client, user=user)
        if create_if_missing and not instructions:
            raise ValueError("Agent.from_name(create_if_missing=True) needs instructions=")
        nullable = dict(model_connection=model_connection, budget_usd_per_month=budget_usd_per_month,
                        browser_profile_id=browser_profile, card_id=card, timezone=timezone,
                        turn_limits=turn_limits, effort=effort, speed=speed, permission_mode=permission_mode)
        given = {k: (None if v is UNSET else v) for k, v in nullable.items()}
        agent._define({
            **cls._body(
                name, instructions, model, harness, tools, ttl_s, parent_id, given["budget_usd_per_month"],
                can_request, triggers, given["browser_profile_id"], given["card_id"], volumes, secrets,
                model_connection=given["model_connection"], timezone=given["timezone"], repos=repos,
                network=network, shell=shell, region=region, machine=machine, memories=memories, skills=skills,
                turn_limits=given["turn_limits"], effort=given["effort"], speed=given["speed"],
                permission_mode=given["permission_mode"], setup=setup, tool_rules=tool_rules, docker=docker,
                sandbox_size=sandbox_size, app_testing=app_testing, model_switching=model_switching, user=user,
                client=client,
            ),
            # An explicit None is a field you pass: it clears it on an existing agent.
            **{k: None for k, v in nullable.items() if v is None},
        }, create_if_missing=create_if_missing)
        return agent

    @classmethod
    def from_id(cls, agent_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Agent":
        """A lazy reference to an agent by NoClick id.

        Returns:
            An agent that loads the first time it's used. Nothing is sent yet.

        Usage::

            agent = noclick.Agent.from_id("7b1e4f2a-3c9d-4e8b-a5f6-0d2c8e9b1a47")
            reply = agent.message("Hi")
        """
        return cls._new(hints={"id": agent_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, agent_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Agent":
        """Load an agent by NoClick id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The agent, loaded.

        Usage::

            agent = noclick.Agent.get("7b1e4f2a-3c9d-4e8b-a5f6-0d2c8e9b1a47")
            print(agent.name, agent.model, agent.user_id)
        """
        agent = cls.from_id(agent_id, client=client, user=user)
        await agent._ensure()
        return agent

    @synced
    @classmethod
    async def list(
        cls, *, name: Optional[str] = None, status: Optional[str] = None, active_since: Any = None,
        parent: Any = None, temporary: Optional[bool] = None, harness: Optional[str] = None,
        order: Optional[str] = None, origin: Optional[str] = None, limit: Optional[int] = None,
        user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> List["Agent"]:
        """The agents the current user can message: inside ``as_user`` their own and the
        account's (messaged, not changed; ``user_id`` ``None``), so a ``name`` may match
        one of each; outside it, the account's. ``user_filter`` lists exactly whose agents instead: a ``User`` or your
        id for one (only theirs), ``noclick.NO_USER`` (the account's) or ``noclick.ALL_USERS``.

        After the account's API agents come the ones built in the NoClick app, which are
        the account's too (``origin="api"`` or ``"app"`` lists only one kind). Of the
        filters below, only ``name`` and ``harness`` apply to them; the others leave them out.

        Expired agents are listed for the 30 days they're kept. ``status`` keeps the
        ``working``, ``waiting``, ``idle`` or ``expired`` ones; ``active_since`` (an aware ``datetime``)
        those with a turn since then; ``parent`` (an ``Agent`` or id) its children;
        ``temporary`` those with (or, False, without) a ``ttl_s``; ``harness`` those on one
        harness; and ``order="last_active"`` puts the most recently active first, those that
        never ran last (``"created"``, the default, the newest first). These reads are cheap:
        ``last_active_at`` is a column stamped as turns start and end, and the counts read
        partial indexes.

        Returns:
            Every matching agent, newest first (or most recently active first), fetched page by page.

        Usage:
            The agents the current user can message, then one name across every user::

                for agent in noclick.Agent.list():
                    print(agent.name, agent.user_id)   # user_id is None for an account agent

                assistants = noclick.Agent.list(name="assistant", user_filter=noclick.ALL_USERS)   # every user's, and the account's

            What's busy right now, and what ran in the last hour::

                from datetime import datetime, timedelta, timezone

                for agent in noclick.Agent.list(status="working"):
                    print(agent.name, agent.running_turns, agent.last_active_at)
                hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
                recent = noclick.Agent.list(active_since=hour_ago, order="last_active", temporary=False)

            The agents built in the app, and a message to one::

                for agent in noclick.Agent.list(origin="app"):
                    print(agent.name, agent.workflow_name, agent.enabled, agent.app_url)
                triage = noclick.Agent.list(origin="app", name="Triage")[0]
                print(triage.message("Anything urgent in the queue this morning?").text)
        """
        params = await _list_params(name, status, active_since, parent, temporary, harness, order, origin)
        return await list_all(
            "/v1/agents", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params=params, user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, name: Optional[str] = None,
        status: Optional[str] = None, active_since: Any = None, parent: Any = None,
        temporary: Optional[bool] = None, harness: Optional[str] = None, order: Optional[str] = None,
        origin: Optional[str] = None, user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of agents; pass ``next_cursor`` back as ``cursor``. Takes ``list``'s
        filters and ``order``.

        Returns:
            A page whose ``data`` holds the agents and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Agent.list_page(limit=50)
            while True:
                for agent in page.data:
                    print(agent.name)
                if page.next_cursor is None:
                    break
                page = noclick.Agent.list_page(limit=50, cursor=page.next_cursor)
        """
        params = await _list_params(name, status, active_since, parent, temporary, harness, order, origin)
        return await list_page(
            "/v1/agents", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params=params, user=user, user_filter=user_filter, cursor=cursor, limit=limit,
            client=client,
        )

    @synced
    @classmethod
    async def coding(cls, *, user_filter: Any = None, user: Any = AMBIENT,
                     client: Optional[Client] = None) -> CodingAgents:
        """Every coding agent, and what each is doing. An agent on ``claude_code``, ``codex``, ``opencode``,
        ``hermes`` or ``openclaw`` (an app's own coding agent among them), with its ``state`` (``working``,
        ``waiting`` on a person, ``warm``, ``paused`` and why, ``stopped``), where it runs, on whose model credential,
        its current job, each conversation that's up (``runs``, a sandbox's with what it reserved) and its spend
        since the first of the month; then counts by harness, model, state and place. Read from the turns, containers
        and sandboxes themselves.
        ``user_filter`` narrows it to whose (a ``User`` or your id for one, ``noclick.NO_USER``,
        ``noclick.ALL_USERS``); omitted, every one of the account's for an account's key, a user's own for theirs.

        Returns:
            A ``CodingAgents``.

        Usage::

            coding = noclick.Agent.coding()
            for agent in coding.agents:
                print(agent.name, agent.state, agent.job.title if agent.job else None)
        """
        scope, user_id = await read_scope(user, user_filter)
        return CodingAgents._from(await resolve_client(client).request(
            "GET", "/v1/agents/coding", params=compact(user_id=user_id), user=scope) or {})

    @synced
    @classmethod
    async def states(cls, *, workspace: Any = None, user_filter: Any = None, user: Any = AMBIENT,
                     client: Optional[Client] = None) -> List[AgentStateRow]:
        """Every agent's state, for a list of agents. On any harness: what it's doing, the tool call it runs now, what
        waits on a person and when, read from its turns, asks and held calls. ``workspace`` (a ``Workspace`` or id)
        keeps a workspace's agents.

        Returns:
            An ``AgentStateRow`` per agent.

        Usage::

            for row in noclick.Agent.states():
                print(row.name, row.state, (row.now or {}).get("line"), row.waiting["total"])
        """
        scope, user_id = await read_scope(user, user_filter)
        page = await resolve_client(client).request(
            "GET", "/v1/agents/states", params=compact(user_id=user_id, workspace_id=await ref_id(workspace)),
            user=scope) or {}
        return [AgentStateRow._from(row) for row in page.get("data") or []]

    @synced
    @classmethod
    async def harnesses(cls, *, client: Optional[Client] = None) -> List[HarnessInfo]:
        """What can run an agent. ``sdk`` is NoClick's own agent loop; the coding
        agents each run in a sandbox of their own (``claude_code``, ``codex``,
        ``opencode``, ``hermes``, ``openclaw``). On a CLI harness a reply arrives whole
        rather than streaming, a conversation's first turn starts its sandbox (it stays
        warm about a minute between turns), and the sandbox's uptime is billed.

        Returns:
            Each harness's ``name`` (what ``harness=`` takes) and ``default_model``, whether it
            needs a ``model_connection`` and which model providers' ``integrations`` serve it,
            whether its reply streams (``streaming``) and whether its ``shell`` is built in.
            ``models()`` on one searches the models it offers.

        Usage:
            Pick a harness, then search the models it offers::

                for harness in noclick.Agent.harnesses():
                    print(harness.name, harness.default_model)
                [codex] = [h for h in noclick.Agent.harnesses() if h.name == "codex"]
                print([m.id for m in codex.models(search="gpt-5")])

            Or find which model providers can run Codex, to make its connection::

                [codex] = [h for h in noclick.Agent.harnesses() if h.name == "codex"]
                print(codex.integrations, codex.notes)   # ['openai'] [...]
        """
        page = await resolve_client(client).request("GET", "/v1/harnesses", user=None)
        return [HarnessInfo._from(row, client) for row in page["data"]]

    @synced
    @classmethod
    async def harness_info(cls, name: str, *, client: Optional[Client] = None) -> HarnessInfo:
        """One of ``harnesses()`` by the name ``harness=`` takes; an unknown name raises
        ``noclick.NotFound``, naming the ones there are.

        Returns:
            The harness: its ``default_model``, whether it needs a ``model_connection``, the model
            providers' ``integrations`` that serve it, and ``models()`` to search what it offers.

        Usage::

            opencode = noclick.Agent.harness_info("opencode")
            print(opencode.default_model, [m.id for m in opencode.models(search="claude", limit=5)])
        """
        harnesses = await cls.harnesses.aio(client=client)
        for harness in harnesses:
            if harness.name == name:
                return harness
        raise NotFound(
            f"No harness is named {name!r}.",
            next_step=f"Use one of: {', '.join(h.name for h in harnesses)}.",
            details={"name": name},
        )

    @property
    def paused(self) -> bool:
        """Whether ``pause()`` stopped its triggers (``False`` too for a user reading an account agent)."""
        return bool(self._sync_raw().get("paused"))

    @property
    def helper(self) -> bool:
        """Whether it's one of NoClick's helpers, made for NoClick's own work rather than one of your agents: an app's
        coding agent (which NoClick hands each change to that app's code), or a child one of NoClick's own agents
        spawned."""
        return bool(self._sync_raw().get("helper"))

    @property
    def noclick(self) -> bool:
        """Whether it's a NoClick, your account's own or one of your spaces', rather than one of your agents: NoClick's
        own app shows it as NoClick, never by the name it's found by (a space's is ``noclick-<the space's id>``)."""
        return bool(self._sync_raw().get("noclick"))

    @property
    def former_names(self) -> List[str]:
        """The names it went by before it was renamed, the latest first. Each still reaches it (``agent:<old name>``,
        ``from_name``, an @mention in a channel) and stays reserved for it: no other agent of its scope takes one."""
        return list(self._sync_raw().get("former_names") or [])

    @property
    def job(self) -> Optional[Job]:
        """The task it was spawned with, as a ``Job`` (``wait()`` gives its last reply);
        ``None`` for an agent ``spawn`` didn't start."""
        raw = self._sync_raw()
        if raw.get("job"):
            return Job._new(raw=raw["job"], client=self._client, user=self._call_scope())
        return Job.from_id(raw["job_id"], client=self._client, user=self._call_scope()) if raw.get("job_id") else None

    @property
    def trigger_kinds(self) -> List[str]:
        """Its triggers' kinds (``cron``, ``webhook``, ``event``, ``platform``, ``queue``, ``email``, ``call``):
        a listing tells automations (with ``cron``) apart. Empty for a user reading an account agent."""
        return list(self._sync_raw().get("trigger_kinds") or [])

    @property
    def console_url(self) -> Optional[str]:
        """This agent in the developer console (None off the hosted API)."""
        return self._api.console_url("agents", self.id)

    async def _load(self) -> Dict[str, Any]:
        agent_id = self._known("id")
        if agent_id:
            return await self._request("GET", f"/v1/agents/{agent_id}")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/agents", params={"name": name}) or {}
        # This scope's own agent, never an account agent of the same name the user can also see,
        # and never an expired one: it gave its name up when it expired. One renamed since still goes by it.
        rows = [row for row in page.get("data") or []
                if (row.get("name") == name or name in (row.get("former_names") or []))
                and bool(row.get("user_id")) == bool(self._scope) and row.get("status") != "expired"]
        if rows:
            return await self._converge(rows[0])
        if not self._creates:
            raise NotFound(
                f"No agent is named {name!r}.",
                next_step="Create it with noclick.Agent.create(...) or pass create_if_missing=True.",
                details={"name": name},
            )
        try:
            body = compact(**await self._wire(self._create_with, scope=self._scope))
            return await self._request("POST", "/v1/agents", json=body)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._converge(await self._request("GET", f"/v1/agents/{exc.existing_id}"))

    async def _converge(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Set the fields ``from_name`` was given on an existing agent, after checking the ones it can't set."""
        if self._create_with is None:
            return raw
        wanted = await self._wire(
            {k: v for k, v in self._create_with.items() if k in _CONVERGED or k in _FIXED}, scope=self._scope,
        )
        check_unchanged("agent", raw, {k: wanted.pop(k) for k in _FIXED if k in wanted})
        changes = {k: v for k, v in wanted.items() if _drifted(k, raw.get(k), v)}
        if changes:
            raw = await self._request("PATCH", f"/v1/agents/{raw['id']}", json=changes)
        if "triggers" in self._create_with and await self._converge_triggers(raw["id"], self._create_with["triggers"]):
            raw = await self._request("GET", f"/v1/agents/{raw['id']}")
        return raw

    async def _converge_triggers(self, agent_id: str, definitions: Sequence[Any]) -> bool:
        """Add the triggers your code lists and the agent lacks, remove the defined ones it no longer
        lists; mail and call triggers are left alone. Whether anything changed."""
        wanted = {spec_key(w): w for w in [await trigger_wire(t) for t in definitions]}
        response = await self._request("GET", f"/v1/agents/{agent_id}/triggers") or {}
        have = {
            spec_key({"kind": row["kind"], **(row.get("spec") or {})}): row
            for row in response.get("data") or [] if row.get("kind") in DEFINED_KINDS
        }
        for key, row in have.items():
            if key not in wanted:
                await self._request("DELETE", f"/v1/agents/{agent_id}/triggers/{row['id']}")
        for key, body in wanted.items():
            if key not in have:
                await self._request("POST", f"/v1/agents/{agent_id}/triggers", json=body)
        return set(wanted) != set(have)

    # --- conversation ----------------------------------------------------

    def _talk_scope(self, user: Any) -> Any:
        owner = self._owner_scope((self._raw or {}).get("user_id"))
        return owner if owner else resolve_scope(user)

    @synced
    async def upload(
        self, file: Any, *, name: Optional[str] = None, mime_type: Optional[str] = None, voice: bool = False,
        peaks: Optional[Sequence[float]] = None,
    ) -> Attachment:
        """Store a file to send this agent with a message: a path, bytes or a binary file object. It's kept as an account file, capped as those are: 10 MB an image (JPEG,
        PNG, WebP or GIF), 15 MB a document, 20 MB audio or video. ``voice=True``
        marks a recorded clip (audio), which may carry its waveform ``peaks``.
        ``message(files=[...])`` uploads paths for you; upload first to send bytes
        or a file object you name, or a voice clip.

        Returns:
            The attachment; send it with ``message(files=[...])``. An upload is sent once; sent, it's one of
            the account's files (``noclick.attachments()``), which the account sends again.

        Usage::

            support = noclick.Agent.from_name("support")
            clip = support.upload(recording, name="question.webm", voice=True)
            reply = support.message("Here's my question.", files=[clip])
        """
        raw = await self._ensure()
        return await upload(self._request, f"/v1/agents/{raw['id']}/attachments", file, name=name,
                            mime_type=mime_type, voice=voice, peaks=peaks)

    @synced
    async def send(self, text: Optional[str] = None, *, conversation: Optional[str] = None, files: Sequence[Any] = (),
                   user: Any = AMBIENT, command: Optional[Mapping[str, str]] = None,
                   delivery: Optional[str] = None) -> Operation:
        """Start a turn without waiting; ``.wait()`` returns the ``AgentReply``.
        ``files`` go with the message, as ``message`` sends them.

        Args:
            command: One of the conversation's harness's own commands, ``{"name": ..., "arguments": ...}``, run in
                place of ``text`` as that command (``commands`` lists them), never parsed from text.
            delivery: For a message sent while the agent works on a turn (it takes one at a time): ``"steer"`` puts
                it into that turn when it's in the same conversation (else it's an ordinary message), ``"queue"`` (or
                omitted) runs it as the agent's next turn. A command is never steered.

        Returns:
            The turn's operation, started. Keep its ``id`` to pick the reply up later, from anywhere.

        Usage::

            support = noclick.Agent.from_name("support")
            turn = support.send("Summarize this customer's open tickets")
            print(turn.id)                                      # save it; then, later, anywhere:
            reply = noclick.Operation.from_id(turn.id).wait()   # an AgentReply
            print(reply.text)

            coder = noclick.Agent.from_name("coder")
            coder.send(conversation="main", command={"name": "compact"})
            coder.send("also update the README", conversation="main", delivery="steer")
        """
        raw = await self._ensure()
        scope = self._talk_scope(user)
        payload = await self._request(
            "POST", f"/v1/agents/{raw['id']}/messages",
            json=await self._message_body(text, conversation, files, command=command, delivery=delivery), user=scope,
        )
        return Operation._from_payload(payload, client=self._client, user=scope, kind="agent.message")

    async def _message_body(self, text: Optional[str], conversation: Optional[str], files: Sequence[Any], *,
                            command: Optional[Mapping[str, str]] = None,
                            delivery: Optional[str] = None) -> Dict[str, Any]:
        if (text is None) == (command is None):
            raise TypeError("Send text or a command, not both.")
        attachments = await attachment_ids(files, self.upload.aio)
        wired = compact(name=command.get("name"), arguments=command.get("arguments")) if command else None
        return compact(text=text, command=wired, delivery=delivery, conversation=conversation,
                       attachments=attachments or None)

    @synced
    async def commands(self, conversation: str, *, user: Any = AMBIENT) -> AgentCommands:
        """What the conversation's harness offers a person to run. Send one with ``send(command=...)``.

        Returns:
            Its commands and skills as the harness itself last listed them, what NoClick can and can't run there
            (``capabilities``, ``not_supported``), and how fresh the list is (``as_of``, ``read_from``).

        Usage::

            coder = noclick.Agent.from_name("coder")
            for command in coder.commands("main").commands:
                print(f"/{command.name} {command.argument_hint}", command.description)
        """
        raw = await self._ensure()
        response = await self._request(
            "GET", f"/v1/agents/{raw['id']}/conversations/{quote(conversation, safe='')}/commands",
            user=self._talk_scope(user),
        ) or {}
        return AgentCommands._from(response)

    def _conversation_path(self, raw: Dict[str, Any], conversation: str) -> str:
        return f"/v1/agents/{raw['id']}/conversations/{quote(conversation, safe='')}"

    @synced
    async def set_permission_mode(self, conversation: str, mode: str, *, user: Any = AMBIENT) -> ConversationSettings:
        """Set how far the conversation's coding harness goes before asking a person. ``approval-required`` asks
        before commands and edits, ``auto-accept-edits`` runs edits and asks about commands, ``auto`` has its own
        review approve routine work, and ``full-access`` (the default) asks nothing. Questions reach a person in every
        mode. Its next message runs in it.

        Returns:
            The conversation's settings: the mode set, the mode its harness runs (``effective_permission_mode``), the
            modes it enforces and what it can't do.

        Usage::

            coder = noclick.Agent.from_name("coder")
            coder.set_permission_mode("main", "approval-required")
        """
        raw = await self._ensure()
        response = await self._request("PATCH", self._conversation_path(raw, conversation),
                                       json={"permission_mode": mode}, user=self._talk_scope(user)) or {}
        return ConversationSettings._from(response)

    @synced
    async def requests(self, conversation: str, *, status: Optional[str] = None,
                       user: Any = AMBIENT) -> List[HarnessRequest]:
        """What the conversation's coding harness asked a person, newest first. ``status`` keeps ``pending``,
        ``answered``, ``expired`` or ``canceled`` ones.

        Returns:
            Each ``HarnessRequest``: an approval (what it would do) or a question, and where it stands.

        Usage::

            for asked in coder.requests("main", status="pending"):
                print(asked.title or asked.questions)
        """
        raw = await self._ensure()
        response = await self._request("GET", f"{self._conversation_path(raw, conversation)}/requests",
                                       params=compact(status=status), user=self._talk_scope(user)) or {}
        return [HarnessRequest._from(r) for r in response.get("data") or []]

    @synced
    async def answer(self, conversation: str, request_id: str, decision: str, *, note: Optional[str] = None,
                     answers: Optional[Mapping[str, Any]] = None, user: Any = AMBIENT) -> HarnessRequest:
        """Answer what the conversation's coding harness asks. The ``decision`` is ``allow_once``, ``allow_always``
        (for the rest of the session, where the harness can), ``reject_once`` (with a ``note`` the agent reads; a
        question: skip it) or ``cancel`` (the turn stops). A question is answered with ``answers`` ({question: [labels] or your own
        words}) and ``allow_once``. A person's answer: never through an MCP connection.

        Returns:
            The request as it stands now (``answered``; a ``cancel`` stops the turn, which ends it ``canceled``).

        Usage::

            [asked] = coder.requests("main", status="pending")
            coder.answer("main", asked.id, "reject_once", note="Push to a branch, not main.")
        """
        raw = await self._ensure()
        response = await self._request(
            "POST", f"{self._conversation_path(raw, conversation)}/requests/{quote(request_id, safe='')}",
            json=compact(decision=decision, note=note, answers=dict(answers) if answers else None),
            user=self._talk_scope(user)) or {}
        return HarnessRequest._from(response)

    @synced
    async def message(
        self,
        text: str,
        *,
        conversation: Optional[str] = None,
        files: Sequence[Any] = (),
        timeout: Optional[float] = None,
        user: Any = AMBIENT,
    ) -> AgentReply:
        """Send ``text`` and wait for the reply. Without ``conversation`` it goes to the
        agent's session, the one conversation everyone talking to it shares (``session()``);
        pass the reply's ``conversation`` back to stay in that thread. A channel's conversation
        (``channel:<its id>``) raises ``noclick.InvalidRequest``: only the channel starts
        turns there, so post in the channel instead. ``files`` (at most 100) are
        paths, which are uploaded first, attachments from ``upload``, or (for the
        account) its files from ``noclick.attachments()``: the turn reads them as
        the agent's media digest does, a document's text, a voice clip's
        transcript, an image as an image.

        Returns:
            The reply: its ``text``, the ``conversation`` it belongs to and the ``tool_calls`` the turn made.

        Usage:
            Ask, then keep talking in the same thread by passing its conversation back::

                support = noclick.Agent.from_name("support")
                reply = support.message("Why was I charged twice in March?")
                print(reply.text)
                follow_up = support.message("Can you refund one of them?", conversation=reply.conversation)

            Or name the thread yourself, with your own ticket id, say (1 to 128 letters,
            digits and ``. _ : @ + -``)::

                support = noclick.Agent.from_name("support")
                reply = support.message("Where's my refund?", conversation="ticket-1841")

            A shared account agent talks to each of your users in threads of their own::

                support = noclick.Agent.from_name("support")
                reply = support.message("Where's my invoice?", user="user_42")

            With files::

                analyst = noclick.Agent.from_name("analyst")
                reply = analyst.message("What stands out this quarter?", files=["q3-report.pdf", "chart.png"])
        """
        operation = await self.send.aio(text, conversation=conversation, files=files, user=user)
        return await operation.wait.aio(timeout=timeout)

    @synced
    async def history(
        self, conversation: str, *, limit: Optional[int] = None, before: Optional[str] = None, user: Any = AMBIENT,
        user_filter: Any = None,
    ) -> List[Message]:
        """The messages of one conversation, oldest first. Every one, or the ``limit`` newest (1-200), just
        before ``before`` (a ``next_cursor`` of ``history_page``).

        Returns:
            Its messages, each with its ``role``, ``text``, ``created_at``, the ``files`` it carried, how it
            arrived (``via``, for a text, a call or an email) and, a reply, the ``tool_calls`` its turn made; a
            ``note`` has its ``data``.

        Usage:
            Read a whole thread::

                support = noclick.Agent.from_name("support")
                for message in support.history("ticket-1841"):
                    print(message.role, message.via or "api", message.text)

            Or only its last few messages::

                support = noclick.Agent.from_name("support")
                latest = support.history("ticket-1841", limit=20)
        """
        return (await self.history_page.aio(conversation, limit=limit, before=before, user=user,
                                            user_filter=user_filter)).data

    @synced
    async def history_page(
        self, conversation: str, *, limit: Optional[int] = None, before: Optional[str] = None, user: Any = AMBIENT,
        user_filter: Any = None,
    ) -> HistoryPage:
        """A page of ``history``, to read a long thread back. The ``limit`` newest messages
        (1-200), just before ``before``, oldest first. ``user_filter`` reads whose thread it is as the account
        (a user's, or ``noclick.NO_USER`` for the account's own) instead of acting as the user; a suspended user's
        thread reads this way too.

        Returns:
            A page whose ``data`` holds the messages and whose ``next_cursor``, while older ones remain, is the
            ``before`` of the page before it (None once it reaches the first message), with the agent's ``session``.

        Usage:
            Read a thread back, 50 messages at a time::

                support = noclick.Agent.from_name("support")
                page = support.history_page("ticket-1841", limit=50)
                while True:
                    for message in reversed(page.data):
                        print(message.role, message.text)
                    if page.next_cursor is None:
                        break
                    page = support.history_page("ticket-1841", limit=50, before=page.next_cursor)
        """
        scope, named = await self._conversation_scope(user, user_filter)
        response = await self._request(
            "GET", f"{await self._conversations_path()}/{quote(conversation, safe='')}",
            params={"limit": limit, "before": before, **named}, user=scope,
        ) or {}
        return HistoryPage([Message._from(m) for m in response.get("messages") or []], response.get("next_cursor"),
                           response.get("session"))

    async def _conversations_path(self) -> str:
        """Its conversations' path. One named by a ref (``Agent.from_id("agent:coordinator")``) reads them without
        loading the agent first, a round trip less."""
        named = None if self._raw is not None else self._known("id")
        if isinstance(named, str) and named.startswith("agent:"):
            return f"/v1/agents/{quote(named, safe='')}/conversations"
        return f"/v1/agents/{(await self._ensure())['id']}/conversations"

    async def _conversation_scope(self, user: Any, user_filter: Any) -> Tuple[Any, Dict[str, Any]]:
        """What a read of a conversation carries: as its user, or as the account naming whose (``user_filter``)."""
        if user_filter is None:
            return self._talk_scope(user), {}
        scope, user_id = await read_scope(user, user_filter)
        return scope, {"user_id": user_id}

    @synced
    async def activity(
        self, conversation: str, *, limit: Optional[int] = None, user: Any = AMBIENT, user_filter: Any = None,
    ) -> List[AgentActivity]:
        """The turns a trigger's event or a wake-up started in one conversation, newest first (the ``limit`` latest,
        50 by default, at most 200): the chat each happened in and who it's with, what came in (a voice note with its
        transcript, a file, what it quoted) and what the agent did, in order. A running turn's ``did`` fills as its
        calls complete. A turn a message from your code started isn't one. ``user_filter`` reads a user's as the
        account.

        Returns:
            Each turn as an ``AgentActivity``.

        Usage::

            support = noclick.Agent.from_name("support")
            for item in support.activity("whatsapp:+14155550101", limit=20):
                print(item.chat.name, item.inbound.text if item.inbound else None, [d.kind for d in item.did])
        """
        scope, named = await self._conversation_scope(user, user_filter)
        response = await self._request(
            "GET", f"{await self._conversations_path()}/{quote(conversation, safe='')}/activity",
            params={"limit": limit, **named}, user=scope,
        ) or {}
        return [AgentActivity._from(row) for row in response.get("data") or []]

    @synced
    async def note(self, conversation: str, text: str, *, data: Optional[Dict[str, Any]] = None,
                   key: Optional[str] = None, user: Any = AMBIENT) -> bool:
        """Add a line to a conversation without starting a turn. It shows in
        ``history`` and ``watch`` as a ``note`` with its ``data``, and the agent
        reads both when its next turn starts, once.

        Args:
            conversation: The current user's conversation (the account's, outside ``as_user``).
            text: The line, 1-4,000 characters.
            data: JSON your app reads back with it (at most 4,096 bytes).
            key: Adds it once: a second note with the same key adds nothing.

        Returns:
            ``True`` when it was added, ``False`` when a note with ``key`` already was.

        Usage::

            support = noclick.Agent.from_name("support")
            support.note("ticket-1841", "Ada upgraded to the Pro plan.", data={"plan": "pro"}, key="plan:pro")
        """
        raw = await self._ensure()
        response = await self._request(
            "POST", f"/v1/agents/{raw['id']}/conversations/{quote(conversation, safe='')}/notes",
            json=compact(text=text, data=data, key=key), user=self._talk_scope(user),
        ) or {}
        return bool(response.get("added"))

    @synced
    async def withdraw_question(self, conversation: str, note: str, *, question_id: Optional[str] = None) -> List[str]:
        """Withdraw the question the agent asked your account's owner once it no longer needs them. It was
        answered or handled another way, in one of the account's conversations. Its page
        and card then refuse a late answer, the turn that asked ends, and the agent reads ``note`` (1-4,000
        characters: who answered, what was already sent) at its next turn there. ``question_id``
        names the question (its ``HumanRequest.request_id``, as ``noclick.HumanRequest.list`` lists
        it) when more than one waits there; the others keep waiting. It acts as the account, which
        alone withdraws one, never a user. With none waiting, or several and none named, it raises
        ``noclick.Conflict``.

        Returns:
            The text of each question withdrawn.

        Usage:
            The owner answered by phone, so the agent's question waits no longer::

                support = noclick.Agent.from_name("support")
                support.withdraw_question("ticket-1841", "Ana approved the refund on the phone; it's issued.")
        """
        raw = await self._ensure()
        response = await self._request(
            "POST", f"/v1/agents/{raw['id']}/conversations/{quote(conversation, safe='')}/withdraw_question",
            json=compact(note=note, question_id=question_id), user=None,
        ) or {}
        return list(response.get("withdrawn") or [])

    async def _conversation_call(self, user: Any, user_filter: Any,
                                 archived: Optional[bool] = None) -> Tuple[Dict[str, Any], str]:
        path = await self._conversations_path()
        return {
            "user": self._talk_scope(user) if user_filter is None else user,
            "user_filter": user_filter, "client": self._client,
            **({"params": {"archived": "true" if archived else "false"}} if archived is not None else {}),
        }, path

    def conversation(self, name: str, *, user: Any = AMBIENT) -> AgentConversation:
        """One of its conversations, as a chat reads and changes it. Its settings, a fork, a revert, its context and
        usage, a command, resuming it as the agent's session; sends nothing yet.

        Returns:
            An ``AgentConversation``.

        Usage::

            chat = noclick.Agent.from_name("coder").conversation("main")
            chat.update(effort="high")
        """
        return AgentConversation._of(self, name, resolve_scope(user))

    @synced
    async def start_conversation(self, *, conversation: Optional[str] = None, title: Optional[str] = None,
                                 user: Any = AMBIENT) -> Conversation:
        """Start a new session (a chat's ``/new`` or ``/clear``), as ``clear`` does, with ``conversation`` naming its
        key (one that already has messages raises ``noclick.Conflict``); omitted, NoClick makes one. Everyone talking
        to the agent shares it from now on, and the one it leaves is kept, listed and can be resumed. Raises
        ``noclick.Conflict`` while the agent is working on a turn.

        Returns:
            The new ``Conversation``, ``active``.

        Usage::

            coder = noclick.Agent.from_name("coder")
            fresh = coder.start_conversation(conversation="retries", title="Retries")
            coder.message("Look at the retry worker")   # goes to the new session
        """
        raw = await self._ensure()
        return Conversation._from(await self._request(
            "POST", f"/v1/agents/{raw['id']}/conversations", json=compact(conversation=conversation, title=title),
            user=self._talk_scope(user)) or {})

    @synced
    async def clear(self, *, title: Optional[str] = None, user: Any = AMBIENT) -> Conversation:
        """Start a new session, like ``/clear`` in a terminal: everyone talking to the agent shares it from now on.
        The one it leaves is kept, listed and can be resumed (``conversation(name).resume()``), and the agent's files
        stay as they are. Raises ``noclick.Conflict`` while the agent is working on a turn.

        Returns:
            The new ``Conversation``, ``active``.

        Usage::

            coder = noclick.Agent.from_name("coder")
            before = coder.session()
            coder.clear()
            coder.message("Start on the billing page")   # the new session
            coder.conversation(before.conversation).resume()
        """
        return await self.start_conversation.aio(title=title, user=user)

    @synced
    async def session(self, *, user: Any = AMBIENT) -> Optional[Conversation]:
        """The agent's session: the one conversation everyone talking to it shares, where a message without a
        ``conversation`` goes (the current user's, or the account's outside ``as_user``).

        Returns:
            Its ``Conversation`` (``active``), or ``None`` before the agent has one.

        Usage::

            support = noclick.Agent.from_name("support")
            current = support.session()
            for message in support.history(current.conversation, limit=20):
                print(message.role, message.text)
        """
        cursor = None
        while True:
            page = await self.conversations_page.aio(cursor=cursor, user=user)
            found = next((c for c in page.data if c.active), None)
            if found or page.next_cursor is None:
                return found
            cursor = page.next_cursor

    @synced
    async def conversations(
        self, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        archived: Optional[bool] = None,
    ) -> List[Conversation]:
        """Its conversations, most recent first. The current user's, or those ``user_filter`` covers; ``archived``
        keeps the archived ones (``True``) or the others (``False``).
        ``user_filter`` reads across users without the user header, which only the signed-in owner
        may do on a user's own agent; with a secret key, read such an agent's threads without it.

        Returns:
            Every matching conversation (or the first ``limit``), fetched page by page. ``cost_usd``
            is ``None`` for a thread with no recorded turns.

        Usage:
            Read the current user's threads (the account's, outside ``as_user``)::

                support = noclick.Agent.from_name("support")
                for convo in support.conversations(limit=10):
                    print(convo.conversation, convo.title, convo.turns, convo.cost_usd)

            Or every user's threads with a shared agent, each naming its ``user_id``
            (``None`` for the account's), and read one::

                support = noclick.Agent.from_name("support")
                for convo in support.conversations(user_filter=noclick.ALL_USERS, limit=20):
                    messages = support.history(convo.conversation, user=convo.user_id)
        """
        call, path = await self._conversation_call(user, user_filter, archived)
        return await list_all(path, Conversation._from, limit=limit, **call)

    @synced
    async def conversations_page(
        self, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT,
    ) -> Page:
        """One page of its conversations; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the conversations and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            support = noclick.Agent.from_name("support")
            page = support.conversations_page(limit=50)
            while True:
                for convo in page.data:
                    print(convo.conversation, convo.last_activity)
                if page.next_cursor is None:
                    break
                page = support.conversations_page(limit=50, cursor=page.next_cursor)
        """
        call, path = await self._conversation_call(user, user_filter)
        return await list_page(path, Conversation._from, cursor=cursor, limit=limit, **call)

    @synced
    async def hand_back(self, conversation: str, *, user: Any = AMBIENT) -> None:
        """Give a conversation back to the agent after it handed it to a person (its
        ``hand_off`` tool). The person's replies stay in its history, and the agent answers
        again from the next message. The person can hand it back from their page too.

        Usage::

            support = noclick.Agent.from_name("support")
            for convo in support.conversations(user_filter=noclick.ALL_USERS):
                if convo.status == "handed_off":
                    support.hand_back(convo.conversation, user=convo.user_id)
        """
        raw = await self._ensure()
        await self._request(
            "POST", f"/v1/agents/{raw['id']}/conversations/{quote(conversation, safe='')}/hand_back",
            user=self._talk_scope(user),
        )

    # --- take-over ---------------------------------------------------------

    @synced
    async def take_over(self, conversation: str, *, interrupt: bool = False, cols: Optional[int] = None,
                        rows: Optional[int] = None, user: Any = AMBIENT) -> Terminal:
        """Take over a coding agent's conversation. Its harness's own terminal (Claude Code, Codex, OpenCode, Hermes
        Agent or OpenClaw) on the session the agent works in, for the account's owner. The turn in flight finishes
        first unless ``interrupt`` stops it (its delivery fails, saying the owner took over); messages wait until it's
        handed back. Needs the account's secret key with the ``agents:terminal`` scope: a terminal shows the sandbox's
        keys and tokens. Asked again while it's taken over, it returns a new token (a reload, a second tab). Raises
        ``noclick.Conflict`` when nothing of the conversation is running (send it a message first).

        Args:
            conversation: The current user's conversation (the account's, outside ``as_user``).
            interrupt: Stop its turn in flight now instead of letting it finish.
            cols: The terminal's width in columns.
            rows: The terminal's height in rows.

        Returns:
            A ``Terminal``: its ``url`` and ``token`` open it (see ``noclick.terminal``).

        Usage::

            coder = noclick.Agent.from_name("coder")
            terminal = coder.take_over("main", cols=120, rows=36)
            send_to_browser(terminal.url, terminal.token)
        """
        raw = await self._ensure()
        scope = self._talk_scope(user)
        response = await self._request(
            "POST", f"/v1/agents/{raw['id']}/conversations/{quote(conversation, safe='')}/terminal",
            json=compact(interrupt=interrupt or None, cols=cols, rows=rows), user=scope,
        )
        return Terminal._of(response, client=self._client, user=scope)

    @synced
    async def terminal(self, conversation: str, *, user: Any = AMBIENT) -> Terminal:
        """Where a coding agent's conversation's terminal stands (``Terminal.state``), with no token. Open it with
        ``take_over``, give it back with ``Terminal.hand_back``.

        Returns:
            A ``Terminal`` with its ``state``, and no ``url`` or ``token``.

        Usage::

            coder = noclick.Agent.from_name("coder")
            if coder.terminal("main").state == "person":
                coder.terminal("main").hand_back()
        """
        raw = await self._ensure()
        scope = self._talk_scope(user)
        response = await self._request(
            "GET", f"/v1/agents/{raw['id']}/conversations/{quote(conversation, safe='')}/terminal", user=scope,
        )
        return Terminal._of(response, client=self._client, user=scope)

    # --- children and A2A ------------------------------------------------

    @synced
    async def spawn(
        self,
        task: str,
        *,
        updates: Optional[Sequence[Any]] = None,
        conversation: Optional[str] = None,
        instructions: Optional[str] = None,
        tools: Optional[Sequence[Any]] = None,
        budget_usd: Optional[float] = None,
        ttl_s: Optional[int] = None,
        model: Optional[str] = None,
        harness: Optional[str] = None,
        model_connection: Any = None,
        name: Optional[str] = None,
        workstream: Optional[str] = None,
        approvals: Optional[Mapping[str, Any]] = None,
        user: Any = AMBIENT,
    ) -> "Agent":
        """Make a child agent and start ``task`` (its first message, up to 16,000
        characters) at once. ``child.job`` is that task: a ``Job`` that runs while the
        child works on it, across as many turns as it takes, and finishes when the child
        stops with nothing left to continue it.

        The child lives where its parent does and runs on the parent's harness, model and
        model connection unless ``harness``, ``model`` or ``model_connection`` say otherwise.
        It gets only tools its parent has: ``tools`` names some of them (a narrower
        ``only(...)`` of one of the parent's connections is fine, and ``"card"`` gives it the
        card its parent pays with; anything the parent lacks raises ``noclick.InvalidRequest``),
        and without ``tools`` it has none of them (nor its parent's ``can_request``). Like every agent it has its shell (none when its parent
        has ``shell=False``) and ``wake_me``, and as a spawned child ``tell_parent``, to reach its
        parent whenever its instructions say to. A person among the parent's tools passes down
        only with the tools the parent has of them, and a bound operation only as bound or
        narrower. ``instructions`` are its
        standing instructions: what its updates should say and when to reach out on its
        own; NoClick adds a short brief saying it works on one task for its parent.
        ``budget_usd`` is held out of what the parent's monthly budget has left (without
        one, the child draws on the parent's as it spends), and ``ttl_s`` makes it
        temporary. ``name`` defaults to ``<parent>-<random>``. ``workstream`` is the line of
        work the task belongs to (``noclick.Workstream``): one of yours, matched whatever its
        case, or a new name, which makes one; every charge of the job, and of what it starts,
        is counted under it.

        ``updates`` is only when NoClick makes it report: ``"done"`` (always on: the job
        finished, any outcome), ``"blocked"`` (it started waiting on a person),
        ``noclick.Before(*tools)`` (before a matching tool call runs) and
        ``noclick.Every(interval)`` (at least that often while it works). Each update is a
        wake-up for the parent in ``conversation``, the parent's conversation it belongs to
        (``user=`` says whose, as for ``message``: your key acting for a user spawns from an
        account agent in that user's thread, and the child is the account's; a user's own
        session can't); updates that come while the parent is mid-turn arrive together in its
        next turn. Without ``conversation``, updates wake nobody and wait on the job
        (``job.updates()``, and your webhooks' ``agent.job.update`` event).
        A coordinator spawns the same way with its ``agents`` tools, its children's updates
        waking it in the conversation it spawned from. An agent holds up to 20 live
        children, and children spawn children up to 3 levels below an agent with no parent
        (``noclick.QuotaExceeded``). ``Agent.create(..., parent_id=)`` still makes a child
        without starting anything. The child follows its parent's ``approvals``; its own (as ``create`` takes them)
        only tighten them, and one looser than its parent's raises ``noclick.InvalidRequest``.

        Returns:
            The child, loaded, with ``parent_id`` set to this agent and ``job`` its running task.

        Usage:
            Hand a coordinator's research to a helper and hear back in the launch conversation::

                planner = noclick.Agent.from_name("planner")
                researcher = planner.spawn(
                    "Find three recent launches in our category and summarize what worked.",
                    instructions="Report each launch as you finish it with tell_parent. Cite your sources.",
                    tools=["search", "fetch"],
                    updates=["blocked", noclick.Every(900)],
                    conversation="launch-plan",
                    budget_usd=0.50,
                    ttl_s=3600,
                    workstream="Q3 launch",
                )
                print(researcher.job.status)   # running

            From your own code, wait for the task the way you'd wait for a message::

                planner = noclick.Agent.from_name("planner")
                reviewer = planner.spawn("Review the draft in /workspace/launch.md and list what's missing.")
                reply = reviewer.job.wait(timeout=600)
                print(reply.text)

            Hear before money moves (the call still runs; a policy rule is what holds one)::

                support = noclick.Agent.from_name("support")
                refunder = support.spawn(
                    "Refund order 1841 if it's within 30 days, then tell the customer.",
                    tools=["stripe.create_refund", "gmail.send_email_message"],
                    updates=[noclick.Before("stripe.create_refund")],
                    conversation="ticket-1841",
                    user="user_42",
                )
        """
        wired_updates = updates_wire(updates)
        raw = await self._ensure()
        owner = self._owner_scope(raw.get("user_id"))
        body = compact(
            task=task, updates=wired_updates, conversation=conversation, instructions=instructions,
            tools=await tool_refs(tools, scope=owner), budget_usd_per_month=budget_usd, ttl_s=ttl_s,
            model=model, harness=harness, model_connection=await model_connection_ref(model_connection, scope=owner),
            name=name, workstream=workstream,
            approvals=settings_wire(dict(approvals)) if approvals is not None else None,
        )
        response = await self._request(
            "POST", f"/v1/agents/{raw['id']}/children", json=body, user=self._talk_scope(user),
        )
        return Agent._new(raw=response, client=self._client, user=owner)

    @synced
    async def children(self, *, status: Optional[str] = None, limit: Optional[int] = None) -> List["Agent"]:
        """Its children, any status (an expired one for its 30 days), newest first:
        ``Agent.list(parent=self)``, read where this agent lives.

        Returns:
            Each child with its ``status``, ``last_active_at``, ``running_turns`` and, if ``spawn``
            made it, the ``job`` it was started with.

        Usage::

            planner = noclick.Agent.from_name("planner")
            for child in planner.children(status="working"):
                print(child.name, child.running_turns, child.last_active_at)
        """
        raw = await self._ensure()
        return await Agent.list.aio(
            parent=raw["id"], status=status, limit=limit, user=self._owner_scope(raw.get("user_id")),
            client=self._client,
        )

    @synced
    async def jobs(
        self,
        *,
        status: Union[None, str, Sequence[str]] = None,
        kind: Union[None, str, Sequence[str]] = None,
        agent: Any = None,
        conversation: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Job]:
        """The jobs it started: the tasks of the children it spawned (``kind="task"``) and
        the messages it sent with its ``agents`` tools (``kind="message"``, whose only update
        is ``done``). ``status`` takes operation statuses, or ``"live"`` for
        every unfinished one; ``agent`` (an ``Agent`` or id) keeps the ones one agent does;
        ``conversation`` the ones started from one of its conversations. Read where this agent
        lives: an account agent's are every user's.

        Returns:
            Every matching job (or the first ``limit``), newest first, each with its ``status``, ``step`` and
            ``latest_update``; ``wait()`` on one gives its reply.

        Usage::

            coordinator = noclick.Agent.from_name("coordinator")
            for job in coordinator.jobs(status="live"):
                update = job.latest_update
                print(job.agent_id, job.status, job.step, update.text if update else "")
        """
        raw = await self._ensure()
        owner = self._owner_scope(raw.get("user_id"))
        params = {"status": csv(status), "kind": job_kinds(kind), "agent_id": await agent_id(agent),
                  "conversation": conversation}
        rows = await paginate(self._api, f"/v1/agents/{raw['id']}/jobs", params=params, user=owner, limit=limit)
        return [Job._new(raw=row, client=self._client, user=owner) for row in rows]

    @synced
    async def ask(
        self,
        question: str,
        *,
        conversation: Optional[str] = None,
        interject: bool = False,
        timeout: Optional[float] = None,
        user: Any = AMBIENT,
    ) -> AgentReply:
        """Ask it something without stopping it. By default its model answers from a
        snapshot of ``conversation`` as it stands: its instructions, the conversation, and
        what a running turn has done so far, with no tools. The question and answer aren't
        added to the conversation and the agent never sees them; a running turn carries on
        untouched. The ask is recorded in its activity as an ``agent.ask`` operation and
        billed like a short turn. On a coding harness the snapshot is what NoClick holds:
        the conversation up to its last finished turn, plus what the running turn has done
        so far: its NoClick tool calls and its own commands (with their output), edits and
        reads, as its sandbox reported them; its model answers on its connection's key. An agent that
        thinks with a Claude or ChatGPT plan raises ``noclick.NotAvailable``: a plan runs
        only in its harness, and answering in a one-off harness session is in invite-only
        beta (``interject=True`` works).

        ``interject=True`` puts the question into the running turn instead (the harness's
        own steering on a coding harness; before its next model call on ``sdk``): the
        agent sees it, may change course, and answers in that turn, which stays in the
        conversation. With no turn running, it's an ordinary message. ``conversation``
        defaults to its session. Asked from another agent's turn, it's an ordinary
        message: a job of the asker's whose reply wakes it.

        Returns:
            The answer as an ``AgentReply``; with ``interject``, the reply the turn it joined ended with.

        Usage:
            Check on a child without interrupting it::

                planner = noclick.Agent.from_name("planner")
                for child in planner.children(status="working"):
                    print(child.name, child.ask("In one line: where are you, and what's left?").text)

            Steer a coding agent mid-task::

                fixer = noclick.Agent.from_name("fixer")
                reply = fixer.ask("Skip the flaky e2e suite; the unit tests are enough.", conversation="issue-1841",
                                  interject=True)
        """
        raw = await self._ensure()
        scope = self._talk_scope(user)
        payload = await self._request(
            "POST", f"/v1/agents/{raw['id']}/ask",
            json=compact(question=question, conversation=conversation, interject=True if interject else None),
            user=scope,
        )
        operation = Operation._from_payload(payload, client=self._client, user=scope, kind="agent.ask")
        return await operation.wait.aio(timeout=timeout)

    @synced
    async def a2a_card(self) -> Dict[str, Any]:
        """The agent's A2A agent card (the JSON other agents discover it by).

        Returns:
            The card as a dict: the agent's ``name``, its JSON-RPC ``url`` and the ``skills`` it offers.

        Usage::

            planner = noclick.Agent.from_name("planner")
            card = planner.a2a_card()
            print(card["url"], [skill["name"] for skill in card["skills"]])
        """
        raw = await self._ensure()
        return await self._request("GET", f"/v1/agents/{raw['id']}/a2a/card")

    @property
    def a2a_url(self) -> str:
        """The A2A JSON-RPC endpoint (``message/send``, ``tasks/get``); callers
        authenticate with a platform key as a bearer token."""
        raw = self._sync_raw()
        return raw.get("a2a_url") or f"{self._api.base_url}/v1/agents/{raw['id']}/a2a"

    # --- management ------------------------------------------------------

    @designed_params("card", "machine")
    @synced
    async def update(
        self,
        *,
        instructions: Any = UNSET,
        model: Any = UNSET,
        tools: Any = UNSET,
        tool_rules: Any = UNSET,
        name: Any = UNSET,
        harness: Any = UNSET,
        model_connection: Any = UNSET,
        budget_usd_per_month: Any = UNSET,
        budget_for_run: bool = False,
        can_request: Any = UNSET,
        timezone: Any = UNSET,
        repos: Any = UNSET,
        network: Any = UNSET,
        shell: Any = UNSET,
        browser_profile: Any = UNSET,
        card: Any = UNSET,
        machine: Any = UNSET,
        memories: Any = UNSET,
        skills: Any = UNSET,
        turn_limits: Any = UNSET,
        effort: Any = UNSET,
        speed: Any = UNSET,
        permission_mode: Any = UNSET,
        setup: Any = UNSET,
        docker: Any = UNSET,
        sandbox_size: Any = UNSET,
        app_testing: Any = UNSET,
        model_switching: Any = UNSET,
        secrets: Any = UNSET,
        approvals: Any = UNSET,
    ) -> "Agent":
        """Change fields. Grants its user gave it are kept. A new ``harness`` without
        a ``model`` takes that harness's default model, and each conversation carries
        on on the new harness, with its own memory and the memories it attaches, from
        its next turn. ``memories`` are as in ``create`` (``[]`` detaches them all), and ``skills`` too (a coding
        harness's running sandbox restarts with them).
        ``model_connection=None`` removes
        an ``sdk`` agent's own model key. ``timezone`` is as in ``create``, and
        ``timezone=None`` goes back to the acting user's zone. ``repos`` are as in
        ``create``, from its next turn (a running sandbox restarts with them; a
        clone already in a conversation's workspace stays as it is). ``shell`` is as in
        ``create``, and ``network`` too, from its next turn (a coding harness's running
        sandbox restarts with it). ``browser_profile`` signs its browser in with
        another profile of its scope, from its next browser, and ``None`` signs it out.
        ``card`` (invite-only beta) gives it a card in
        place of the one it holds, as in ``create``, and ``card=None`` takes its card back.
        ``machine`` (invite-only beta) moves it onto a
        ``Machine``, or with ``None`` back to a sandbox of its own; it moves between
        turns and keeps its files. ``turn_limits`` is as in
        ``create``, from its next turn, and ``None`` goes back to the defaults. ``effort``, ``speed`` and
        ``permission_mode`` are as in ``create``, and ``None`` clears one (``full-access`` for the mode).
        ``docker`` and ``sandbox_size`` are as in ``create``, from its next turn (a running sandbox restarts with them):
        ``docker=False`` drops its size, and ``sandbox_size=None`` is ``"small"`` again. ``app_testing`` is as in
        ``create``; ``"never"`` turns off what's on now, from its next turn. ``model_switching`` is as in ``create``;
        ``None`` goes back to the default rule. Letting it switch more freely is the owner's own call.
        ``secrets`` are the secrets in its shell, as in ``create``, in place of those it has (``[]`` takes them all
        away). ``tool_rules`` are as in ``create``, in place of the ones it has (``{}`` clears them). ``name``
        renames it, unique among its scope's agents: its old name keeps reaching it and stays reserved for it
        (``former_names``), and a NoClick keeps its name. ``approvals`` changes the kinds it names, as in ``create``
        (``None`` for a kind puts back the account's, a child's its parent's); what changed is in
        ``agent.raw["approval_changes"]``. Anyone who may change the agent tightens them; an agent loosening its own
        or another's on its own initiative waits for the owner, and on the owner's own word it applies at once.
        ``budget_for_run=True`` with ``budget_usd_per_month`` sets that budget for one run alone (its turn under
        way, else its next one): the budget it replaced comes
        back once that run ends, however it ends, and ``budget_restore`` says what comes back meanwhile. A budget
        set without it stands until changed.

        Returns:
            This agent, updated. A field you leave out is unchanged, and changes apply from its next turn.

        Usage:
            Let it buy what costs $20 or less without asking (the account's ceiling must allow it)::

                noclick.Agent.from_name("buyer").update(approvals={"purchase": {"disposition": "allow", "under_usd": 20}})

            Change what it does and what it can use::

                support = noclick.Agent.from_name("support")
                support.update(
                    instructions="You answer billing questions and can refund a charge.",
                    tools=["stripe.list_invoices", "stripe.create_refund", "search"],
                )

            Move it to Codex, on a ChatGPT connection::

                openai = noclick.Connection.from_name("openai", integration="openai", create_if_missing=True)
                support = noclick.Agent.from_name("support")
                support.update(harness="codex", model_connection=openai)
                print(support.model)   # codex's default model

            Tell it the time in New York::

                support = noclick.Agent.from_name("support")
                support.update(timezone="America/New_York")

            Keep its shell off the open internet::

                support = noclick.Agent.from_name("support")
                support.update(network=["api.stripe.com"])

            Let it read what another agent remembers::

                sales = noclick.Agent.from_name("sales")
                noclick.Agent.from_name("support").update(memories=[sales.memory])

            Give its turns more room, and keep each to $3::

                noclick.Agent.from_name("builder").update(turn_limits={"steps": 150, "usd": 3})

            Hold its next job to $2, then give it its budget back::

                coder = noclick.Agent.from_name("coder")
                coder.update(budget_usd_per_month=2, budget_for_run=True)
                print(coder.budget_restore)   # {'budget_usd_per_month': 10.0, 'operation_id': None}
        """
        changes = {
            k: v for k, v in dict(
                instructions=instructions, model=model, name=name, harness=harness,
                budget_usd_per_month=budget_usd_per_month, timezone=timezone, shell=shell, effort=effort,
                speed=speed, permission_mode=permission_mode, docker=docker, sandbox_size=sandbox_size,
                app_testing=app_testing,
                model_switching=model_switching if model_switching in (UNSET, None)
                else await switching_wire(model_switching, scope=self._call_scope()),
                setup=setup if setup is UNSET else list(setup or []),
            ).items()
            if v is not UNSET
        }
        if budget_for_run:
            changes["budget_for_run"] = True
        if network is not UNSET:
            changes["network"] = network_wire(network)
        if turn_limits is not UNSET:
            changes["turn_limits"] = _limits_wire(turn_limits)
        if repos is not UNSET:
            changes["repos"] = await _repo_wires(repos or [], self._call_scope())
        if model_connection is not UNSET:
            changes["model_connection"] = await model_connection_ref(model_connection, scope=self._call_scope())
        if tools is not UNSET:
            changes["tools"] = await tool_refs(tools, scope=self._call_scope())
        if tool_rules is not UNSET:
            changes["tool_rules"] = dict(tool_rules or {})
        if can_request is not UNSET:
            changes["can_request"] = _integration_refs(can_request)
        if memories is not UNSET:
            changes["memories"] = await memory_links(
                memory_refs(memories or [], user=self._call_scope(), client=self._client) or [])
        if skills is not UNSET:
            changes["skills"] = await skill_links(
                skill_refs(skills or [], user=self._call_scope(), client=self._client) or [])
        if secrets is not UNSET:
            changes["secret_ids"] = await secret_ids(secret_refs(secrets or [], user=self._call_scope(), client=self._client))
        if approvals is not UNSET:
            changes["approvals"] = settings_wire(dict(approvals or {}))
        for key, value in (("browser_profile_id", browser_profile), ("card_id", card), ("machine_id", machine)):
            if value is not UNSET:
                changes[key] = await ref_id(value)
        raw = await self._ensure()
        self._raw = await self._request("PATCH", f"/v1/agents/{raw['id']}", json=changes)
        return self

    @synced
    async def grants(self) -> List[AgentGrant]:
        """The connections its user gave it at run time (requested or active), oldest first.

        Returns:
            Each grant with the ``connection`` it names, its ``integration``, its ``status`` and the
            ``operations`` it covers (``None``: every one).

        Usage::

            assistant = noclick.Agent.from_name("assistant", user="user_42")
            for grant in assistant.grants():
                print(grant.connection, grant.integration, grant.status, grant.operations)
                # google_calendar  google_calendar  active  None
        """
        raw = await self._ensure()
        self._raw = await self._request("GET", f"/v1/agents/{raw['id']}")
        return [AgentGrant._from(g) for g in self._raw.get("grants") or []]

    @synced
    async def tool_access(self) -> AgentToolAccess:
        """What it may do with each app it reaches, app by app.

        Returns:
            Each connection of its scope (connected later ones too), any app its rules name, NoClick and the web:
            whether it's ``on``, each action with what its rules say of it (``verdict``) and how often each ran in
            the last 7 days (``calls``). ``mode`` is ``restricted`` when it's kept to the apps its rules turn on.

        Usage::

            support = noclick.Agent.from_name("support")
            for app in support.tool_access().apps:
                print(app.label, app.on, app.calls)
            support.update(tool_rules={"work-gmail.delete_email_message": "off", "stripe.create_refund": "ask"})
        """
        raw = await self._ensure()
        return AgentToolAccess._from(await self._request("GET", f"/v1/agents/{raw['id']}/tool_access"))

    @synced
    async def switch_model(self, connection: Any, *, reason: Optional[str] = None,
                           evidence: Optional[Mapping[str, Any]] = None, scope: str = "once") -> Dict[str, Any]:
        """Move it onto another model connection (``Connection``, its name, or ``"noclick"`` for NoClick's key): its
        harness and model too where that one runs another, its conversations carrying over from their next turn. The
        same call its own ``switch_model`` tool makes, by its ``model_switching`` rule.

        Any of the owner's own plans is allowed. A paid key is allowed on the owner's own call (their key or
        session), or with ``evidence`` citing where they said so (``{"channel_id", "message_id", "quote"}``),
        which NoClick checks is theirs, for this switch or, ``scope="standing"``, whenever a plan runs out. Without
        it, NoClick asks them with one tap.

        Returns:
            ``status``: ``switched``, ``unchanged``, or ``asked`` with its ``request_id``.

        Usage::

            atlas = noclick.Agent.from_name("atlas")
            atlas.switch_model("claude-personal", reason="work plan used up")
        """
        raw = await self._ensure()
        return await self._request("POST", f"/v1/agents/{raw['id']}/model/switch", json=compact(
            connection=await model_connection_ref(connection, scope=self._call_scope()), reason=reason,
            evidence=None if evidence is None else dict(evidence), scope=scope))

    @synced
    async def model_grants(self) -> List[ModelSwitchGrant]:
        """The owner's say-so for its paid keys, newest first.

        Returns:
            Each ``ModelSwitchGrant``: which keys, once or standing, and how, where and when the owner gave it.

        Usage::

            for grant in noclick.Agent.from_name("atlas").model_grants():
                print(grant.scope, grant.evidence.get("quote"))
        """
        raw = await self._ensure()
        self._raw = await self._request("GET", f"/v1/agents/{raw['id']}")
        return [ModelSwitchGrant._from(g) for g in self._raw.get("model_grants") or []]

    @synced
    async def grant_model_switch(self, connections: Optional[Sequence[Any]] = None, *,
                                 scope: str = "standing") -> ModelSwitchGrant:
        """Let it move onto paid keys by itself (``connections``, or any): the owner's own call.

        Returns:
            The ``ModelSwitchGrant`` kept.

        Usage::

            noclick.Agent.from_name("scout").grant_model_switch(["kestrel-api"])
        """
        raw = await self._ensure()
        return ModelSwitchGrant._from(await self._request(
            "POST", f"/v1/agents/{raw['id']}/model/grants",
            json={"connections": None if connections is None else [
                await model_connection_ref(c, scope=self._call_scope()) for c in connections], "scope": scope}))

    @synced
    async def revoke_model_grant(self, grant: Any) -> ModelSwitchGrant:
        """Take back the owner's say-so (a ``ModelSwitchGrant`` or its id).

        Returns:
            The grant, with ``revoked_at``.

        Usage::

            atlas = noclick.Agent.from_name("atlas")
            for grant in atlas.model_grants():
                atlas.revoke_model_grant(grant)
        """
        raw = await self._ensure()
        grant_id = grant if isinstance(grant, str) else grant.id
        self._raw = await self._request("PATCH", f"/v1/agents/{raw['id']}", json={"revoke_model_grants": [grant_id]})
        return ModelSwitchGrant._from(next(g for g in self._raw.get("model_grants") or [] if g["id"] == grant_id))

    @synced
    async def revoke_grant(self, grant: Any) -> None:
        """Take back a grant (an ``AgentGrant`` or its id): its tools leave the
        agent; the connection stays the user's.

        Usage::

            assistant = noclick.Agent.from_name("assistant", user="user_42")
            for grant in assistant.grants():
                if grant.integration == "slack":
                    assistant.revoke_grant(grant)
        """
        raw = await self._ensure()
        grant_id = grant if isinstance(grant, str) else grant.id
        await self._request("DELETE", f"/v1/agents/{raw['id']}/grants/{grant_id}")

    @synced
    async def delete(self) -> TrashItem:
        """Delete the agent and the sub-agents under it: they go to the trash, restorable for 30 days. Its
        pending wake-ups and jobs end now and stay ended if it's restored.

        Returns:
            Its ``TrashItem``: ``restore()`` brings it and its sub-agents back.

        Usage::

            noclick.Agent.from_name("support").delete()
        """
        found = await self._ensure()
        raw = await self._request("DELETE", f"/v1/agents/{found['id']}")
        return trashed(raw, client=self._client, user=self._call_scope())

    # --- wake-ups --------------------------------------------------------

    @synced
    async def wake(
        self,
        conversation: str,
        *,
        note: str,
        at: Any = None,
        after: Any = None,
        when: Any = None,
        filters: Optional[Dict[str, Any]] = None,
        every: Any = None,
        user: Any = AMBIENT,
    ) -> Wakeup:
        """Have it take a turn later in ``conversation``, told ``note`` (up to 4,000
        characters) and what woke it. Exactly one of: ``at`` (an aware ``datetime``),
        ``after`` (seconds, or a ``timedelta``), ``when``: an ``Operation`` (a ``Job``,
        a ``HumanRequest``, a ``ConnectLink``, ...: it wakes when that settles, with its
        outcome; one already settled wakes it at once), a list of them (up to 20: it wakes
        once, when the last settles, told what each came to, and a child's ``done`` update
        for one of those jobs comes in that turn), or a NoClick event type
        (``"connection.connected"``, ``"human.answered"``; ``*`` matches the rest of a name),
        narrowed by ``filters``, dotted paths into the event's ``data`` and the values they
        must have: the first matching event after it was set wakes it, with the event; or
        ``every``, a ``noclick.Cron``: a routine that wakes the conversation at each of its
        times until it's canceled (``tz="user"`` follows the conversation's user). A
        user's conversation hears that user's events; one of your account's own hears every
        event, your users' included. ``user=`` says whose conversation it is, as for
        ``message``.

        A turn already running in the conversation goes first: the wake-up waits for it,
        never ``Conflict``. A channel's conversation raises ``noclick.InvalidRequest``, as for
        ``message``. It survives restarts, starts its turn once, and is billed and
        capped like any turn; when the turn can't be paid for, the wake-up fails with the
        reason. A recurring one stays ``pending``, due at its schedule's next time after each
        turn, so times it missed (held, or late) fold into one turn. Every agent can also wake
        itself with its ``wake_me`` tool, and list, change and cancel its own (``list_wakeups``,
        ``cancel_wakeup``), in the conversation it's in or, with ``conversation``, another of its
        own (never a channel's, nor from a conversation with someone outside its scope), so work
        nobody is waiting on runs apart from the thread a person reads. An agent holds up to 100
        pending wake-ups and 20 recurring ones
        (``noclick.QuotaExceeded``); a time is 1 minute to 365 days ahead, a schedule comes
        round at most every minute (every 15 for one the agent sets itself), and one
        conversation's wake-ups at a time are delivered at least a minute apart (news, an
        operation it waited on or a child's update, comes as soon as the conversation is free).

        Returns:
            The wake-up, ``pending``; ``update()`` changes it, ``cancel()`` calls it off.

        Usage:
            Pick a conversation up tomorrow morning, Berlin time::

                from datetime import datetime
                from zoneinfo import ZoneInfo

                support = noclick.Agent.from_name("support")
                support.wake("ticket-1841", at=datetime(2026, 10, 2, 9, 0, tzinfo=ZoneInfo("Europe/Berlin")),
                             note="Check whether the replacement shipped, and tell the customer.")

            Carry on once the user has connected their calendar::

                with noclick.as_user("user_42"):
                    assistant = noclick.Agent.from_name("assistant")
                    calendar = noclick.Connection.from_name("calendar", integration="google_calendar", create_if_missing=True)
                    link = calendar.connect_link(reason="to book your flights")
                    assistant.wake("trip-planning", when=link, note="The calendar is connected: book the flights now.")

            Or when the user's connection named gmail connects::

                with noclick.as_user("user_42"):
                    assistant = noclick.Agent.from_name("assistant")
                    assistant.wake("inbox-zero", when="connection.connected", filters={"name": "gmail"},
                                   note="Gmail is connected: sort the inbox as we discussed.")

            Keep a routine: every weekday at 8, in the user's own timezone::

                with noclick.as_user("user_42"):
                    assistant = noclick.Agent.from_name("assistant")
                    briefing = assistant.wake("briefing", every=noclick.Cron("0 8 * * 1-5", tz="user"),
                                              note="Brief me on today's calendar and anything urgent in my inbox.")
        """
        body = {"conversation": conversation, "note": check_note(note),
                **await wake_condition(at, after, when, filters, every)}
        raw = await self._ensure()
        scope = self._talk_scope(user)
        response = await self._request("POST", f"/v1/agents/{raw['id']}/wakeups", json=body, user=scope)
        return Wakeup._new(raw=response, client=self._client, user=scope)

    @synced
    async def wakeups(
        self,
        conversation: Optional[str] = None,
        *,
        status: Union[None, str, Sequence[str]] = None,
        limit: Optional[int] = None,
        user: Any = AMBIENT,
        user_filter: Any = None,
    ) -> List[Wakeup]:
        """Its wake-ups in the acting user's conversations (or one ``conversation``), or in
        those of the users ``user_filter`` covers. They're those your code set, those it set itself
        with ``wake_me``, and NoClick's own: a child's update (``update``), the link it asked its
        user to connect an account with being done (``answer``) and a decided approval
        (``approval``). ``status`` keeps ``pending``, ``delivered``,
        ``canceled`` or ``failed`` ones. ``user_filter`` (``noclick.ALL_USERS``,
        ``noclick.NO_USER``, a ``User`` or your id for one) reads across users without the user
        header, as ``conversations`` does: an account agent's wake-ups in every user's threads.

        Returns:
            Every matching wake-up (or the first ``limit``), newest first, each with its ``source``, when it's
            due (``at``) or what it waits for (``when``), whose thread it's in (``user_id``) and, once delivered,
            the turn it started. ``cancel()`` acts in that wake-up's own thread.

        Usage:
            What will wake it in the acting user's threads::

                support = noclick.Agent.from_name("support")
                for wakeup in support.wakeups(status="pending"):
                    print(wakeup.conversation, wakeup.source, wakeup.at or wakeup.when, wakeup.note)

            Or what will wake a shared agent in any of its users' threads::

                support = noclick.Agent.from_name("support")
                for wakeup in support.wakeups(status="pending", user_filter=noclick.ALL_USERS):
                    print(wakeup.user_id, wakeup.conversation, wakeup.at, wakeup.note)
        """
        statuses = [status] if isinstance(status, str) else list(status or ())
        unknown = [s for s in statuses if s not in WAKEUP_STATUSES]
        if unknown:
            raise ValueError(f"A wake-up's status is one of {WAKEUP_STATUSES}, not {unknown[0]!r}")
        raw = await self._ensure()
        return await list_all(
            f"/v1/agents/{raw['id']}/wakeups",
            lambda row, scope: Wakeup._new(raw=row, client=self._client, user=scope),
            params={"conversation": conversation, "status": csv(status)}, limit=limit, client=self._client,
            user=self._talk_scope(user) if user_filter is None else user, user_filter=user_filter,
        )

    # --- triggers --------------------------------------------------------

    @synced
    async def triggers(self) -> List[AgentTrigger]:
        """What wakes it besides a message: schedules, webhooks, app and NoClick
        events, queues, and the inboxes and numbers that hand it mail and calls.

        Returns:
            Each trigger with its ``kind``, its ``spec``, its ``status`` (``paused`` while the agent is),
            the ``url`` a webhook listens at, when a schedule's ``next_run`` is and when it
            ``last_fired_at``. An ``error`` says why one can't fire.

        Usage::

            support = noclick.Agent.from_name("support")
            for trigger in support.triggers():
                print(trigger.kind, trigger.status, trigger.url or trigger.spec)
        """
        raw = await self._ensure()
        response = await self._request("GET", f"/v1/agents/{raw['id']}/triggers") or {}
        return [AgentTrigger._from(row) for row in response.get("data") or []]

    @synced
    async def add_trigger(self, trigger: Any) -> AgentTrigger:
        """Add a trigger: a ``noclick.OnWebhook``, ``OnEvent``, ``OnPlatformEvent``, ``Cron``
        or ``OnQueue``. An agent holds up to 20. (On an agent whose ``from_name(..., triggers=...)``
        sets its triggers, that code sets the list instead, and removes one added here the next time
        it runs.)

        Returns:
            The trigger as added; a webhook's ``url`` is where to send its POSTs. An event
            trigger whose connection isn't connected yet is ``error`` until it is.

        Usage:
            Give an agent a URL your systems can wake it at::

                fulfilment = noclick.Agent.from_name("fulfilment")
                orders = fulfilment.add_trigger(noclick.OnWebhook(name="orders"))
                print(orders.url)

            Or wake it on each new HubSpot contact::

                sales = noclick.Agent.from_name("sales")
                sales.add_trigger(noclick.OnEvent("hubspot", "contact_created", message="Research this contact."))

            Or put it on a schedule, which makes it an automation::

                support = noclick.Agent.from_name("support")
                support.add_trigger(noclick.Cron("0 17 * * 5", tz="America/New_York", message="Send the weekly ticket report"))
        """
        definition = await trigger_wire(trigger)
        raw = await self._ensure()
        return AgentTrigger._from(await self._request("POST", f"/v1/agents/{raw['id']}/triggers", json=definition))

    @synced
    async def update_trigger(self, trigger: Any, *, cron: Optional[Cron] = None, message: Any = UNSET,
                             conversation: Any = UNSET, filters: Any = UNSET,
                             mode: Optional[str] = None) -> AgentTrigger:
        """Change a trigger in place: it keeps its id, its history, and a webhook its URL. ``cron``, a
        ``noclick.Cron``, moves a schedule to its time in its ``tz`` at once (and changes its
        ``message`` when the ``Cron`` has one); ``message`` changes what any trigger's turn is
        told, and ``conversation`` the template a webhook, event or queue trigger keys its
        conversations by (``None`` clears either); ``filters`` replaces an app event's or a NoClick
        event's filters (it hears by them from the next delivery); ``mode`` (``"mentions"`` or
        ``"all"``) changes the mode of a channel the agent sits in, for every agent in it (your key
        needs ``channels``). A webhook's name, an event's connection and event, and a queue stay:
        remove it and add another for that. ``trigger`` is an ``AgentTrigger``, its id, or the
        definition you added, as for ``remove_trigger``. Checked and registered as ``add_trigger``
        does; a paused schedule takes its new time when it resumes.

        Returns:
            The trigger as it is now, with its new ``next_run_at``.

        Usage::

            digest = noclick.Agent.from_name("digest")
            [schedule] = [t for t in digest.triggers() if t.kind == "cron"]
            digest.update_trigger(schedule, cron=noclick.Cron("30 7 * * 1-5", tz="Europe/London"))
        """
        if cron is not None and not isinstance(cron, Cron):
            raise TypeError(f"cron is a noclick.Cron, not {type(cron).__name__}")
        changes: Dict[str, Any] = dict(cron._wire()) if cron is not None else {}
        changes.update({k: v for k, v in (("message", message), ("conversation", conversation), ("filters", filters))
                        if v is not UNSET})
        if mode is not None:
            changes["mode"] = mode
        if not changes:
            raise ValueError("Nothing to change: pass cron=, message=, conversation=, filters= or mode=")
        raw = await self._ensure()
        path = f"/v1/agents/{raw['id']}/triggers/{await self._trigger_id(trigger)}"
        return AgentTrigger._from(await self._request("PATCH", path, json=changes))

    @synced
    async def pause_trigger(self, trigger: Any) -> AgentTrigger:
        """Pause one trigger, the agent running on. A schedule is skipped (its ``next_run_at``
        still reads), a webhook's calls and app or NoClick events are acknowledged and dropped, a
        queue's messages wait on the queue. ``pause()`` stops everything that wakes the agent.

        Returns:
            The trigger as it is now (``paused`` is ``True``).

        Usage::

            support = noclick.Agent.from_name("support")
            [orders] = [t for t in support.triggers() if t.spec.get("name") == "orders"]
            support.pause_trigger(orders)
        """
        return await self._switch_trigger(trigger, "pause")

    @synced
    async def resume_trigger(self, trigger: Any) -> AgentTrigger:
        """Resume a trigger paused on its own, or one its failures stopped. It wakes the agent
        again (a schedule at its next run), unless the agent itself is paused.

        Returns:
            The trigger as it is now (``state`` is ``live`` unless the agent is paused).

        Usage::

            support = noclick.Agent.from_name("support")
            for trigger in support.triggers():
                if "resume" in trigger.actions:
                    support.resume_trigger(trigger)
        """
        return await self._switch_trigger(trigger, "resume")

    async def _switch_trigger(self, trigger: Any, to: str) -> AgentTrigger:
        raw = await self._ensure()
        path = f"/v1/agents/{raw['id']}/triggers/{await self._trigger_id(trigger)}/{to}"
        return AgentTrigger._from(await self._request("POST", path))

    @synced
    async def remove_trigger(self, trigger: Any) -> None:
        """Remove a trigger: an ``AgentTrigger``, its id, or the definition you added
        (``noclick.NotFound`` if none matches; an ``OnWebhook`` by its unique
        ``name``). Mail and call triggers change on their inbox or number.

        Usage::

            support = noclick.Agent.from_name("support")
            for trigger in support.triggers():
                if trigger.kind == "webhook":
                    support.remove_trigger(trigger)
        """
        raw = await self._ensure()
        await self._request("DELETE", f"/v1/agents/{raw['id']}/triggers/{await self._trigger_id(trigger)}")

    # ── MCP servers ──

    @synced
    async def tool_servers(self, *, conversation: Optional[str] = None) -> List[AgentToolServer]:
        """Its MCP servers, each a step of its automation, with each one's state: how it lets its client in
        (``sign_in``), its ``status`` and ``problem``, the ``tools`` its last run found, its ``host`` and ``icon``.
        With ``conversation``, each as that conversation's coding harness last said it where that's newer (``status``
        ``connecting`` too), and whether it can connect one again in place now (``reconnectable``:
        ``agent.conversation(name).reconnect_tool_server(server.name)``).

        Returns:
            A list of ``AgentToolServer``, in the order they were added.

        Usage::

            for server in noclick.Agent.from_name("coder").tool_servers():
                print(server.name, server.status, [tool.name for tool in server.tools])
                if server.status == "needs_sign_in":
                    print("Sign in:", server.connect_link().url)
        """
        raw = await self._ensure()
        listed = await self._request("GET", f"/v1/agents/{raw['id']}/tool_servers",
                                     params={"conversation": conversation} if conversation else None)
        return [AgentToolServer._from(s, self) for s in listed.get("data") or [] if isinstance(s, dict)]

    @synced
    async def add_tool_server(self, url: str, *, name: Optional[str] = None, transport: str = "http",
                              credential: Optional[str] = None,
                              headers: Optional[Dict[str, str]] = None) -> AgentToolServer:
        """Give it an MCP server's tools from its next turn. The server is a step of its automation, reached at
        its public https URL (``transport`` ``sse`` for one that speaks only the older SSE), named ``name``, else
        after the URL's host (``mcp.linear.app`` is ``linear``). ``credential`` is the account's own sign-in to it,
        which NoClick's MCP sign-in makes, or ``headers`` carry the key it takes instead (``{"Authorization":
        "Bearer <key>"}``): kept as a credential, sent on every request, never read back. A server that asks its
        client to sign in, given neither, is added waiting for a person (``status`` ``needs_sign_in``):
        ``server.connect_link()`` signs them in. Up to 20.

        Returns:
            The ``AgentToolServer`` as added: its ``id`` (what ``remove_tool_server`` takes), ``name``, ``url``,
            how it lets its client in (``sign_in``), its ``status`` and its ``headers``' names.

        Usage::

            coder = noclick.Agent.from_name("coder")
            docs = coder.add_tool_server("https://mcp.example.com/mcp", name="docs",
                                         headers={"X-Api-Key": os.environ["DOCS_KEY"]})
            print(docs.id)
        """
        raw = await self._ensure()
        body = {"url": url, "transport": transport, **({"name": name} if name else {}),
                **({"credential_id": credential} if credential else {}), **({"headers": headers} if headers else {})}
        return AgentToolServer._from(await self._request("POST", f"/v1/agents/{raw['id']}/tool_servers", json=body),
                                     self)

    @synced
    async def update_tool_server(self, server: Union[str, AgentToolServer], *,
                                 headers: Dict[str, str]) -> AgentToolServer:
        """Replace an MCP server's headers. From its next turn it sends ``headers`` (a new key; ``{}``: none), and
        those given before are deleted.

        Returns:
            The ``AgentToolServer`` as it stands, its ``headers`` naming the new ones.

        Usage::

            coder = noclick.Agent.from_name("coder")
            coder.update_tool_server("mcp_docs", headers={"X-Api-Key": os.environ["DOCS_KEY"]})
        """
        raw = await self._ensure()
        step = server.id if isinstance(server, AgentToolServer) else server
        return AgentToolServer._from(await self._request(
            "PATCH", f"/v1/agents/{raw['id']}/tool_servers/{quote(step, safe='')}", json={"headers": headers}), self)

    @synced
    async def remove_tool_server(self, server: Union[str, AgentToolServer]) -> None:
        """Take an MCP server away (by ``AgentToolServer`` or ``id``). Its tools stop from its next turn and
        the headers given it go; its sign-in stays connected.

        Usage::

            coder = noclick.Agent.from_name("coder")
            coder.remove_tool_server("mcp_docs")
        """
        raw = await self._ensure()
        step = server.id if isinstance(server, AgentToolServer) else server
        await self._request("DELETE", f"/v1/agents/{raw['id']}/tool_servers/{quote(step, safe='')}")

    @synced
    async def rehearse_trigger(self, trigger: Any, *, sample: Any = None) -> Operation:
        """A test run of the turn a trigger would start now, without a real delivery. The agent
        reads what ``sample`` would hand it (a webhook's body; an app event's or a NoClick event's
        data; a queue message's body; an email's ``{"from", "subject", "text"}``; a channel post's
        text or ``{"text", "from"}``), else a sample of its own (a schedule's or a recurring
        wake-up's run; an app event's values placeholders in the shape it has reached your account
        in, no data until one has; a NoClick event's from the event catalog), under the trigger's
        ``message``, its tool calls answered by a simulated world as in ``rehearse``, so nothing is
        sent. A call and an approval can't be tested. ``trigger`` is an ``AgentTrigger``, its id,
        or the definition you added.

        Returns:
            The run's operation (kind ``agent.rehearse``); ``.wait()`` gives the ``Rehearsal``.

        Usage::

            whatsapp = noclick.Connection.from_name("whatsapp", integration="whatsapp")
            inbox = noclick.Agent.from_name("inbox")
            run = inbox.rehearse_trigger(noclick.OnEvent(whatsapp, "receive_message"))
            print(run.wait().reply)
        """
        raw = await self._ensure()
        path = f"/v1/agents/{raw['id']}/triggers/{await self._trigger_id(trigger)}/test"
        payload = await self._request("POST", path, **({"json": {"sample": sample}} if sample is not None else {}))
        return Operation._from_payload(payload, client=self._client, user=self._call_scope(), kind="agent.rehearse")

    async def _trigger_id(self, trigger: Any) -> str:
        """An ``AgentTrigger``'s id, an id, or the id of the trigger a definition names."""
        if isinstance(trigger, AgentTrigger):
            return trigger.id
        if isinstance(trigger, str):
            return trigger
        raw = await self._ensure()
        wanted = named_by(await trigger_wire(trigger))
        match = [t for t in await self.triggers.aio() if t.defined and named_by({"kind": t.kind, **t.spec}) == wanted]
        if not match:
            raise NotFound(
                f"{raw['name']} has no trigger like {trigger!r}.",
                next_step="List them with agent.triggers() and use one of those.",
                details={"agent_id": raw["id"]},
            )
        return match[0].id

    @synced
    async def inboxes(self) -> List["Inbox"]:
        """The inboxes whose mail wakes it (created or updated with ``agent=`` it).

        Returns:
            Every such inbox, newest first, each with its ``address``.

        Usage::

            support = noclick.Agent.from_name("support")
            print([inbox.address for inbox in support.inboxes()])
        """
        from .inbox import Inbox  # inbox imports this module

        raw = await self._ensure()
        return await Inbox.list.aio(agent=raw["id"], user=self._call_scope(), client=self._client)

    @synced
    async def pause(self) -> "Agent":
        """Stop every trigger from waking it: scheduled runs are skipped (not made up),
        webhook calls get a 409 their sender can retry, and app events, mail and
        calls meanwhile don't wake it. Messages your code sends still run.

        Returns:
            This agent, with ``paused`` true.

        Usage::

            digest = noclick.Agent.from_name("digest")
            digest.pause()
            print(digest.paused)   # True
        """
        raw = await self._ensure()
        self._raw = await self._request("POST", f"/v1/agents/{raw['id']}/pause")
        return self

    @synced
    async def resume(self) -> "Agent":
        """Let its triggers wake it again, including one that stopped after failing
        the same way five times; a schedule picks up at its next run.

        Returns:
            This agent, with ``paused`` false.

        Usage::

            digest = noclick.Agent.from_name("digest")
            digest.resume()
        """
        raw = await self._ensure()
        self._raw = await self._request("POST", f"/v1/agents/{raw['id']}/resume")
        return self

    # --- memory, files and sharing ---------------------------------------

    @property
    def memory(self) -> AgentMemory:
        """What it remembers across conversations: ``list``, ``search``, ``read``, ``save`` and ``delete``
        named entries (see ``AgentMemory``)."""
        return AgentMemory._of(self)

    def workspace(self, conversation: Optional[str] = None, *, user: Any = AMBIENT) -> AgentWorkspace:
        """The files it works on: its one ``/workspace`` (``AgentWorkspace``; a ``conversation`` is accepted and
        ignored). Sends nothing yet.

        Returns:
            Its workspace, whose ``files``, ``read``, ``write`` and ``url`` reach its files.

        Usage::

            support = noclick.Agent.from_name("support")
            workspace = support.workspace(user="user_42")
            for file in workspace.files():
                print(file.path, file.size_bytes)
        """
        return AgentWorkspace._of(self, conversation, resolve_scope(user))

    def sandbox(self, conversation: Optional[str] = None, *, user: Any = AMBIENT) -> AgentSandbox:
        """The machine it works on, one whoever it answers. An ``AgentSandbox``: what it is and costs, its files, and
        your own commands on it beside its work. Without a ``conversation`` it's read through its session. Sends
        nothing yet.

        Returns:
            Its sandbox, whose ``get``, ``files``, ``read`` and ``exec`` reach it.

        Usage::

            coder = noclick.Agent.from_name("coder")
            machine = coder.sandbox()
            if machine.get().status == "running":
                print(machine.exec("git log --oneline -5").stdout)
        """
        return AgentSandbox._of(self, conversation, resolve_scope(user))

    @synced
    async def share(self) -> ShareLink:
        """Turn on its public chat page, or read it if it's on: anyone with the
        link talks to the agent, no sign-in, each visitor in their own
        conversations. Their turns bill to you, against its budget, rate limited
        per visitor.

        Returns:
            The link: its ``url``, and ``disable()`` and ``rotate()`` to turn it off or change it.

        Usage::

            support = noclick.Agent.from_name("support")
            link = support.share()
            print(link.url)   # https://noclick.com/a/...
        """
        raw = await self._ensure()
        response = await self._request("POST", f"/v1/agents/{raw['id']}/share")
        return ShareLink._new(raw=response, hints={"agent_id": raw["id"]}, client=self._client, user=self._call_scope())

    @synced
    async def share_link(self) -> Optional[ShareLink]:
        """Its chat page as it is, without turning it on (``share()`` does that).

        Returns:
            The link, ``enabled`` or not, or ``None`` if the agent has never been shared.

        Usage::

            support = noclick.Agent.from_name("support")
            link = support.share_link()
            print(link.url if link and link.enabled else "Not shared")
        """
        raw = await self._ensure()
        try:
            response = await self._request("GET", f"/v1/agents/{raw['id']}/share")
        except NotFound:
            return None
        return ShareLink._new(raw=response, hints={"agent_id": raw["id"]}, client=self._client, user=self._call_scope())

    # --- streaming and test runs -----------------------------------------

    @synced
    async def stream(
        self, text: str, *, conversation: Optional[str] = None, files: Sequence[Any] = (), user: Any = AMBIENT,
    ) -> AsyncIterator[AgentEvent]:
        """Send ``text`` (and any ``files``) and watch the turn as it happens: the
        reply as it's written, each tool call and result, each file, approval and
        long action, then the whole reply. The same turn as ``message``, billed the
        same.

        Returns:
            ``AgentEvent`` values in order, ending with one whose ``type`` is ``done`` and whose ``reply`` is the
            ``AgentReply``. A turn that fails raises its error instead.

        Usage:
            Print the reply as it's written::

                support = noclick.Agent.from_name("support")
                for event in support.stream("Where's my refund?", conversation="ticket-1841"):
                    if event.type == "text":
                        print(event.text, end="", flush=True)
                    elif event.type == "tool_call":
                        print(f"\\n[{event.tool}]")

            In async code, relay it to your own UI::

                support = noclick.Agent.from_name("support")
                async for event in support.stream.aio("Where's my refund?", user="user_42"):
                    await websocket.send_json(event.raw)
        """
        raw = await self._ensure()
        events = self._api._events(
            "POST", f"/v1/agents/{raw['id']}/messages", json=await self._message_body(text, conversation, files),
            user=self._talk_scope(user), params={"stream": 1},
        )
        async for kind, data in events:
            yield _agent_event(kind, data)
            if kind == "done":
                return

    @synced
    async def watch(self, conversation: str, *, user: Any = AMBIENT, replay: bool = False) -> AsyncIterator[AgentEvent]:
        """Follow one conversation live, whoever moves it (a trigger, an answered ``ask``,
        an approved held call, another client, a person after a hand-off), your own turns
        too (by ``operation_id``). It
        runs until you stop reading or the conversation is deleted. ``replay`` starts
        with the last hour's kept moments, so a turn joined halfway is seen whole.

        Returns:
            ``AgentEvent`` values as they happen: ``message`` (a whole message, with its ``role``:
            ``user``, ``assistant`` or ``person``, and its ``files``), ``text`` as a reply is written,
            ``tool_call`` (``held`` names the approval when policy holds it), ``tool_result``, ``file``,
            ``approval`` and ``operation`` (from its ``"noclick"`` tools), and ``status`` when the
            conversation starts waiting on a person, is handed off or becomes ``active``. A coding
            harness's turn adds ``output`` and ``diff`` (``AgentEvent``).

        Usage:
            Push what happens in a support thread to your own UI::

                support = noclick.Agent.from_name("support")
                for event in support.watch("ticket-1841", user="user_42"):
                    if event.type == "message":
                        print(event.role, event.text)
                    elif event.type == "tool_call" and event.held:
                        print("Waiting for approval:", event.held["url"])

            In async code::

                support = noclick.Agent.from_name("support")
                async for event in support.watch.aio("ticket-1841"):
                    await websocket.send_json(event.raw)
        """
        raw = await self._ensure()
        events = self._api._events(
            "GET", f"/v1/agents/{raw['id']}/conversations/{quote(conversation, safe='')}/events",
            user=self._talk_scope(user), params={"replay": 1} if replay else None,
        )
        async for kind, data in events:
            yield _agent_event(kind, data)

    @synced
    async def rehearse(self, message: str, *, scenario: Optional[str] = None, user: Any = AMBIENT) -> Operation:
        """A test run of this agent against a simulated world. A real turn (its model, instructions and tools)
        where that world answers every tool call, so nothing is sent, no
        account is touched and its connections needn't be connected yet (its model
        connection must be). ``scenario`` says what that world is like; the world
        keeps to it, and without one it's an ordinary busy day. The run is billed
        like a turn, counts toward the agent's budget, and is no turn in any of its
        conversations. An account has up to 10 runs queued or running at once
        (``noclick.QuotaExceeded`` past that).

        Returns:
            The run's operation (kind ``agent.rehearse``); ``.wait()`` gives the ``Rehearsal``: the ``reply``, and
            the ``tool_calls`` it made with what the world answered.

        Usage::

            support = noclick.Agent.from_name("support")
            run = support.rehearse(
                "Order 1841 arrived broken. I want my money back.",
                scenario="Order 1841 was delivered on Sep 2 and paid by card; the customer has asked once before.",
            ).wait()
            print(run.reply)
            for call in run.tool_calls:
                print(call["tool"], call["arguments"])
        """
        raw = await self._ensure()
        scope = self._talk_scope(user)
        payload = await self._request(
            "POST", f"/v1/agents/{raw['id']}/rehearsals", json=compact(message=message, scenario=scenario), user=scope,
        )
        return Operation._from_payload(payload, client=self._client, user=scope, kind="agent.rehearse")
