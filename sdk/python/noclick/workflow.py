"""Workflows, built from a description or edited step by step, and run from code.

    brief = noclick.Workflow.create("Morning brief")
    brief.build("Every day at 8, email me today's calendar").wait()
    run = brief.run().wait()

Your keys read every workflow your account can open in the app, its own and
those shared with it (``access``), and change, build and run the ones they can
edit (one a team workspace's owner pays for is billed to them). NoClick's
builder (the one in the app) builds and changes one from what you describe: a
``WorkflowBuild`` you wait on, which may stop to ask something first, and which
can publish the workflow's app too. A run starts where its trigger does, with
the inputs as the trigger's payload. A run started inside ``as_user`` (or with
``user=``) is recorded for that user and counts toward their spend cap; its
steps still use the app's connections.

A workflow's graph is also a handle you change directly: ``graph()`` reads its
steps, each ``Step`` changes with one call (``update``, ``connect``, ...), and
``edit()`` sends several changes as one batch that lands whole or not at all,
refused with ``noclick.Conflict`` when the workflow moved on since the version
you read. Every change is a version, listed by ``versions()`` and undone with
``restore(history_version=...)``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from ._client import Client, path_segment, resolve_client
from ._object import (
    Page, _Object, compact, csv, field, list_all, list_page, paginate, parse_time, read_scope, ref_id,
)
from ._sync import run_sync, synced
from ._scope import AMBIENT, resolve_scope
from .exceptions import AnswerRequired, Conflict, NotFound
from .operation import Operation, register_result
from .workflow_approval import WorkflowApproval


@dataclass(frozen=True)
class RunStep:
    """What one step did in a run: ``status`` is ``succeeded``, ``failed``
    (``error`` says why) or ``skipped``; ``output`` is what it produced, with
    long lists and text cut short and never a secret (``withheld`` names, by
    path, what was left out). ``Step.output`` reads it whole."""

    id: str
    name: str
    status: str
    error: Optional[str]
    output: Any
    withheld: List[str] = dc_field(default_factory=list)

    @classmethod
    def _from(cls, raw: Any) -> "RunStep":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("id") or "", raw.get("name") or "", raw.get("status") or "", raw.get("error"),
                   raw.get("output"), list(raw.get("withheld") or []))


@dataclass(frozen=True)
class StepOutput:
    """What one step produced in one run (``Step.outputs``, ``Step.output``). ``run_id`` is the
    run's id (``Workflow.get_run`` reads a run from code by it), ``source`` how it started (as
    ``WorkflowRun.source`` says it), ``status`` the step's there (``succeeded``, ``failed`` with
    ``error``, ``skipped``). A trigger's deliveries are its outputs too: ``no_event`` marks a
    manual run's placeholder for one that got no event. ``iteration`` is set for one iteration of
    a step that runs in a loop.

    A listing gives a one-line ``preview`` (``path=value`` pairs); one read gives the ``output``,
    with long text and lists cut short (``truncated``) unless read ``full``, or the part at ``path``.
    Never a secret: ``withheld`` names, by path, what was left out (a request's ``Authorization``
    header, a key, a token)."""

    step_id: str
    run_id: str
    workflow_id: Optional[str]
    iteration: Optional[int]
    source: Optional[str]
    status: Optional[str]
    error: Optional[str]
    created_at: Any
    no_event: bool
    preview: Optional[str] = None
    output: Any = None
    path: Optional[str] = None
    full: bool = False
    truncated: bool = False
    withheld: List[str] = dc_field(default_factory=list)
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "StepOutput":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            step_id=raw.get("step_id") or "", run_id=raw.get("run_id") or "", workflow_id=raw.get("workflow_id"),
            iteration=raw.get("iteration"), source=raw.get("source"), status=raw.get("status"),
            error=raw.get("error"), created_at=parse_time(raw.get("created_at")), no_event=bool(raw.get("no_event")),
            preview=raw.get("preview"), output=raw.get("output"), path=raw.get("path"), full=bool(raw.get("full")),
            truncated=bool(raw.get("truncated")), withheld=list(raw.get("withheld") or []), raw=raw,
        )


@dataclass(frozen=True)
class WorkflowRunCounts:
    """How many runs ``Workflow.runs`` lists (``Workflow.run_counts``): the ``total``,
    ``by_status`` (``running``, ``succeeded``, ``failed``, each there even at 0), ``waiting``
    (how many of the running ones wait on an approval, a delay or an agent's turn),
    ``by_source`` (``api``, ``endpoint``, ``schedule``, ``trigger``, ``app``: only those with
    runs) and ``by_trigger`` (the kinds of event that started the runs a trigger did:
    ``webhook``, ``email``, …, only those with runs). A run from code counts once, however
    many executions it spans."""

    workflow_id: str
    total: int
    by_status: Dict[str, int]
    by_source: Dict[str, int]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)
    waiting: int = 0
    by_trigger: Dict[str, int] = dc_field(default_factory=dict)

    @classmethod
    def _from(cls, raw: Any) -> "WorkflowRunCounts":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("workflow_id") or "", int(raw.get("total") or 0),
                   {"running": 0, "succeeded": 0, "failed": 0, **(raw.get("by_status") or {})},
                   dict(raw.get("by_source") or {}), raw, waiting=int(raw.get("waiting") or 0),
                   by_trigger=dict(raw.get("by_trigger") or {}))


@dataclass(frozen=True)
class StepLastRun:
    """How a step's latest run ended (``LatestOutputs.last_runs``): its ``status``
    (``succeeded``, ``failed``, ``skipped``), when it ``finished_at``, its ``error``."""

    status: str
    finished_at: Any
    error: Optional[str]


@dataclass(frozen=True)
class LatestOutputs:
    """Each step's latest output, whatever run it's from (``Workflow.latest_outputs``):
    ``outputs`` by step id, each cut short as a run's steps are unless read ``full``
    (``truncated`` names the steps cut), never a secret (``withheld``: each step's paths left
    out). A step that never stored one isn't in ``outputs``. ``last_runs``: how each step's
    latest run ended, as the app's canvas marks it beside the step; a step never run isn't in
    it."""

    workflow_id: str
    outputs: Dict[str, Any]
    withheld: Dict[str, List[str]]
    full: bool
    truncated: List[str]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)
    last_runs: Dict[str, StepLastRun] = dc_field(default_factory=dict)

    @classmethod
    def _from(cls, raw: Any) -> "LatestOutputs":
        raw = raw if isinstance(raw, dict) else {}
        last_runs = {str(step): StepLastRun(str(run.get("status") or ""), parse_time(run.get("finished_at")),
                                            run.get("error"))
                     for step, run in (raw.get("last_runs") or {}).items() if isinstance(run, dict)}
        return cls(raw.get("workflow_id") or "", dict(raw.get("outputs") or {}),
                   {step: list(paths) for step, paths in (raw.get("withheld") or {}).items()},
                   bool(raw.get("full")), list(raw.get("truncated") or []), raw, last_runs)


@dataclass(frozen=True)
class ExpressionPreview:
    """What an expression gives (``Step.preview_expression``): ``ok``, with the value's ``kind``
    (``object``, ``array``, ``string``, ``number``, ``boolean``, ``null``), an object's ``keys``
    and a short ``preview``; or ``ok`` False with the ``error``."""

    ok: bool
    kind: Optional[str]
    keys: Optional[List[str]]
    preview: Optional[str]
    error: Optional[str]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "ExpressionPreview":
        raw = raw if isinstance(raw, dict) else {}
        keys = raw.get("keys")
        return cls(bool(raw.get("ok")), raw.get("kind"), list(keys) if isinstance(keys, list) else None,
                   raw.get("preview"), raw.get("error"), raw)


@dataclass(frozen=True)
class ClearedStepState:
    """What ``Step.clear_state`` forgot: how many of its state records and of its
    conversations were deleted."""

    step_id: str
    state_rows_deleted: int
    conversations_deleted: int
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "ClearedStepState":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("step_id") or "", int(raw.get("state_rows_deleted") or 0),
                   int(raw.get("conversations_deleted") or 0), raw)


@dataclass(frozen=True)
class WorkflowRun:
    """One run of a workflow. ``status`` is ``running`` (a run waiting on an
    approval or a delay too: ``waiting_on`` says on what, ``approval``,
    ``delay`` or for a run from code ``agent_turn``; ``None`` while it runs
    on), ``succeeded`` or ``failed`` (``error`` says why). ``outputs`` holds
    what its final steps produced (each step that finished with nothing after
    it running), by step name. ``source`` is how it started: ``api``,
    ``endpoint``, ``schedule``, ``trigger`` (an event) or ``app``; for a
    ``trigger`` run, ``trigger`` names the kind of event: ``webhook`` (a
    delivery to one of its trigger steps, a webhook's or an app's event),
    ``email``, ``call``, ``agent`` (an agent's turn), ``shared_link`` or
    ``error`` (it handled another run's failure). ``inputs`` and
    ``operation_id`` are set for a run started from code. ``steps`` says what
    each step did, read with one run (``Workflow.get_run``); empty in a list."""

    id: str
    workflow_id: Optional[str]
    status: str
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    error: Optional[str]
    source: Optional[str]
    user_id: Optional[str]
    operation_id: Optional[str]
    started_at: Any
    finished_at: Any
    steps: List[RunStep] = dc_field(default_factory=list)
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)
    trigger: Optional[str] = None
    waiting_on: Optional[str] = None

    @classmethod
    def _from(cls, raw: Any) -> "WorkflowRun":
        raw = raw if isinstance(raw, dict) else {}
        error = raw.get("error")
        return cls(
            id=raw.get("id") or "", workflow_id=raw.get("workflow_id"), status=raw.get("status") or "running",
            inputs=dict(raw.get("inputs") or {}), outputs=dict(raw.get("outputs") or {}),
            error=error.get("message") if isinstance(error, dict) else error, source=raw.get("source"),
            user_id=raw.get("user_id"), operation_id=raw.get("operation_id"),
            started_at=parse_time(raw.get("started_at")), finished_at=parse_time(raw.get("finished_at")),
            steps=[RunStep._from(s) for s in raw.get("steps") or []], raw=raw,
            trigger=raw.get("trigger"), waiting_on=raw.get("waiting_on"),
        )


@dataclass(frozen=True)
class WorkflowEndpoint:
    """The URL a workflow answers at: send ``method`` (``POST``) with the inputs
    as a JSON body, and the run's outputs come back (a run longer than 30
    seconds answers ``202`` with its operation). A ``public`` endpoint also takes
    a publishable key (``nk_pub_...``) that lists it, so a web page can call it;
    otherwise it needs a secret key."""

    url: str
    public: bool
    method: str
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "WorkflowEndpoint":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("url") or "", bool(raw.get("public")), raw.get("method") or "POST", raw)


@dataclass(frozen=True)
class WorkflowStep:
    """One step of a workflow, as the app shows it: its ``name``, its kind
    (``type``, like ``automation-gmail`` or ``trigger-cron``) and the
    ``operation`` it does there (``None`` for a step with one thing to do).

    Read with one workflow, a step also says whether it's ``enabled``, its
    ``settings`` (never a secret; long values cut short), its ``connection``
    (``None`` for a step that takes no account, else ``{attached, healthy,
    hint}``: ``healthy`` is ``None`` when NoClick can't tell) and, for a
    trigger, its ``trigger`` state (``{error, paused_reason, next_run}``;
    ``None`` for any other step)."""

    id: str
    name: str
    type: str
    operation: Optional[str]
    enabled: bool = True
    settings: Dict[str, Any] = dc_field(default_factory=dict)
    connection: Optional[Dict[str, Any]] = None
    trigger: Optional[Dict[str, Any]] = None

    @classmethod
    def _from(cls, raw: Any) -> "WorkflowStep":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("id") or "", raw.get("name") or "", raw.get("type") or "", raw.get("operation"),
                   raw.get("enabled", True) is not False, dict(raw.get("settings") or {}), raw.get("connection"),
                   raw.get("trigger"))


@dataclass(frozen=True)
class BuildQuestion:
    """What a build waits on. Each of ``inputs`` is ``{id, label, type,
    description, options?, request_id?}``: ``request_id`` is the human request
    that asks it, which NoClick sent the person whose build it is (``sent_to``)
    and any client answers (its page, a chat's card, their texts,
    ``POST /v1/humans/requests/{id}/answer``); the build goes on once each is
    answered. Or answer them all at once with
    ``build.answer({id: value})``, which goes on now: an input of type
    ``credential`` takes a connection's ref or name, one of type ``env`` its
    values in ``secret_values`` (both with a key acting for the whole
    account). ``answer_url`` is a page anyone holding it answers on."""

    id: Optional[str]
    title: Optional[str]
    inputs: List[Dict[str, Any]]
    answer_url: Optional[str]
    answerable_from_code: bool
    raw: Dict[str, Any] = dc_field(repr=False)
    sent_to: List[str] = dc_field(default_factory=list)

    @classmethod
    def _from(cls, raw: Any) -> "BuildQuestion":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("id"), raw.get("title"), list(raw.get("inputs") or []), raw.get("answer_url"),
                   bool(raw.get("answerable_from_code")), raw, list(raw.get("sent_to") or []))


@dataclass(frozen=True)
class WorkflowBuildResult:
    """A finished build: what the builder says it did (``summary``), the
    workflow's ``steps`` as they now stand, and, when it published the
    workflow's app, ``published`` (``{state, url}``: ``state`` is
    ``published``, ``renamed`` or ``unpublished``; unpublished, its
    ``trash_id`` restores it until ``restorable_until``).

    Beside the builder's words, facts no model wrote: whether it ``built``
    anything (``False``: the workflow is as it was, whatever ``summary``
    says), the ``version`` it ended on (what ``edit(if_version=...)`` takes),
    its ``readiness`` as ``Workflow.readiness`` reads it (``status``,
    ``meaning``, ``issues``, ``warnings``, ``unverified``), and each step's
    verdict by step id (``verdicts``: ``config_valid``, ``validation_error``,
    ``missing_required``, as an edit answers them). ``sent_back`` counts the
    times the build went back to the builder for settings the run engine
    rejects (at most 2) before it finished. A fact NoClick couldn't read is
    ``None`` and named in ``unread``: then nothing says the workflow is
    ready."""

    workflow_id: Optional[str]
    summary: Optional[str]
    steps: List[WorkflowStep]
    app_url: Optional[str]
    published: Optional[Dict[str, Any]] = None
    built: Optional[bool] = None
    version: Optional[int] = None
    readiness: Optional[Dict[str, Any]] = None
    verdicts: Optional[Dict[str, Dict[str, Any]]] = None
    sent_back: int = 0
    unread: List[str] = dc_field(default_factory=list)
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "WorkflowBuildResult":
        raw = raw if isinstance(raw, dict) else {}
        readiness, verdicts = raw.get("readiness"), raw.get("verdicts")
        return cls(raw.get("workflow_id"), raw.get("summary"), [WorkflowStep._from(s) for s in raw.get("steps") or []],
                   raw.get("app_url"), raw.get("published"), built=raw.get("built"), version=raw.get("version"),
                   readiness=dict(readiness) if isinstance(readiness, dict) else None,
                   verdicts=dict(verdicts) if isinstance(verdicts, dict) else None,
                   sent_back=int(raw.get("sent_back") or 0), unread=list(raw.get("unread") or []), raw=raw)


@dataclass(frozen=True)
class WorkflowRehearsal:
    """A workflow's test run, as the app's Test Run plays one: a staged event arrived at one of its triggers
    (``trigger``: ``{step_id, type, name}``) and the agents it reached took a real turn while a simulated world
    answered every tool call, so nothing was sent and no account was touched. ``test_run`` is the run it played
    (``{key, name, custom}``; ``None`` for a message you typed). ``reply`` is the agent's closing words;
    ``tool_calls`` the calls it made, each with its ``tool``, ``arguments`` and the ``result`` the world answered
    (and ``outbound``, the message it would have sent, for a call that carries one); ``transcript`` the run step by
    step (``role`` ``assistant`` steps, its ``text``, and ``tool`` steps; a coding harness's own shell and file steps
    carry ``source`` ``harness``). ``scenario`` is the world it ran in, ``note`` says when it wrote nothing or what
    it did to act was simulated, and ``cost_usd`` is what it cost you."""

    workflow_id: Optional[str]
    test_run: Optional[Dict[str, Any]]
    trigger: Optional[Dict[str, Any]]
    reply: str
    tool_calls: List[Dict[str, Any]]
    transcript: List[Dict[str, Any]]
    scenario: Optional[str]
    note: Optional[str]
    cost_usd: Optional[float]
    operation_id: Optional[str]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class WorkflowTestRun:
    """A test run a workflow offers (``Workflow.test_runs``), as its Test Run screen lists it: a staged situation for
    one of its triggers, or one the workflow authored (``custom``; ``edit().add_test_run``). ``key`` and ``name``
    each name it to ``rehearse``. ``trigger`` is what it stages on (``{type, label, operation}``: the trigger step's
    type, the type's name in the app and the step's operation), and ``message`` the staged message as the run would
    stage it (``title``, ``body``, and where it has them ``author``, ``handle``, ``meta`` and ``time``): an offered
    situation's with the workflow's edits, an authored run's own."""

    key: str
    name: str
    custom: bool
    trigger: Dict[str, Any]
    message: Dict[str, Any]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "WorkflowTestRun":
        raw = raw if isinstance(raw, dict) else {}
        return cls(key=str(raw.get("key") or ""), name=str(raw.get("name") or ""), custom=raw.get("custom") is True,
                   trigger=dict(raw.get("trigger") or {}), message=dict(raw.get("message") or {}), raw=raw)


def _read_rehearsal(result: Any, op: Operation) -> WorkflowRehearsal:
    result = result if isinstance(result, dict) else {}
    return WorkflowRehearsal(
        workflow_id=result.get("workflow_id"), test_run=result.get("test_run"), trigger=result.get("trigger"),
        reply=result.get("reply") or "", tool_calls=list(result.get("tool_calls") or []),
        transcript=list(result.get("transcript") or []), scenario=result.get("scenario"), note=result.get("note"),
        cost_usd=result.get("cost_usd"), operation_id=op._known("id"), raw=result,
    )


@dataclass(frozen=True)
class WorkflowDraftResult:
    """A finished draft: the workflow's ``version`` once the drafted steps were written (one version of its
    history, ``history_version``; ``changed`` false when the drafter changed nothing), a ``summary`` of what
    changed, and for each step it drafted (``steps``, by id) the verdict an edit answers (``config_valid``,
    ``validation_error``, ``missing_required``, ``references``) beside ``drafted``, its ``operation``, the
    ``settings`` it wrote, the ones it left for a person (``unfilled``: a choice read from the connected account, a
    value only they know) and, for a step it couldn't draft (left as it was), its ``error``."""

    workflow_id: str
    mode: str
    version: Optional[int]
    history_version: Optional[int]
    changed: bool
    summary: Optional[str]
    steps: Dict[str, Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "WorkflowDraftResult":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("workflow_id") or "", raw.get("mode") or "full", raw.get("version"),
                   raw.get("history_version"), bool(raw.get("changed")), raw.get("summary"),
                   {str(k): dict(v) for k, v in (raw.get("steps") or {}).items()}, raw)


def _read_run(result: Any, op: Operation) -> WorkflowRun:
    return WorkflowRun._from(result)


def _read_build(result: Any, op: Operation) -> WorkflowBuildResult:
    return WorkflowBuildResult._from(result)


def _read_draft(result: Any, op: Operation) -> WorkflowDraftResult:
    return WorkflowDraftResult._from(result)


register_result("workflow.run", _read_run)
register_result("workflow.build", _read_build)
register_result("workflow.rehearse", _read_rehearsal)
register_result("workflow.draft", _read_draft)

# How often next_question looks while the build works (the server's wait answers only once it's done).
_QUESTION_POLL_S = 2.0
# How long one read in a build's wait() lets the server hold it, so a question surfaces within seconds.
_QUESTION_WAIT_S = 5


class WorkflowBuild(Operation):
    """A build of a workflow from a description (kind ``workflow.build``). It's
    an ``Operation``: ``wait()`` returns the ``WorkflowBuildResult``, or raises
    why the build failed.

    While it builds, ``step`` is ``building``. When the builder needs something
    it's ``awaiting_human`` (step ``asking``) and ``question`` says what: each
    input is a human request NoClick sent the person whose build it is, and the
    build goes on once they answer; or answer it all now with ``answer()``.
    ``wait()`` stops at a question it hasn't shown you, raising
    ``noclick.AnswerRequired`` with it; called again, it waits through that
    question for its answer. ``next_question()`` returns as soon as there is one."""

    workflow_id: Optional[str] = field("workflow_id")
    _wait_window_s = _QUESTION_WAIT_S

    def _shown(self, question: BuildQuestion) -> bool:
        """Whether ``question`` was already shown to the caller; records that it now has been."""
        shown = self.__dict__.setdefault("_questions_shown", set())
        if question.id in shown:
            return True
        shown.add(question.id)
        return False

    def _waited(self) -> bool:
        raw = self._raw or {}
        if raw.get("status") == "awaiting_human" and raw.get("question"):
            question = BuildQuestion._from(raw["question"])
            if not self._shown(question):
                asks = question.title or next((i.get("label") for i in question.inputs if i.get("label")), None)
                err = AnswerRequired(
                    f"The build is waiting on an answer: {asks or 'the builder has a question'}",
                    next_step=("Answer it with build.answer({input id: value}), or let the person NoClick sent each "
                               "input's request (question.sent_to) answer it; then call wait() again."),
                    details={"operation_id": self._id(), "question": raw["question"]},
                )
                err.question = question
                raise self._linked(err)
        return super()._waited()

    @property
    def question(self) -> Optional[BuildQuestion]:
        """What the build waits on (``None`` unless it's asking)."""
        raw = self._sync_raw()
        return BuildQuestion._from(raw["question"]) if raw.get("question") else None

    @synced
    async def next_question(self, timeout: Optional[float] = None) -> Optional[BuildQuestion]:
        """Block until the build asks something (its ``question``) or finishes (``None``: ``wait()`` gives the result).

        Returns:
            The question to answer, or ``None`` once the build is done.

        Usage::

            build = noclick.Workflow.from_name("Morning brief").build("Also post it to #team on Slack")
            while (question := build.next_question(timeout=600)) is not None:
                build.answer({question.inputs[0]["id"]: "#team"})
            print(build.wait().summary)
        """
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        while True:
            self._absorb(await self._request("GET", f"/v1/operations/{self._id()}"))
            raw = self._raw or {}
            if raw.get("status") == "awaiting_human" and raw.get("question"):
                question = BuildQuestion._from(raw["question"])
                self._shown(question)
                return question
            if raw.get("status") in ("succeeded", "failed", "canceled", "expired"):
                return None
            if deadline is not None and loop.time() >= deadline:
                from .exceptions import OperationTimeout

                raise OperationTimeout(f"Build {self._id()} is still {raw.get('status')} after {timeout}s.",
                                       next_step="Call next_question() or wait() again.",
                                       details={"operation_id": self._id()})
            await asyncio.sleep(_QUESTION_POLL_S)

    @synced
    async def answer(
        self, values: Optional[Dict[str, Any]] = None, *, message: Optional[str] = None, skip: bool = False,
        secret_values: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> "WorkflowBuild":
        """Answer the question the build waits on, all at once, by input id: the
        build goes on now. Each value answers its input's human request as your
        key; those you leave unanswered are withdrawn. A choice, words, or for a
        ``credential`` input a connection's ref or name; an ``env`` input's values
        go in ``secret_values`` (``{input id: {KEY: value}}``), kept as the
        account's secret and never shown to a model. An account or a secret
        takes a key acting for the whole account. ``message`` tells the builder
        anything else, ``skip=True`` goes on without answering.

        Returns:
            This build, ``running`` again.

        Usage::

            build = noclick.Workflow.from_name("Morning brief").build("Send it on Slack too")
            question = build.next_question()
            if question:
                build.answer({"channel": "#team"}, message="Keep it under five lines")
            print(build.wait().steps)
        """
        workflow_id = self.workflow_id or (self._sync_raw().get("input") or {}).get("workflow_id")
        raw = await self._request("POST", f"/v1/workflows/{workflow_id}/builds/{self._id()}/answer",
                                  json=compact(values=values or {}, secret_values=secret_values, message=message,
                                               skip=skip or None))
        self._absorb(raw)
        return self


# --- the graph ----------------------------------------------------------

# A step's config holds these beside its settings; each is a field of its own on a ``Step``.
_OWN_FIELDS = frozenset({"label", "operation", "disabled", "credentialIds", "mockedOutput"})
# The canvas's node shape keeps these beside its ``data.config`` (the API's shape keeps them all in ``config``).
_DATA_FIELDS = ("label", "operation", "credentialIds", "model", "disabled", "mockedOutput")
_NOTE = "stickyNote"
# The handle a step wired into an agent as its tools joins on.
_TOOLS_HANDLE = "bottom"

Position = Union[Tuple[float, float], Mapping[str, float]]


def _node_config(node: Mapping[str, Any]) -> Dict[str, Any]:
    """A stored step's config, from either node shape the graph holds."""
    merged: Dict[str, Any] = {}
    data = node.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("config"), dict):
            merged.update(data["config"])
        merged.update({k: data[k] for k in _DATA_FIELDS if k in data and k not in merged})
    if isinstance(node.get("config"), dict):
        merged.update(node["config"])
    return merged


def _edge(raw: Mapping[str, Any]) -> Dict[str, Any]:
    tools = raw.get("targetHandle") == _TOOLS_HANDLE
    return {"id": raw.get("id"), "from": raw.get("source") or raw.get("sourceId"),
            "to": raw.get("target") or raw.get("targetId"), "kind": "tools" if tools else "data",
            "handle": raw.get("sourceHandle"), "target_handle": None if tools else raw.get("targetHandle")}


def _new_id(kind: str) -> str:
    """An id for a step added without one, made as the API makes one: its type, the time, six hex digits."""
    return f"{kind}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"


def _step_id(step: Any) -> str:
    if isinstance(step, Step):
        return step.id
    if isinstance(step, str):
        return step
    raise TypeError(f"A step is a noclick.Step or its id, not {type(step).__name__}")


def _position(value: Position) -> Dict[str, float]:
    if isinstance(value, Mapping):
        return {"x": value["x"], "y": value["y"]}
    x, y = value
    return {"x": x, "y": y}


async def _secret_names(secrets: Any) -> List[str]:
    """An agent step's ``secrets`` as the API takes them: names (a ``noclick.Secret`` is its name, once it's loaded,
    or created by ``from_name(..., create_if_missing=True)``)."""
    from .secret import Secret

    names: List[str] = []
    for secret in [secrets] if isinstance(secrets, (str, Secret)) else secrets:
        if isinstance(secret, Secret):
            names.append((await secret._ensure())["name"])
        elif isinstance(secret, str):
            names.append(secret)
        else:
            raise TypeError(f"A secret is a noclick.Secret or its name, not {type(secret).__name__}")
    return names


async def _sent(op: Dict[str, Any]) -> Dict[str, Any]:
    """``op`` as the API takes it: a connection given as an object is its ref, secrets given as objects their names."""
    if op["op"] == "set_connection":
        return {**op, "connection": await ref_id(op["connection"])}
    settings = op.get("settings")
    if op["op"] in ("add_step", "update_step") and isinstance(settings, Mapping) and settings.get("secrets"):
        return {**op, "settings": {**settings, "secrets": await _secret_names(settings["secrets"])}}
    return op


def _step_settings(settings: Optional[Dict[str, Any]], secrets: Any) -> Optional[Dict[str, Any]]:
    """A step's ``settings``, with an agent step's ``secrets`` (resolved to names when sent)."""
    if secrets is None:
        return settings
    return {**(settings or {}), "secrets": list(secrets) if isinstance(secrets, (list, tuple)) else [secrets]}


def _add_step_op(kind: str, operation: Optional[str], settings: Optional[Dict[str, Any]], name: Optional[str],
                 step_id: Optional[str], position: Optional[Position], secrets: Any = None) -> Dict[str, Any]:
    return compact(op="add_step", type=kind, operation=operation, settings=_step_settings(settings, secrets),
                   name=name, id=step_id or _new_id(kind),
                   position=_position(position) if position is not None else None)


def _update_step_op(step: Any, settings: Optional[Dict[str, Any]], name: Optional[str], operation: Optional[str],
                    enabled: Optional[bool], secrets: Any = None) -> Dict[str, Any]:
    return compact(op="update_step", id=_step_id(step), settings=_step_settings(settings, secrets), name=name,
                   operation=operation, enabled=enabled)


def _connect_op(op: str, source: Any, target: Any, **fields: Any) -> Dict[str, Any]:
    return {"op": op, "from": _step_id(source), "to": _step_id(target), **compact(**fields)}


def _note_op(content: str, note_id: Optional[str], **fields: Any) -> Dict[str, Any]:
    return {"op": "add_note", "content": content, "id": note_id or _new_id(_NOTE), **compact(**fields)}


def _update_workflow_op(name: Optional[str], description: Optional[str], settings: Optional[Dict[str, Any]],
                        display_metadata: Optional[Dict[str, Any]] = None,
                        interface: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return compact(op="update_workflow", name=name, description=description, settings=settings,
                   display_metadata=display_metadata, interface=interface)


@dataclass(frozen=True)
class StepOption:
    """One choice a step's setting takes, as the app's dropdown lists it: its ``value`` (what the setting takes),
    its ``label`` and what the service says beside it (``metadata``: an icon, a count, ``None`` for none)."""

    value: Any
    label: Any
    metadata: Optional[Dict[str, Any]]

    @classmethod
    def _from(cls, raw: Any) -> "StepOption":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("value"), raw.get("label"), raw.get("metadata"))


@dataclass(frozen=True)
class StepOptions:
    """A page of the choices a step's ``field`` takes (``Step.options``). ``next_page_token`` reads the next page;
    ``withheld`` names, by path, a choice or a part of one left out because it held a secret."""

    field: str
    options: List[StepOption]
    next_page_token: Optional[str]
    withheld: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "StepOptions":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("field") or "", [StepOption._from(o) for o in raw.get("options") or []],
                   raw.get("next_page_token"), list(raw.get("withheld") or []), raw)


@dataclass(frozen=True)
class StepValue:
    """A widget's value on a step (``Step.value``): ``value``, or ``values`` where it fills several of the step's
    settings at once (a trigger's address, whether it's registered, why not). ``withheld`` names, by path, what was
    left out because it held a secret (a webhook's signing secret, a signed upload link)."""

    field: str
    value: Any
    values: Optional[Dict[str, Any]]
    withheld: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "StepValue":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("field") or "", raw.get("value"), raw.get("values"), list(raw.get("withheld") or []), raw)


@dataclass(frozen=True)
class StepPublication:
    """What ``Step.publish``, ``Step.rename_app`` and ``Step.unpublish`` left of an interface step's app: its
    ``state`` (``published``, ``renamed`` or ``unpublished``) and ``url``, as a build's ``published`` names them;
    the app itself (``project_id``, a ``noclick.Project``'s id, and its ``subdomain``); the release a publish made
    (``deployment_id``); where it answered before a rename or an unpublish (``previous_url``); and, unpublished,
    the trash entry that restores it (``trash_id``) until ``restorable_until``."""

    workflow_id: str
    step_id: str
    action: str
    state: str
    url: Optional[str]
    project_id: Optional[str]
    subdomain: Optional[str]
    deployment_id: Optional[str]
    previous_url: Optional[str]
    trash_id: Optional[str]
    restorable_until: Any
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "StepPublication":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("workflow_id") or "", raw.get("step_id") or "", raw.get("action") or "",
                   raw.get("state") or "", raw.get("url"), raw.get("project_id"), raw.get("subdomain"),
                   raw.get("deployment_id"), raw.get("previous_url"), raw.get("trash_id"),
                   parse_time(raw.get("restorable_until")), raw)


class Step(_Object):
    """One step of a workflow's graph: its trigger, an app's operation, an agent, a
    note. ``Workflow.graph()`` reads them all; ``Workflow.step(id)`` is a handle to
    one by id that loads the first time you read a field.

    Its fields are as stored: ``type`` (``automation-gmail``, ``agent``,
    ``trigger-cron``), its ``name`` in the app, the ``operation`` it does,
    whether it's ``enabled``, its ``settings`` (never a secret: ``withheld``
    names the ones left out), its ``connections`` (each slot's connected account,
    by id), where it sits (``position``) and the output it gives on test runs
    instead of running (``mock_output``). A note on the canvas is a step of type
    ``stickyNote`` (its text is ``settings["content"]``), listed in
    ``WorkflowGraph.notes``.

    Each method is one edit, applied as its own version: the step comes back as
    written, with what the edit said about it (``notes``) and whether it's ready
    to run (``verdict``). To change several things at once, or only if the
    workflow hasn't changed since you read it, use ``Workflow.edit()``."""

    _repr_keys = ("id", "type", "name")
    _workflow: "Workflow"

    def _init(self, **kwargs: Any) -> None:
        self._withheld: List[str] = []
        self._verdict: Optional[Dict[str, Any]] = None
        self._notes: Dict[str, Any] = {}
        super()._init(**kwargs)

    @classmethod
    def _of(cls, workflow: "Workflow", step_id: str, node: Optional[Dict[str, Any]] = None,
            withheld: Sequence[str] = ()) -> "Step":
        step = cls._new(raw=node, hints={"id": step_id}, client=workflow._client, user=None)
        step._workflow = workflow
        step._withheld = list(withheld)
        return step

    def _call_scope(self) -> Any:
        return None

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Step):
            return NotImplemented
        return self.id == other.id and self._workflow == other._workflow

    def __hash__(self) -> int:
        return hash(("Step", self.id))

    # --- reading -----------------------------------------------------------

    def _from_graph(self, graph: "WorkflowGraph") -> Dict[str, Any]:
        node = graph._node(self.id)
        if node is None:
            raise NotFound(f"No step {self.id!r} in this workflow.",
                           next_step="Read its steps with workflow.graph().steps.", details={"step": self.id})
        self._withheld = list(graph.withheld.get(self.id) or [])
        return node

    async def _load(self) -> Dict[str, Any]:
        return self._from_graph(await self._workflow._read_graph())

    async def _ensure(self) -> Dict[str, Any]:
        if self._raw is None:
            cached = self._workflow._graph
            known = cached is not None and cached._node(self.id) is not None
            self._raw = self._from_graph(cached) if known else await self._load()
        return self._raw

    def _config(self) -> Dict[str, Any]:
        return _node_config(self._sync_raw())

    @property
    def id(self) -> str:
        """Its id in the workflow, which edits name it by."""
        return self._hints["id"]

    @property
    def workflow(self) -> "Workflow":
        """The workflow it's a step of."""
        return self._workflow

    @property
    def type(self) -> str:
        """What kind of step it is: ``automation-gmail``, ``agent``, ``trigger-cron``, ``stickyNote`` for a note."""
        return str(self._sync_raw().get("type") or "")

    @property
    def name(self) -> Optional[str]:
        """Its name in the app (``None`` when it has none and the app shows its type)."""
        return self._config().get("label") or None

    @property
    def operation(self) -> Optional[str]:
        """What it does, one of its type's operations (``None`` for a step with one thing to do)."""
        return self._config().get("operation") or None

    @property
    def enabled(self) -> bool:
        """Whether it runs: a step switched off (``update(enabled=False)``) is passed over."""
        raw = self._sync_raw()
        return not (raw.get("disabled") or self._config().get("disabled"))

    @property
    def settings(self) -> Dict[str, Any]:
        """Its settings, by field name, as stored (a secret is never read back: see ``withheld``)."""
        return {k: v for k, v in self._config().items() if k not in _OWN_FIELDS and not k.endswith("__label")}

    @property
    def connections(self) -> Dict[str, str]:
        """The accounts connected to it: each slot (a connection type, like ``gmail_oauth``) to the id of the
        account connected there, which the connection holding it names as its ``credential_id``.
        ``set_connection`` changes them."""
        found = self._config().get("credentialIds")
        return dict(found) if isinstance(found, dict) else {}

    @property
    def position(self) -> Optional[Dict[str, float]]:
        """Where it sits on the canvas: ``{"x", "y"}``."""
        found = self._sync_raw().get("position")
        return dict(found) if isinstance(found, dict) else None

    @property
    def mock_output(self) -> Any:
        """What it outputs on test runs instead of running (``mock()``), or ``None``."""
        return self._config().get("mockedOutput", self._sync_raw().get("mockedOutput"))

    @property
    def withheld(self) -> List[str]:
        """The settings left out of ``settings`` because they hold a secret (a key, a token, a
        password), each by its path: ``api_key``, ``auth.password``, ``headers[0].value``. An
        update that leaves them out keeps them."""
        self._sync_raw()
        return list(self._withheld)

    @property
    def verdict(self) -> Optional[Dict[str, Any]]:
        """Whether it's ready to run, as the last edit through this handle that touched it judged:
        ``config_valid``, and when it isn't, ``validation_error`` and ``missing_required``; an agent's
        ``agent_credential_hint``; and ``references`` (see ``references``). ``None`` until an edit judged it (a
        read doesn't)."""
        return self._verdict

    @property
    def references(self) -> List[Dict[str, Any]]:
        """Each read of another step's output in its settings (``{{ $('x').key }}``) that won't resolve at run
        time, as the last edit through this handle that touched it judged: ``{field, step, key, known_keys}`` for a
        key ``x``'s output isn't known to have (``known_keys``: what it has, from what ``x`` declares, its latest
        output in this workflow, or what your account's own runs of its type showed), or ``{field, step,
        reference, missing, near}`` for a step ``x`` the workflow doesn't have (``near``: the one it likely
        means). A read of a step whose output nothing has shown yet isn't judged. Empty when every read resolves,
        or before an edit judged it."""
        return list((self._verdict or {}).get("references") or [])

    @property
    def notes(self) -> Dict[str, Any]:
        """What the last edit through this handle answered for its change, beyond the step's id: ``changed``
        for an update, the edge for a connect, and anything the edit did on its own, such as ``resolutions``
        (a value it resolved, like a model's full id), ``harness_switch`` (an agent moved to another harness,
        with the settings that went with the old one), ``coerced_values`` or ``stripped_trigger_refs``."""
        return dict(self._notes)

    def _absorb(self, edit: "WorkflowEdit", result: Optional[Dict[str, Any]] = None) -> None:
        """This step as ``edit`` wrote it, with what it said about it."""
        if edit.graph is not None:
            node = edit.graph._node(self.id)
            if node is not None:
                self._raw = node
                self._withheld = list(edit.graph.withheld.get(self.id) or [])
        if result is not None:
            self._notes = {k: v for k, v in result.items() if k not in ("op", "id")}
        if self.id in edit.steps:
            self._verdict = edit.steps[self.id]

    async def _edit(self, op: Dict[str, Any], *also: Any) -> "Step":
        return await self._workflow._edit_step(self, op, *also)

    # --- what its form shows -------------------------------------------------

    async def _form(self, kind: str, body: Dict[str, Any]) -> Any:
        return await self._request("POST", f"{await self._step_path()}/{kind}", json=compact(**body))

    @synced
    async def options(
        self, field: str, *, settings: Optional[Dict[str, Any]] = None, search: Optional[str] = None,
        page_token: Optional[str] = None, type: Optional[str] = None, connection: Optional[str] = None,
    ) -> StepOptions:
        """The choices ``field`` takes, as the app's dropdown lists them: read from the account the
        step connects to (a Google account's spreadsheets, a Slack workspace's channels) by the
        step's own lookup, with its settings as saved and ``settings`` laid over them (what a list
        that depends on another reads, like the tabs of a spreadsheet you haven't saved yet).
        ``search`` narrows them where the service can search. A page at a time: pass
        ``page_token=`` its ``next_page_token``. A connection whose owner reviews its calls holds
        the lookup for them (``noclick.ApprovalRequired``). A step the workflow doesn't hold yet
        (one a canvas added and hasn't saved) lists its choices by its ``type``
        (``automation-slack``), and ``connection`` (a connection's ref or id) names the account to
        read from in place of the one the step holds. Takes read access to the workflow: whoever
        can change it reads through the step's account as a run does, anyone else only through
        an account that's theirs to use.

        Returns:
            The ``StepOptions``: ``options`` (each a ``StepOption``), ``next_page_token`` and
            ``withheld``.

        Usage::

            sheet = noclick.Workflow.from_name("Morning brief").step("read_sheet")
            for choice in sheet.options("spreadsheet_id").options:
                print(choice.value, choice.label)
            tabs = sheet.options("sheet_name", settings={"spreadsheet_id": "1AbCdEf"})
        """
        raw = await self._form("options", {"field": field, "settings": settings, "search": search,
                                           "page_token": page_token, "type": type, "connection": connection})
        return StepOptions._from(raw)

    @synced
    async def value(self, field: str, *, settings: Optional[Dict[str, Any]] = None) -> StepValue:
        """A widget's value on the step, as the app loads it beside the step's settings: a
        trigger's address, minted and registered where its events come from (``webhook_url``), an
        app's event subscription (``subscription_status``), the files in a filesystem step's
        volume (``file_browser``), an alarm's schedules (``active_alarms``), an MCP step's hosted
        link (``hosted_url``). ``settings`` are laid over the step's saved ones. One that mints or
        registers something changes the account, and takes what changing the workflow takes; one
        that only reads (a list, an id from the step's account) takes read access. A hosted MCP
        link's URL is its capability, so no MCP connection loads it.

        Returns:
            The ``StepValue``: ``value``, or ``values`` where it fills several settings at once,
            and ``withheld``.

        Usage::

            hook = noclick.Workflow.from_name("Order intake").step("hook")
            print(hook.value("webhook_url").values["webhook_url"])
        """
        return StepValue._from(await self._form("values", {"field": field, "settings": settings}))

    # --- changing it -------------------------------------------------------

    @synced
    async def update(
        self, *, settings: Optional[Dict[str, Any]] = None, name: Optional[str] = None,
        operation: Optional[str] = None, enabled: Optional[bool] = None, secrets: Any = None,
    ) -> "Step":
        """Change its settings, name or operation, or switch it off or on. ``settings`` merge
        into what it has (a nested object merges, any other value replaces, and ``None`` takes
        that setting out, a secret included); a field you leave out is never touched. An agent
        given another ``model`` on another harness drops the
        old harness's own settings and connections, as the app does (``notes["harness_switch"]``
        says what went). Values are judged as a run judges them: one that can't be is refused
        with ``noclick.InvalidRequest`` naming the field, and nothing changes.

        ``secrets`` (an agent step's) are the account's own secrets in its shell's environment
        on every run, ``noclick.Secret`` objects or their names, replacing the ones it had
        (``[]`` takes them all off). Only a key acting for the whole account of the workflow's
        owner gives a step one, and an agent's own tools as your approval settings let them
        (``attach_connection``, allowed by default); any other caller keeps or drops what it
        was given. Their values never show in a read of the workflow, nor to the agent's model.

        Returns:
            This step as written, with ``notes`` and ``verdict``.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            send = brief.step("send_summary")
            send.update(settings={"to": "team@acme.com", "subject": "Today"}, name="Email the team")
            print(send.verdict)   # {"config_valid": True}
            brief.step("summarize").update(secrets=["warehouse"])
        """
        return await self._edit(_update_step_op(self, settings, name, operation, enabled, secrets))

    @synced
    async def patch(self, field: str, patch: str) -> "Step":
        """Change part of one long text setting (an agent's instructions, a step's code)
        with a patch: ``@@`` lines naming text that's there, then ``-`` lines to remove and
        ``+`` lines to add. Text the patch names that isn't there is refused.

        Returns:
            This step as written.

        Usage::

            writer = noclick.Workflow.from_name("Morning brief").step("writer")
            writer.patch("system_prompt", "@@ Keep it short.\\n-Keep it short.\\n+Keep it under five lines.")
        """
        return await self._edit({"op": "patch_step", "id": self.id, "field": field, "patch": patch})

    @synced
    async def remove(self) -> None:
        """Take the step out of the workflow, with its edges. A trigger's schedule or webhook
        stops with it. Removing a step that holds an app, conversations or files deletes them for
        good, so it may be held for the account's owner (``noclick.ApprovalRequired``), as a
        batch is (``Workflow.edit``).

        Usage::

            noclick.Workflow.from_name("Morning brief").step("old_digest").remove()
        """
        await self._workflow._send([{"op": "remove_step", "id": self.id}], include_graph=True)

    @synced
    async def connect(self, other: Any, *, kind: str = "data", handle: Optional[str] = None,
                      target_handle: Optional[str] = None) -> "Step":
        """Wire this step into ``other`` (a ``Step`` or its id). ``kind="data"`` runs ``other``
        after it with its output; ``kind="tools"`` makes its operations tools of ``other``, an
        agent (or an MCP step). ``handle`` names which of this step's outputs, for a step with
        several (an iteration's ``loop``), and ``target_handle`` which of ``other``'s inputs (a
        code step's ``state``). Connecting what's already connected changes nothing.

        Returns:
            This step; ``notes`` holds the edge (``edge_id``, ``kind``).

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            brief.step("summarize").connect("send_summary")
            brief.step("linear").connect("triage_agent", kind="tools")
        """
        return await self._edit(_connect_op("connect", self, other, kind=kind, handle=handle,
                                            target_handle=target_handle), other)

    @synced
    async def disconnect(self, other: Any, *, handle: Optional[str] = None) -> "Step":
        """Remove the edge from this step to ``other`` (a ``Step`` or its id); one that isn't
        there raises ``noclick.InvalidRequest``.

        Returns:
            This step.

        Usage::

            noclick.Workflow.from_name("Morning brief").step("summarize").disconnect("send_summary")
        """
        return await self._edit(_connect_op("disconnect", self, other, handle=handle), other)

    @synced
    async def set_connection(self, connection: Any, *, slot: Optional[str] = None) -> "Step":
        """Connect an account to the step: one of the account's own connections, as a
        ``noclick.Connection`` (connected in the app, ``credential:<id>``, or a named one), its
        ref or id, or a named connection's name; the step takes the account it holds. Its slot
        is the account's own type unless ``slot`` names it. ``connection=None`` with ``slot``
        takes the account in that slot off. One of a user's connections, one holding no
        working account, or one your account may not use is refused (``noclick.InvalidRequest``
        naming it), as is one of a type the step doesn't take; a caller that doesn't act for
        the whole account (a user's key, an app's code) only keeps one the workflow already
        uses. An agent's own tools attach your account's own connections in your account's own
        workflows, never another member's, a user's or one held for someone else, as your
        approval settings let them (``attach_connection``: allowed by default; asked, the edit
        waits for the owner's yes, ``noclick.ApprovalRequired``).

        Returns:
            This step, its ``connections`` as written.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            gmail = noclick.Connection.from_id("credential:9b2a1c5e-7d9f-4a31-8f6d-3f1d2c4b8a7e")
            brief.step("send_summary").set_connection(gmail)
            brief.step("post").set_connection("work-slack")  # a named connection, by its name
        """
        return await self._edit({"op": "set_connection", "id": self.id, "connection": connection,
                                 **compact(slot=slot)})

    @synced
    async def mock(self, output: Any) -> "Step":
        """Have the step give ``output`` on test runs instead of running (no email sent,
        no API called), so the steps after it can be tried.

        Returns:
            This step, its ``mock_output`` set.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            brief.step("read_calendar").mock({"events": [{"title": "Standup", "start": "09:00"}]})
        """
        return await self._edit({"op": "mock_step", "id": self.id, "output": output})

    @synced
    async def unmock(self) -> "Step":
        """Have the step run for real on test runs again.

        Returns:
            This step.

        Usage::

            noclick.Workflow.from_name("Morning brief").step("read_calendar").unmock()
        """
        return await self._edit({"op": "unmock_step", "id": self.id})

    @synced
    async def run(self, *, only: bool = False, user: Any = AMBIENT, idempotency_key: Optional[str] = None) -> Operation:
        """Run the workflow from this step: it and what comes after it (``only=True``: it alone), the steps
        before it giving the outputs they last stored. ``Workflow.run(from_step=...)`` says more.

        Returns:
            An operation whose ``.wait()`` gives the finished ``WorkflowRun``.

        Usage::

            summarize = noclick.Workflow.from_name("order-intake").step("summarize")
            print(summarize.run(only=True).wait().outputs)
        """
        return await self._workflow.run.aio(from_step=self.id, only=only, user=user, idempotency_key=idempotency_key)

    # --- what it produced --------------------------------------------------

    async def _step_path(self) -> str:
        return f"{await self._workflow._path()}/steps/{path_segment(self.id)}"

    async def _outputs_path(self) -> str:
        return f"{await self._step_path()}/outputs"

    @synced
    async def outputs(
        self, *, search: Optional[str] = None, limit: Optional[int] = 10, user: Any = AMBIENT,
    ) -> List[StepOutput]:
        """What the step produced, run by run, newest first, each a ``StepOutput`` with its run,
        how that run started, the step's status there and a one-line ``preview``. A trigger's
        deliveries are its outputs (``no_event`` marks a manual run's placeholder). ``search``
        keeps those holding the text (any case), reading 100 at a time. Inside ``as_user`` (or
        with ``user=``) only the runs recorded for that user are read.

        Returns:
            The newest ``limit`` (10 by default; ``None`` for every one).

        Usage::

            hook = noclick.Workflow.from_name("order-intake").step("hook")
            for out in hook.outputs(search="o_1042"):
                print(out.created_at, out.source, out.preview)
        """
        return await list_all(await self._outputs_path(), lambda raw, _scope: StepOutput._from(raw),
                              params={"search": search}, user=user, limit=limit, client=self._client)

    @synced
    async def output(
        self, run_id: str, *, path: Optional[str] = None, full: bool = False, iteration: Optional[int] = None,
        user: Any = AMBIENT,
    ) -> StepOutput:
        """What the step produced in one run (``run_id``, as ``outputs()`` or ``Workflow.runs()``
        name it): its ``output``, long text and lists cut short unless ``full``, or only the
        part at ``path`` (``payload.items[0].id``, as a preview names it). ``iteration`` reads
        one iteration of a step that runs in a loop. Never a secret (``withheld``); a path to
        one raises ``noclick.InvalidRequest``, as does a path that isn't there (naming what is).

        Returns:
            The ``StepOutput``; a run the step stored nothing in raises ``noclick.NotFound``.

        Usage::

            hook = noclick.Workflow.from_name("order-intake").step("hook")
            latest = hook.outputs(limit=1)[0]
            print(hook.output(latest.run_id, path="items[0].sku").output)
        """
        raw = await self._api.request(
            "GET", f"{await self._outputs_path()}/{run_id}",
            params=compact(path=path, full="true" if full else None, iteration=iteration), user=resolve_scope(user),
        )
        return StepOutput._from(raw)

    @synced
    async def preview_expression(
        self, expression: str, *, samples: Optional[Dict[str, Any]] = None, user: Any = AMBIENT,
    ) -> ExpressionPreview:
        """What an expression in one of the step's settings gives, evaluated as a run
        evaluates it (what goes inside ``{{ }}``, like ``$('hook').order_id`` or
        ``$json.items.length``), as the app's editor previews it while you type. It's
        evaluated against what every other step last stored (never a secret, so an
        expression reaching one finds nothing there), or against ``samples``, each step's
        output by step id (``vars`` the workflow's variables). ``$json`` is the step's one
        input's output, when it has one. Changes nothing.

        Returns:
            The ``ExpressionPreview``; an expression that fails has ``ok`` False and its ``error``.

        Usage::

            note = noclick.Workflow.from_name("order-intake").step("summarize")
            print(note.preview_expression("$('hook').items.length").preview)   # 2
        """
        raw = await self._api.request(
            "POST", f"{await self._step_path()}/expression",
            json={"expression": expression, **compact(samples=samples)}, user=resolve_scope(user),
        )
        return ExpressionPreview._from(raw)

    @synced
    async def clear_state(self) -> ClearedStepState:
        """Forget what the step keeps between runs, as the app's Clear state does: its state
        (an RSS step's seen items, a State step's values) and its conversations (an agent
        step's threads), so its next run starts fresh. Clearing an agent step deletes its
        conversations for good: a deletion, which through MCP waits for your account's owner
        (preview it with ``POST /v1/delete_previews``). Takes what changing the workflow
        takes, and always acts for your account, never one of your users: an agent step's
        threads are every user's.

        Returns:
            How many state records and conversations were deleted.

        Usage::

            feed = noclick.Workflow.from_name("news digest").step("rss")
            print(feed.clear_state().state_rows_deleted)   # 1
        """
        raw = await self._api.request("POST", f"{await self._step_path()}/clear_state", user=None)
        return ClearedStepState._from(raw)

    # --- its app (an interface step) ---------------------------------------

    async def _publication(self, body: Dict[str, Any]) -> StepPublication:
        raw = await self._api.request("POST", f"{await self._step_path()}/publish", json=compact(**body), user=None)
        return StepPublication._from(raw)

    @synced
    async def publish(self, subdomain: Optional[str] = None, *, title: Optional[str] = None) -> StepPublication:
        """Put this interface step's app live as the app's canvas does, with no build: at
        ``subdomain`` the first time (``morrow`` is ``morrow.noclick.app``); again, the saved
        edits at the address it has (a ``subdomain`` other than its own raises
        ``noclick.Conflict``: ``rename_app`` moves it). An app in the trash comes back where it
        was. Its pages carry the account's one key for it. Takes what changing the workflow
        takes, and through MCP ``deploy``, as ``Workflow.publish`` does.

        Returns:
            The ``StepPublication``: ``state`` ``published``, the app's ``url``, its
            ``project_id`` and ``subdomain``, and the release (``deployment_id``).

        Usage::

            site = noclick.Workflow.from_name("Morrow Bakehouse site").step("page")
            print(site.publish("morrow").url)   # https://morrow.noclick.app
        """
        return await self._publication({"action": "publish", "subdomain": subdomain, "title": title})

    @synced
    async def rename_app(self, subdomain: str) -> StepPublication:
        """Move this interface step's app to ``subdomain``, publishing no edits; its old
        address stops answering.

        Returns:
            The ``StepPublication``: ``state`` ``renamed``, the new ``url`` and where it was
            (``previous_url``).

        Usage::

            noclick.Workflow.from_name("Morrow Bakehouse site").step("page").rename_app("morrow-bakery")
        """
        return await self._publication({"action": "rename", "subdomain": subdomain})

    @synced
    async def unpublish(self) -> StepPublication:
        """Take this interface step's app down, to the trash: its public URL stops answering and
        its page's key stops working. For 30 days its address stays its own, and restoring it
        (or ``publish()``) brings it back there with the same key. One not published changes
        nothing.

        Returns:
            The ``StepPublication``: ``state`` ``unpublished``, where it answered
            (``previous_url``) and the ``trash_id`` that restores it until ``restorable_until``.

        Usage::

            gone = noclick.Workflow.from_name("Morrow Bakehouse site").step("page").unpublish()
            noclick.TrashItem.from_id(gone.trash_id).restore()
        """
        return await self._publication({"action": "unpublish"})


@dataclass(frozen=True)
class WorkflowGraph:
    """A workflow's definition as it was read, at ``version``: its ``name``,
    ``description`` and ``settings`` (its variables, its Test Runs and the rest), its
    ``steps`` (each a ``Step`` you can change), its ``notes`` (steps of type
    ``stickyNote``) and its ``edges``.

    Each edge is ``{id, from, to, kind, handle}``: ``kind`` ``data``, or ``tools`` for a
    step wired into an agent as its tools; ``handle`` names which output of ``from`` it
    leaves (``None`` for its only one).

    A secret is never read back, and writing a step or the settings back without one keeps
    it: ``withheld`` names, by step id, the paths of the settings left out
    (``api_key``, ``auth.password``, ``headers[0].value``), ``settings_withheld`` those of
    the workflow's own settings (``variable_definitions[1].value``), and
    ``variables_withheld`` the graph's own variables. The graph a ``noclick.Conflict``
    carries holds the steps and edges alone: its ``name``, ``description``, ``settings``
    and ``settings_withheld`` are ``None``.

    An edge into a step with several inputs names which in ``target_handle`` (a code step's
    ``state``). ``display_metadata`` is what the app shows of the workflow (its canvas's
    viewport, the step open in its panel), read with ``graph()``: never part of a version.
    ``access`` is what you may do with it (``owner``, ``editor`` or ``viewer``) and ``agent``
    the agent whose own flow it is (``{id, name, yours}``, ``yours`` when it's your account's
    own), both read with ``graph()``."""

    workflow_id: str
    version: int
    name: Optional[str]
    description: Optional[str]
    settings: Optional[Dict[str, Any]]
    settings_withheld: Optional[List[str]]
    steps: List[Step]
    notes: List[Step]
    edges: List[Dict[str, Any]]
    withheld: Dict[str, List[str]]
    variables_withheld: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)
    display_metadata: Optional[Dict[str, Any]] = None
    access: Optional[str] = None
    agent: Optional[Dict[str, Any]] = None

    @classmethod
    def _from(cls, raw: Any, *, workflow: "Workflow", workflow_id: str, version: int,
              definition: Optional[Mapping[str, Any]] = None) -> "WorkflowGraph":
        """``raw``: the graph (``nodes``, ``edges``, ``withheld``); ``definition``: the answer it came in, with the
        workflow's own fields beside it (none for a conflict's)."""
        raw = raw if isinstance(raw, dict) else {}
        withheld = {str(k): list(v or []) for k, v in (raw.get("withheld") or {}).items()}
        nodes = [n for n in raw.get("nodes") or [] if isinstance(n, dict) and n.get("id") is not None]
        made = [Step._of(workflow, str(n["id"]), node=n, withheld=withheld.get(str(n["id"])) or ()) for n in nodes]
        own = definition or {}
        return cls(
            workflow_id=workflow_id, version=version, name=own.get("name"), description=own.get("description"),
            settings=dict(own["settings"]) if isinstance(own.get("settings"), dict) else None,
            settings_withheld=list(own.get("settings_withheld") or []) if definition is not None else None,
            steps=[s for s, n in zip(made, nodes) if n.get("type") != _NOTE],
            notes=[s for s, n in zip(made, nodes) if n.get("type") == _NOTE],
            edges=[_edge(e) for e in raw.get("edges") or [] if isinstance(e, dict)],
            withheld=withheld, variables_withheld=list(raw.get("variables_withheld") or []), raw=raw,
            display_metadata=dict(own["display_metadata"]) if isinstance(own.get("display_metadata"), dict) else None,
            access=own.get("access"), agent=dict(own["agent"]) if isinstance(own.get("agent"), dict) else None,
        )

    def _node(self, step_id: str) -> Optional[Dict[str, Any]]:
        return next((n for n in self.raw.get("nodes") or [] if isinstance(n, dict) and str(n.get("id")) == step_id),
                    None)

    def step(self, ref: str) -> Step:
        """One of its steps or notes, by id, else by its name in the app.

        Returns:
            The step. None by that id or name raises ``noclick.NotFound``; a name two steps
            share raises ``noclick.Conflict`` (name it by id).

        Usage::

            graph = noclick.Workflow.from_name("Morning brief").graph()
            send = graph.step("Send the summary")
            print(send.id, send.settings)
        """
        everything = [*self.steps, *self.notes]
        found = next((s for s in everything if s.id == ref), None)
        if found is not None:
            return found
        named = [s for s in everything if s.name == ref]
        if len(named) > 1:
            raise Conflict(f"{len(named)} steps are named {ref!r}.", next_step="Name the step by its id.",
                           details={"name": ref, "ids": [s.id for s in named]})
        if not named:
            raise NotFound(f"No step has the id or name {ref!r}.",
                           next_step="Read the steps' ids and names with graph.steps.", details={"step": ref})
        return named[0]


def _definition(raw: Mapping[str, Any], workflow: "Workflow") -> Optional[WorkflowGraph]:
    """The definition an answer carries beside its graph (``GET .../graph``, an edit with ``include_graph``, one
    version), or None when it carries none."""
    graph = raw.get("graph")
    if not isinstance(graph, dict):
        return None
    return WorkflowGraph._from(graph, workflow=workflow, workflow_id=raw.get("workflow_id") or "",
                               version=raw.get("version"), definition=raw)


@dataclass(frozen=True)
class WorkflowEdit:
    """What an edit did: the workflow's ``version`` once it and what it set in motion
    were written (a trigger's registration writes too), to edit on from; whether its
    definition ``changed`` (moving things on the canvas changes none); the version of
    its history it landed in (``history_version``, what ``version_at`` and ``restore``
    name: a version of its own, which this key's next edits join for five minutes from
    its first; a layout-only edit is none); a ``summary`` of what changed; each op's
    ``results`` in order (an added
    step's ``id``, and what the edit did on its own: ``resolutions``,
    ``harness_switch``, ``coerced_values``, ``stripped_trigger_refs``,
    ``http_auth_credential_hint``); and, for each step an op touched, whether it's ready
    to run (``steps``: ``config_valid``, ``validation_error``, ``missing_required``,
    ``agent_credential_hint``, and ``references``: each read of another step's output that
    won't resolve, as ``Step.references`` reads them). ``graph`` is the workflow as written, read as
    ``Workflow.graph()`` reads it, when the edit asked for it; ``restored_from`` names
    the version of its history a restore put back. ``warnings`` say what an edit did that
    won't work as it may look (a workspace member's own connection given to a team
    workflow's step, which its owner's automatic runs can't use). An edit sent with
    ``settle`` also says whether what it set going finished in time (``settled``) and, by
    step, why each trigger it left unregistered can't be registered yet (``unregistered``)."""

    workflow_id: str
    version: int
    history_version: Optional[int]
    changed: bool
    summary: Optional[str]
    results: List[Dict[str, Any]]
    steps: Dict[str, Dict[str, Any]]
    graph: Optional[WorkflowGraph]
    restored_from: Optional[int] = None
    warnings: List[str] = dc_field(default_factory=list)
    settled: Optional[bool] = None
    unregistered: Dict[str, str] = dc_field(default_factory=dict)
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any, workflow: "Workflow") -> "WorkflowEdit":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            workflow_id=raw.get("workflow_id") or "", version=raw.get("version"),
            history_version=raw.get("history_version"), changed=bool(raw.get("changed")), summary=raw.get("summary"),
            results=[dict(r) for r in raw.get("results") or []],
            steps={str(k): dict(v) for k, v in (raw.get("steps") or {}).items()},
            graph=_definition(raw, workflow), restored_from=raw.get("restored_from"),
            warnings=[str(w) for w in raw.get("warnings") or []], settled=raw.get("settled"),
            unregistered={str(k): str(v) for k, v in (raw.get("unregistered") or {}).items()}, raw=raw,
        )


@dataclass(frozen=True)
class WorkflowVersion:
    """One version of a workflow's history: its own number (``history_version``, what
    ``version_at`` and ``restore`` take, fixed once given), the workflow's ``version``
    its latest write left, where the change came from (``source``: ``api``,
    ``canvas``, ``builder``, ``mcp``, ``coordinator``, ``deploy``, ``restore``,
    ``baseline``, the workflow as it was before its history began, or ``checkpoint``, one
    saved in the app before its history was kept, numbered below 1), who began it
    (``author``: ``{user_id, key_id}``, ``None`` for the baseline) and everyone who
    wrote into it (``authors``, its author first), a ``summary`` and each of its
    ``changes``, and for a restore the version of the history it put back
    (``restored_from``). A named version (a checkpoint: ``Workflow.name_version``) has its
    ``label`` and ``note``, who named it (``labeled_by``: ``{user_id}``) and when
    (``labeled_at``), and is kept for good while it has a name.

    Saves in the app's canvas within five minutes of a session's first are one
    version, whoever made them. Any other change (from your code, the builder, an MCP
    client, NoClick's assistant, a restore) is a version of its own, which only the
    same key's next changes from the same place join, within five minutes of its
    first; so ``updated_at`` is its latest write. ``graph`` is the whole definition it
    holds, its name, description and settings with its steps, read with
    ``Workflow.version_at`` (``None`` in a list): a restore puts all of it back. Its
    steps are as they were then, and changing one changes the workflow's step of that
    id as it is now."""

    workflow_id: str
    history_version: int
    version: int
    source: str
    author: Optional[Dict[str, Any]]
    authors: List[Dict[str, Any]]
    summary: Optional[str]
    changes: List[str]
    restored_from: Optional[int]
    created_at: Any
    updated_at: Any
    graph: Optional[WorkflowGraph] = None
    label: Optional[str] = None
    note: Optional[str] = None
    labeled_by: Optional[Dict[str, Any]] = None
    labeled_at: Any = None
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any, workflow: "Workflow") -> "WorkflowVersion":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            workflow_id=raw.get("workflow_id") or "", history_version=raw.get("history_version"),
            version=raw.get("version"), source=raw.get("source") or "", author=raw.get("author"),
            authors=[dict(a) for a in raw.get("authors") or []],
            summary=raw.get("summary"), changes=list(raw.get("changes") or []),
            restored_from=raw.get("restored_from"), created_at=parse_time(raw.get("created_at")),
            updated_at=parse_time(raw.get("updated_at")), graph=_definition(raw, workflow),
            label=raw.get("label"), note=raw.get("note"), labeled_by=raw.get("labeled_by"),
            labeled_at=parse_time(raw.get("labeled_at")), raw=raw,
        )


@dataclass(frozen=True)
class WorkflowFolder:
    """One of your account's workflow folders, as the app's Automations page shows it:
    ``Workflow.folders()`` lists them, ``Workflow.create_folder()`` makes one and
    ``workflow.move_to()`` files a workflow in one."""

    id: str
    name: str
    description: Optional[str]
    #: The folder it's in; ``None`` at the top.
    parent_id: Optional[str]
    #: How deep it sits: 0 at the top, 10 at most.
    depth: int
    #: How many workflows are in it (not counting its folders').
    workflow_count: int
    created_at: Any
    updated_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "WorkflowFolder":
        return cls(raw["id"], raw["name"], raw.get("description"), raw.get("parent_id"), int(raw["depth"]),
                   int(raw.get("workflow_count") or 0), parse_time(raw.get("created_at")),
                   parse_time(raw.get("updated_at")), raw)


def _folder_id(folder: Union["WorkflowFolder", str, None]) -> Optional[str]:
    return folder.id if isinstance(folder, WorkflowFolder) else folder


class EditBatch:
    """The edits ``Workflow.edit()`` collects: each method queues one, and the ``with``
    block's end sends them as one batch, applied in order as one version, or not at all
    (an op that can't apply raises ``noclick.InvalidRequest`` naming it, and nothing of
    the batch lands). A block that raises sends nothing.

    Steps are named by ``Step`` or by id; a step ``add_step`` queues has its id already,
    so later edits in the batch can name it. After the block, ``result`` is the
    ``WorkflowEdit``."""

    _workflow: "Workflow"

    @classmethod
    def _of(cls, workflow: "Workflow", if_version: Optional[int], include_graph: bool,
            source: Optional[str] = None, origin: Optional[str] = None, settle: bool = False) -> "EditBatch":
        batch = cls.__new__(cls)
        batch._workflow = workflow
        batch._if_version = if_version
        batch._include_graph = include_graph
        batch._source = source
        batch._origin = origin
        batch._settle = settle
        batch._ops = []
        batch._added = []
        batch._result = None
        return batch

    def __repr__(self) -> str:
        return f"EditBatch(ops={len(self._ops)}, if_version={self._if_version!r})"

    @property
    def ops(self) -> List[Dict[str, Any]]:
        """The edits queued so far, as the API takes them (a connection given as an object is resolved when sent)."""
        return [dict(op) for op in self._ops]

    @property
    def result(self) -> Optional[WorkflowEdit]:
        """What the batch did, once it was sent (``None`` before, or when nothing was queued)."""
        return self._result

    def _queue(self, op: Dict[str, Any]) -> None:
        if self._result is not None:
            raise RuntimeError("This batch was sent already: start another with workflow.edit().")
        self._ops.append(op)

    async def _send(self) -> Optional[WorkflowEdit]:
        if not self._ops:
            return None
        edit = await self._workflow._send(self._ops, if_version=self._if_version, include_graph=self._include_graph,
                                          source=self._source, origin=self._origin, settle=self._settle)
        for index, step in self._added:
            step._absorb(edit, edit.results[index] if index < len(edit.results) else None)
        self._result = edit
        return edit

    def __enter__(self) -> "EditBatch":
        return self

    def __exit__(self, exc_type: Any, *exc: Any) -> None:
        if exc_type is None:
            run_sync(self._send())

    async def __aenter__(self) -> "EditBatch":
        return self

    async def __aexit__(self, exc_type: Any, *exc: Any) -> None:
        if exc_type is None:
            await self._send()

    def add_step(
        self, type: str, *, operation: Optional[str] = None, settings: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None, id: Optional[str] = None, position: Optional[Position] = None,
        secrets: Any = None,
    ) -> Step:
        """Queue a new step of ``type`` (``automation-gmail``, ``agent``, ``trigger-cron``),
        doing ``operation`` with ``settings``. ``id`` names it (made from its type when left
        out); without ``position`` it's laid out beside the rest. An agent step's ``secrets``
        are as ``Step.update`` takes them.

        Returns:
            The step, whose ``id`` later edits in the batch can name. Its fields load once the batch is sent.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            with brief.edit() as e:
                post = e.add_step("automation-slack", operation="send_message_to_channel", name="Post it",
                                  settings={"channel": "#team", "text": "{{ $('summarize').text }}"})
                e.connect("summarize", post)
                e.set_connection(post, "work-slack")
        """
        op = _add_step_op(type, operation, settings, name, id, position, secrets)
        self._queue(op)
        step = Step._of(self._workflow, op["id"])
        self._added.append((len(self._ops) - 1, step))
        return step

    def update_step(
        self, step: Any, *, settings: Optional[Dict[str, Any]] = None, name: Optional[str] = None,
        operation: Optional[str] = None, enabled: Optional[bool] = None, secrets: Any = None,
    ) -> None:
        """Queue a change to a step, as ``Step.update`` makes it (``secrets`` too).

        Usage::

            with noclick.Workflow.from_name("Morning brief").edit() as e:
                e.update_step("send_summary", settings={"subject": "Today"}, enabled=True)
                e.update_step("summarize", secrets=["warehouse"])
        """
        self._queue(_update_step_op(step, settings, name, operation, enabled, secrets))

    def patch_step(self, step: Any, field: str, patch: str) -> None:
        """Queue a patch to one long text setting of a step, as ``Step.patch`` makes it.

        Usage::

            with noclick.Workflow.from_name("Morning brief").edit() as e:
                e.patch_step("writer", "system_prompt", "@@ Keep it short.\\n-Keep it short.\\n+Keep it brief.")
        """
        self._queue({"op": "patch_step", "id": _step_id(step), "field": field, "patch": patch})

    def remove_step(self, step: Any) -> None:
        """Queue taking a step (or a note) out, with its edges.

        Usage::

            with noclick.Workflow.from_name("Morning brief").edit() as e:
                e.remove_step("old_digest")
        """
        self._queue({"op": "remove_step", "id": _step_id(step)})

    def connect(self, source: Any, target: Any, *, kind: str = "data", handle: Optional[str] = None,
                target_handle: Optional[str] = None, id: Optional[str] = None) -> None:
        """Queue an edge from ``source`` into ``target``, as ``Step.connect`` makes it
        (``kind="tools"`` wires ``source`` into an agent as its tools). ``id`` names the edge
        (made for it when left out), as a canvas names its own.

        Usage::

            with noclick.Workflow.from_name("Morning brief").edit() as e:
                e.connect("every_morning", "summarize")
        """
        self._queue(_connect_op("connect", source, target, kind=kind, handle=handle, target_handle=target_handle,
                                id=id))

    def disconnect(self, source: Any, target: Any, *, handle: Optional[str] = None, id: Optional[str] = None) -> None:
        """Queue removing the edge from ``source`` into ``target`` (``id``: the one edge of
        that id, when two join them).

        Usage::

            with noclick.Workflow.from_name("Morning brief").edit() as e:
                e.disconnect("summarize", "send_summary")
        """
        self._queue(_connect_op("disconnect", source, target, handle=handle, id=id))

    def set_connection(self, step: Any, connection: Any, *, slot: Optional[str] = None) -> None:
        """Queue connecting an account to a step, as ``Step.set_connection`` does
        (``connection=None`` with ``slot`` takes one off).

        Usage::

            gmail = noclick.Connection.from_id("credential:9b2a1c5e-7d9f-4a31-8f6d-3f1d2c4b8a7e")
            with noclick.Workflow.from_name("Morning brief").edit() as e:
                e.set_connection("send_summary", gmail)
        """
        self._queue({"op": "set_connection", "id": _step_id(step), "connection": connection, **compact(slot=slot)})

    def mock_step(self, step: Any, output: Any) -> None:
        """Queue giving a step ``output`` on test runs instead of running it.

        Usage::

            with noclick.Workflow.from_name("Morning brief").edit() as e:
                e.mock_step("read_calendar", {"events": []})
        """
        self._queue({"op": "mock_step", "id": _step_id(step), "output": output})

    def unmock_step(self, step: Any) -> None:
        """Queue having a step run for real on test runs again.

        Usage::

            with noclick.Workflow.from_name("Morning brief").edit() as e:
                e.unmock_step("read_calendar")
        """
        self._queue({"op": "unmock_step", "id": _step_id(step)})

    def update_workflow(
        self, *, name: Optional[str] = None, description: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None, display_metadata: Optional[Dict[str, Any]] = None,
        interface: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Queue a change to the workflow's own fields, as ``Workflow.update`` makes it.
        ``display_metadata`` replaces what the app shows of it (its canvas's viewport, the step
        open in its panel; 16 KB at most): never a version, nor a change anyone is told of.
        ``interface`` replaces its Interface tab's layout as the app draws it (each block's
        place on the grid, the tabs' order; 256 KB at most): part of its graph, so a version.

        Usage::

            with noclick.Workflow.from_name("Morning brief").edit() as e:
                e.update_workflow(description="Emails the team the day's calendar at 8.")
        """
        self._queue(_update_workflow_op(name, description, settings, display_metadata, interface))

    def move(self, step: Any, position: Position, *, width: Optional[float] = None,
             height: Optional[float] = None) -> None:
        """Queue moving a step (or a note) on the canvas, to ``(x, y)``, and for one drawn at a
        size (a note) giving it ``width`` and ``height``. Moving things is never a version of
        its own.

        Usage::

            with noclick.Workflow.from_name("Morning brief").edit() as e:
                e.move("send_summary", (640, 120))
        """
        self._queue({"op": "move", "id": _step_id(step), "position": _position(position),
                     **compact(width=width, height=height)})

    def layout(self) -> None:
        """Queue laying every step out again, as the app's Tidy up does.

        Usage::

            with noclick.Workflow.from_name("Morning brief").edit() as e:
                e.layout()
        """
        self._queue({"op": "layout"})

    def add_note(
        self, content: str, *, id: Optional[str] = None, color: Optional[int] = None,
        near: Optional[Sequence[Any]] = None, direction: Optional[str] = None, after: Any = None,
        before: Any = None, width: Optional[int] = None, height: Optional[int] = None,
        position: Optional[Position] = None,
    ) -> Step:
        """Queue a note on the canvas, as ``Workflow.add_note`` makes it (``position``: where it
        sits, instead of beside steps).

        Returns:
            The note, a step of type ``stickyNote`` whose ``id`` later edits can name.

        Usage::

            with noclick.Workflow.from_name("Morning brief").edit() as e:
                e.add_note("Runs at 8 on weekdays.", near=["every_morning"])
        """
        op = _note_op(content, id, color=color, near=[_step_id(s) for s in near] if near is not None else None,
                      direction=direction, after=_step_id(after) if after is not None else None,
                      before=_step_id(before) if before is not None else None, width=width, height=height,
                      position=_position(position) if position is not None else None)
        self._queue(op)
        note = Step._of(self._workflow, op["id"])
        self._added.append((len(self._ops) - 1, note))
        return note

    def define_variable(
        self, name: str, *, value: str = "", description: Optional[str] = None, per_user: bool = False,
    ) -> None:
        """Queue defining a workflow variable: a value its steps read as ``{{vars.name}}``,
        changed in one place. ``per_user=True`` asks each person who copies the workflow for
        their own. Only the workflow's owner defines one.

        Usage::

            with noclick.Workflow.from_name("Morning brief").edit() as e:
                e.define_variable("team_email", value="team@acme.com", description="Who gets the brief")
        """
        self._queue(compact(op="define_variable", name=name, value=value, description=description,
                            per_user=per_user or None))

    def add_test_run(
        self, trigger: Any, name: str, body: str, *, title: Optional[str] = None, author: Optional[str] = None,
        handle: Optional[str] = None,
    ) -> None:
        """Queue a Test Run: a message staged on ``trigger`` (a trigger step wired into an
        agent, by step or id, or its type) that the app's Test Run plays to the agent.
        Only the workflow's owner adds one.

        Usage::

            with noclick.Workflow.from_name("Support inbox").edit() as e:
                e.add_test_run("support_email", "Refund request", "Hi, I'd like a refund for order 1042.",
                               title="Refund for order 1042", author="ana@example.com")
        """
        self._queue(compact(op="add_test_run", trigger=_step_id(trigger), name=name, body=body, title=title,
                            author=author, handle=handle))


class Workflow(_Object):
    """A workflow built in the NoClick app: its trigger, steps and outputs. Run it
    with ``run(inputs)``; ``inputs`` names what its trigger takes. ``access`` is
    your account's: ``owner``, ``editor`` or ``viewer`` (one shared with it);
    building, running, testing and publishing it take edit access, billed to
    whoever pays for it (a team workspace's owner; its app stays its owner's);
    pausing and deleting it take owning it and paying for it.

    It's also a handle to its graph: ``graph()`` reads its steps whole, each
    ``Step`` changes with one call, and ``edit()`` sends several changes as one
    version, checked against the version you read (``version``) when you say so.
    Editing takes edit access, as the app's canvas does: an ``editor`` edits a
    workflow shared with it."""

    _repr_keys = ("id", "name")

    def _init(self, **kwargs: Any) -> None:
        # The graph as this handle last read or wrote it (None: read it again), and the version it was at.
        self._graph: Optional[WorkflowGraph] = None
        self._version: Optional[int] = None
        self._last_edit: Optional[WorkflowEdit] = None
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    id: str = field("id")
    name: str = field("name")
    description: Optional[str] = field("description")
    inputs: Dict[str, Any] = field("inputs", doc=(
        "A JSON schema of what ``run`` takes: a form's fields, any object for a webhook, empty if nothing."))
    app_url: Optional[str] = field("app_url", doc="Where to open it in the NoClick app.")
    access: str = field("access", doc="Your account's access: ``owner``, ``editor`` or ``viewer``.")
    folder_id: Optional[str] = field("folder_id", doc=(
        "The folder of your account's it's in (``Workflow.folders()``); ``None`` at the top, and for one shared with "
        "you."))
    step_types: List[str] = field("step_types", lambda raw: [str(t) for t in raw or []], doc=(
        "What it's made of, at a glance, in a list too: at most four of its step types, its triggers first, then "
        "its agents (one on a coding harness as ``agent:<harness>``, ``agent:codex``), then the rest, never a note."))
    created_at: Any = field("created_at", parse_time)
    updated_at: Any = field("updated_at", parse_time)
    steps: List[WorkflowStep] = field("steps", lambda raw: [WorkflowStep._from(s) for s in raw or []], doc=(
        "Its steps in order, each with its settings, connection and trigger state (read with one workflow, "
        "not in a list)."))
    edges: List[Dict[str, Any]] = field("edges", lambda raw: list(raw or []), doc=(
        "How its steps are wired: ``{from, to, kind}``, ``kind`` ``data`` or ``tools`` (a step an agent "
        "uses as a tool)."))
    paused: bool = field("paused", lambda raw: bool(raw), doc="Whether a pause switched its triggers off.")
    readiness: Dict[str, Any] = field("readiness", lambda raw: dict(raw or {}), doc=(
        "Whether it's set up to run: ``status`` (``needs_setup``, ``waiting_for_input``, ``input_observed``, "
        "``configured``, ...), what that status ``meaning`` is in a sentence, the ``issues`` in the way (a step "
        "whose last run failed among them), the ``warnings`` that don't stop it running (an agent's tool with "
        "no account connected), and ``unverified``, the steps no run has completed yet, each "
        "``{step, code, message}``."))
    urls: List[Dict[str, Any]] = field("urls", lambda raw: list(raw or []), doc=(
        "The URLs it answers at: ``{kind, url, step, public}``, ``kind`` ``endpoint``, ``app`` (its published "
        "app) or ``mcp`` (a hosted MCP server)."))

    # Workflow routes are account-level; only a run acts for a user.
    def _call_scope(self) -> Any:
        return None

    @synced
    @classmethod
    async def create(
        cls, name: str, *, instructions: Optional[str] = None, description: Optional[str] = None,
        questions: Optional[str] = None, client: Optional[Client] = None,
    ) -> "Workflow":
        """A new workflow in your account. With ``instructions`` NoClick's
        builder starts building it: wait on ``latest_build``. A name your
        account already has raises ``noclick.Conflict`` (change that one with
        ``build``). ``questions="assume"``: the builder asks nothing, as
        ``build()`` takes it.

        Returns:
            The new workflow; ``latest_build`` is its build when ``instructions`` describe it.

        Usage::

            brief = noclick.Workflow.create(
                "Morning brief", instructions="Every day at 8, email me today's calendar and unread emails",
            )
            result = brief.latest_build.wait(timeout=900)
            print(result.summary, [step.name for step in result.steps])
        """
        api = resolve_client(client)
        raw = await api.request("POST", "/v1/workflows", json=compact(
            name=name, instructions=instructions, description=description, questions=questions))
        return cls._new(raw=raw, client=client, user=None)

    @property
    def latest_build(self) -> Optional[WorkflowBuild]:
        """The build ``create(..., instructions=...)`` or ``build()`` started here (``None`` otherwise)."""
        started = getattr(self, "_started_build", None)
        if started is not None:
            return started
        raw = (self._raw or {}).get("build")
        return WorkflowBuild._from_payload(raw, client=self._client, user=None) if raw else None

    @classmethod
    def from_name(
        cls, name: str, *, description: Optional[str] = None, client: Optional[Client] = None,
    ) -> "Workflow":
        """A lazy reference to the workflow called ``name`` in the app. Two
        workflows with the same name raise ``noclick.Conflict`` on first use
        (rename one, or use ``from_id``), and none raises ``noclick.NotFound``
        (``create`` makes one).

        Given ``description``, it gets the workflow, then sets its description
        when it differs, every time it runs; nothing else about the workflow is
        touched. Set it in a setup script or at startup, and take the bare
        handle in request handlers.

        Returns:
            A workflow that loads the first time it's used. Nothing is sent yet.

        Usage:
            Refer to a workflow by name::

                intake = noclick.Workflow.from_name("order-intake")
                run = intake.run({"order_id": "o_1042"}).wait()
                print(run.outputs)

            Or get it and set its description::

                intake = noclick.Workflow.from_name("order-intake", description="Files each new order in Linear.")
                print(intake.description)
        """
        workflow = cls._new(hints={"name": name}, client=client, user=None)
        workflow._define(compact(name=name, description=description), create_if_missing=False)
        return workflow

    @classmethod
    def from_id(cls, workflow_id: str, *, client: Optional[Client] = None) -> "Workflow":
        """A lazy reference to a workflow by id.

        Returns:
            A workflow that loads the first time it's used. Nothing is sent yet.

        Usage::

            intake = noclick.Workflow.from_id("2e3a9296-1bf5-4088-a20d-7c31937380c4")
            print(intake.name, intake.inputs)
        """
        return cls._new(hints={"id": workflow_id}, client=client, user=None)

    @synced
    @classmethod
    async def get(cls, workflow_id: str, *, client: Optional[Client] = None) -> "Workflow":
        """Load a workflow by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The workflow, loaded.

        Usage::

            intake = noclick.Workflow.get("2e3a9296-1bf5-4088-a20d-7c31937380c4")
            print(intake.name, intake.app_url)
        """
        workflow = cls.from_id(workflow_id, client=client)
        await workflow._ensure()
        return workflow

    @synced
    @classmethod
    async def list(
        cls, *, q: Optional[str] = None, search: Optional[str] = None, limit: Optional[int] = None,
        client: Optional[Client] = None,
    ) -> List["Workflow"]:
        """Your account's workflows, most recently changed first. ``q`` is a
        case-insensitive prefix of the name; ``search``, text its name or
        description holds, in any case.

        Returns:
            Every matching workflow, fetched page by page (or the first ``limit``).

        Usage::

            for workflow in noclick.Workflow.list():
                print(workflow.name, workflow.updated_at)
        """
        return await list_all(
            "/v1/workflows", lambda raw, _scope: cls._new(raw=raw, client=client, user=None),
            params={"q": q, "search": search}, user=None, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, q: Optional[str] = None,
        search: Optional[str] = None, client: Optional[Client] = None,
    ) -> Page:
        """One page of workflows; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the workflows and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Workflow.list_page(limit=25)
            for workflow in page.data:
                print(workflow.name)
        """
        return await list_page(
            "/v1/workflows", lambda raw, _scope: cls._new(raw=raw, client=client, user=None),
            params={"q": q, "search": search}, user=None, cursor=cursor, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def folders(cls, *, client: Optional[Client] = None) -> List[WorkflowFolder]:
        """Your account's workflow folders, as the app's Automations page shows
        them: the ones it made in its own workspace, the shallowest first, then
        by name. A workflow's ``folder_id`` names the one it's in.

        Returns:
            Each folder, with its ``parent_id`` (``None`` at the top) and its ``workflow_count``.

        Usage::

            for folder in noclick.Workflow.folders():
                print("  " * folder.depth + folder.name, folder.workflow_count)
        """
        rows = await paginate(resolve_client(client), "/v1/workflows/folders", user=None)
        return [WorkflowFolder._from(row) for row in rows]

    @synced
    @classmethod
    async def create_folder(
        cls, name: str, *, description: Optional[str] = None, parent: Union[WorkflowFolder, str, None] = None,
        client: Optional[Client] = None,
    ) -> WorkflowFolder:
        """A new folder in your account's workspace, at the top or in
        ``parent`` (a ``WorkflowFolder`` or its id), as the app makes one. A
        name ``parent``'s folders already have raises ``noclick.Conflict``,
        naming that folder (``folder_id``).

        Returns:
            The new folder.

        Usage::

            reports = noclick.Workflow.create_folder("Reports")
            weekly = noclick.Workflow.create_folder("Weekly", parent=reports)
            noclick.Workflow.from_name("Morning brief").move_to(weekly)
        """
        raw = await resolve_client(client).request(
            "POST", "/v1/workflows/folders",
            json=compact(name=name, description=description, parent_id=_folder_id(parent)), user=None)
        return WorkflowFolder._from(raw)

    @synced
    @classmethod
    async def delete_folder(cls, folder: Union[WorkflowFolder, str], *, client: Optional[Client] = None) -> WorkflowFolder:
        """Delete one of your account's folders (a ``WorkflowFolder`` or its
        id), as the app does: the workflows in it move to its parent (the top,
        for one at the top) and the folders in it go with it, their workflows
        moving to the top. No workflow is deleted.

        Returns:
            The folder as it was.

        Usage::

            for folder in noclick.Workflow.folders():
                if folder.workflow_count == 0:
                    noclick.Workflow.delete_folder(folder)
        """
        raw = await resolve_client(client).request("DELETE", f"/v1/workflows/folders/{_folder_id(folder)}", user=None)
        return WorkflowFolder._from(raw)

    @synced
    async def move_to(self, folder: Union[WorkflowFolder, str, None]) -> "Workflow":
        """Move it into one of your account's folders (a ``WorkflowFolder`` or
        its id), or out to the top with ``None``, as dragging it does in the app.
        It takes what changing it takes: owning it and paying for it.

        Returns:
            This workflow, read again (``folder_id`` is the folder it's in now).

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            brief.move_to(noclick.Workflow.create_folder("Reports"))
            brief.move_to(None)   # back to the top
        """
        return self._took(await self._request("POST", f"{await self._path()}/move",
                                              json={"folder_id": _folder_id(folder)}))

    async def _load(self) -> Dict[str, Any]:
        raw = await self._read_view()
        self._version = raw.get("version", self._version)
        return raw

    def _took(self, raw: Any) -> "Workflow":
        """The workflow as an answer shows it (a pause's, a resume's), with the version it's at."""
        self._raw = raw
        if isinstance(raw, dict) and raw.get("version") is not None:
            self._version = raw["version"]
        return self

    async def _read_view(self) -> Dict[str, Any]:
        workflow_id = self._known("id")
        if workflow_id:
            return await self._request("GET", f"/v1/workflows/{workflow_id}")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/workflows", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        if not rows:
            raise NotFound(
                f"No workflow is named {name!r}.",
                next_step="Check the name in the NoClick app, or list them with noclick.Workflow.list().",
                details={"name": name},
            )
        if len(rows) > 1:
            raise Conflict(
                f"{len(rows)} workflows are named {name!r}.",
                next_step="Rename one in the app, or use noclick.Workflow.from_id(...).",
                details={"name": name, "ids": [row.get("id") for row in rows]},
            )
        return await self._converge(rows[0])

    async def _converge(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Set the fields ``from_name`` was given on the workflow it found, where they differ."""
        wanted = {k: v for k, v in (self._create_with or {}).items() if k != "name" and row.get(k) != v}
        if not wanted:
            return row
        path = f"/v1/workflows/{row['id']}"
        op = _update_workflow_op(None, wanted.get("description"), None)
        self._wrote(await self._request("POST", f"{path}/edits", json={"ops": [op]}))
        return await self._request("GET", path)

    async def _path(self) -> str:
        known = self._known("id")
        return f"/v1/workflows/{known or (await self._ensure())['id']}"

    # --- its graph --------------------------------------------------------

    @property
    def version(self) -> Optional[int]:
        """Its version as this handle last read or wrote it: what ``edit(if_version=...)``
        checks against. Every change to its definition moves it on, and so do NoClick's own
        records of a trigger's registration. Reading it loads the workflow if nothing has yet."""
        if self._version is None:
            self._version = self._sync_raw().get("version")
        return self._version

    @property
    def last_edit(self) -> Optional[WorkflowEdit]:
        """What this handle's last edit did (``None`` until one): its version, its summary,
        each op's results and each touched step's verdict."""
        return self._last_edit

    async def _read_graph(self) -> WorkflowGraph:
        raw = await self._request("GET", f"{await self._path()}/graph") or {}
        graph = WorkflowGraph._from(raw.get("graph"), workflow=self, workflow_id=raw.get("workflow_id") or "",
                                    version=raw.get("version"), definition=raw)
        self._graph, self._version = graph, graph.version
        return graph

    @synced
    async def graph(self) -> WorkflowGraph:
        """Read its definition whole: its name, description and settings, every step with its
        settings as stored (never a secret), its notes and edges, at its current ``version``.

        Returns:
            The ``WorkflowGraph``; this handle's ``version`` is now its.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            graph = brief.graph()
            for step in graph.steps:
                print(step.id, step.type, step.name, step.settings)
            print(graph.edges, graph.version)
        """
        return await self._read_graph()

    def step(self, step_id: str) -> Step:
        """A handle to one of its steps by id. Nothing is sent: an edit through it names the
        step by its id, and its fields load from the graph the first time you read one (a step
        that isn't there raises ``noclick.NotFound`` then, or when an edit names it).

        Returns:
            The ``Step``.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            brief.step("summarize").connect("send_summary")
        """
        cached = self._graph._node(step_id) if self._graph is not None else None
        withheld = (self._graph.withheld.get(step_id) or ()) if cached is not None else ()
        return Step._of(self, step_id, node=cached, withheld=withheld)

    async def _send(self, ops: Sequence[Dict[str, Any]], *, if_version: Optional[int] = None,
                    include_graph: bool = False, source: Optional[str] = None,
                    origin: Optional[str] = None, settle: bool = False) -> WorkflowEdit:
        """One batch of ``ops``; what it did is this handle's now, and a refusal for a stale version carries the
        workflow as it stands (``Conflict.graph``)."""
        path = await self._path()
        sent = [await _sent(op) for op in ops]
        try:
            raw = await self._request("POST", f"{path}/edits", json=compact(
                ops=sent, if_version=if_version, include_graph=include_graph or None, source=source, origin=origin,
                settle=settle or None))
        except Conflict as err:
            self._stale(err)
            raise
        return self._wrote(raw)

    async def _edit_step(self, step: Step, op: Dict[str, Any], *also: Any) -> Step:
        """One op about ``step``, sent alone with the graph back: the step (and ``also``, any steps it names) as
        written."""
        edit = await self._send([op], include_graph=True)
        step._absorb(edit, edit.results[0] if edit.results else None)
        for other in also:
            if isinstance(other, Step) and other is not step:
                other._absorb(edit)
        return step

    def _stale(self, err: Conflict) -> None:
        graph, version = err.details.get("graph"), err.details.get("version")
        if isinstance(graph, dict) and isinstance(version, int):
            err.graph = WorkflowGraph._from(graph, workflow=self, workflow_id=err.details.get("workflow_id") or "",
                                            version=version)
            self._graph, self._version = err.graph, version

    def _wrote(self, raw: Any) -> WorkflowEdit:
        """What a write did is this handle's now."""
        edit = WorkflowEdit._from(raw, self)
        self._graph, self._version, self._last_edit = edit.graph, edit.version, edit
        # Its name, description and steps may have moved with the edit: the next read loads them again.
        if edit.workflow_id:
            self._hints["id"] = edit.workflow_id
            self._raw = None
        return edit

    @synced
    async def add_step(
        self, type: str, *, operation: Optional[str] = None, settings: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None, id: Optional[str] = None, position: Optional[Position] = None,
        secrets: Any = None,
    ) -> Step:
        """Add a step of ``type`` (``automation-gmail``, ``agent``, ``trigger-cron``) doing
        ``operation`` with ``settings``, as one edit. ``id`` names it (made from its type when
        left out); without ``position`` it's laid out beside the rest. It's judged as the app's
        builder judges one: a type, operation or value that can't be is refused with
        ``noclick.InvalidRequest`` naming it, and a setting it can't run without yet is in its
        ``verdict``. A trigger's schedule or webhook registers once it's added. An agent step's
        ``secrets`` are as ``Step.update`` takes them.

        Returns:
            The new ``Step``, with its ``verdict`` and what the edit said about it (``notes``).

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            send = brief.add_step(
                "automation-gmail", operation="send_email_message", name="Send the summary",
                settings={"to": "team@acme.com", "subject": "Today", "body": "{{ $('summarize').text }}"},
            )
            brief.step("summarize").connect(send)
            print(send.id, send.verdict)
        """
        op = _add_step_op(type, operation, settings, name, id, position, secrets)
        return await self._edit_step(Step._of(self, op["id"]), op)

    @synced
    async def update(
        self, *, name: Optional[str] = None, description: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None, display_metadata: Optional[Dict[str, Any]] = None,
        interface: Optional[Dict[str, Any]] = None,
    ) -> "Workflow":
        """Change its name, description or settings (by top-level key; only its owner changes
        those, and NoClick's own are refused). A field you leave out is never touched.
        ``display_metadata`` replaces what the app shows of it (its canvas's viewport), never a
        version; ``interface`` its Interface tab's layout as the app draws it, part of its graph.

        Returns:
            This workflow; it loads again the next time you read a field.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            brief.update(name="Team brief", description="Emails the team the day's calendar at 8.")
        """
        await self._send([_update_workflow_op(name, description, settings, display_metadata, interface)],
                         include_graph=True)
        return self

    @synced
    async def add_note(
        self, content: str, *, id: Optional[str] = None, color: Optional[int] = None,
        near: Optional[Sequence[Any]] = None, direction: Optional[str] = None, after: Any = None,
        before: Any = None, width: Optional[int] = None, height: Optional[int] = None,
    ) -> Step:
        """Put a note on the canvas: ``near`` some steps (``direction``: ``above``, the
        default, ``below``, ``left`` or ``right``), or over a stretch of them from ``after``
        to ``before``. ``color`` is the app's 0 to 20; ``width`` and ``height`` its size.

        Returns:
            The note: a ``Step`` of type ``stickyNote`` (its text is ``settings["content"]``).

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            note = brief.add_note("Runs at 8 on weekdays; edit the schedule in its trigger.", near=["every_morning"])
            print(note.id)
        """
        op = _note_op(content, id, color=color, near=[_step_id(s) for s in near] if near is not None else None,
                      direction=direction, after=_step_id(after) if after is not None else None,
                      before=_step_id(before) if before is not None else None, width=width, height=height)
        return await self._edit_step(Step._of(self, op["id"]), op)

    @synced
    async def move(self, step: Any, position: Position) -> Step:
        """Move a step (or a note) on the canvas to ``(x, y)`` (or ``{"x", "y"}``). Where
        things sit is never a version of its own.

        Returns:
            The step, at its new ``position``.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            brief.move("send_summary", (640, 120))
        """
        handle = step if isinstance(step, Step) else Step._of(self, _step_id(step))
        return await self._edit_step(handle, {"op": "move", "id": handle.id, "position": _position(position)})

    def edit(self, *, if_version: Optional[int] = None, include_graph: bool = False,
             source: Optional[str] = None, origin: Optional[str] = None, settle: bool = False) -> EditBatch:
        """Collect several edits and send them as one batch when the ``with`` block ends:
        they're applied in order and land as one version, or none of them do. With
        ``if_version`` (a version you read: ``version``, ``graph().version``, or the last
        edit's) the batch is refused with ``noclick.Conflict`` when the workflow moved on since,
        and the error carries the workflow as it stands (``graph`` and ``version``), so your code
        decides again from what's there. ``include_graph=True`` has the answer carry the
        workflow as written, read as ``graph()`` reads it.

        A batch that can't be undone from its versions alone (one that removes a step holding an
        app, conversations or files) may be held for the account's owner when an agent, a
        connected app or a deployed app's code sends it: it raises ``noclick.ApprovalRequired``,
        nothing of it has landed, and NoClick applies it once they approve: its ``operation``
        settles then, with the batch's answer. The workflow one of your agents runs on is
        edited as its canvas edits it: the agent follows its prompt, harness and model, its own
        step stays (removing it raises ``noclick.InvalidRequest`` naming the agent), and a key
        that couldn't change the agent can't change it this way either.

        ``source="canvas"`` says the edits are a canvas's saves, as the app's canvas sends them:
        each setting ``update_step`` sends replaces that setting whole and is kept as written
        (never rewritten nor refused for its value; the step's verdict says it isn't ready),
        an edge joins the handles it names, a connection sits under the slot it's given (one the
        step takes), and they join the canvas session's version (saves within five minutes of its
        first, whoever made them). ``origin`` is a name the sender gives itself (letters, digits,
        ``-`` and ``_``, up to 64; a canvas tab's own id): what the workflow's open canvases hear
        of the write names it, so the canvas that sent it knows the change is its own.

        ``settle=True`` waits, up to 30 seconds, for what the batch sets going (a trigger's
        registration: its webhook, its schedule, its inbox; a removed step's teardown) before the
        answer: ``result.settled`` says whether it finished in time, the graph (with
        ``include_graph``) carries what it wrote on the steps (a trigger's ``webhook_url``), and
        ``result.unregistered`` names, by step, why each trigger it left unregistered can't be yet.

        Returns:
            An ``EditBatch`` to use as a context manager (``async with`` in async code);
            its ``result`` is the ``WorkflowEdit`` once the block ends.

        Usage:
            Add a step and wire it in, both or neither::

                brief = noclick.Workflow.from_name("Morning brief")
                with brief.edit() as e:
                    post = e.add_step("automation-slack", operation="send_message_to_channel",
                                      settings={"channel": "#team", "text": "{{ $('summarize').text }}"})
                    e.connect("summarize", post)
                print(e.result.summary)

            Read, decide, then change only if nothing changed in between, and decide again if it did::

                brief = noclick.Workflow.from_name("Morning brief")
                graph = brief.graph()
                for attempt in range(3):
                    send = graph.step("Send the summary")
                    try:
                        with brief.edit(if_version=graph.version) as e:
                            e.update_step(send, settings={"cc": ["ops@acme.com", *send.settings.get("cc", [])]})
                        break
                    except noclick.Conflict as changed:
                        graph = changed.graph   # the workflow as it stands; decide again from it
        """
        return EditBatch._of(self, if_version, include_graph, source, origin, settle)

    @synced
    async def settle(self, *, include_graph: bool = False) -> WorkflowEdit:
        """Wait, up to 30 seconds, for what earlier edits set going (their triggers' registrations,
        removed steps' teardowns), changing nothing, as an edit with ``settle=True`` waits for its own.

        Returns:
            A ``WorkflowEdit``: ``settled`` (whether it finished in time), ``unregistered`` (by step,
            why each trigger left unregistered can't be yet) and, with ``include_graph``, the workflow
            as that left it.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            with brief.edit() as e:
                e.add_step("trigger-webhook", id="hook", name="Order placed")
            print(brief.settle(include_graph=True).graph.step("hook").settings["webhook_url"])
        """
        return await self._send([], include_graph=include_graph, settle=True)

    @synced
    async def versions(self, *, limit: Optional[int] = 20, named: bool = False) -> List[WorkflowVersion]:
        """Its versions, newest first, kept 90 days (a named one for good): each one's number,
        where it came from, who made it and what changed. ``named=True`` lists only the named
        ones, its checkpoints.

        Returns:
            The first ``limit`` versions (20 by default; ``None`` for all of them), fetched page by page.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            for version in brief.versions(limit=10):
                print(version.version, version.source, version.summary, version.created_at)
        """
        return await list_all(
            f"{await self._path()}/versions", lambda raw, _scope: WorkflowVersion._from(raw, self),
            user=None, limit=limit, client=self._client, params=compact(named="true" if named else None),
        )

    @synced
    async def name_version(
        self, label: str, *, note: Optional[str] = None, history_version: Optional[int] = None,
        if_version: Optional[int] = None,
    ) -> WorkflowVersion:
        """Name a version of its history, keeping it for good while it has a name: the version
        it's at now (a checkpoint, as the app saves one; ``if_version`` refuses it with
        ``noclick.Conflict`` when the workflow moved on since you read it), or the one
        ``history_version`` names, or another name for a named one. No later change joins a
        named version. Naming the version it's at now when it has a name already raises
        ``noclick.Conflict`` naming it (``label``). Restore it with
        ``restore(history_version=...)``. A name someone else gave is changed only by them or the
        workflow's owner.

        Returns:
            The named ``WorkflowVersion``.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            saved = brief.name_version("Before the Slack change", note="Sends at 8.")
            brief.step("send_summary").update(settings={"channel": "#team"})
            brief.restore(history_version=saved.history_version)   # back to it
        """
        path = f"{await self._path()}/versions"
        if history_version is None:
            raw = await self._request("POST", path, json=compact(label=label, note=note, if_version=if_version))
        else:
            raw = await self._request("PATCH", f"{path}/{history_version}", json={"label": label, "note": note})
        return WorkflowVersion._from(raw, self)

    @synced
    async def unname_version(self, history_version: int) -> WorkflowVersion:
        """Take a version's name away (a checkpoint deleted): it's kept 90 days from its last
        write then, as any version. Only who named it or the workflow's owner takes it away.

        Returns:
            The ``WorkflowVersion``, its ``label`` ``None``.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            for version in brief.versions(named=True, limit=None):
                if version.label.startswith("tmp"):
                    brief.unname_version(version.history_version)
        """
        path = f"{await self._path()}/versions/{history_version}"
        return WorkflowVersion._from(await self._request("PATCH", path, json={"label": None}), self)

    @synced
    async def versions_page(self, *, cursor: Optional[str] = None, limit: Optional[int] = None,
                            named: bool = False) -> Page:
        """One page of its versions, newest first; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the versions and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            page = brief.versions_page(limit=50)
            while True:
                for version in page.data:
                    print(version.version, version.summary)
                if page.next_cursor is None:
                    break
                page = brief.versions_page(limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            f"{await self._path()}/versions", lambda raw, _scope: WorkflowVersion._from(raw, self),
            user=None, cursor=cursor, limit=limit, client=self._client,
            params=compact(named="true" if named else None),
        )

    @synced
    async def version_at(self, history_version: int) -> WorkflowVersion:
        """One version of its history, by its ``history_version``, with the definition it
        holds. A version it doesn't have (kept 90 days) raises ``noclick.NotFound``.

        Returns:
            The ``WorkflowVersion``; its ``graph`` is the workflow as it was: its name,
            description, settings and steps.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            before = brief.version_at(11)
            print(before.graph.name, [step.name for step in before.graph.steps])
        """
        path = f"{await self._path()}/versions/{history_version}"
        return WorkflowVersion._from(await self._request("GET", path), self)

    # --- building -------------------------------------------------------

    @synced
    async def build(self, instructions: Optional[str] = None, *,
                    publish: Union[None, bool, Dict[str, Any]] = None,
                    questions: Optional[str] = None) -> WorkflowBuild:
        """Change the workflow by describing the change; NoClick's builder makes
        it, reading the workflow as it stands. ``publish=True`` then puts its
        app live (or pass ``{"subdomain": "morrow", "title": ...}``; ``publish()``
        and ``unpublish()`` publish without a change). One build at a time:
        another in progress raises ``noclick.Conflict``. A change costs AI
        usage, as building in the app does.

        What the builder can't decide it asks the person whose build it is (you
        as the account's owner, or the user your key acts for): each input of its
        question is a human request NoClick sends them, which any client answers.
        ``questions="assume"`` asks nothing: the builder decides, and its summary
        and the workflow's readiness say what it assumed and what's missing.

        Returns:
            A ``WorkflowBuild``: ``wait()`` gives the ``WorkflowBuildResult`` (its ``steps``, and what was
            ``published``), and ``next_question()`` returns anything it asks first.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            result = brief.build("Also post the brief to #team on Slack").wait(timeout=900)
            print(result.summary)
        """
        options = {} if publish is True else publish or None
        payload = await self._request("POST", f"{await self._path()}/builds",
                                      json=compact(instructions=instructions, publish=options, questions=questions))
        build = WorkflowBuild._from_payload(payload, client=self._client, user=None)
        self._started_build = build
        return build

    @synced
    async def draft(
        self, steps: Sequence[Any], *, mode: str = "full", field: Optional[str] = None,
        instructions: Optional[str] = None,
    ) -> Operation:
        """Have NoClick's drafter (the builder's own) pick ``steps``' operations and fill their settings, the steps
        together. Each step is a ``Step``, its id, or ``{"id": ..., "goal": ...}``: its goal says what it's for (the
        drafter reads it, and a drafted step keeps it). ``mode`` is ``full`` (pick each step's operation and fill
        its settings; a step drafts against the operation each step it reads was given), ``operation`` (pick only
        the operation), ``fields`` (fill the settings of the operation a step has) or ``field`` (fill the one
        setting ``field`` names). ``instructions`` say what the workflow does. A step the workflow doesn't have, a
        note, a step that provides an agent its tools or a setting it doesn't have raises
        ``noclick.InvalidRequest`` before anything runs. What's drafted lands as one version of the workflow,
        written as an edit with your key is; the drafter never connects an account. It costs its AI usage, at cost.

        Returns:
            An operation (kind ``workflow.draft``) that reports each step as it lands (``progress``); ``wait()``
            gives the ``WorkflowDraftResult``, each step's verdict among it, or raises when no step could be drafted.

        Usage::

            brief = noclick.Workflow.from_name("Morning brief")
            with brief.edit() as batch:
                batch.add_step("automation-gmail", id="fetch")
                batch.add_step("automation-slack", id="post")
                batch.connect("fetch", "post")
            drafted = brief.draft([{"id": "fetch", "goal": "Read today's unread email"},
                                   {"id": "post", "goal": "Post a summary to #team"}]).wait()
            for step_id, step in drafted.steps.items():
                print(step_id, step["operation"], step["unfilled"], step["references"])
        """
        def entry(step: Any) -> Dict[str, Any]:
            if isinstance(step, Mapping):
                return compact(id=_step_id(step.get("id") or step.get("step")), goal=step.get("goal"))
            return {"id": _step_id(step)}

        payload = await self._request("POST", f"{await self._path()}/drafts", json=compact(
            steps=[entry(s) for s in steps], mode=mode, field=field, instructions=instructions))
        return Operation._from_payload(payload, client=self._client, user=None, kind="workflow.draft",
                                       reader=_read_draft)

    @synced
    async def publish(self, *, subdomain: Optional[str] = None, title: Optional[str] = None) -> WorkflowBuild:
        """Put the workflow's app live as it now stands, at ``subdomain``
        (``morrow`` is ``morrow.noclick.app``; omitted, the address it has).

        Returns:
            A ``WorkflowBuild`` whose result's ``published`` holds the app's ``url``.

        Usage::

            site = noclick.Workflow.from_name("Morrow Bakehouse site")
            print(site.publish(subdomain="morrow").wait().published["url"])
        """
        return await self.build.aio(publish=compact(subdomain=subdomain, title=title))

    @synced
    async def unpublish(self) -> WorkflowBuild:
        """Take the workflow's app down, to the trash: its public URL stops answering. For 30 days its address
        stays its own, and restoring it (or ``publish()``) brings it back there with the same key.

        Returns:
            A ``WorkflowBuild``; its result's ``published`` says ``unpublished``, with the ``trash_id`` that
            restores it and until when (``restorable_until``).

        Usage::

            done = noclick.Workflow.from_name("Morrow Bakehouse site").unpublish().wait()
            noclick.TrashItem.from_id(done.published["trash_id"]).restore()
        """
        return await self.build.aio(publish={"action": "unpublish"})

    @synced
    async def pause(self, reason: Optional[str] = None) -> "Workflow":
        """Switch off each of its triggers that's on, with ``reason`` beside them
        in the app: nothing starts it on its own until you ``resume()``. Runs
        from code still start.

        Returns:
            This workflow, read again (``paused`` is ``True``).

        Usage::

            digest = noclick.Workflow.from_name("Hourly digest")
            digest.pause("Too noisy over the weekend")
        """
        return self._took(await self._request("POST", f"{await self._path()}/pause", json=compact(reason=reason)))

    @synced
    async def resume(self) -> "Workflow":
        """Switch back on each trigger a pause switched off (never one turned off by hand).

        Returns:
            This workflow, read again.

        Usage::

            noclick.Workflow.from_name("Hourly digest").resume()
        """
        return self._took(await self._request("POST", f"{await self._path()}/resume"))

    @synced
    async def restore(
        self, *, history_version: Optional[int] = None, if_version: Optional[int] = None,
    ) -> "Workflow":
        """Bring the workflow back from the trash (within 30 days of ``delete()``);
        its schedules and webhooks register again.

        With ``history_version``, put that version of its history back instead (``versions()``
        lists them): its graph, name, description and settings, as a new version of its own
        (source ``restore``), so it's undone by restoring the one before it. ``if_version``
        (the workflow's ``version`` you read) refuses it with ``noclick.Conflict``, carrying the
        workflow as it stands, when the workflow moved on since. One that takes away a step
        holding an app, conversations or files may be held for the account's owner, as a batch
        is (``noclick.ApprovalRequired``).

        Returns:
            This workflow. Out of the trash it's read again; after a version's restore,
            ``version`` is the new one, ``last_edit`` says what it did (``restored_from``,
            ``summary``) and its fields load again the next time you read one.

        Usage:
            Out of the trash::

                noclick.Workflow.from_id("2e3a9296-1bf5-4088-a20d-7c31937380c4").restore()

            Undo the last change, unless something changed since you looked::

                brief = noclick.Workflow.from_name("Morning brief")
                now = brief.graph().version
                latest, before = brief.versions(limit=2)
                brief.restore(history_version=before.history_version, if_version=now)
                print(brief.last_edit.summary)   # restored version 11
        """
        if history_version is not None:
            path = await self._path()
            try:
                raw = await self._request("POST", f"{path}/versions/{history_version}/restore",
                                          json=compact(if_version=if_version))
            except Conflict as err:
                self._stale(err)
                raise
            self._wrote(raw)
            return self
        if if_version is not None:
            raise TypeError("if_version checks a version's restore: pass history_version= too.")
        known = self._known("id")
        if not known:
            raise NotFound("A workflow in the trash is restored by id.",
                           next_step="Use noclick.Workflow.from_id(...).restore().")
        return self._took(await self._request("POST", f"/v1/workflows/{known}/restore"))

    @synced
    async def delete(self) -> None:
        """Move the workflow to the trash: its schedules and webhooks stop now,
        and ``restore()`` brings it back within 30 days.

        Returns:
            Nothing.

        Usage::

            noclick.Workflow.from_name("Old digest").delete()
        """
        await self._request("DELETE", await self._path())

    # --- runs ------------------------------------------------------------

    @synced
    async def run(
        self,
        inputs: Optional[Dict[str, Any]] = None,
        *,
        from_step: Any = None,
        only: bool = False,
        user: Any = AMBIENT,
        idempotency_key: Optional[str] = None,
    ) -> Operation:
        """Start a run with ``inputs`` (checked against ``inputs``, the workflow's
        schema; a mismatch raises ``noclick.InvalidRequest`` naming the field).
        What would stop the run is refused before anything runs: a step with no
        account connected raises ``noclick.NeedsConnection``, and a workflow that
        can't start from code (several triggers and no Run trigger, or only
        events an integration pushes) or isn't set up ``noclick.ActionRequired``.

        ``from_step`` (a ``Step`` or its id) runs that step and what comes after
        it instead, the steps before it giving the outputs they last stored, as
        the app's Run from here does; with ``only=True`` that step alone. A run
        from a step takes no inputs, unless it's a trigger that does. A step
        that provides an agent its tools has no run of its own
        (``noclick.InvalidRequest``, ``details["reason"]`` ``tool_provider``).

        Returns:
            An operation whose ``.wait()`` gives the finished ``WorkflowRun``, or
            raises the run's error if it failed.

        Usage:
            Run it and wait for the outputs::

                intake = noclick.Workflow.from_name("order-intake")
                run = intake.run({"order_id": "o_1042", "rush": True}).wait(timeout=300)
                print(run.outputs["summary"])

            Record the run for a user, and make a retried request safe::

                intake = noclick.Workflow.from_name("order-intake")
                op = intake.run({"order_id": "o_1042"}, user="acme", idempotency_key="order-o_1042")
                print(op.id)   # resume anywhere with noclick.Operation.from_id(op.id).wait()

            Try one step again on what came in last, nothing after it::

                intake = noclick.Workflow.from_name("order-intake")
                run = intake.run(from_step="summarize", only=True).wait()
        """
        scope = resolve_scope(user)
        body = {"inputs": inputs or {}, **compact(from_step=None if from_step is None else _step_id(from_step),
                                                  only=True if only else None)}
        payload = await self._api.request(
            "POST", f"{await self._path()}/runs", json=body, user=scope, idempotency_key=idempotency_key,
        )
        return Operation._from_payload(payload, client=self._client, user=scope, kind="workflow.run", reader=_read_run)

    @synced
    async def test_runs(self) -> List[WorkflowTestRun]:
        """The test runs the workflow offers, as its Test Run screen lists them: for each trigger an agent comes
        after, the staged situations NoClick offers for it (under the names the workflow gave them, with its edits
        to their messages, less the ones it removed) and the runs it authored (``edit().add_test_run``). Empty for
        a workflow with no trigger a test can stage. Reading them costs nothing.

        Returns:
            Each ``WorkflowTestRun``, in the order ``rehearse`` finds them: its ``key`` and ``name`` (either names
            it to ``rehearse``), the ``trigger`` it stages on and its staged ``message``.

        Usage::

            inbox = noclick.Workflow.from_name("Support inbox")
            for run in inbox.test_runs():
                print(run.name, run.trigger["label"], run.message.get("title"))
            test = inbox.rehearse(inbox.test_runs()[0].key).wait()
        """
        raw = await self._request("GET", f"{await self._path()}/test_runs") or {}
        return [WorkflowTestRun._from(run) for run in (raw.get("data") or [])]

    @synced
    async def rehearse(
        self,
        test_run: Optional[str] = None,
        *,
        trigger: Any = None,
        body: Optional[str] = None,
        title: Optional[str] = None,
        author: Optional[str] = None,
        handle: Optional[str] = None,
        scenario: Optional[str] = None,
        user: Any = AMBIENT,
    ) -> Operation:
        """A test run of the workflow, as the app's Test Run plays one: a staged
        event arrives at one of its triggers and the agents it reaches take a
        real turn (their models, instructions and tools) while a simulated world
        answers every tool call, so nothing is sent, no account is touched and
        its connections needn't be connected yet (its agents' model connections
        must be). The steps after an agent that would reach an account never run.

        ``test_run`` plays one the workflow offers, by its name or key, as its
        Test Run screen lists them (``test_runs()`` reads them): a staged situation for one of its triggers,
        or one authored for it (``edit().add_test_run``). Or stage a message you
        type on ``trigger`` (a trigger ``Step``, its id or its type): ``body``,
        with ``title``, ``author`` and ``handle``. ``scenario`` says what the
        simulated world is like, in place of the staged situation's own. One
        the workflow doesn't offer raises ``noclick.NotFound`` naming the ones
        it does. Billed as the app's Test Run is; an account has up to 10
        queued or running at once (``noclick.QuotaExceeded`` past that).

        Returns:
            The run's operation (kind ``workflow.rehearse``); ``.wait()`` gives the ``WorkflowRehearsal``: the
            agent's ``reply`` and the ``tool_calls`` it made with what the world answered.

        Usage::

            inbox = noclick.Workflow.from_name("Support inbox")
            test = inbox.rehearse("Refund request").wait()
            print(test.reply)
            for call in test.tool_calls:
                print(call["tool"], call["arguments"])

            # A message of your own, on the trigger step support_email:
            test = inbox.rehearse(trigger="support_email", body="My order 1042 never came.",
                                  title="Where is order 1042?", author="ana@example.com").wait()
        """
        scope = resolve_scope(user)
        payload = await self._api.request(
            "POST", f"{await self._path()}/rehearsals", user=scope,
            json=compact(test_run=test_run, trigger=None if trigger is None else _step_id(trigger), body=body,
                         title=title, author=author, handle=handle, scenario=scenario),
        )
        return Operation._from_payload(payload, client=self._client, user=scope, kind="workflow.rehearse",
                                       reader=_read_rehearsal)

    @synced
    async def runs(
        self,
        *,
        status: Union[None, str, Sequence[str]] = None,
        limit: Optional[int] = 20,
        user_filter: Any = None,
        user: Any = AMBIENT,
        source: Union[None, str, Sequence[str]] = None,
        trigger: Union[None, str, Sequence[str]] = None,
        waiting: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> List[WorkflowRun]:
        """Recent runs, newest first, however they started (your code, its
        endpoint, a schedule, the app). Outside ``as_user`` you read runs recorded
        for your account; ``user_filter`` reads your users'. Narrow them by
        ``status``, by how they started (``source``: ``api``, ``endpoint``,
        ``app``, ``schedule``, ``trigger``), by the kind of event that started
        them (``trigger``: ``webhook``, ``email``, ``call``, ``agent``,
        ``shared_link``, ``error``), to those that wait (``waiting=True``) or
        that don't (``False``), and by text in their error (``search``, any
        case).

        Returns:
            The first ``limit`` matching runs (20 by default; ``None`` for all of them).

        Usage::

            intake = noclick.Workflow.from_name("order-intake")
            for run in intake.runs(status="failed", user_filter=noclick.ALL_USERS):
                print(run.started_at, run.source, run.error)
            for run in intake.runs(trigger="email", waiting=True):
                print(run.id, "waits on", run.waiting_on)
        """
        return await list_all(
            f"{await self._path()}/runs", lambda raw, _scope: WorkflowRun._from(raw),
            params={"status": csv(status), "source": csv(source), "trigger": csv(trigger),
                    "waiting": None if waiting is None else ("true" if waiting else "false"),
                    "search": search or None},
            user=user, user_filter=user_filter, limit=limit, client=self._client,
        )

    @synced
    async def get_run(self, run_id: str) -> WorkflowRun:
        """One run, with what each step did (``steps``: status, error and output, in order).
        While it runs, each step reads as it moves (``running``, then how it ended with its
        output); ``noclick.watch`` says when, with a ``workflow_run`` change naming the run
        (``change`` ``step`` when a step moved, ``run`` when it started or ended).

        Returns:
            The ``WorkflowRun``; an unknown id raises ``noclick.NotFound``.

        Usage::

            intake = noclick.Workflow.from_name("order-intake")
            failed = intake.runs(status="failed", limit=1)[0]
            for step in intake.get_run(failed.id).steps:
                print(step.name, step.status, step.error)
        """
        return WorkflowRun._from(await self._request("GET", f"{await self._path()}/runs/{run_id}"))

    @synced
    async def stop_run(self, run_id: str, *, user: Any = AMBIENT) -> WorkflowRun:
        """Stop a run that's running, however it started, as the app's stop does: the step
        it's on stops at once and nothing after it runs. A run from code is its operation's
        cancel (the operation reads ``canceled``). Takes what starting one takes; inside
        ``as_user`` (or with ``user=``) only that user's runs.

        Returns:
            The run once it stopped (or as it stands after a few seconds). A run that already
            ended raises ``noclick.Conflict``, as does any other that waits with nothing running
            (an approval, a delay).

        Usage::

            intake = noclick.Workflow.from_name("order-intake")
            for run in intake.runs(status="running"):
                print(intake.stop_run(run.id).status)   # failed
        """
        raw = await self._api.request("POST", f"{await self._path()}/runs/{run_id}/stop", user=resolve_scope(user))
        return WorkflowRun._from(raw)

    @synced
    async def run_counts(self, *, user_filter: Any = None, user: Any = AMBIENT) -> WorkflowRunCounts:
        """How many runs ``runs()`` lists: in all, ``by_status`` (and how many of the running
        ones are ``waiting``), ``by_source`` and ``by_trigger``. Outside ``as_user`` you count
        the runs recorded for your account; ``user_filter`` counts your users'.

        Returns:
            The ``WorkflowRunCounts``.

        Usage::

            counts = noclick.Workflow.from_name("order-intake").run_counts()
            print(counts.total, counts.by_status["failed"], counts.by_source)
        """
        user, user_id = await read_scope(user, user_filter)
        raw = await self._api.request("GET", f"{await self._path()}/runs/counts",
                                      params=compact(user_id=user_id), user=user)
        return WorkflowRunCounts._from(raw)

    @synced
    async def latest_outputs(
        self, *, steps: Optional[Sequence[Any]] = None, full: bool = False, user: Any = AMBIENT,
    ) -> LatestOutputs:
        """Each step's latest output, whatever run it's from, as the app's canvas shows the
        workflow when it opens: cut short as a run's steps are unless ``full``, never a
        secret. ``steps`` reads only those steps' (each a ``Step`` or its id). Inside
        ``as_user`` (or with ``user=``) only that user's runs are read.

        Returns:
            The ``LatestOutputs``: ``outputs`` by step id, with what each ``withheld``.

        Usage::

            latest = noclick.Workflow.from_name("order-intake").latest_outputs()
            print(latest.outputs["hook"]["order_id"], latest.withheld.get("hook"))
        """
        wanted = ",".join(_step_id(s) for s in steps) if steps else None
        raw = await self._api.request("GET", f"{await self._path()}/outputs",
                                      params=compact(steps=wanted, full="true" if full else None),
                                      user=resolve_scope(user))
        return LatestOutputs._from(raw)

    @synced
    async def approvals(self, *, status: Optional[str] = None, limit: Optional[int] = 20) -> List[WorkflowApproval]:
        """Its Approval steps, newest first: those its runs wait at (``status="pending"``), and those approved,
        declined or expired. NoClick asks your account's owner to answer each; your code answers one with a key
        naming ``approvals:answer`` (``approval.approve()``, ``approval.decline()``).

        Returns:
            The first ``limit`` (20 by default, at most 100), each a ``noclick.WorkflowApproval``.

        Usage::

            invoices = noclick.Workflow.from_name("Invoices")
            for approval in invoices.approvals(status="pending"):
                print(approval.title, approval.values)
        """
        workflow_id = self._known("id") or (await self._ensure())["id"]
        return await WorkflowApproval.list.aio(workflow_id, status=status, limit=limit, client=self._client)

    @synced
    async def endpoint(self, *, public: Optional[bool] = None) -> WorkflowEndpoint:
        """The workflow's HTTP endpoint, turned on if it wasn't. ``public=True``
        lets a publishable key call it from a web page, with per-visitor rate
        limits; ``public=False`` requires a secret key again; leave it out to keep
        what it is.

        Returns:
            The endpoint: its ``url``, whether it's ``public``, and the ``method`` to call it with.

        Usage::

            intake = noclick.Workflow.from_name("order-intake")
            endpoint = intake.endpoint(public=True)
            print(endpoint.method, endpoint.url, endpoint.public)
        """
        raw = await self._request("PUT", f"{await self._path()}/endpoint", json=compact(public=public))
        return WorkflowEndpoint._from(raw)
