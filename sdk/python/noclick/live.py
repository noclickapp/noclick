"""Live editing: an app's site served from a dev server while you edit it, each edit swapping into the pages its
owner has open, and deployed when the session ends once its build and check pass.

Reached through the app: ``app.live``.

    app = noclick.Project.from_name("larkspur")
    app.update(live_editing=True)
    session = app.live.start()
    print(session.enter_url)   # open it once to see the site in live mode
    app.live.exec("sed -i 's/Score/Points/' src/render.js", background=True).wait()
    app.live.end().wait()
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Literal, Mapping, Optional, Union, overload

from ._object import compact, parse_time
from ._sync import synced
from .app_services import _Service
from .operation import Operation, register_result

# How long a call that may wait on the session waits for its answer: the API answers within 100 seconds.
_REQUEST_S = 115

OPEN_STATES = ("warming", "live", "idle", "ending")


@dataclass(frozen=True)
class LiveEditCounts:
    """How a session's edits went so far: how many, and how many swapped in place (``hot``), reloaded the page
    (``reload``) or didn't compile (``error``)."""

    count: int
    hot: int
    reload: int
    error: int
    #: The newest edit's sequence number: ``app.live.edits(after=...)`` reads the ones after it.
    last_seq: int

    @classmethod
    def _from(cls, raw: Any) -> "LiveEditCounts":
        raw = raw if isinstance(raw, dict) else {}
        return cls(int(raw.get("count") or 0), int(raw.get("hot") or 0), int(raw.get("reload") or 0),
                   int(raw.get("error") or 0), int(raw.get("last_seq") or 0))


@dataclass(frozen=True)
class LiveDataCopy:
    """One resource the app binds that a session's code reaches a copy of, never production's."""

    #: ``database``, ``bucket``, ``dict`` or ``queue``.
    kind: str
    #: The binding's name.
    name: str
    production_id: str
    #: The copy's id, once the session's first write made it (None until then: it reads production's).
    copy_id: Optional[str]
    #: Whether the copy starts with production's data.
    with_data: bool
    #: What the copy holds, in a sentence.
    note: Optional[str]

    @classmethod
    def _from(cls, raw: Any) -> "LiveDataCopy":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("kind") or "", raw.get("name") or "", raw.get("production_id") or "", raw.get("copy_id"),
                   bool(raw.get("with_data")), raw.get("note"))


@dataclass(frozen=True)
class LiveSession:
    """An app's live session: its site on a dev server, with its code checked out in ``workdir``. ``state`` goes
    ``warming`` (starting; ``phase`` says where), ``live``, ``idle`` (no page open and no command for a minute),
    ``ending`` (building, checking and deploying what was edited), then ``ended`` (``release`` says how) or
    ``failed`` (``error`` says why)."""

    id: str
    project_id: str
    state: str
    phase: Optional[str]
    #: ``vite`` (over its package.json: its own Vite, or NoClick's for files whose package.json builds nothing) or
    #: ``plain`` (NoClick's Vite over a site of only files).
    mode: str
    #: The app's own URL, where the pages open in live mode show the session.
    url: Optional[str]
    #: A link that opens the app in live mode, on the session a ``start()`` returns (None otherwise).
    enter_url: Optional[str]
    #: Where the site's code is checked out in the session's container.
    workdir: str
    #: The pages open in live mode: ``{"connected": ..., "visible": ...}``.
    viewers: Dict[str, int]
    edits: LiveEditCounts
    #: What the session's code writes to instead of production's data.
    data: List[LiveDataCopy]
    #: What keeps an edit from swapping in place: ``{"ready", "mode", "reasons": [{"code", "detail"}]}``.
    readiness: Optional[Dict[str, Any]]
    #: The session's branch, ``noclick-live``: ``{"branch", "head", "pushed", "dirty", "state", "conflict"}``.
    git: Optional[Dict[str, Any]]
    #: The timers in force, in seconds (``idle_end_s``, ``max_session_s``, ...), when the session reported them.
    limits: Optional[Dict[str, int]]
    started_at: Any
    live_at: Any
    ended_at: Any
    #: Why it ended: ``api`` (``end()``), ``idle``, ``max_quiet``, ``max_session``, ``switch_off``, ...
    end_reason: Optional[str]
    #: ``{"code", "message"}`` once it failed, or once its end couldn't deploy.
    error: Optional[Dict[str, Any]]
    #: How its end went: ``{"outcome", "deployment_id", "script"}``, ``outcome`` ``deployed``, ``deploy_failed``,
    #: ``no_changes`` or ``stopped``.
    release: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(repr=False)

    @property
    def open(self) -> bool:
        """Whether the session is still open (``warming``, ``live``, ``idle`` or ``ending``)."""
        return self.state in OPEN_STATES

    @classmethod
    def _from(cls, raw: Any) -> "LiveSession":
        raw = raw if isinstance(raw, dict) else {}
        viewers = raw.get("viewers") or {}
        return cls(
            raw.get("id") or "", raw.get("project_id") or "", raw.get("state") or "", raw.get("phase"),
            raw.get("mode") or "", raw.get("url"), raw.get("enter_url"), raw.get("workdir") or "/site",
            {"connected": int(viewers.get("connected") or 0), "visible": int(viewers.get("visible") or 0)},
            LiveEditCounts._from(raw.get("edits")), [LiveDataCopy._from(row) for row in raw.get("data") or []],
            raw.get("readiness"), raw.get("git"), raw.get("limits"), parse_time(raw.get("started_at")),
            parse_time(raw.get("live_at")), parse_time(raw.get("ended_at")), raw.get("end_reason"), raw.get("error"),
            raw.get("release"), raw,
        )


@dataclass(frozen=True)
class LiveStatus:
    """Whether an app is edited live, whether it can be, and its session."""

    #: The app's ``live_editing`` switch.
    enabled: bool
    #: Whether the app can be edited live, as far as is known without reading its code.
    supported: bool
    #: Why it can't, when it can't.
    unsupported_reason: Optional[str]
    #: Its open session, else its last one (None before its first).
    session: Optional[LiveSession]
    #: The agents' conversations editing it: ``[{"agent_id", "conversation"}]``.
    attached: List[Dict[str, Optional[str]]]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "LiveStatus":
        raw = raw if isinstance(raw, dict) else {}
        return cls(bool(raw.get("enabled")), bool(raw.get("supported")), raw.get("unsupported_reason"),
                   LiveSession._from(raw["session"]) if raw.get("session") else None,
                   [dict(row) for row in raw.get("attached") or []], raw)


@dataclass(frozen=True)
class LiveEdit:
    """What Vite did with one batch of changed files in the open pages. ``outcome`` is ``hot`` (swapped in place;
    ``applied`` counts the pages that took it), ``reload`` (the page reloaded and lost its state; ``reload`` says
    why), ``error`` (it doesn't compile, and the page shows Vite's error overlay; ``error`` says where) or ``none``
    (nothing imports the files)."""

    #: Its sequence number in the session.
    seq: int
    files: List[str]
    outcome: str
    #: How many pages were open.
    clients: int
    #: ``{"path", "triggeredBy", "reason", "chain"}``: ``reason`` is ``no-boundary``, ``html``, ``config``,
    #: ``dependency``, ``server-restart`` or ``other``, and ``chain`` the imports from the changed file up to the page.
    reload: Optional[Dict[str, Any]]
    #: ``{"message", "file", "loc": {"line", "column"}, "frame"}``.
    error: Optional[Dict[str, Any]]
    #: ``{"ok", "failed", "errors"}``: the pages that applied the swap, and what threw as it ran.
    applied: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "LiveEdit":
        raw = raw if isinstance(raw, dict) else {}
        return cls(int(raw.get("seq") or 0), list(raw.get("files") or []), raw.get("outcome") or "none",
                   int(raw.get("clients") or 0), raw.get("reload"), raw.get("error"), raw.get("applied"), raw)


class LiveEdits(List[LiveEdit]):
    """The edits a read returns, oldest first: a list of ``LiveEdit``, with where the next read starts."""

    #: The sequence number to pass as ``after`` to read the edits after these.
    last_seq: int = 0

    @classmethod
    def _from(cls, response: Any) -> "LiveEdits":
        response = response if isinstance(response, dict) else {}
        edits = cls(LiveEdit._from(row) for row in response.get("data") or [])
        edits.last_seq = int(response.get("last_seq") or 0)
        return edits


@dataclass(frozen=True)
class LiveExecResult:
    """What a command run in a live session printed and how it exited (a non-zero ``exit_code`` is a result, not an
    error), with what Vite did in the open pages with each file it changed."""

    stdout: str
    stderr: str
    exit_code: Optional[int]
    #: Whether it ran past its ``timeout_s`` and was stopped.
    timed_out: bool
    #: How long it ran, in milliseconds.
    ms: int
    #: A record per batch of files the command changed; empty when it changed none.
    vite: List[LiveEdit]
    #: Edits made outside the command since the one before, when there were any.
    earlier: List[LiveEdit]
    note: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @property
    def ok(self) -> bool:
        """Whether the command exited 0."""
        return self.exit_code == 0

    def __str__(self) -> str:
        return self.stdout

    @classmethod
    def _from(cls, raw: Any) -> "LiveExecResult":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("stdout") or "", raw.get("stderr") or "", raw.get("exit_code"), bool(raw.get("timed_out")),
                   int(raw.get("ms") or 0), [LiveEdit._from(row) for row in raw.get("vite") or []],
                   [LiveEdit._from(row) for row in raw.get("earlier") or []], raw.get("note"), raw)


@dataclass(frozen=True)
class LiveEnterLink:
    """A link that opens the app in live mode on whatever device opens it."""

    url: str
    #: When the link stops working (2 hours after it was made); it works any number of times until then.
    expires_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "LiveEnterLink":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("url") or "", parse_time(raw.get("expires_at")), raw)


@dataclass(frozen=True)
class LiveEnd:
    """How a live session's end went. ``outcome`` is ``deployed`` (what was edited serves at the app's URL, as
    ``deployment_id``), ``no_changes`` (nothing was edited), ``stopped`` (it ended without deploying) or ``aborted``
    (an edit came in as it ended, and the session is live again). A build or check that failed fails the operation
    instead, leaving production as it was."""

    outcome: str
    session_id: Optional[str]
    #: The production deployment it released (None unless ``deployed``).
    deployment_id: Optional[str]
    #: It deployed, but the production branch couldn't be moved to its commit; the next session's start merges it.
    main_behind: bool
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "LiveEnd":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("outcome") or "stopped", raw.get("session_id"), raw.get("deployment_id"),
                   bool(raw.get("main_behind")), raw)


def _read_end(result: Any, op: Operation) -> LiveEnd:
    return LiveEnd._from(result)


def _read_exec(result: Any, op: Operation) -> LiveExecResult:
    return LiveExecResult._from(result)


register_result("project.live_end", _read_end)
register_result("project.live_exec", _read_exec)


class ProjectLive(_Service):
    """``app.live``: edit the app in a live session. The site runs on a Vite dev server with its code checked out at
    ``/site``; each change swaps into the pages its owner has open (a game keeps running, a form keeps what was
    typed), and the session's end deploys what was edited, only once its build and check pass. It's for your
    account's own apps built with Vite (6 to 8), or of files whose package.json builds nothing or that have none,
    whose previews get their own data (``preview_resources="branch"``), with ``live_editing`` on: such an app has it
    on from its first production release (``app.update(live_editing=True)`` for one released before). The container
    is billed by the minute at what it costs NoClick.

    Usage::

        app = noclick.Project.from_name("larkspur")
        live = app.live   # this app's noclick.ProjectLive
        session = live.start()
        print(session.state, session.enter_url)
    """

    _name = "live"

    @synced
    async def status(self) -> LiveStatus:
        """Read whether the app is edited live, whether it can be, and its session.

        Returns:
            The app's switch and whether it's supported, its open session (else its last one) and the agents'
            conversations editing it.

        Usage::

            app = noclick.Project.from_name("larkspur")
            status = app.live.status()
            if not status.supported:
                print(status.unsupported_reason)
            elif status.session and status.session.open:
                print(status.session.state, status.session.viewers, status.session.edits.hot)
        """
        return LiveStatus._from(await self._request("GET"))

    @synced
    async def start(
        self, *, wait: bool = False, refresh_data: bool = False, limits: Optional[Mapping[str, int]] = None,
    ) -> LiveSession:
        """Start the app's live session, or return the one that's open. A session reads the ``noclick-live``
        branch (production's branch at the first one), and its code writes to copies of the app's data, not
        production's: ``refresh_data=True`` makes them again from production's. It answers while the session
        starts (``state`` ``warming``); ``wait=True`` waits for it to be live, up to 60 seconds, and answers it
        as it stands then: a first start in a place can take a few minutes, so a session can still come back
        ``warming``. ``status()`` reads it again.

        ``limits`` shortens the session's timers, in seconds (a session's timers can only be shortened):
        ``idle_grace_s`` (60: no page open and no command, before it's ``idle``), ``idle_end_s`` (600: idle
        before it ends), ``max_quiet_with_viewers_s`` (14,400: pages open but no command), ``max_session_s``
        (43,200) and ``hold_warming_s`` (30: how long a page waits for a starting session before it shows that
        it's starting).

        An account has at most 3 sessions open, and 24 session-hours a day. A start is refused while your
        account can't pay for it (``noclick.PaymentRequired``) or the app's budget is spent
        (``noclick.SpendCapExceeded``), and for an app live editing can't run (``noclick.Conflict``, whose
        ``readiness`` says what to change).

        Returns:
            The session, with its ``enter_url``: a link that opens the app in live mode, for 2 hours. Its
            ``state`` is ``warming`` while it starts, ``wait=True`` or not.

        Usage:
            Start a session and send its owner the link::

                app = noclick.Project.from_name("larkspur")
                session = app.live.start()
                print(session.enter_url)

            Start one that ends a minute after its last command, and wait until it's live::

                import time

                app = noclick.Project.from_name("larkspur")
                session = app.live.start(wait=True, limits={"idle_grace_s": 30, "idle_end_s": 30})
                while session.state == "warming":
                    time.sleep(5)
                    session = app.live.status().session or session
                print(session.state, session.limits)
        """
        body = compact(wait=wait or None, refresh_data=refresh_data or None,
                       limits=dict(limits) if limits is not None else None)
        raw = await self._request("POST", "sessions", json=body or None, timeout=_REQUEST_S if wait else None)
        return LiveSession._from(raw)

    @overload
    async def exec(
        self, command: str, *, background: Literal[False] = False, timeout_s: int = 90,
    ) -> LiveExecResult: ...

    @overload
    async def exec(self, command: str, *, background: Literal[True], timeout_s: int = 90) -> Operation: ...

    @synced
    async def exec(
        self, command: str, *, background: bool = False, timeout_s: int = 90,
    ) -> Union[LiveExecResult, Operation]:
        """Run a bash command in the session's container, in the site's working tree (``/site``), starting a
        session when none is open, and wait for it: ``timeout_s`` is 90 by default, and at most 90. A file the
        command writes is committed to the ``noclick-live`` branch by itself, and swaps into the open pages: the
        result says how, per batch of files it changed (``vite``). A non-zero exit is a result, not an exception.

        A command answers within its request, so one sent while the session is still starting (a first start
        in a place can take a few minutes) or deploying what was edited doesn't run: it raises
        ``noclick.Conflict``, whose ``state`` is ``warming`` or ``ending``. ``background=True`` returns an
        ``Operation`` at once instead, which waits for a starting session, then runs the command with
        ``timeout_s`` up to 600: for a command longer than a request allows (an install, a test run), or the
        first one of a session. An account runs at most 4 background commands at once. Cancelling one stops
        its wait, not a command already sent.

        Returns:
            What it printed (``stdout`` and ``stderr``), its ``exit_code``, and a ``LiveEdit`` per batch of
            files it changed: ``hot``, ``reload``, ``error`` or ``none``. With ``background=True``, an
            ``Operation`` at once, whose ``wait()`` gives that result.

        Usage:
            Edit a file, then read what the open pages did with it::

                app = noclick.Project.from_name("larkspur")
                result = app.live.exec("sed -i 's/Score/Points/' src/render.js")
                for edit in result.vite:
                    print(edit.outcome, edit.files, edit.applied)
                    if edit.outcome == "reload":
                        print("reloaded:", edit.reload["reason"], edit.reload["chain"])
                    elif edit.outcome == "error":
                        print(edit.error["message"], edit.error["file"])

            Install a dependency, which takes longer than a request allows, in the background::

                app = noclick.Project.from_name("larkspur")
                installed = app.live.exec("npm install canvas-confetti", background=True, timeout_s=300).wait()
                print(installed.ok, installed.stderr)
        """
        if background:
            payload = await self._request("POST", "exec",
                                          json={"command": command, "background": True, "timeout_s": timeout_s})
            return Operation._from_payload(
                payload, client=self._project._client, user=self._project._call_scope(), kind="project.live_exec",
                reader=_read_exec,
            )
        raw = await self._request("POST", "exec", json={"command": command, "timeout_s": timeout_s},
                                  timeout=_REQUEST_S)
        return LiveExecResult._from(raw)

    @synced
    async def edits(self, *, after: int = 0, limit: int = 50) -> LiveEdits:
        """What Vite did with each edit of the app's newest session after ``after`` (a sequence number), oldest
        first: edits made by commands and by agents attached to it alike.

        Returns:
            Up to ``limit`` edits (at most 200), with ``last_seq`` to read the next ones after. Empty when no
            session has run.

        Usage::

            app = noclick.Project.from_name("larkspur")
            seen = 0
            edits = app.live.edits(after=seen)
            for edit in edits:
                print(edit.seq, edit.outcome, edit.files)
            seen = edits.last_seq
        """
        return LiveEdits._from(await self._request("GET", "edits", params={"after": after or None, "limit": limit}))

    @synced
    async def enter_link(self) -> LiveEnterLink:
        """Make a link that opens the app in live mode (``start()`` returns one too). Whoever opens it sees the
        session's dev server at the app's own URL, on that device, for 12 hours, and can change nothing; everyone
        else sees production.

        Returns:
            The link, which works any number of times for 2 hours.

        Usage::

            app = noclick.Project.from_name("larkspur")
            link = app.live.enter_link()
            print(link.url, link.expires_at)
        """
        return LiveEnterLink._from(await self._request("POST", "enter_links"))

    @synced
    async def change(self, text: str, *, title: Optional[str] = None, workstream: Optional[str] = None) -> Operation:
        """Hand a change to the app's code to its coding agent, in your words: one per app, made the first time, on
        the harness and model your account's own model keys pick (else NoClick's key, at its cost). It works in the
        app's live session (each edit shows in the pages open on it), else in its own sandbox on a branch of its own;
        it commits and pushes, and never deploys: ending the session deploys what passes its check, and a job in its
        own sandbox that pushed ends with a preview of its branch deploying (its reply's ``code`` names it). Another
        change while it works joins the job under way.

        Returns:
            The job's ``agent.message`` operation: ``.wait()`` gives its reply.

        Usage::

            app = noclick.Project.from_name("larkspur")
            reply = app.live.change("Add a dark mode toggle to the header").wait()
            print(reply.text)
        """
        payload = await self._request("POST", "changes", json=compact(text=text, title=title, workstream=workstream))
        return Operation._from_payload(payload, client=self._project._client, user=self._project._call_scope(),
                                       kind="agent.message")

    @synced
    async def end(self, *, deploy: bool = True) -> Operation:
        """End the app's live session now (it also ends on its own, about 11 minutes after the last page closed
        and the last command ran). What it edited is committed, built and checked where production serves, and
        only then deployed; a build or check that fails leaves production as it was, and the edits stay on the
        ``noclick-live`` branch for the next session. ``deploy=False`` stops it without deploying. A session still
        starting is stopped.

        Returns:
            An operation whose ``.wait()`` gives the ``LiveEnd``. A build or check that failed raises
            ``noclick.OperationFailed``, saying why.

        Usage::

            app = noclick.Project.from_name("larkspur")
            ended = app.live.end().wait()
            print(ended.outcome, ended.deployment_id)
        """
        payload = await self._request("POST", "end", json={"deploy": deploy})
        return Operation._from_payload(
            payload, client=self._project._client, user=self._project._call_scope(), kind="project.live_end",
            reader=_read_end,
        )
