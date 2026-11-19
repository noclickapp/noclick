"""Projects: a repo deployed to a URL, with what the running app needs.

    repo = noclick.Repo.from_name("booking", create_if_missing=True)
    app = noclick.Project.from_name("booking", repo=repo, create_if_missing=True)
    app.bind("DB", noclick.Database.from_name("booking-db", create_if_missing=True))
    app.secrets.set("MAPS_API_KEY", "...")
    deployment = app.deploy().wait()
    print(deployment.url)   # https://booking.noclick.site

A deploy of the production branch goes live at ``app.url``; any other branch
gets a preview URL of its own. Bindings, secrets and schedules apply from the
next deployment.

Inside the running app, ``noclick.Project.current()`` is the app itself, signed
in by its deployment (no key in the app's code), and the whole client acts as a
key of the app's user: ``app.database("DB")`` reaches what it's bound to,
``noclick.Agent.from_name(..., create_if_missing=True)`` makes what it needs,
``app.ai`` and ``app.agent("SUPPORT")`` think and talk as the app, and
``app.verify_request(...)`` checks a scheduled request. What the app spends
counts toward its ``budget_usd_per_month`` ($10 unless set) and its user's cap.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Union

from ._client import Client, app_client, resolve_client
from ._object import (
    UNSET, Page, _Object, compact, field, iso_time, list_all, list_page, paginate, parse_time, read_scope,
    ref_id, required_number,
)
from ._sync import synced
from ._scope import AMBIENT, resolve_scope
from .ai import AI, AIModel, ChatReply, Embeddings, GeneratedImage, Transcript
from .app_services import ProjectEmail, ProjectPayments, ProjectSignIn, _Service
from .cron import Cron
from .exceptions import Conflict, InvalidRequest, NotFound, Unauthenticated
from .export import ExportBundle
from .live import ProjectLive
from .operation import Operation, register_result
from .repo import Repo
from .trash import TrashItem, trashed
from .versions import Version, version_id, versions_of
from .webhook import verify_signature

if TYPE_CHECKING:
    from .agent import Agent
    from .bucket import Bucket
    from .channel import Subscription
    from .connection import Connection
    from .database import Database
    from .domain import Domain
    from .queues import Queue

# What NoClick sets in every deployment's environment: its credential, and the key its scheduled requests are signed with.
SIGNING_SECRET_ENV = "NOCLICK_SIGNING_SECRET"


# --- values ----------------------------------------------------------------


@dataclass(frozen=True)
class Binding:
    """A resource the running app reads by ``name``: a ``database``, ``bucket``, ``dict``,
    ``queue``, ``secret``, ``connection`` or ``agent`` (``kind``), with its ``resource_id``
    and ``resource_name``."""

    name: str
    kind: str
    resource_id: str
    resource_name: Optional[str]
    #: The variables the app's code reads it as from its next deployment: its ``name``, or for a
    #: secret each of its keys under the key's own name (``name`` only lists it).
    variables: List[str]
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "Binding":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            raw.get("name") or "", raw.get("kind") or "", raw.get("resource_id") or "", raw.get("resource_name"),
            [str(v) for v in raw.get("variables") or []], parse_time(raw.get("created_at")), raw,
        )


@dataclass(frozen=True)
class LogLine:
    """One line an app printed, or its build did: when (``at``), its ``level``
    (``info``, ``warn`` or ``error``), the ``message``, and the deployment it came from.
    A line written while serving also names its ``environment`` (``production`` or
    ``preview``) and the request it was written in (``request_id``, shared by that
    request's lines); the host's own line for a request carries the ``status`` it
    answered (0 when it never did)."""

    at: Any
    level: str
    message: str
    deployment_id: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)
    environment: Optional[str] = None
    request_id: Optional[str] = None
    status: Optional[int] = None

    @classmethod
    def _from(cls, raw: Any) -> "LogLine":
        raw = raw if isinstance(raw, dict) else {}
        return cls(parse_time(raw.get("at")), raw.get("level") or "info", raw.get("message") or "",
                   raw.get("deployment_id"), raw, raw.get("environment"), raw.get("request_id"), raw.get("status"))

    def __str__(self) -> str:
        return self.message


class LogLines(List[LogLine]):
    """The lines a log read returns, oldest first: a list of ``LogLine``, with how long a line can take to show."""

    #: Up to how many seconds a line takes to show after a request writes it (the host's logs lag its requests):
    #: a read that's empty, or misses a request just made, may only be early. None for a build's log, which is
    #: kept whole as it's written.
    delay_s: Optional[int] = None

    @classmethod
    def _from(cls, response: Any) -> "LogLines":
        response = response if isinstance(response, dict) else {}
        lines = cls(LogLine._from(row) for row in response.get("data") or [])
        lines.delay_s = response.get("delay_s")
        return lines


@dataclass(frozen=True)
class PathCheck:
    """One path a check asked: a page, loaded in a browser, or a request entry of the check's paths, asked with a
    plain request (``expected`` says what it had to answer). Where it ended (``url``), its HTTP ``status``, how long
    it took (``load_ms``, None when it didn't load or answer within 30 seconds), and of a page its ``title``, the
    errors its console showed and a ``screenshot``. ``ok`` is False when a page answered 400 or more, didn't load, a
    script threw and nothing caught it, what the check waits for (``wait_for``) never showed, or a picture it shows
    doesn't (``broken_images``), and when a request entry answered other than it asks; ``problem`` says which. Other
    console errors are reported without failing it."""

    path: str
    url: str
    ok: bool
    problem: Optional[str]
    status: Optional[int]
    load_ms: Optional[int]
    title: Optional[str]
    #: Each ``{"kind", "message"}``: ``exception`` (uncaught), ``console`` (``console.error``) or ``browser`` (a
    #: file that failed to load, ...).
    console_errors: List[Dict[str, str]]
    #: The screenshot, an account file the chat shows: ``{"id", "name", "url", "mime_type", ...}`` (None when the
    #: page couldn't be opened at all, and for a request entry).
    screenshot: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(repr=False)
    #: The pictures the page shows that a browser can't (a missing file, or text committed in an image's place),
    #: each the site's own path (its URL when it's elsewhere); any fails the path.
    broken_images: List[str] = dc_field(default_factory=list)
    #: Each address the page shows (a ``mailto:`` link or its text) whose domain takes no mail (no MX record),
    #: reported without failing it.
    undeliverable_emails: List[str] = dc_field(default_factory=list)
    #: A request entry's ``{"status", "json"}``, as far as it asks them (``{}``: any status below 400); None for a
    #: page.
    expected: Optional[Dict[str, Any]] = None

    @classmethod
    def _from(cls, raw: Any) -> "PathCheck":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("path") or "", raw.get("url") or "", bool(raw.get("ok")), raw.get("problem"),
                   raw.get("status"), raw.get("load_ms"), raw.get("title"), list(raw.get("console_errors") or []),
                   raw.get("screenshot"), raw, list(raw.get("broken_images") or []),
                   list(raw.get("undeliverable_emails") or []), raw.get("expected"))


@dataclass(frozen=True)
class CheckReview:
    """What a model made of a check's screenshots (``Deployment.check(review=...)``), against NoClick's design
    rubric for a site or an app: each criterion's score from 1 to 5 (under 4 a defect), the issues to fix, most
    important first, and of a site the ``claims`` its pages make that neither its brief nor the owner's words give.
    ``passed`` is True when every score is 4 or more. A review that couldn't answer has its ``error`` instead, and
    leaves the check as it was."""

    #: The model that looked.
    model: str
    #: None when the review couldn't answer (``error`` says why).
    passed: Optional[bool]
    #: Each criterion's score, 1-5: a site's ``belongs``, ``first_screen``, ``type``, ``colour``, ``images``,
    #: ``phone``, ``finish`` and ``generated``; an app's ``task``, ``forms``, ``states``, ``density``, ``touch``,
    #: ``type``, ``navigation`` and ``finish``.
    scores: Dict[str, int]
    #: Each ``{"where", "what", "fix"}``, the most important first.
    issues: List[Dict[str, str]]
    #: A site's facts on its pages (a name, number, price, hour, quote) that neither the brief nor the owner's
    #: words give, each ``{"where", "what"}``: listed, never scored. Empty for an app.
    claims: List[Dict[str, str]]
    error: Optional[str]
    #: What the model's call cost, counted in the check's ``cost_usd`` too.
    cost_usd: float
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "CheckReview":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("model") or "", raw.get("passed"), dict(raw.get("scores") or {}),
                   list(raw.get("issues") or []), list(raw.get("claims") or []), raw.get("error"),
                   float(raw.get("cost_usd") or 0), raw)


@dataclass(frozen=True)
class DeploymentCheck:
    """What ``Deployment.check()`` saw where the deployment serves (``url``): ``passed`` when every path did,
    each path's ``PathCheck``, and what it cost (``cost_usd``: the browser at its provider's price by the second,
    and the review's model call)."""

    deployment_id: str
    url: str
    passed: bool
    paths: List[PathCheck]
    checked_at: Any
    cost_usd: float
    raw: Dict[str, Any] = dc_field(repr=False)
    #: The review of its screenshots, when the check asked for one (``review=``).
    review: Optional[CheckReview] = None
    #: Set when every path passed but the release's static files answered each of them, so the app's server code
    #: never ran: a broken API behind a working home page passes such a check. Name a route its code answers as a
    #: request entry (``{"path": "/api/health", "status": 200}``) to check the code too.
    code_unchecked: Optional[str] = None

    @classmethod
    def _from(cls, raw: Any) -> "DeploymentCheck":
        raw = raw if isinstance(raw, dict) else {}
        review = raw.get("review")
        return cls(raw.get("deployment_id") or "", raw.get("url") or "", bool(raw.get("passed")),
                   [PathCheck._from(p) for p in raw.get("paths") or []], parse_time(raw.get("checked_at")),
                   float(raw.get("cost_usd") or 0), raw, CheckReview._from(review) if review else None,
                   raw.get("code_unchecked"))


@dataclass(frozen=True)
class RouteTiming:
    """One route's requests: how many, how many failed (``errors``), and their times in milliseconds."""

    method: str
    path: str
    requests: int
    errors: int
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True)
class RequestOutcomes:
    """How the requests a deployment served between ``since`` and ``until`` went: how many, by HTTP status
    (``by_status``: ``{"200": 120, "500": 2, "none": 1}``, ``none`` for one never answered), the ``errors`` (an
    answer of 500 or more, or none) and their ``error_rate``, and the ``slowest_routes`` by their 95th-percentile
    time. ``sampled``: there were more than the 2,000 newest it read, or the record of a very busy app is a
    sample, each request in it counted for the ones it stands for."""

    requests: int
    errors: int
    error_rate: Optional[float]
    by_status: Dict[str, int]
    slowest_routes: List[RouteTiming]
    sampled: bool
    since: Any
    until: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "RequestOutcomes":
        raw = raw if isinstance(raw, dict) else {}
        routes = [RouteTiming(r.get("method") or "", r.get("path") or "", int(r.get("requests") or 0),
                              int(r.get("errors") or 0), float(r.get("p50_ms") or 0), float(r.get("p95_ms") or 0),
                              float(r.get("max_ms") or 0)) for r in raw.get("slowest_routes") or []]
        return cls(int(raw.get("requests") or 0), int(raw.get("errors") or 0), raw.get("error_rate"),
                   dict(raw.get("by_status") or {}), routes, bool(raw.get("sampled")), parse_time(raw.get("since")),
                   parse_time(raw.get("until")), raw)


@dataclass(frozen=True)
class PreviewLink:
    """A link that opens a preview of an app to whoever holds it, until ``expires_at``: the preview's address
    carrying a token NoClick signed for it. The browser that opens it keeps a cookie for that preview alone. On an app
    whose ``preview_access`` is ``link`` it's the only way in (but for its ``preview_public_paths``); on a public
    app's preview the address alone opens it too."""

    url: str
    branch: str
    #: The preview's own address, which tells anyone without the link that it's private.
    preview_url: str
    #: ``public`` or ``link``: the app's ``preview_access`` when the link was made.
    preview_access: str
    expires_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "PreviewLink":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("url") or "", raw.get("branch") or "", raw.get("preview_url") or "",
                   raw.get("preview_access") or "", parse_time(raw.get("expires_at")), raw)


# The settings ``container`` takes, by name (``ProjectContainer`` reads each back).
_CONTAINER_SETTINGS = ("cpu", "memory", "min_instances", "max_instances", "cpu_always", "request_timeout_s")


@dataclass(frozen=True)
class ProjectContainer:
    """How each instance of an app runs in a container, and what its warm instances cost: the ``cpu`` and
    ``memory`` each instance gets, how many are kept running (``min_instances``) and how many it may grow to
    (``max_instances``), whether its CPU runs between requests too (``cpu_always``), and how long a request may take
    (``request_timeout_s``). Changed with ``update(container=...)``, they apply from the app's next release (a deploy,
    or a promote). An app on the edge has them too: they size its releases in a container."""

    #: vCPUs per instance: 0.5 to 8 (1, 2, 4, 6 or 8; under 1 in steps of 0.01, where each instance answers one
    #: request at a time). 1 unless set.
    cpu: float
    #: Memory per instance, in MiB, from 512: up to 1024 under 1 vCPU, 4096 at 1, 8192 at 2, 2048 to 16384 at 4, 4096
    #: to 24576 at 6 and 4096 to 32768 at 8. 512 unless set.
    memory: int
    #: Instances kept running while production serves it, whether or not anything calls it, so no request waits for
    #: one to start: 0 to 3. 0 unless set.
    min_instances: int
    #: The most instances it runs at once: 1 to 10. 10 unless set.
    max_instances: int
    #: Whether its CPU runs between requests too, for work that goes on without one (a bot, a queue worker, a loop):
    #: each instance is then billed from start to stop. Takes 1 vCPU or more. False unless set.
    cpu_always: bool
    #: How long a request may take, in seconds: 1 to 3600. 300 unless set.
    request_timeout_s: int
    #: What its warm instances cost a month with nothing calling it, in US dollars, at the price where it runs:
    #: 0 with none kept warm.
    idle_usd_per_month: float
    #: What its settings cost or change beyond each request, in a sentence: the instances kept warm and their price,
    #: that under 1 vCPU each instance answers one request at a time, or that an app pinned to the edge doesn't use
    #: them. None when there's nothing to say.
    note: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "ProjectContainer":
        raw = raw if isinstance(raw, dict) else {}
        return cls(float(raw.get("cpu") or 1), int(raw.get("memory") or 512), int(raw.get("min_instances") or 0),
                   int(raw.get("max_instances") or 10), bool(raw.get("cpu_always")),
                   int(raw.get("request_timeout_s") or 300), float(raw.get("idle_usd_per_month") or 0),
                   raw.get("note"), raw)


def _container(settings: Any) -> Optional[Dict[str, Any]]:
    """Container settings on the wire: a mapping as it is, or a ``ProjectContainer``'s settings (None resets them)."""
    if settings is None:
        return None
    if isinstance(settings, ProjectContainer):
        return {name: getattr(settings, name) for name in _CONTAINER_SETTINGS}
    if not isinstance(settings, Mapping):
        raise TypeError("container is a mapping of settings by name: "
                        "cpu, memory, min_instances, max_instances, cpu_always, request_timeout_s.")
    return dict(settings)


@dataclass(frozen=True)
class TrafficInterval:
    """One hour or day of an app's traffic: the ``requests`` from ``at`` on, and how many of them failed
    (``errors``: an answer of 500 or more, or none)."""

    at: Any
    requests: int
    errors: int


@dataclass(frozen=True)
class PathTraffic:
    """One of an app's busiest paths: its requests, how many failed, their 95th-percentile time in milliseconds,
    and how many of them a browser made (``browser_requests``)."""

    path: str
    requests: int
    errors: int
    p95_ms: Optional[float]
    browser_requests: int


@dataclass(frozen=True)
class ProjectAnalytics:
    """How an app's traffic went over a ``period`` (``24h``, ``7d`` or ``30d``, from ``since`` up to ``until``):
    the ``requests`` its sites answered and the ``errors`` among them (an answer of 500 or more, or none) with their
    ``error_rate``, ``by_status`` (``{"200": 1180, "404": 21, "none": 1}``), how long answers took to begin
    (``p50_ms``, ``p95_ms``), each ``interval``'s (``hour`` or ``day``, starting in ``tz``) in ``series``, the
    busiest ``top_paths``, and the same length of time just before ``since`` (``previous_requests``,
    ``previous_errors``) to compare with. Counted from NoClick's record of every request, its files and API calls
    included: requests, not visitors. ``by_source`` says who made them as their user agents say: ``browser`` (a
    person's browser, or a program that says it's one) and ``automated`` (curl, an HTTP library, a headless browser,
    a crawler), and ``unknown`` for any recorded before NoClick told them apart. NoClick's own checks of the app are
    in no figure but ``noclick_requests``. ``sampled``: a very busy app's record is a sample, each request in it
    counted for the ones it stands for."""

    period: str
    environment: str
    interval: str
    tz: str
    since: Any
    until: Any
    requests: int
    errors: int
    error_rate: Optional[float]
    by_status: Dict[str, int]
    p50_ms: Optional[float]
    p95_ms: Optional[float]
    series: List[TrafficInterval]
    top_paths: List[PathTraffic]
    previous_requests: int
    previous_errors: int
    sampled: bool
    by_source: Dict[str, int]
    noclick_requests: int
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "ProjectAnalytics":
        raw = raw if isinstance(raw, dict) else {}
        series = [TrafficInterval(parse_time(r.get("at")), int(r.get("requests") or 0), int(r.get("errors") or 0))
                  for r in raw.get("series") or []]
        paths = [PathTraffic(r.get("path") or "", int(r.get("requests") or 0), int(r.get("errors") or 0),
                             r.get("p95_ms"), int(r.get("browser_requests") or 0)) for r in raw.get("top_paths") or []]
        return cls(raw.get("period") or "", raw.get("environment") or "", raw.get("interval") or "",
                   raw.get("tz") or "", parse_time(raw.get("since")), parse_time(raw.get("until")),
                   int(raw.get("requests") or 0), int(raw.get("errors") or 0), raw.get("error_rate"),
                   dict(raw.get("by_status") or {}), raw.get("p50_ms"), raw.get("p95_ms"), series, paths,
                   int(raw.get("previous_requests") or 0), int(raw.get("previous_errors") or 0),
                   bool(raw.get("sampled")), dict(raw.get("by_source") or {}), int(raw.get("noclick_requests") or 0),
                   raw)


@dataclass(frozen=True)
class AppRequests:
    """One app's requests to its production site over a summary's period, how many failed and how many a browser
    made; NoClick's own checks of it are in none of them but ``noclick_requests``."""

    project_id: str
    requests: int
    errors: int
    browser_requests: int
    noclick_requests: int


@dataclass(frozen=True)
class AnalyticsSummary:
    """Every app's requests over a ``period`` (from ``since`` up to ``until``, days starting in ``tz``), read at once:
    ``apps`` newest first, an app nobody reached at 0. ``of(app)`` is one app's. Requests, not visitors, NoClick's
    own checks left out. ``sampled``: a very busy app's record is a sample, each request in it counted for the ones it
    stands for."""

    period: str
    tz: str
    since: Any
    until: Any
    apps: List[AppRequests]
    sampled: bool
    raw: Dict[str, Any] = dc_field(repr=False)

    def of(self, app: Any) -> AppRequests:
        """One app's line in the summary.

        Returns:
            The ``AppRequests`` of ``app`` (a ``Project`` or its id); one the summary didn't cover reads as 0.

        Usage::

            week = noclick.Project.analytics_summary()
            app = noclick.Project.from_name("booking")
            print(week.of(app).requests, week.of(app).errors)
        """
        project_id = app if isinstance(app, str) else app.id
        return next((a for a in self.apps if a.project_id == project_id), AppRequests(project_id, 0, 0, 0, 0))

    @classmethod
    def _from(cls, raw: Any) -> "AnalyticsSummary":
        raw = raw if isinstance(raw, dict) else {}
        apps = [AppRequests(r.get("project_id") or "", int(r.get("requests") or 0), int(r.get("errors") or 0),
                            int(r.get("browser_requests") or 0), int(r.get("noclick_requests") or 0))
                for r in raw.get("data") or []]
        return cls(raw.get("period") or "", raw.get("tz") or "", parse_time(raw.get("since")),
                   parse_time(raw.get("until")), apps, bool(raw.get("sampled")), raw)


@dataclass(frozen=True)
class ProjectUsage:
    """What an app spent this month so far, against its budget: ``requests`` served,
    ``cpu_ms`` of compute, everything it cost in ``usd``, and the ``period_start`` it
    counts from."""

    requests: int
    cpu_ms: int
    #: Everything the app spent: hosting, builds, its calls to what it's bound to, its email, its AI and its agent turns.
    usd: float
    period_start: Any
    #: Its ``budget_usd_per_month`` (None without one).
    budget_usd: Optional[float]
    #: What refuses its paid calls now: ``project`` (its budget is used up), ``user`` (its user's cap is) or
    #: ``account`` (your account's balance is); None while they go through.
    limited_by: Optional[str]
    #: ``usd`` split by the spend types of ``Usage.series(group_by="type")``: ``apps``, ``ai``, ``model_tokens``, ...
    by_type: Dict[str, float]
    raw: Dict[str, Any] = dc_field(repr=False)


# --- deployments -----------------------------------------------------------


def _read_deployment(result: Any, op: Operation) -> "Deployment":
    return Deployment._new(raw=result if isinstance(result, dict) else {}, client=op._client, user=op._scope)


def _read_export(result: Any, op: Operation) -> ExportBundle:
    return ExportBundle._from(result)


def _read_check(result: Any, op: Operation) -> DeploymentCheck:
    return DeploymentCheck._from(result)


register_result("project.deploy", _read_deployment)
register_result("deployment.promote", _read_deployment)
register_result("deployment.check", _read_check)
register_result("project.export", _read_export)


class Deployment(_Object):
    """One build of a project at one commit. ``status`` goes ``queued``,
    ``building``, then ``ready`` (serving at ``url``), ``failed`` (``error``
    says why) or ``canceled``. ``production`` is True for the one serving the
    project's own URL."""

    _repr_keys = ("id", "branch", "status")

    id: str = field("id")
    project_id: str = field("project_id")
    branch: str = field("branch")
    commit: Optional[str] = field("commit", doc="The sha it was built from.")
    commit_message: Optional[str] = field("commit_message")
    status: str = field("status")
    url: Optional[str] = field("url", doc="Where this deployment serves (a preview URL unless it's production).")
    production: bool = field("production")
    environment: str = field(
        "environment", doc="``production`` for a deploy of the production branch, ``preview`` for any other: whose "
        "secrets it was built with. A promoted preview keeps ``preview`` and serves with production's secrets.",
    )
    started_by: str = field(
        "started_by", doc="``deploy`` (a ``deploy()``, or promoting a retired one) or ``push`` (the app deploys on "
        "push, see ``Project.deploy_on_push``).",
    )
    error: Optional[str] = field(
        "error", doc="Why the build failed, or why a push couldn't deploy, in one line (None unless ``failed``).",
    )
    failure: Optional[str] = field(
        "failure", doc="Whose its failure is (None unless ``failed``): ``app`` (its code, settings or config), "
        "``limit`` (one of the app's limits: the build's time or memory, the size of its source or output) or "
        "``platform``, NoClick's own, which changing the app won't fix and which isn't charged.",
    )
    platform_error: bool = field(
        "platform_error", doc="True when it failed on NoClick's side (``failure`` is ``platform``): don't change the "
        "app to work around it; tell whoever it's for, with ``error_id``.",
    )
    error_id: Optional[str] = field(
        "error_id", doc="The id NoClick's team finds a failure of its own by (None unless ``platform_error``).",
    )
    fix: Optional[Dict[str, str]] = field(
        "fix", doc="What fixes a failure when it's a known change to the app (None otherwise). Today only "
        "``{\"kind\": \"next_upgrade\", \"found\": <the Next.js it asks for>, \"needed\": <a release that "
        "builds>}``: its ``next_step`` says how to upgrade it, or to hand it to the app's coding agent.",
    )
    runtime: Optional[str] = field(
        "runtime", doc="Where it runs: ``edge`` or ``container``, chosen when its build starts (None until then).",
    )
    runtime_reason: Optional[str] = field(
        "runtime_reason", doc="Why it runs there, in words: the app's pinned runtime, or what its commit has, its "
        "own scripts named (``the app's own Dockerfile describes its server, built as it's written``).",
    )
    created_at: Any = field("created_at", parse_time)
    ready_at: Any = field("ready_at", parse_time)
    last_check: Optional[Dict[str, Any]] = field(
        "check", doc="Its latest check, in short: ``{operation_id, passed, url, checked_at, paths: [{path, ok, "
        "status, problem}]}``, with ``code_unchecked`` when its code never ran (None before its first). The check's "
        "operation has the whole of it; a promote's check is kept here too.",
    )
    serves: Optional[Dict[str, Optional[str]]] = field(
        "serves", doc="Each URL it answers now: ``{\"production\": <the app's URL, or None>, \"preview\": <its "
        "branch's preview URL, or None>}``. A promoted preview serves both, while its ``environment`` stays the one "
        "it was built for.",
    )
    warning: Optional[str] = field(
        "warning", doc="On the deployment a deploy's or a promote's (a rollback's) ``wait()`` gives: it went live, "
        "but its home page didn't load as "
        "a visitor's browser would (an answer other than 2xx, a redirect to another site, a script or stylesheet it "
        "names that doesn't load as one), another page answered 500 or more, one of the app's ``check_paths`` "
        "answered other than it asks, or nothing answered, with the error the app logged then. A site of files with "
        "no ``index.html`` gets one too, though it may mean to serve only its files. It stays live (nothing is rolled "
        "back): ``next_step`` says what to fix. None when everything asked answered as asked, and on a deployment "
        "read later.",
    )
    next_step: Optional[str] = field(
        "next_step", doc="On the deployment a deploy's or a promote's ``wait()`` gives, beside its ``warning``: what "
        "to fix, then deploy again. None otherwise.",
    )
    code_unchecked: Optional[str] = field(
        "code_unchecked", doc="On the deployment a deploy's or a promote's ``wait()`` gives: its static files "
        "answered every path asked, so its server code never ran, and a broken API would pass unseen. Add a route its "
        "code answers to the app's ``check_paths`` as a request entry (``{\"path\": \"/api/health\", \"status\": 200}``). "
        "None otherwise.",
    )
    parked: Optional[List[str]] = field(
        "parked", doc="On the deployment a rollback's ``wait()`` gives: the Durable Object classes production's objects "
        "have that this release is from before, parked rather than dropped. Their objects keep their data and answer "
        "that they're parked until a release that exports them serves production again, which takes them back. None "
        "otherwise.",
    )
    rebuilt: Optional[str] = field(
        "rebuilt", doc="On the deployment a promote of one past the rollback window gives: that one's release was no "
        "longer kept, so its commit was built again with the app's settings and secrets as they are now, as this "
        "deployment. None otherwise.",
    )
    settings_changed: Optional[str] = field(
        "settings_changed", doc="On the deployment a promote's (a rollback's) ``wait()`` gives: the app's settings "
        "changed since this release was built, named, so what its build read of them (a ``VITE_`` or ``NEXT_PUBLIC_`` "
        "value it put in its pages) is still as it was then; deploying production again builds with them. None "
        "otherwise.",
    )
    preview_link: Optional[str] = field(
        "preview_link", doc="On the deployment a preview's deploy gives, when the app's ``preview_access`` is "
        "``link``: the link that opens the preview (its ``url`` with a token NoClick signed, good for 7 days), which "
        "is what to hand people; anyone else opening the preview is told it's private. None otherwise "
        "(``app.preview_link()`` makes one any time).",
    )
    preview_data: Optional[str] = field(
        "preview_data", doc="On the deployment a preview's deploy gives, when the app's ``preview_resources`` is "
        "``branch``: what the preview writes to (its own copies of what its code reaches, made at its first write), "
        "when the copies go to the trash, and that promoting never carries them to production. None for production, "
        "and for an app whose previews use production's resources.",
    )
    variables: Optional[Dict[str, List[str]]] = field(
        "variables", doc="The names each of its releases was given in its environment, by the environment it was "
        "released to (``{\"production\": [...], \"preview\": [...]}``): the app's settings and secrets, its bindings, "
        "a container's ``DATABASE_URL`` and NoClick's own. Never a value.",
    )
    databases: Optional[List[Dict[str, Any]]] = field(
        "databases", doc="On the deployment a container's deploy's or promote's (a rollback's) ``wait()`` gives, when "
        "the app binds databases: ``{binding, engine, variable}`` each. ``variable`` names where a Postgres "
        "database's connection URL reached the app (``DATABASE_URL``, or ``<binding>_URL`` when it binds several or "
        "sets ``DATABASE_URL`` itself), a login of the release's own that lasts as long as the release; a SQLite one "
        "has none (``variable`` None), and its ``note`` says the code reaches it through the SDK. None otherwise.",
    )

    @classmethod
    def from_id(cls, deployment_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Deployment":
        """A lazy reference to a deployment by id.

        Returns:
            A deployment that loads the first time you read a field. Nothing is sent yet.

        Usage::

            deployment = noclick.Deployment.from_id("0d6c2f8e-4b1a-4e97-a3c5-7f8e9d0c1b2a")
            for line in deployment.logs(kind="build"):
                print(line.message)
        """
        return cls._new(hints={"id": deployment_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, deployment_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Deployment":
        """Load a deployment by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The deployment, loaded.

        Usage::

            deployment = noclick.Deployment.get("0d6c2f8e-4b1a-4e97-a3c5-7f8e9d0c1b2a")
            print(deployment.status, deployment.url, deployment.error)
        """
        deployment = cls.from_id(deployment_id, client=client, user=user)
        await deployment._ensure()
        return deployment

    def _path(self) -> str:
        return f"/v1/deployments/{self._known('id')}"

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", self._path())

    @synced
    async def logs(
        self, *, kind: str = "build", limit: Optional[int] = None, level: Optional[str] = None,
        environment: str = "all",
    ) -> LogLines:
        """Its build output (``kind="build"``) or what it printed while
        serving (``kind="runtime"``), oldest first. Of runtime lines, ``level``
        keeps ``warn`` or ``error`` lines only and ``environment``
        (``production`` or ``preview``) one environment's: a promoted preview
        writes in both. A request's lines are never cut apart.

        Returns:
            The lines, or the last ``limit`` of them, with ``delay_s``: how long a runtime line can take to show.
            A build keeps every line; runtime lines are kept 7 days.

        Usage:
            Find out why a build failed::

                deployment = noclick.Deployment.get("0d6c2f8e-4b1a-4e97-a3c5-7f8e9d0c1b2a")
                if deployment.status == "failed":
                    for line in deployment.logs(kind="build"):
                        print(line.at, line.level, line.message)

            Read the last errors a preview printed, each with the request it was in::

                preview = noclick.Deployment.from_id("0d6c2f8e-4b1a-4e97-a3c5-7f8e9d0c1b2a")
                tail = preview.logs(kind="runtime", level="error", environment="preview", limit=20)
                for line in tail:
                    print(line.request_id, line.status, line.message)
                if not tail:
                    print(f"Nothing yet: a line takes up to {tail.delay_s}s to show.")
        """
        params = {"kind": kind, "limit": limit, "level": level,
                  "environment": environment if environment != "all" else None}
        return LogLines._from(await self._request("GET", f"{self._path()}/logs", params=params))

    @synced
    async def cancel(self) -> "Deployment":
        """Stop a deployment that's still ``queued`` or ``building``; one that
        already finished is left as it is.

        Returns:
            This deployment, ``canceled`` unless it had already finished.

        Usage::

            deployment = noclick.Deployment.get("0d6c2f8e-4b1a-4e97-a3c5-7f8e9d0c1b2a")
            deployment.cancel()
            print(deployment.status)   # canceled
        """
        response = await self._request("POST", f"{self._path()}/cancel")
        if isinstance(response, dict) and response.get("id"):
            self._raw = response
        return self

    @synced
    async def check(
        self,
        paths: Optional[Sequence[Union[str, Mapping[str, Any]]]] = None,
        *,
        review: Optional[Mapping[str, Any]] = None,
        wait_for: Optional[str] = None,
        settle_ms: Optional[int] = None,
        headers: Optional[Mapping[str, str]] = None,
        cookies: Optional[Sequence[Mapping[str, str]]] = None,
    ) -> Operation:
        """Check up to 10 ``paths`` of this ``ready`` deployment where it serves (its preview URL, or the app's
        URL when it's production), one after another. A path given as a string is a page, loaded in a browser:
        its HTTP status, load time, console errors and a screenshot, kept as a file the chat shows. One given as
        ``{"path": "/api/health", "status": 200}`` is what a plain request for it must answer (that status; else
        any below 400), with ``"json": True`` for a JSON body: no browser, no screenshot. A page the app's files
        serve never runs its code, so name the code's routes as requests. Without ``paths``, the app's
        ``check_paths`` (else its home page). A deployment no URL serves now can't be checked
        (``noclick.Conflict``). The browser is billed at its provider's price, by the second.

        ``review`` has a model look at the screenshots too, in one call billed at its price:
        ``{"brief": ...}`` says what the site is for (who it's for and the idea it's built on), ``"facts"`` gives
        the owner's own words about the business, and ``"rubric": "app"`` judges screens people use (their task,
        forms, states, density, tap targets) instead of a site people read (``"site"``, the default). A page its
        scripts draw after it loads is judged once an element matching the CSS selector ``wait_for`` shows (up to
        20 seconds after it loads; one it never shows on fails), and ``settle_ms`` (1,000 unless given, at most
        10,000) is how long each page is watched before its screenshot, its console errors until then counting.

        A page behind a sign-in is checked signed in: ``headers`` (an ``Authorization`` header, say) go with each
        request to the deployment's own address, never to another site, and ``cookies`` (each ``{"name",
        "value", "path"}``, the path ``/`` unless given) are set on that address alone, httpOnly, and sent with
        the request entries their path covers. They're secrets: sealed until the check runs, then dropped, never
        in its result, its log or its operation.

        Returns:
            An operation whose ``.wait()`` gives a ``DeploymentCheck``; ``passed`` is False when a path failed
            (``PathCheck.problem`` says why), and its ``review`` has the model's scores and issues.

        Usage:
            Check the pages you changed before you say they work::

                preview = noclick.Project.from_name("booking").deploy(branch="new-form").wait()
                checked = preview.check(["/", "/book"]).wait()
                for page in checked.paths:
                    print(page.path, page.status, page.problem, page.screenshot["url"])
                    for error in page.console_errors:
                        print("  ", error["kind"], error["message"])

            Check the API the page calls, and have a model review the page::

                checked = preview.check(
                    ["/", {"path": "/api/bookings", "status": 200, "json": True}],
                    review={"brief": "A booking page for Le Comptoir, a bistro in Lyon"},
                ).wait()
                print(checked.passed, checked.code_unchecked)
                print(checked.review.scores, [issue["fix"] for issue in checked.review.issues])

            Check a screen behind the app's sign-in, once it has drawn::

                checked = preview.check(
                    ["/library"], wait_for="main#docs", cookies=[{"name": "session", "value": session_token}],
                    review={"brief": "A study library for one pilot", "rubric": "app"},
                ).wait()
        """
        body = compact(
            paths=_check_paths(paths) if paths is not None else None,
            review=dict(review) if review is not None else None, wait_for=wait_for, settle_ms=settle_ms,
            headers=dict(headers) if headers is not None else None,
            cookies=[dict(c) for c in cookies] if cookies is not None else None,
        )
        payload = await self._request("POST", f"{self._path()}/check", json=body or None)
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="deployment.check", reader=_read_check,
        )

    @synced
    async def requests(self, *, since: Union[None, str, datetime] = None) -> RequestOutcomes:
        """How the requests this deployment served went since ``since`` (a timezone-aware datetime; the last 24
        hours when omitted, at most 7 days back): how many, by status, the error rate and the slowest routes.

        Returns:
            Its ``RequestOutcomes``, read from NoClick's record of each request it answered, files included.

        Usage:
            See whether a release is failing in production::

                app = noclick.Project.from_name("booking")
                outcomes = app.production.requests()
                print(outcomes.requests, outcomes.error_rate, outcomes.by_status)
                for route in outcomes.slowest_routes:
                    print(route.method, route.path, route.p95_ms)
        """
        response = await self._request("GET", f"{self._path()}/requests", params={"since": iso_time(since)})
        return RequestOutcomes._from(response)

    @synced
    async def promote(self, *, force: bool = False) -> Operation:
        """Make this ``ready`` deployment the project's production one: its
        URL starts serving this build within a minute. Promoting an older
        production deployment is a rollback. Either way it's released again,
        without a build, with production's settings, secrets and bindings as
        they are now, so a key revoked since never comes back with it. Once
        production serves it, its home page and the app's ``check_paths`` are
        asked as a deploy asks them: the deployment's ``warning`` says what
        answered wrong (it stays live). A rollback to a release from before one
        of the app's Durable Object classes parks the class (``parked``).

        An app with ``check_paths`` checks the deployment first (``check()``)
        and doesn't promote one that fails: the operation fails with the check
        in its error, and production keeps serving. ``force=True`` promotes it
        without the check. Before production switches, the databases the app
        binds are bookmarked: undoing the promote (``Operation.undo()``) puts
        them back as they were, with the release before, taking out what was
        written to them since and keeping it in the trash for 30 days as a
        database copy each. The operation's ``undo_rewinds`` says that before
        you undo, and the undo's result says it again (``warning``), with each
        copy and how it goes back (``copies``).

        Rollback covers the app's last 10 production deployments, and each
        branch's newest preview for 30 days. One older than that was retired:
        promoting it builds its commit again, checked as a promote is, and the
        operation (``project.deploy``) gives the new deployment, whose
        ``rebuilt`` says so.

        Returns:
            An operation whose ``.wait()`` gives this deployment (or, past the window, the one built
            from its commit), now ``production``.

        Usage:
            Put a preview live once you've checked it::

                app = noclick.Project.from_name("booking")
                preview = app.deploy(branch="new-form").wait()
                print(preview.url)   # check it here first
                preview.promote().wait()

            Take it back, data included, if it goes wrong::

                promoted = preview.promote()
                promoted.wait()
                promoted.undo()
        """
        payload = await self._request("POST", f"{self._path()}/promote", json={"force": True} if force else None)
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="deployment.promote",
            reader=_read_deployment,
        )


# --- schedules -------------------------------------------------------------


class Schedule(_Object):
    """A project's cron job: NoClick POSTs ``path`` on the app on every tick
    of ``cron`` (read in ``tz``). When 5 runs in a row fail the same way over
    at least 30 minutes it pauses itself (``status`` ``paused``,
    ``paused_reason`` says why) until you ``resume()`` it."""

    _repr_keys = ("id", "cron", "path", "status")

    id: str = field("id")
    project_id: str = field("project_id")
    name: str = field("name", doc="What keys it within the project (the path unless you named it).")
    cron: str = field("cron", doc="The five-field cron expression.")
    tz: str = field("tz")
    path: str = field("path")
    status: str = field("status", doc="``active`` or ``paused``.")
    paused_reason: Optional[str] = field("paused_reason")
    next_run: Any = field("next_run", parse_time)
    last_run: Any = field("last_run", parse_time)
    last_status: Optional[str] = field(
        "last_status", doc="How the last run went: ``succeeded`` (a 2xx answer) or ``failed`` (None before the first).",
    )
    last_error: Optional[str] = field(
        "last_error", doc="Why the last run failed, in one line (``Answered 500.``); None after a success.",
    )
    created_at: Any = field("created_at", parse_time)

    @classmethod
    def from_id(cls, schedule_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Schedule":
        """A lazy reference to a schedule by id.

        Returns:
            A schedule that loads the first time you read a field. Nothing is sent yet.

        Usage::

            schedule = noclick.Schedule.from_id("6a1f3c9e-2d4b-4e8a-b7c0-5d9e8f1a2b3c")
            schedule.pause()
        """
        return cls._new(hints={"id": schedule_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, schedule_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Schedule":
        """Load a schedule by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The schedule, loaded.

        Usage::

            schedule = noclick.Schedule.get("6a1f3c9e-2d4b-4e8a-b7c0-5d9e8f1a2b3c")
            print(schedule.cron, schedule.tz, schedule.next_run, schedule.last_status)
        """
        schedule = cls.from_id(schedule_id, client=client, user=user)
        await schedule._ensure()
        return schedule

    def _path(self) -> str:
        return f"/v1/schedules/{self._known('id')}"

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", self._path())

    async def _act(self, verb: str) -> "Schedule":
        response = await self._request("POST", f"{self._path()}/{verb}")
        if isinstance(response, dict) and response.get("id"):
            self._raw = response
        return self

    @synced
    async def pause(self) -> "Schedule":
        """Stop firing until ``resume()``.

        Returns:
            This schedule, ``paused``.

        Usage::

            schedule = noclick.Schedule.get("6a1f3c9e-2d4b-4e8a-b7c0-5d9e8f1a2b3c")
            schedule.pause()
        """
        return await self._act("pause")

    @synced
    async def resume(self) -> "Schedule":
        """Fire again from the next tick, clearing ``paused_reason``.

        Returns:
            This schedule, ``active``, with its ``next_run``.

        Usage:
            Fix what made it fail, then resume it::

                app = noclick.Project.from_name("booking")
                for schedule in app.schedules():
                    if schedule.status == "paused":
                        print(schedule.path, schedule.paused_reason)
                        schedule.resume()
        """
        return await self._act("resume")

    @synced
    async def run_now(self) -> "Schedule":
        """Call its path once now, outside the cron, and wait for the answer
        (at most 30 seconds). A paused schedule runs too, and stays paused.

        Returns:
            This schedule, with ``last_run`` and ``last_status`` from that call.

        Usage::

            schedule = noclick.Schedule.get("6a1f3c9e-2d4b-4e8a-b7c0-5d9e8f1a2b3c")
            schedule.run_now()
            print(schedule.last_status)   # succeeded
        """
        return await self._act("run")

    @synced
    async def delete(self) -> None:
        """Delete the schedule; it stops firing.

        Usage::

            schedule = noclick.Schedule.from_id("6a1f3c9e-2d4b-4e8a-b7c0-5d9e8f1a2b3c")
            schedule.delete()
        """
        await self._request("DELETE", self._path())


# --- Durable Objects --------------------------------------------------------


@dataclass(frozen=True)
class DurableObjectInstance:
    """One object of a Durable Object class, as its host lists it: its ``id`` and whether it holds data. What it
    stores is reached only by the app's own code."""

    id: str
    has_stored_data: bool


class DurableObjectClasses(List["DurableObjectClass"]):
    """An app's classes; ``unread`` names a figure the host couldn't report this time (``stored_bytes`` or
    ``objects``), left None on each class rather than shown as nothing; ``cost`` is what the app's Durable Objects
    were charged this month, every environment's together (``{"usd", "period_start"}``; None with no classes)."""

    unread: List[str]
    cost: Optional[Dict[str, Any]]


class DurableObjectClass(_Object):
    """One of an app's Durable Object classes in one environment (production's, or a preview branch's): its
    ``name``, the ``binding`` its code reaches it by, how many ``objects`` it has (``objects_more`` when there were
    more than were counted) and what they store (``stored_bytes``, the latest the host reported; None when it
    couldn't be read). ``status`` is ``trashed`` while it's in the trash, ``parked`` while no release that serves
    exports it (a rollback to a release from before it, or a live edit's release that added it and never went live),
    and ``stopped`` while its environment's objects
    are stopped (``stopped_for``: the app in the trash, or past its hard spending limit), their data kept. Its
    objects' data is reached only by the app's own code."""

    _repr_keys = ("name", "environment", "status", "objects")

    id: str = field("id")
    project_id: str = field("project_id")
    name: str = field("name")
    binding: Optional[str] = field("binding", doc="The name the app's code reaches it by (``env.ROOM``).")
    environment: str = field("environment", doc="``production`` or ``preview``.")
    branch: Optional[str] = field("branch", doc="A preview's branch; None in production.")
    status: str = field("status", doc="``live``, ``trashed`` while it's in the trash, ``parked`` (kept behind a "
                        "stub, its data kept, while no release that serves exports it), or ``stopped`` (its "
                        "environment's objects stopped, its data kept).")
    stopped_for: Optional[str] = field("stopped_for", doc="Why its objects are stopped: ``trash``, or ``budget`` (the "
                                       "app past its hard spending limit); None when they run.")
    objects_count: Optional[int] = field("objects", doc="How many objects it has; None when the host couldn't say.")
    objects_more: bool = field("objects_more", doc="More objects than were counted.")
    stored_bytes: Optional[int] = field("stored_bytes")
    added_by_deployment_id: Optional[str] = field("added_by_deployment_id")
    created_at: Any = field("created_at", parse_time)
    parked_at: Any = field("parked_at", parse_time)
    trashed_at: Any = field("trashed_at", parse_time)
    trash_id: Optional[str] = field("trash_id", doc="Its entry in the trash while it's there.")
    restorable_until: Any = field("restorable_until", parse_time)

    def _path(self, tail: str = "") -> str:
        return f"/v1/projects/{self._known('project_id')}/durable_objects/{self._known('id')}{tail}"

    async def _load(self) -> Dict[str, Any]:
        listed = await self._request("GET", f"/v1/projects/{self._known('project_id')}/durable_objects")
        for row in (listed or {}).get("data") or []:
            if row.get("id") == self._known("id"):
                return row
        raise NotFound("The app has no such Durable Object class.",
                       next_step="List them with app.durable_objects().")

    @synced
    async def objects(self, *, limit: int = 100, cursor: Optional[str] = None) -> Page[DurableObjectInstance]:
        """A page of its objects, as the host lists them.

        Returns:
            A page of ``DurableObjectInstance``; pass ``next_cursor`` as ``cursor`` for the next.

        Usage::

            app = noclick.Project.from_name("chat")
            room = next(c for c in app.durable_objects() if c.name == "Room")
            page = room.objects()
            print([o.id for o in page.data if o.has_stored_data])
        """
        found = await self._request("GET", self._path("/objects"),
                                    params=compact({"limit": limit, "cursor": cursor}))
        rows = (found or {}).get("data") or []
        return Page([DurableObjectInstance(str(r.get("id")), bool(r.get("has_stored_data"))) for r in rows],
                    (found or {}).get("next_cursor"))

    @synced
    async def delete(self) -> TrashItem:
        """Move the class to the trash for 30 days: its objects and their data are kept, and every request and alarm
        reaching it is refused meanwhile. A key from code, an agent or an MCP connection gets
        ``noclick.ApprovalRequired``: the account's owner approves it from the link NoClick sends them. Restore it
        from the trash to have it back; a release that deletes the class (``deleted_classes``) deploys once it's
        there.

        Returns:
            The trash entry, with ``restore()``.

        Usage::

            app = noclick.Project.from_name("chat")
            old = next(c for c in app.durable_objects() if c.name == "OldRoom")
            item = old.delete()
            item.restore()   # changed your mind
        """
        return trashed(await self._request("DELETE", self._path()), client=self._client, user=self._call_scope())


# --- secrets ---------------------------------------------------------------


def _environment(environment: str) -> Dict[str, str]:
    """A secret's ``environment`` on the wire: left out for ``all``."""
    return {} if environment == "all" else {"environment": environment}


class ProjectSecrets(_Service):
    """``app.secrets``: values the running app reads from its environment by
    name, set for production deployments, previews or both. Values are
    write-only; nothing reads one back. An app's environment holds 128 values
    in all, NoClick's own and each bound secret's included."""

    _name = "secrets"

    @synced
    async def set(self, name: str, value: str, *, environment: str = "all") -> None:
        """Set the secret ``name`` (letters, digits and ``_``, starting with a
        letter) to ``value`` (at most 5 KB), replacing any value it had, for
        ``environment``: ``production`` (deploys of the production branch, and
        what's promoted), ``preview`` (every other branch) or ``all``. It
        reaches the app at the next deployment. Keep a larger value in a bound
        ``noclick.Secret`` or bucket the app reads.

        Usage:
            The same key everywhere::

                app = noclick.Project.from_name("booking")
                app.secrets.set("MAPS_API_KEY", "...")
                app.deploy()

            A live key in production and a test key in previews::

                app = noclick.Project.from_name("booking")
                app.secrets.set("STRIPE_KEY", "sk_live_...", environment="production")
                app.secrets.set("STRIPE_KEY", "sk_test_...", environment="preview")
        """
        await self._request("PUT", name, json={"value": value, **_environment(environment)})

    @synced
    async def list(self, *, environment: str = "all") -> Dict[str, datetime]:
        """The project's secrets by name, never their values: those set for
        ``environment`` (``production``, ``preview`` or ``all``).

        Returns:
            Each secret's name mapped to when its value was last set.

        Usage::

            app = noclick.Project.from_name("booking")
            for name, updated_at in app.secrets.list(environment="preview").items():
                print(name, updated_at)
        """
        response = await self._request("GET", params=_environment(environment)) or {}
        return {row["name"]: parse_time(row.get("updated_at")) for row in response.get("data") or []}

    @synced
    async def delete(self, name: str, *, environment: str = "all") -> None:
        """Delete the secret ``name`` from ``environment`` (``all`` by default);
        the app stops seeing it at the next deployment. A name that isn't set
        there raises ``noclick.NotFound``.

        Usage::

            app = noclick.Project.from_name("booking")
            app.secrets.delete("MAPS_API_KEY")
        """
        await self._request("DELETE", name, params=_environment(environment))

    @synced
    async def versions(self, name: str, *, environment: str = "all") -> List[Version]:
        """What ``name`` held before each change or deletion of the last 30 days, newest first, in
        ``environment`` (``production``, ``preview`` or ``all``), never the values.

        Returns:
            Each earlier version, with its ``environment``.

        Usage::

            app = noclick.Project.from_name("booking")
            for version in app.secrets.versions("STRIPE_KEY", environment="production"):
                print(version.op, version.replaced_at)
        """
        return versions_of(await self._request("GET", name, "versions", params=_environment(environment)))

    @synced
    async def restore(self, name: str, version: Any) -> None:
        """Set ``name`` back to ``version``'s value in its environment (deleted since, it's back). It reaches the
        app at the next deployment.

        Usage:
            Undo deleting a secret::

                app = noclick.Project.from_name("booking")
                app.secrets.delete("MAPS_API_KEY")
                app.secrets.restore("MAPS_API_KEY", app.secrets.versions("MAPS_API_KEY")[0])
        """
        await self._request("POST", name, "versions", version_id(version), "restore")


class ProjectSettings(_Service):
    """``app.settings``: plain values the running app reads from its environment by
    name, such as a feature flag or a public URL. Unlike ``app.secrets`` they read back,
    and they show in the console; put anything sensitive in ``app.secrets``."""

    _name = "settings"

    @synced
    async def set(self, name: str, value: str) -> None:
        """Set ``name`` (letters, digits and ``_``, starting with a letter; not a secret's
        name) to ``value`` (at most 4 KB). It reaches the app at the next deployment.

        Usage::

            app = noclick.Project.from_name("booking")
            app.settings.set("PUBLIC_BASE_URL", "https://book.acme.com")
            app.deploy()
        """
        await self._request("PUT", name, json={"value": value})

    @synced
    async def list(self) -> Dict[str, str]:
        """The project's settings and their values.

        Returns:
            Each setting's name mapped to its value.

        Usage::

            app = noclick.Project.from_name("booking")
            for name, value in app.settings.list().items():
                print(name, value)
        """
        response = await self._request("GET") or {}
        return {row["name"]: row.get("value") or "" for row in response.get("data") or []}

    @synced
    async def delete(self, name: str) -> None:
        """Delete the setting ``name``; the app stops seeing it at the next deployment.
        A name that isn't set raises ``noclick.NotFound``.

        Usage::

            app = noclick.Project.from_name("booking")
            app.settings.delete("PUBLIC_BASE_URL")
        """
        await self._request("DELETE", name)

    @synced
    async def versions(self, name: str) -> List[Version]:
        """What ``name`` held before each change or deletion of the last 30 days, newest first, with each
        ``value``.

        Returns:
            Each earlier version.

        Usage::

            app = noclick.Project.from_name("booking")
            print([v.value for v in app.settings.versions("PUBLIC_BASE_URL")])
        """
        return versions_of(await self._request("GET", name, "versions"))

    @synced
    async def restore(self, name: str, version: Any) -> str:
        """Set ``name`` back to ``version``'s value (deleted since, it's back). It reaches the app at the next
        deployment.

        Returns:
            The value it holds again.

        Usage::

            app = noclick.Project.from_name("booking")
            app.settings.restore("PUBLIC_BASE_URL", app.settings.versions("PUBLIC_BASE_URL")[0])
        """
        restored = await self._request("POST", name, "versions", version_id(version), "restore")
        return restored["value"]


# --- AI as the app ---------------------------------------------------------


class ProjectAI(_Service):
    """``app.ai``: ``noclick.AI`` acting as the app, from the app's own code
    (``Project.current()``). Every call is billed to your account and attributed to the app
    and its user: it counts toward the app's ``budget_usd_per_month`` and its user's cap, and
    raises ``noclick.SpendCapExceeded`` once either is used up (``noclick.PaymentRequired``
    once your account's balance is). Only the app acts as the app: on a project reached with
    your own key, each call raises ``noclick.InvalidRequest`` (use ``noclick.AI`` there,
    inside ``as_user`` for the app's user)."""

    def _client(self) -> Client:
        if not self._project._hints.get("current"):
            raise InvalidRequest(
                "app.ai acts as the app, so it runs in the app's own code, from noclick.Project.current().",
                next_step="From your own code, call noclick.AI inside noclick.as_user(<the app's user>).",
            )
        return resolve_client(self._project._client)

    @property
    def base_url(self) -> str:
        """The OpenAI-compatible endpoint, for an OpenAI client in the app's code; pair it
        with ``headers()``, which carry the deployment's credential."""
        return f"{self._client().base_url}/v1/ai"

    @synced
    async def chat(
        self,
        messages: Union[str, Sequence[Any]],
        *,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, Any]] = None,
        tools: Optional[Sequence[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
        conversation: Optional[str] = None,
    ) -> ChatReply:
        """``noclick.AI.chat`` as the app, with the same arguments. ``model="agent:<name>"``
        reaches only an agent bound to the app, in the app's own conversations.

        Returns:
            The answer: its ``text``, the ``message`` to append, and what it cost.

        Usage:
            Summarize a review in a request handler::

                app = noclick.Project.current()
                reply = app.ai.chat("Summarize in one line: the class was great but the room was cold.")
                print(reply.text)

            Serve the page without the summary once the app's budget is used up::

                app = noclick.Project.current()
                try:
                    summary = app.ai.chat("Summarize in one line: the class was great but the room was cold.").text
                except (noclick.SpendCapExceeded, noclick.PaymentRequired):
                    summary = None
        """
        return await AI.chat.aio(
            messages, model=model, max_tokens=max_tokens, temperature=temperature,
            response_format=response_format, tools=tools, tool_choice=tool_choice,
            reasoning_effort=reasoning_effort, conversation=conversation, user=None, client=self._client(),
        )

    @synced
    async def embed(
        self, texts: Union[str, Sequence[str]], *, model: Optional[str] = None, dimensions: Optional[int] = None,
    ) -> Embeddings:
        """``noclick.AI.embed`` as the app.

        Returns:
            One vector per text, in order, with their length and what the call cost.

        Usage::

            app = noclick.Project.current()
            [vector] = app.ai.embed("Yoga for beginners on Saturday mornings").vectors
            classes = app.database("DB").query(
                "select id, title from classes order by embedding <=> cast(? as halfvec) limit 5", [vector])
        """
        return await AI.embed.aio(texts, model=model, dimensions=dimensions, user=None, client=self._client())

    @synced
    async def image(self, prompt: str, *, model: Optional[str] = None, size: Optional[str] = None,
                    images: Optional[Sequence[str]] = None) -> GeneratedImage:
        """``noclick.AI.image`` as the app.

        Returns:
            The image: a signed ``url`` that lasts 24 hours, its size and what it cost.

        Usage::

            app = noclick.Project.current()
            image = app.ai.image("A sunlit yoga studio, watercolor", size="1024x1024")
            print(image.url, image.cost_usd)
        """
        return await AI.image.aio(prompt, model=model, size=size, images=images, user=None, client=self._client())

    @synced
    async def transcribe(
        self,
        audio: Union[str, bytes],
        *,
        model: Optional[str] = None,
        language: Optional[str] = None,
        speakers: Union[bool, Sequence[str]] = False,
    ) -> Transcript:
        """``noclick.AI.transcribe`` as the app: an ``https`` URL to a recording, or its bytes.

        Returns:
            The transcript: its ``text``, timed ``segments``, the ``language`` and how long the audio was.

        Usage::

            app = noclick.Project.current()
            words = app.ai.transcribe("https://booking.noclick.site/uploads/voicemail-1042.m4a", language="en")
            print(words.text)
        """
        return await AI.transcribe.aio(
            audio, model=model, language=language, speakers=speakers, user=None, client=self._client(),
        )

    @synced
    async def models(self, *, kind: Optional[str] = None) -> List[AIModel]:
        """The models the app can call, as ``noclick.AI.models`` lists them; ``kind="agent"``
        lists the agents bound to it.

        Returns:
            Every matching model with its prices in US dollars, the default of each kind first.

        Usage::

            app = noclick.Project.current()
            for m in app.ai.models(kind="chat"):
                print(m.id, m.input_usd_per_token, m.output_usd_per_token)
        """
        return await AI.models.aio(kind=kind, user=None, client=self._client())

    @synced
    async def headers(self) -> Dict[str, str]:
        """The headers an OpenAI client in the app's code sends to ``base_url``: the
        deployment's credential as the bearer, so every call is the app's.

        Returns:
            ``Authorization``.

        Usage:
            Code written for OpenAI's client works as the app::

                from openai import OpenAI

                app = noclick.Project.current()
                gpt = OpenAI(base_url=app.ai.base_url, api_key="-", default_headers=app.ai.headers())
                answer = gpt.chat.completions.create(
                    model="openrouter/anthropic/claude-sonnet-4.6", messages=[{"role": "user", "content": "Hi"}])
        """
        return await AI.headers.aio(user=None, client=self._client())


# --- the project -----------------------------------------------------------

# What ``from_name`` sets on an existing project.
_CONVERGED = ("repo_id", "runtime", "framework", "production_branch", "budget_usd_per_month", "region",
              "deploy_on_push", "preview_resources", "check_paths")


def _a(kind: str) -> str:
    return f"an {kind}" if kind[:1] in "aeiou" else f"a {kind}"


def _check_paths(paths: Sequence[Union[str, Mapping[str, Any]]]) -> List[Any]:
    """Check paths on the wire: a page's path as it is, a request entry as a plain dict."""
    return [dict(path) if isinstance(path, Mapping) else path for path in paths]


_BINDABLE = {
    "Database": "database", "Bucket": "bucket", "Connection": "connection",
    "Dict": "dict", "Queue": "queue", "Secret": "secret", "Agent": "agent",
}


class Project(_Object):
    """An app: a repo deployed to a URL. ``Project.from_name("booking",
    repo=repo, create_if_missing=True)`` is lazy; ``app.deploy()`` builds and
    ships it."""

    _repr_keys = ("id", "name", "url")

    id: str = field("id")
    name: str = field("name")
    url: str = field("url", doc="Its production URL (``https://<name>.noclick.site`` until a domain serves it).")
    hostname: str = field(
        "hostname", doc="Its own name under NoClick's user-sites domain (``booking.noclick.site``), which never "
        "changes (NoClick moves only an app it publishes, when it's renamed where it was published from).",
    )
    repo_id: Optional[str] = field("repo_id", doc="None for an app NoClick publishes (``published``).")
    published: bool = field(
        "published", doc="NoClick publishes its files itself (an automation's interface): it has no repo, and "
        "deploys when it's published again from there.",
    )
    workflow: Optional[Dict[str, Any]] = field(
        "workflow", doc="``{id, name, step}`` of the automation it was published from (None for every other app): "
        "``step`` is the interface it serves, for a key that reads workflows (None for any other), which renaming or "
        "unpublishing one of several takes: ``workflow.build(publish={\"action\": \"unpublish\", \"step\": step})``.",
    )
    runtime: str = field(
        "runtime", doc="``auto`` (each deployment runs where its commit says: ``Deployment.runtime``), ``edge`` "
        "(JavaScript frameworks and files) or ``container`` (any server, in any language).",
    )
    framework: Optional[str] = field(
        "framework", doc="On ``edge``: ``nextjs``, ``remix``, ``astro``, ``vite`` or ``static``; on ``container``: "
        "``python``, ``node`` or ``docker`` (the repo's own Dockerfile); under ``auto`` either, which names its "
        "runtime. Detected at each build when None.",
    )
    production_branch: str = field("production_branch", doc="The branch whose deploys go live (the repo's default).")
    domain_names: List[str] = field(
        "domain_names", doc="The live hostnames of the domains serving it, oldest first; ``domains()`` loads the domains.",
    )
    deploy_on_push: str = field(
        "deploy_on_push", doc="What a push to its repo deploys by itself: ``off`` (only ``deploy()`` deploys), "
        "``production`` (a push to the production branch deploys it) or ``all`` (any other branch's push deploys "
        "a preview too).",
    )
    preview_resources: str = field(
        "preview_resources", doc="``branch``: each preview branch gets its own copy of every resource its code names, "
        "made the first time it writes to one (until then it reads production's), so preview data never reaches "
        "production; ``shared``: previews use production's resources. New apps start with ``branch``.",
    )
    preview_access: str = field(
        "preview_access", doc="Who opens its previews: ``public`` (every app's unless set: anyone with a preview's "
        "URL, while search engines are told not to list it) or ``link`` (only a link NoClick signs, from "
        "``preview_link()`` or a preview's deploy, until ``revoke_preview_links()``; anyone else is told it's "
        "private). Production is always public. ``link`` is refused for an app whose previews run in containers "
        "until NoClick turns on front-door-only containers, since a container answers at its own address too.",
    )
    preview_public_paths: List[str] = field(
        "preview_public_paths", doc="With ``preview_access`` ``link``, the paths of a preview that stay open to anyone "
        "(``/auth/callback`` exactly, or everything under ``/api/webhooks/*``): what calls a preview without a "
        "person's browser, such as a webhook's sender or an OAuth provider's redirect. Empty unless set.",
    )
    budget_usd_per_month: Optional[float] = field(
        "budget_usd_per_month", doc="The most it may spend in a calendar month, in US dollars: $10 unless its maker set "
                                    "another. An app with code always has one; None only for an app NoClick publishes.",
    )
    check_paths: List[Union[str, Dict[str, Any]]] = field(
        "check_paths", doc="What a ``Deployment.check()`` asks when it names no paths, what a promote checks where "
        "the release serves and then at production's URL, and what a deploy of code asks once it's live: each a "
        "page's path (``/pricing``), loaded in a browser, or what a plain request for a path must answer "
        "(``{\"path\": \"/api/health\", \"status\": 200}``, with ``\"json\": True`` for a JSON body). Empty: "
        "promotes aren't checked, and a deploy asks only the home page.",
    )
    region: Optional[str] = field(
        "region", doc="The region its server code is placed near (``noclick.regions()``), fixed when it was created.",
    )
    live_editing: bool = field(
        "live_editing", doc="Whether it's edited live (``app.live``): each edit swaps into the pages its owner has "
        "open, and deploys when the session ends. On from its first production release for an app live editing "
        "can run.",
    )
    live_editing_set_by: Optional[str] = field(
        "live_editing_set_by", doc="Who set ``live_editing`` last: ``owner`` (set with ``update``, which NoClick "
        "never turns back on), ``noclick`` (its default), or None while nobody has.",
    )
    badge: bool = field(
        "badge", bool, doc="Whether its production pages carry the \"Built with NoClick\" link: while its paying "
        "account's plan keeps NoClick's branding.",
    )
    badge_corner: str = field(
        "badge_corner", doc="The corner of its pages the badge sits in, where it carries one: ``bottom-right`` unless "
        "set with ``update`` (``bottom-left``, ``top-right`` or ``top-left``).",
    )
    container: ProjectContainer = field(
        "container", ProjectContainer._from, doc="How each of its instances runs in a container (``cpu``, "
        "``memory``, ``min_instances``, ``max_instances``, ``cpu_always``, ``request_timeout_s``), and what its warm "
        "instances cost a month with nothing calling it (``idle_usd_per_month``, with a ``note`` in words). Set with "
        "``create`` or ``update``; each release runs at the settings it was released with.",
    )
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    @property
    def production(self) -> Optional[Deployment]:
        """The deployment serving ``url`` (None before the first production deploy)."""
        view = self._sync_raw().get("production")
        return Deployment._new(raw=view, client=self._client, user=self._call_scope()) if view else None

    @property
    def repo(self) -> Optional[Repo]:
        """The repo it deploys from (None for an app NoClick publishes)."""
        if self.repo_id is None:
            return None
        return Repo.from_id(self.repo_id, client=self._client, user=self._call_scope())

    @property
    def secrets(self) -> ProjectSecrets:
        """Its secrets: ``app.secrets.set("MAPS_API_KEY", "...")``."""
        return ProjectSecrets(self)

    @property
    def settings(self) -> ProjectSettings:
        """Its plain settings: ``app.settings.set("PUBLIC_BASE_URL", "...")``."""
        return ProjectSettings(self)

    @property
    def email(self) -> ProjectEmail:
        """Transactional email from the app."""
        return ProjectEmail(self)

    @property
    def payments(self) -> ProjectPayments:
        """Payments into an account the owner claims."""
        return ProjectPayments(self)

    @property
    def sign_in(self) -> ProjectSignIn:
        """Sign-in for the app's own users."""
        return ProjectSignIn(self)

    @property
    def ai(self) -> ProjectAI:
        """``noclick.AI`` acting as the app, from its own code: ``app.ai.chat(...)``."""
        return ProjectAI(self)

    @property
    def live(self) -> ProjectLive:
        """Its live editing session: ``app.live.start()``."""
        return ProjectLive(self)

    # --- construction ----------------------------------------------------

    @staticmethod
    def _body(
        name: str, repo: Any, framework: Optional[str], production_branch: Optional[str], budget: Any = UNSET,
        region: Optional[str] = None, runtime: Optional[str] = None, deploy_on_push: Optional[str] = None,
        preview_resources: Optional[str] = None, check_paths: Optional[Sequence[Any]] = None,
    ) -> Dict[str, Any]:
        # ``repo_id`` may still be a lazy Repo here; ``_wire`` resolves it. An explicit None budget clears it.
        body = compact(name=name, repo_id=repo, runtime=runtime, framework=framework,
                       production_branch=production_branch, region=region, deploy_on_push=deploy_on_push,
                       preview_resources=preview_resources,
                       check_paths=_check_paths(check_paths) if check_paths is not None else None)
        if budget is not UNSET:
            body["budget_usd_per_month"] = budget
        return body

    @staticmethod
    async def _wire(body: Dict[str, Any]) -> Dict[str, Any]:
        if "repo_id" in body:
            body = {**body, "repo_id": await ref_id(body["repo_id"])}
        return body

    @synced
    @classmethod
    async def create(
        cls,
        name: str,
        *,
        repo: Any = None,
        runtime: Optional[str] = None,
        framework: Optional[str] = None,
        production_branch: Optional[str] = None,
        budget_usd_per_month: Optional[float] = None,
        region: Optional[str] = None,
        deploy_on_push: Optional[str] = None,
        preview_resources: Optional[str] = None,
        check_paths: Optional[Sequence[Union[str, Mapping[str, Any]]]] = None,
        container: Optional[Union[Mapping[str, Any], ProjectContainer]] = None,
        allow_existing: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Project":
        """Create a project called ``name`` (unique per user; a duplicate
        raises ``noclick.Conflict`` with ``existing_id``, or with ``allow_existing=True``
        returns the project already there, as it is: nothing about it changes) that deploys ``repo``
        (a ``noclick.Repo`` or its id). Without ``repo`` a new, empty repo of
        the same name is created for it. ``runtime`` is ``auto`` unless given:
        each deployment runs where its commit says, on the edge (a wrangler
        config naming its entry, a JavaScript framework, or only files: server
        code in isolates, static files served from everywhere) or in a
        container that scales to zero (a Dockerfile, or a server in another
        language: Flask, Django, Go, or a Node server with a ``start`` script),
        and the deployment says which and why. ``edge`` or ``container`` pins
        it there whatever the commit has. ``framework`` is detected from the
        repo at each build when omitted: on ``edge`` ``nextjs``, ``remix``,
        ``astro``, ``vite`` or ``static``; on ``container`` ``docker`` (the
        repo's own Dockerfile), else ``python`` or ``node``.
        ``production_branch`` is the repo's default branch.
        ``deploy_on_push`` (``off`` unless given) makes a push deploy by itself:
        ``production`` deploys a push to the production branch, ``all`` a push
        to any other branch too, as a preview.
        ``budget_usd_per_month`` caps what the app may spend in a calendar month:
        its hosting and builds, its calls to what it's bound to, its email, its AI
        and the agent turns it starts, all of which count toward its user's cap too.
        Every app gets one: $10 unless you pass another (an agent making a site sets
        one that fits it). At it the app's paid calls stop and its pages keep serving;
        at twice it its pages pause.
        ``region`` (``noclick.regions()``) places its server code near that region,
        for good: put it with the database it binds (``region=db.region``), so its
        queries stay short. Without one, your account's default region, else
        ``us-east``. Its static files are served from everywhere. It says where the
        code runs, not where data stays: that's the database's and bucket's region.
        ``preview_resources`` is ``branch`` unless given: each preview branch gets
        its own copy of every database, bucket, dict and queue its code reaches,
        made at its first write, so a preview never changes production's data
        (``shared``: previews use production's). ``check_paths`` (up to 10) are
        what a deploy of code asks once it's live, what a promote checks and what
        ``Deployment.check()`` asks when it names none: each a page's path
        (``/pricing``), loaded in a browser, or what a plain request for a path
        must answer (``{"path": "/api/health", "status": 200}``, with
        ``"json": True`` for a JSON body), as ``update()`` takes them.
        ``container`` sizes each instance of its releases in a container, by
        name: ``cpu`` (vCPUs, 1 unless given), ``memory`` (MiB, 512),
        ``min_instances`` kept running while production serves it whether or
        not anything calls it (0), ``max_instances`` (10), ``cpu_always`` (CPU
        between requests too, for a bot or a worker: each instance billed from
        start to stop) and ``request_timeout_s`` (300); ``ProjectContainer``
        says each one's bounds. A setting out of bounds raises
        ``noclick.InvalidRequest`` naming it (``container.memory``), and so
        do warm instances whose cost alone passes the budget
        (``container.min_instances``, with their ``idle_usd_per_month``).

        Returns:
            The new project, loaded. Nothing is deployed until ``deploy()``.

        Usage:
            Deploy code you already committed::

                repo = noclick.Repo.from_name("booking")
                app = noclick.Project.create("booking", repo=repo)
                print(app.url)   # https://booking.noclick.site

            Inside ``as_user`` the app is that user's, and what it spends counts toward their cap
            and its own budget::

                with noclick.as_user("acme"):
                    app = noclick.Project.create("status-page", framework="astro", budget_usd_per_month=10)

            Check its API, not only its home page, at every deploy and promote::

                app = noclick.Project.create(
                    "booking", repo=repo, preview_resources="branch",
                    check_paths=["/", {"path": "/api/health", "status": 200}],
                )

            Run a Discord bot that stays connected with nothing calling it: one instance kept running, its CPU
            on between requests::

                bot = noclick.Project.create(
                    "standup-bot", repo=repo, runtime="container",
                    container={"cpu_always": True, "min_instances": 1},
                )
                print(bot.container.idle_usd_per_month, bot.container.note)
        """
        scope = resolve_scope(user)
        budget = UNSET if budget_usd_per_month is None else budget_usd_per_month
        body = await cls._wire(cls._body(name, repo, framework, production_branch, budget, region, runtime,
                                         deploy_on_push, preview_resources, check_paths))
        if container is not None:
            body["container"] = _container(container)
        raw = await cls._create_named("/v1/projects", body, allow_existing=allow_existing, user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        repo: Any = None,
        create_if_missing: bool = False,
        runtime: Optional[str] = None,
        framework: Optional[str] = None,
        production_branch: Optional[str] = None,
        budget_usd_per_month: Any = UNSET,
        region: Optional[str] = None,
        deploy_on_push: Optional[str] = None,
        preview_resources: Optional[str] = None,
        check_paths: Optional[Sequence[Union[str, Mapping[str, Any]]]] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Project":
        """A lazy reference to the project called ``name`` in the current (or
        given) user. Given fields, it gets the project and sets the ones you pass, on every run: an
        existing project whose repo, runtime, framework, production branch, budget,
        ``deploy_on_push``, ``preview_resources`` or ``check_paths`` differ gets yours.
        ``create_if_missing=True`` creates it with the fields ``Project.create`` takes when there's
        none; without it, a missing project raises ``noclick.NotFound``. A field you leave out is
        never changed; an app with code always has a budget, so
        ``budget_usd_per_month=None`` raises ``noclick.InvalidRequest``.
        ``region`` is fixed once it's created: an existing app in another region
        raises ``noclick.Conflict`` naming its ``region``. Each run with fields is a write: set
        them in a setup script or at deploy, and take the bare ``from_name`` in the app's handlers.

        Returns:
            A project that loads (or is created, or has your fields set) the first time it's used.
            Nothing is sent yet.

        Usage:
            Refer to an app by name::

                app = noclick.Project.from_name("booking")
                print(app.url, app.production)

            Or get it, creating it if it's missing, and set its fields. The same lines set it up the
            first time and deploy it every time after::

                repo = noclick.Repo.from_name("booking", create_if_missing=True)
                app = noclick.Project.from_name("booking", repo=repo, budget_usd_per_month=25, create_if_missing=True)
                app.deploy().wait()
        """
        project = cls._new(hints={"name": name}, client=client, user=user)
        project._define(cls._body(
            name, repo, framework, production_branch, budget_usd_per_month, region, runtime, deploy_on_push,
            preview_resources, check_paths,
        ), create_if_missing=create_if_missing)
        return project

    @classmethod
    def current(cls, *, client: Optional[Client] = None) -> "Project":
        """The app this code runs in, from inside a deployment. NoClick puts the
        deployment's own credential in its environment (``NOCLICK_DEPLOYMENT_TOKEN``), so
        the app's code holds no key, and the whole client (``noclick.Agent``,
        ``noclick.Database``, ``noclick.AI``, ...) acts as a key of the app's user, attributed
        to the app. Outside a deployment it raises ``noclick.Unauthenticated``; pass
        ``client=`` to act with a key of your own instead. Python runs in an app on the
        ``container`` runtime; an ``edge`` app's code uses the TypeScript client's
        ``Project.current()``.

        What its code makes (an agent, a database, a sandbox) or buys (a phone number, a domain)
        is the app's own. Its user's other resources it reads and uses but never changes or
        deletes (on one bound to the app, it may clear its data), and it never reaches another
        app, another user, or what another app's code made. It never mints or revokes keys,
        sets a cap or budget (its own included), changes policy, answers approvals, accepts
        terms for a person, or reads secrets' values or raw tokens: those raise
        ``noclick.PermissionDenied``. It talks to agents in threads of its own (``agent``), and
        never to one holding the ``noclick`` tool. The app's code decides who may make it do
        what: policy doesn't judge its calls (an agent it messages still runs under its policy).

        What the app does is billed to your account, attributed to the app and its user, and
        counts toward the app's ``budget_usd_per_month`` and its user's cap: what its code
        spends, what it buys (each renewal in the month it renews) and what bills after its
        request (its numbers' calls and texts, its automations' runs, its MCP servers, channels,
        machines and cards). A purchase must fit what's left of the budget, and one in a
        person's name raises ``noclick.ApprovalRequired`` until they approve it. Once the budget
        or the cap is used up the app keeps serving and reading its data, but its paid calls
        (writes, email, ``app.ai``, agent turns) raise ``noclick.SpendCapExceeded`` naming the
        app; catch it and serve the page without them.

        Returns:
            The app, loaded on first use. Nothing is sent yet.

        Usage:
            In a request handler of a deployed app, read what the app is bound to by name::

                app = noclick.Project.current()
                db = app.database("DB")
                rows = db.query("select id, starts_at from bookings where day = ?", ["2026-10-02"])
                app.email.send(to="ana@example.com", subject="Your booking", text="See you Friday at 3pm.")

            Make what it needs as it goes, which is the app's own from then on::

                noclick.Project.current()
                helper = noclick.Agent.from_name("helper", instructions="Answer in French.", tools=["search"],
                                                 create_if_missing=True)
                print(helper.message("Bonjour !", conversation="visitor-91c2").text)
        """
        return cls._new(hints={"current": True}, client=client if client is not None else app_client(), user=None)

    @classmethod
    def from_id(cls, project_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Project":
        """A lazy reference to a project by id.

        Returns:
            A project that loads the first time you read a field. Nothing is sent yet.

        Usage::

            app = noclick.Project.from_id("2b7e9c4a-6f1d-4a3b-8e5c-0d9f7a1b3c52")
            op = app.deploy()
        """
        return cls._new(hints={"id": project_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, project_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Project":
        """Load a project by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The project, loaded, with its ``production`` deployment.

        Usage::

            app = noclick.Project.get("2b7e9c4a-6f1d-4a3b-8e5c-0d9f7a1b3c52")
            print(app.name, app.url, app.framework)
        """
        project = cls.from_id(project_id, client=client, user=user)
        await project._ensure()
        return project

    @synced
    @classmethod
    async def list(
        cls, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Project"]:
        """The current user's projects (the account's own outside ``as_user``, or those ``user_filter`` covers).

        Returns:
            Every matching project, newest first, fetched page by page, each with its ``production`` deployment.

        Usage::

            for app in noclick.Project.list(user_filter=noclick.ALL_USERS):
                live = app.production
                print(app.name, app.url, live.status if live else "not deployed")
        """
        return await list_all(
            "/v1/projects", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of projects; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the projects and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Project.list_page(limit=50)
            while True:
                for app in page.data:
                    print(app.name, app.url)
                if page.next_cursor is None:
                    break
                page = noclick.Project.list_page(limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/projects", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def analytics_summary(
        cls, *, period: str = "7d", tz: Optional[str] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> AnalyticsSummary:
        """Every app's requests over the last ``period`` (``24h``, ``7d`` or ``30d``) and how many failed, in one
        read however many apps there are: each production site's, over the same window ``analytics`` reads, its days
        starting in ``tz`` (UTC when omitted). Which apps: the current user's, or those ``user_filter`` covers, as
        ``list``. Requests, not visitors.

        Returns:
            Its ``AnalyticsSummary``: one line per app, newest first.

        Usage:
            Each app's week, busiest first::

                week = noclick.Project.analytics_summary(tz="Europe/Paris")
                for line in sorted(week.apps, key=lambda a: a.requests, reverse=True):
                    print(line.project_id, line.requests, line.errors)
        """
        scope, user_id = await read_scope(user, user_filter)
        raw = await resolve_client(client).request(
            "GET", "/v1/projects/analytics/summary", params={"period": period, "tz": tz, "user_id": user_id}, user=scope)
        return AnalyticsSummary._from(raw)

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        project_id = self._known("id")
        if project_id:
            return await self._request("GET", f"/v1/projects/{project_id}")
        if self._hints.get("current"):
            return await self._request("GET", "/v1/projects/current")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/projects", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        if rows:
            return await self._converge(rows[0])
        if not self._creates:
            raise NotFound(
                f"No project is named {name!r}.",
                next_step="Create it with noclick.Project.create(...) or pass create_if_missing=True.",
                details={"name": name},
            )
        try:
            return await self._request("POST", "/v1/projects", json=await self._wire(self._create_with))
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._converge(await self._request("GET", f"/v1/projects/{exc.existing_id}"))

    async def _converge(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Set the fields ``from_name`` was given on an existing project."""
        if self._create_with is None:
            return raw
        wanted = await self._wire({k: v for k, v in self._create_with.items() if k in _CONVERGED})
        changes = {k: v for k, v in wanted.items() if raw.get(k) != v}
        if not changes:
            return raw
        return await self._request("PATCH", f"/v1/projects/{raw['id']}", json=changes)

    async def _project_path(self) -> str:
        return f"/v1/projects/{await ref_id(self)}"

    @synced
    async def update(
        self,
        *,
        repo: Any = UNSET,
        runtime: Any = UNSET,
        framework: Any = UNSET,
        production_branch: Any = UNSET,
        budget_usd_per_month: Any = UNSET,
        deploy_on_push: Any = UNSET,
        preview_resources: Any = UNSET,
        check_paths: Any = UNSET,
        live_editing: Any = UNSET,
        badge_corner: Any = UNSET,
        preview_access: Any = UNSET,
        preview_public_paths: Any = UNSET,
        container: Any = UNSET,
    ) -> "Project":
        """Change the ``repo`` it deploys (a ``noclick.Repo`` or its id), its ``runtime``
        (``auto``, ``edge`` or ``container``), its ``framework``, its ``production_branch``, its
        ``budget_usd_per_month``, what a push deploys (``deploy_on_push``: ``off``,
        ``production`` or ``all``), what deploys, promotes and checks ask (``check_paths``, up
        to 10: a page's path, loaded in a browser, or what a plain request for a path must
        answer, ``{"path": "/api/health", "status": 200}`` or ``{"path": ..., "json": True}``;
        ``[]`` stops checking promotes), whether previews get their own
        resources (``preview_resources``: ``branch`` or ``shared``), whether it's edited live
        (``live_editing``, see ``app.live``), the corner its badge sits in (``badge_corner``:
        ``bottom-right``, ``bottom-left``, ``top-right`` or ``top-left``, away from a chat's composer
        or a corner button, say), or who opens its previews (``preview_access``: ``public`` or
        ``link``, the paths a private preview leaves open in ``preview_public_paths``; production
        is always public; while NoClick's front door doesn't keep previews private yet the answer's
        ``raw["notes"]`` say so), or how each of its instances runs in a container (``container``:
        a mapping of ``cpu``, ``memory``, ``min_instances``, ``max_instances``, ``cpu_always`` and
        ``request_timeout_s``, where a setting left out keeps its value, or another app's
        ``container``; ``container=None`` sets every one back to its default; ``ProjectContainer``
        says each one's bounds). A new repo, runtime, framework, branch or container settings apply
        from the next release (a deploy, or for container settings a promote of what production
        serves; the answer's ``raw["notes"]`` say so), and what's live keeps serving as it runs until
        then; the rest apply at once. A container setting out of bounds raises
        ``noclick.InvalidRequest`` naming it (``container.memory``), and so do warm instances whose
        cost alone passes the app's budget (``container.min_instances``, with their
        ``idle_usd_per_month``). An app with code always has a budget: ``budget_usd_per_month=None``
        raises ``noclick.InvalidRequest`` (only an app NoClick publishes may have none). Its user's
        cap still applies either way. Pinning a runtime the app's framework doesn't run on raises
        ``noclick.InvalidRequest``: change the framework with it.

        Returns:
            This app, updated. A field you leave out is unchanged.

        Usage:
            Give an app a budget of its own, so it can't spend all of its user's cap::

                app = noclick.Project.from_name("booking", user="user_42")
                app.update(budget_usd_per_month=25)

            Lift it for the rest of the month after a busy launch::

                app = noclick.Project.from_name("booking", user="user_42")
                if app.usage().limited_by == "project":
                    app.update(budget_usd_per_month=50)

            Deploy every push to the production branch from now on::

                app = noclick.Project.from_name("booking")
                app.update(deploy_on_push="production")

            Promote only releases whose home and booking pages load cleanly, and whose API answers::

                app = noclick.Project.from_name("booking")
                app.update(check_paths=["/", "/book", {"path": "/api/bookings", "status": 200, "json": True}])

            Give an app made before branched previews its own copies per branch, so a preview's
            writes never reach production's data::

                app = noclick.Project.from_name("booking")
                app.update(preview_resources="branch")

            Edit a Vite site live, each change showing in the page its owner has open: it takes an app of
            your account's own whose previews get their own data (``noclick.Conflict`` says what else to change)::

                app = noclick.Project.from_name("larkspur")
                app.update(live_editing=True)
                print(app.live_editing, app.live.start().enter_url)

            Let an app made before ``auto`` run each commit where it says (its next deploy of a
            Dockerfile runs in a container)::

                app = noclick.Project.from_name("booking")
                app.update(runtime="auto", framework=None)
                deployment = app.deploy().wait()
                print(deployment.runtime, deployment.runtime_reason)

            Keep the badge clear of a chat's composer in the bottom-right corner::

                app = noclick.Project.from_name("inbox")
                app.update(badge_corner="top-right")

            Make an app's previews private, its Stripe webhook still reaching them, and hand its owner the link::

                app = noclick.Project.from_name("booking")
                app.update(preview_access="link", preview_public_paths=["/api/webhooks/*"])
                print(app.preview_link(branch="new-form").url)

            Give an app that loads a model at start more room, then deploy to run at it::

                app = noclick.Project.from_name("transcriber")
                app.update(container={"cpu": 2, "memory": 4096})
                app.deploy().wait()

            Keep a bot connected with nothing calling it, seeing what that costs before it's live::

                bot = noclick.Project.from_name("standup-bot")
                bot.update(container={"cpu_always": True, "min_instances": 1})
                print(bot.container.idle_usd_per_month, bot.raw["notes"])

            Put every setting back to its default::

                noclick.Project.from_name("standup-bot").update(container=None)
        """
        changes = {
            k: v for k, v in dict(
                runtime=runtime, framework=framework, production_branch=production_branch,
                budget_usd_per_month=budget_usd_per_month, deploy_on_push=deploy_on_push,
                preview_resources=preview_resources, live_editing=live_editing, badge_corner=badge_corner,
                preview_access=preview_access,
                preview_public_paths=list(preview_public_paths) if preview_public_paths not in (UNSET, None)
                else preview_public_paths,
                check_paths=_check_paths(check_paths) if check_paths not in (UNSET, None) else check_paths,
                container=container if container is UNSET else _container(container),
            ).items()
            if v is not UNSET
        }
        if repo is not UNSET:
            changes["repo_id"] = await ref_id(repo)
        self._raw = await self._request("PATCH", await self._project_path(), json=changes)
        return self

    # --- deploying -------------------------------------------------------

    @synced
    async def deploy(self, *, branch: Optional[str] = None, commit: Optional[str] = None) -> Operation:
        """Build and deploy ``branch`` (the production branch when omitted) at
        its head, or at ``commit``. A deploy of the production branch goes live
        at ``url`` once it's ready; any other branch is a preview with a URL of
        its own. Every release is asked for its home page (its scripts and
        stylesheets too) and the app's ``check_paths`` as soon as its URL
        serves it: one that answers wrong stays live, the deployment's
        ``warning`` says what answered and its ``next_step`` what to fix.
        When its static files answer every path asked, its code is asked at a
        path no file answers too; ``code_unchecked`` says when nothing asked
        could reach its code. A preview of an app whose
        ``preview_resources`` is ``branch`` says what it writes to in
        ``preview_data``.

        Returns:
            An operation whose ``.wait()`` gives the ``Deployment``, ``ready``, with its ``warning``,
            ``next_step``, ``code_unchecked`` and ``preview_data``. A failed build raises ``noclick.OperationFailed``, whose
            ``deployment_id`` names the deployment to read the build log of.

        Usage:
            Deploy production and wait for it::

                app = noclick.Project.from_name("booking")
                deployment = app.deploy().wait()
                print(deployment.url, deployment.commit)
                if deployment.warning:
                    print(deployment.warning, deployment.next_step)   # live, but not working

            Deploy a branch as a preview, and read the build log when it fails::

                app = noclick.Project.from_name("booking")
                try:
                    preview = app.deploy(branch="new-form").wait()
                    print(preview.url)   # https://new-form--booking.noclick.site
                except noclick.OperationFailed as failed:
                    for line in noclick.Deployment.from_id(failed.deployment_id).logs(kind="build"):
                        print(line.message)
        """
        payload = await self._request(
            "POST", f"{await self._project_path()}/deployments", json=compact(branch=branch, commit=commit),
        )
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="project.deploy", reader=_read_deployment,
        )

    @synced
    async def deployments(self, *, branch: Optional[str] = None, limit: Optional[int] = 20) -> List[Deployment]:
        """Its deployments, newest first, of every branch or of ``branch``.

        Returns:
            Up to ``limit`` deployments (20 by default; ``None`` for all), fetched page by page.

        Usage::

            app = noclick.Project.from_name("booking")
            for deployment in app.deployments(limit=10):
                print(deployment.branch, deployment.status, deployment.production, deployment.url)
        """
        rows = await paginate(
            self._api, f"{await self._project_path()}/deployments", params={"branch": branch},
            user=self._call_scope(), limit=limit,
        )
        return [Deployment._new(raw=row, client=self._client, user=self._call_scope()) for row in rows]

    @synced
    async def preview_link(self, *, branch: Optional[str] = None, expires_in: Optional[int] = None) -> PreviewLink:
        """Make a link that opens a preview of the app (``branch``'s, else the newest serving) to whoever holds it,
        for ``expires_in`` seconds (7 days unless given; 5 minutes to 30 days). It's what to hand people when the
        app's ``preview_access`` is ``link``. It lasts until it expires, or until ``revoke_preview_links()`` stops
        every link made before.

        Returns:
            The ``PreviewLink``. No preview serving (or one of the production branch, always public) raises
            ``noclick.NotFound`` (``noclick.InvalidRequest``), saying what to deploy.

        Usage::

            app = noclick.Project.from_name("booking")
            link = app.preview_link(branch="new-form", expires_in=24 * 3600)
            print(link.url, link.expires_at)
        """
        payload = await self._request(
            "POST", f"{await self._project_path()}/previews/link",
            json=compact(branch=branch, expires_in=expires_in),
        )
        return PreviewLink._from(payload)

    @synced
    async def revoke_preview_links(self) -> "Project":
        """Stop every link to the app's previews made before now, and the cookie each left in a browser: within 30
        seconds none of them opens a preview, while links made after (``preview_link()``, a preview's deploy) open
        them as before. For a link that reached someone who shouldn't have it. On an app whose previews are public
        their URLs still open them, which ``raw["notes"]`` says.

        Returns:
            This app, as it is then.

        Usage::

            app = noclick.Project.from_name("booking")
            app.revoke_preview_links()
            print(app.preview_link(branch="new-form").url)   # a fresh link for the people who should keep it
        """
        self._raw = await self._request("POST", f"{await self._project_path()}/previews/links/revoke")
        return self

    @synced
    async def rollback(self, *, to: Union[Deployment, str]) -> Operation:
        """Serve an earlier deployment (a ``Deployment`` or its id, still
        ``ready``) at ``url`` again, without rebuilding: released again with
        production's settings and secrets as they are now, then live within a
        minute. The same as ``to.promote()``. It covers the app's last 10
        production deployments; an older one is built again from its commit.

        Returns:
            An operation whose ``.wait()`` gives that deployment (or, past the window, the one built
            from its commit), now ``production``.

        Usage:
            Go back to the production deployment before the current one::

                app = noclick.Project.from_name("booking")
                previous = [d for d in app.deployments(branch=app.production_branch) if d.status == "ready" and not d.production][0]
                app.rollback(to=previous).wait()
        """
        deployment = to if isinstance(to, Deployment) else Deployment.from_id(
            to, client=self._client, user=self._call_scope(),
        )
        return await deployment.promote.aio()

    # --- what the app reads ----------------------------------------------

    @synced
    async def bind(self, name: str, resource: Any, *, kind: Optional[str] = None) -> Binding:
        """Give the app ``resource`` under ``name``: a ``noclick.Database``,
        ``Bucket``, ``Connection``, ``Dict``, ``Queue``, ``Secret`` or ``Agent``, or its id
        with ``kind`` (``database``, ``bucket``, ``connection``, ``dict``, ``queue``,
        ``secret`` or ``agent``). The running app reads it
        from its environment by that name. Binding a name again replaces what it
        pointed at; it takes effect at the next deployment. An agent is the app's
        user's own or one of your account's, and the app talks to it as itself (see
        ``agent``).

        A ``Secret`` reaches the app as one variable per key, each under the key's own
        name, and ``name`` only lists it. The app's environment holds a name once, so
        a key that another bound secret holds, or that another binding, the app's own
        ``secrets`` or ``settings`` or NoClick sets, raises ``noclick.Conflict``; a secret
        that gains such a key after it's bound fails the next deployment the same way.

        Returns:
            The binding, naming the resource.

        Usage:
            Give the app its database, its files and the owner's CRM::

                app = noclick.Project.from_name("booking")
                app.bind("DB", noclick.Database.from_name("booking-db", create_if_missing=True))
                app.bind("FILES", noclick.Bucket.from_name("uploads", create_if_missing=True))
                app.bind("CRM", noclick.Connection.from_name("hubspot"))
                app.deploy()

            Give it an agent to answer its visitors::

                app = noclick.Project.from_name("booking")
                app.bind("SUPPORT", noclick.Agent.from_name("support"))
                app.deploy()

            With an id, say what it is::

                app = noclick.Project.from_name("booking")
                app.bind("DB", "5c2e8a1f-3b7d-4e9a-a6c4-8d1f0e2b3a79", kind="database")
        """
        if isinstance(resource, str):
            if kind not in _BINDABLE.values():
                raise TypeError(f"With a resource id, pass kind= (one of {', '.join(sorted(_BINDABLE.values()))}).")
        else:
            kind = _BINDABLE.get(type(resource).__name__)
            if kind is None:
                raise TypeError(
                    f"Bind a Database, Bucket, Connection, Dict, Queue, Secret or Agent, not {type(resource).__name__}"
                )
        body = {"name": name, "kind": kind, "id": await ref_id(resource)}
        return Binding._from(await self._request("POST", f"{await self._project_path()}/bindings", json=body))

    @synced
    async def bindings(self) -> List[Binding]:
        """What the app is given, by name.

        Returns:
            Each binding with the resource it names.

        Usage::

            app = noclick.Project.from_name("booking")
            for binding in app.bindings():
                print(binding.name, binding.kind, binding.resource_name)   # DB database booking-db
        """
        rows = await paginate(self._api, f"{await self._project_path()}/bindings", user=self._call_scope())
        return [Binding._from(row) for row in rows]

    @synced
    async def unbind(self, name: str) -> None:
        """Take ``name`` away from the app at the next deployment. The resource itself is kept.

        Usage::

            app = noclick.Project.from_name("booking")
            app.unbind("CRM")
        """
        await self._request("DELETE", f"{await self._project_path()}/bindings/{name}")

    async def _bound(self, name: str, kind: str) -> Binding:
        binding = Binding._from(await self._request("GET", f"{await self._project_path()}/bindings/{name}"))
        if binding.kind != kind:
            raise InvalidRequest(
                f"{name} is bound to {_a(binding.kind)}, not {_a(kind)}.",
                next_step=f"Read it with app.{binding.kind}({name!r}).",
                details={"name": name, "kind": binding.kind},
            )
        return binding

    @synced
    async def database(self, name: str) -> "Database":
        """The database bound to the app as ``name``, from the app's own code
        (``Project.current()``) or yours.

        Returns:
            The ``noclick.Database``; a name bound to something else raises ``noclick.InvalidRequest``,
            an unbound one ``noclick.NotFound``.

        Usage::

            app = noclick.Project.current()
            bookings = app.database("DB").query("select count(*) as n from bookings")
            print(bookings.rows[0]["n"])
        """
        from .database import Database

        binding = await self._bound(name, "database")
        return Database.from_id(binding.resource_id, client=self._client, user=self._call_scope())

    @synced
    async def bucket(self, name: str) -> "Bucket":
        """The bucket bound to the app as ``name``.

        Returns:
            The ``noclick.Bucket``.

        Usage::

            app = noclick.Project.current()
            files = app.bucket("FILES")
            files.put("invoices/1042.pdf", b"%PDF-...")
        """
        from .bucket import Bucket

        binding = await self._bound(name, "bucket")
        return Bucket.from_id(binding.resource_id, client=self._client, user=self._call_scope())

    @synced
    async def dict(self, name: str) -> "Dict":
        """The dict bound to the app as ``name``.

        Returns:
            The ``noclick.Dict``.

        Usage::

            app = noclick.Project.current()
            sessions = app.dict("SESSIONS")
            sessions.put("sess_91c2", {"user": "ana"}, ttl_s=3600)
        """
        from .dicts import Dict as NoClickDict

        binding = await self._bound(name, "dict")
        return NoClickDict.from_id(binding.resource_id, client=self._client, user=self._call_scope())

    @synced
    async def queue(self, name: str) -> "Queue":
        """The queue bound to the app as ``name``.

        Returns:
            The ``noclick.Queue``.

        Usage::

            app = noclick.Project.current()
            app.queue("JOBS").put({"booking": 1042, "send": "reminder"})
        """
        from .queues import Queue

        binding = await self._bound(name, "queue")
        return Queue.from_id(binding.resource_id, client=self._client, user=self._call_scope())

    @synced
    async def connection(self, name: str) -> "Connection":
        """The connection bound to the app as ``name``: the app runs its operations as the
        account that connected it.

        Returns:
            The ``noclick.Connection``.

        Usage::

            app = noclick.Project.current()
            crm = app.connection("CRM")
            crm.run("create_contact", {"email": "ana@example.com"})
        """
        from .connection import Connection

        binding = await self._bound(name, "connection")
        return Connection.from_id(binding.resource_id, client=self._client, user=self._call_scope())

    @synced
    async def agent(self, name: str) -> "Agent":
        """The agent bound to the app as ``name``. From the app's own code it acts as the app:
        ``message``, ``send`` and ``ask`` start turns in the app's own conversations, and
        ``history`` and ``conversations`` read only those. A key the app passes (its visitor's
        id, say) always names a thread of the app's: ``visitor-91c2`` from the app is
        ``app:<app id>:visitor-91c2`` to your own code, which reads those threads, and no other
        app reaches them. The agent's policy still judges its tool calls, and its turns are
        billed like any turn, attributed to the app: to the agent's budget, the app's and its
        user's cap. Anything else (``update``, ``delete``, its triggers, memory, wake-ups or
        children) raises ``noclick.PermissionDenied`` from the app, unless its code made the
        agent. A preview's code talks to it in threads of the preview's own
        (``app-preview:<app id>:<key>``), its tools answering from a simulated world; no app's
        code talks to an agent that holds the ``noclick`` tool.

        Returns:
            The ``noclick.Agent``.

        Usage:
            Answer a visitor in a thread of their own, and degrade once the money runs out::

                app = noclick.Project.current()
                support = app.agent("SUPPORT")
                try:
                    reply = support.message("Can I move my booking to Saturday?", conversation="visitor-91c2")
                    print(reply.text)
                except (noclick.SpendCapExceeded, noclick.PaymentRequired):
                    print("Chat is resting for now. Email help@acmebooking.com and we'll answer today.")
        """
        from .agent import Agent

        binding = await self._bound(name, "agent")
        return Agent.from_id(binding.resource_id, client=self._client, user=self._call_scope())

    def verify_request(
        self, body: Union[bytes, str], headers: Mapping[str, Any], *, tolerance_s: int = 300,
    ) -> None:
        """Check that a request to the app came from NoClick (one of its schedules or
        subscriptions): ``body`` is the raw body exactly as it arrived, ``headers`` its
        headers. Every request NoClick makes to the app carries a
        ``NoClick-Signature`` header (``t=<unix seconds>,v1=<hex>``, HMAC-SHA256 of
        ``"<t>.<body>"``) keyed with the app's signing secret, which NoClick sets in the
        deployment's environment as ``NOCLICK_SIGNING_SECRET``. It sends nothing.

        Raises ``noclick.WebhookSignatureError`` when the header is missing or malformed, the
        timestamp is more than ``tolerance_s`` from now, or the signature doesn't match; answer
        such a request 401.

        Usage:
            In a Flask route a schedule calls, in an app on the ``container`` runtime::

                from flask import Flask, request

                server = Flask(__name__)

                @server.post("/jobs/reminders")
                def reminders():
                    app = noclick.Project.current()
                    try:
                        app.verify_request(request.get_data(), request.headers)
                    except noclick.WebhookSignatureError:
                        return "", 401
                    return "", 204
        """
        secret = os.environ.get(SIGNING_SECRET_ENV)
        if not secret:
            raise Unauthenticated(
                f"verify_request() runs inside a deployed app, where NoClick sets {SIGNING_SECRET_ENV}.",
                next_step="Call it from the app's own code, in a deployment.",
            )
        verify_signature(body, headers, secret, tolerance_s=tolerance_s)

    # --- schedules -------------------------------------------------------

    @synced
    async def schedule(self, cron: Cron, *, path: str, name: Optional[str] = None) -> Schedule:
        """POST ``path`` on the app on every tick of ``cron`` (a
        ``noclick.Cron``). A schedule is keyed by ``name`` (the path when
        omitted), so calling this again with the same one updates it rather
        than adding another. Each request carries a signed ``NoClick-Signature``
        header, so the app can refuse anyone else.

        Returns:
            The schedule, ``active``, with its ``next_run``.

        Usage:
            Send reminders at 9am New York time on weekdays::

                app = noclick.Project.from_name("booking")
                reminders = app.schedule(noclick.Cron("0 9 * * 1-5", tz="America/New_York"), path="/jobs/reminders")
                print(reminders.next_run)

            Two schedules on one path need names::

                app = noclick.Project.from_name("booking")
                app.schedule(noclick.Cron("0 * * * *"), path="/jobs/sync", name="hourly-sync")
                app.schedule(noclick.Cron("0 3 * * 0"), path="/jobs/sync", name="weekly-full-sync")
        """
        if not isinstance(cron, Cron):
            raise TypeError(f"Pass a noclick.Cron, not {type(cron).__name__}")
        # An app's schedule calls a path, so a Cron's ``message`` (an agent's turn) isn't sent.
        body = {"cron": cron.expr, "tz": cron.tz, **compact(path=path, name=name)}
        raw = await self._request("POST", f"{await self._project_path()}/schedules", json=body)
        return Schedule._new(raw=raw, client=self._client, user=self._call_scope())

    @synced
    async def schedules(self) -> List[Schedule]:
        """Its schedules.

        Returns:
            Each schedule with its ``status``, ``next_run`` and how its ``last_run`` went.

        Usage::

            app = noclick.Project.from_name("booking")
            for schedule in app.schedules():
                print(schedule.cron, schedule.tz, schedule.path, schedule.status, schedule.last_status)
        """
        rows = await paginate(self._api, f"{await self._project_path()}/schedules", user=self._call_scope())
        return [Schedule._new(raw=row, client=self._client, user=self._call_scope()) for row in rows]

    @synced
    async def durable_objects(self) -> DurableObjectClasses:
        """Its Durable Object classes in every environment, production's first.

        Returns:
            Each class with how many objects it has and what they store; ``unread`` names a figure the host
            couldn't report.

        Usage::

            app = noclick.Project.from_name("chat")
            for room in app.durable_objects():
                print(room.name, room.environment, room.objects_count, room.stored_bytes, room.status)
        """
        found = await self._request("GET", f"{await self._project_path()}/durable_objects")
        out = DurableObjectClasses(
            DurableObjectClass._new(raw=row, client=self._client, user=self._call_scope())
            for row in (found or {}).get("data") or [])
        out.unread = list((found or {}).get("unread") or [])
        out.cost = (found or {}).get("cost")
        return out

    # --- subscriptions ---------------------------------------------------

    @synced
    async def subscribe(self, source: Any, *, path: str) -> "Subscription":
        """POST each of a connection's app events to ``path`` on the app, signed as its
        schedules' calls are, so the app runs its own pipeline with no agent in between.
        ``source`` is a ``noclick.OnEvent`` (a connection of the app's own scope, one of its
        integration's events, its filters). The body is JSON: ``{object: "app_event", id,
        subscription_id, connection, integration, event, text, thread, data, test,
        created_at}``, where ``data`` is the event as the integration sent it, ``text`` the
        same in words and ``thread`` the conversation it belongs to (a WhatsApp chat, a Slack
        thread). Check it with ``verify_request``, answer 2xx within 10 seconds (do slow work
        after answering), and key on ``id``: an event the app didn't take is sent again, the
        same body, for three days. Up to 20 an app; one whose connection isn't connected yet
        is ``error`` until it is.

        Returns:
            The subscription, with its ``path``.

        Usage:
            Every WhatsApp message to the app's own route, from its own code::

                whatsapp = noclick.Connection.from_name("whatsapp", integration="whatsapp")
                app = noclick.Project.current()
                app.subscribe(noclick.OnEvent(whatsapp, "receive_message"), path="/hooks/whatsapp")
        """
        from .channel import Subscription
        from .trigger import OnEvent

        if not isinstance(source, OnEvent):
            raise TypeError(f"An app subscribes to a connection's app events: pass a noclick.OnEvent, not {source!r}")
        if source.message is not None or source.conversation is not None:
            raise ValueError("An app's subscription takes no message= or conversation=: the app gets the event itself, "
                             "with its thread.")
        body = {"source": await source._wire_async(), "path": path}
        raw = await self._request("POST", f"{await self._project_path()}/subscriptions", json=body)
        return Subscription._new(raw=raw, client=self._client, user=self._call_scope())

    @synced
    async def subscriptions(self) -> List["Subscription"]:
        """Its subscriptions, oldest first.

        Returns:
            Each ``noclick.Subscription`` with its ``source``, ``path`` and ``status``.

        Usage::

            app = noclick.Project.from_name("booking")
            for subscription in app.subscriptions():
                print(subscription.source["event"], subscription.path, subscription.status)
        """
        from .channel import Subscription

        response = await self._request("GET", f"{await self._project_path()}/subscriptions") or {}
        return [Subscription._new(raw=row, client=self._client, user=self._call_scope())
                for row in response.get("data") or []]

    # --- domains ---------------------------------------------------------

    @synced
    async def add_domain(self, name: str) -> "Domain":
        """Serve the app at the domain ``name`` too. A domain you bought through
        NoClick is pointed at it at once, at its name and ``www``; one owned elsewhere
        is connected and waits in ``pending_dns`` until its records are set (``records``
        lists them). Each name is live once its certificate is issued.

        A subdomain of a domain your account holds (``ana.acmebooking.com`` under the account's
        ``acmebooking.com``) can serve any project, a user's included, so each user's app gets an
        address of yours; only a key acting for the whole account (not a user session or a key
        pinned to a user) may hand one out. Under a bought domain the record is written for you;
        under a connected one connected with ``wildcard=True`` it needs no record of its own and
        is live within minutes, and otherwise ``records`` lists the one to add.

        Returns:
            The ``noclick.Domain``, with its ``status``.

        Usage:
            Serve the app at a domain you own::

                app = noclick.Project.from_name("booking")
                domain = app.add_domain("book.acme.com")
                print(domain.status)   # pending_dns until the records are set
                for record in domain.records:
                    print(record.type, record.name, record.value)

            Give a user's app a subdomain of your account's domain::

                ana_app = noclick.Project.from_name("store", user="user_42")
                domain = ana_app.add_domain("ana.acmebooking.com")
                print(domain.status)   # active: the account bought acmebooking.com through NoClick
        """
        from .domain import Domain

        raw = await self._request("POST", f"{await self._project_path()}/domains", json={"name": name})
        return Domain._new(raw=raw, client=self._client, user=self._call_scope())

    @synced
    async def domains(self) -> List["Domain"]:
        """The domains that serve the app.

        Returns:
            Each ``noclick.Domain`` with its ``status``.

        Usage::

            app = noclick.Project.from_name("booking")
            for domain in app.domains():
                print(domain.name, domain.status)
        """
        from .domain import Domain

        rows = await paginate(self._api, f"{await self._project_path()}/domains", user=self._call_scope())
        return [Domain._new(raw=row, client=self._client, user=self._call_scope()) for row in rows]

    @synced
    async def remove_domain(self, name: str) -> None:
        """Stop serving the app at ``name`` (a bare domain's ``www`` too). The domain itself is
        kept: a bought one stays yours, and one connected for the app stays connected until you
        delete it. A name that doesn't serve the app raises ``noclick.NotFound``.

        Usage::

            app = noclick.Project.from_name("booking")
            app.remove_domain("book.acme.com")
        """
        await self._request("DELETE", f"{await self._project_path()}/domains/{name}")

    # --- watching --------------------------------------------------------

    @synced
    async def logs(
        self,
        *,
        since: Union[None, str, datetime] = None,
        level: Optional[str] = None,
        deployment: Union[None, Deployment, str] = None,
        limit: int = 100,
        environment: str = "all",
    ) -> LogLines:
        """What the app printed while serving, oldest first: the last ``limit``
        lines (at most 1,000), or with ``since`` (a timezone-aware
        ``datetime``) the first ``limit`` after it. ``level`` keeps ``warn`` or
        ``error`` lines only; ``deployment`` one deployment's; ``environment``
        (``production`` or ``preview``) one environment's. A request's lines are
        never cut apart. Lines are kept 7 days, and take up to a minute to show
        after a request writes them.

        Returns:
            The lines, with ``delay_s``: how long a line can take to show, so an empty read may only be early.
            Pass the last one's ``at`` as ``since`` to read on from there.

        Usage:
            The errors of the last hour::

                from datetime import datetime, timedelta, timezone

                app = noclick.Project.from_name("booking")
                an_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
                for line in app.logs(since=an_hour_ago, level="error"):
                    print(line.at, line.message)

            Follow the log, a page at a time::

                app = noclick.Project.from_name("booking")
                lines = app.logs(limit=50)
                while lines:
                    for line in lines:
                        print(line.message)
                    lines = app.logs(since=lines[-1].at, limit=50)
        """
        params = {
            "since": iso_time(since), "level": level, "limit": limit,
            "deployment_id": await ref_id(deployment) if deployment is not None else None,
            "environment": environment if environment != "all" else None,
        }
        return LogLines._from(await self._request("GET", f"{await self._project_path()}/logs", params=params))

    @synced
    async def analytics(self, *, period: str = "7d", environment: str = "production",
                        tz: Optional[str] = None) -> ProjectAnalytics:
        """How the app's traffic went over the last ``period`` (``24h``, ``7d`` or ``30d``): its requests each hour
        (``24h``) or day, starting in ``tz`` (an IANA time zone; UTC when omitted), how many failed, the totals
        against the same length of time before, by status, how long answers took to begin and the busiest paths.
        ``environment``: its production site (``production``), its previews (``preview``) or both (``all``).

        It counts every request the app's sites answered, its static files and API calls included, people's and
        bots' alike: requests, not visitors.

        Returns:
            Its ``ProjectAnalytics``, read from NoClick's record of each request.

        Usage:
            How the site is doing this week, against last week::

                app = noclick.Project.from_name("booking")
                week = app.analytics(tz="Europe/Paris")
                print(week.requests, week.previous_requests, week.error_rate, week.p95_ms)
                for day in week.series:
                    print(day.at.date(), day.requests, day.errors)
                for page in week.top_paths:
                    print(page.path, page.requests)

            The last 24 hours, hour by hour::

                for hour in app.analytics(period="24h").series:
                    print(hour.at, hour.requests)
        """
        params = {"period": period, "environment": environment, "tz": tz}
        return ProjectAnalytics._from(await self._request("GET", f"{await self._project_path()}/analytics",
                                                          params=params))

    @synced
    async def usage(self) -> ProjectUsage:
        """What the app has spent this month, against its budget: everything it cost in
        ``usd`` (hosting and builds, its calls to what it's bound to, its email, its AI and its
        agent turns), split ``by_type``, and ``limited_by``, what refuses its paid calls now.

        Returns:
            Requests served, compute in ``cpu_ms``, ``usd`` and its ``budget_usd``, what refuses its paid
            calls (``limited_by``), and the ``period_start`` it counts from.

        Usage:
            Show the app's spend against its budget::

                app = noclick.Project.from_name("booking")
                used = app.usage()
                print(used.requests, used.cpu_ms, f"${used.usd:.2f}")
                if used.budget_usd is not None:
                    print(f"${used.usd:.2f} of ${used.budget_usd:.2f}", used.by_type)

            Find out why its paid calls fail::

                app = noclick.Project.from_name("booking")
                if app.usage().limited_by == "user":
                    print("Its user reached their monthly cap.")
        """
        raw = await self._request("GET", f"{await self._project_path()}/usage") or {}
        return ProjectUsage(
            int(required_number(raw, "requests")), int(required_number(raw, "cpu_ms")),
            float(required_number(raw, "usd")), parse_time(raw.get("period_start")), raw.get("budget_usd"),
            raw.get("limited_by"), {k: float(v) for k, v in (raw.get("by_type") or {}).items()}, raw,
        )

    # --- leaving ---------------------------------------------------------

    @synced
    async def export(self) -> Operation:
        """Package everything the app is, to run it elsewhere: its code as a
        git bundle, ``apps/<name>.json`` with its settings, bindings and secret
        names (never values), and each database, bucket, dict and queue it binds,
        each in its own export's format. To put the code on GitHub, use the
        repo's ``export_to_github``.

        Returns:
            An operation whose ``.wait()`` gives an ``noclick.ExportBundle``.

        Usage::

            app = noclick.Project.from_name("booking")
            bundle = app.export().wait()
            print(bundle.url)
            for item in bundle.contents:
                print(item.kind, item.name, item.detail)
        """
        payload = await self._request("POST", f"{await self._project_path()}/export", json={})
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="project.export", reader=_read_export,
        )

    @synced
    async def delete(self, *, delete_data: bool = False) -> TrashItem:
        """Delete the app: it goes offline within seconds and to the trash,
        restorable for 30 days with everything it had (its releases,
        settings, secrets, bindings, schedules and domains), served again
        with no build. Its name is free meanwhile. The repo and every bound
        database and bucket are kept, unless ``delete_data=True`` moves the
        repo to the trash too, with each database and bucket no other app
        binds.

        Returns:
            Its ``TrashItem``: ``restore()`` serves it again where it was.

        Usage:
            Delete the app and keep its data::

                app = noclick.Project.from_name("status-page", user="acme")
                item = app.delete()

            Or delete what only it used as well, then change your mind::

                item = noclick.Project.from_name("scratch").delete(delete_data=True)
                item.restore()
        """
        raw = await self._request(
            "DELETE", await self._project_path(), params={"delete_data": "true" if delete_data else None},
        )
        return trashed(raw, client=self._client, user=self._call_scope())

    @synced
    async def unpublish(self) -> TrashItem:
        """Take down an app NoClick publishes (``published``), to the trash: its page's key stops working and every
        address it answers at stops at once. For 30 days no other app takes its address, and ``restore()`` (or
        publishing its automation's interface again) serves it where it was with the same key; then, or when the
        item is purged, it's deleted for good. Only the account's own key or session can: a key acting for one of
        your users gets ``noclick.NotFound``.

        Returns:
            Its ``TrashItem``: ``restore()`` puts it back live.

        Usage:
            Take down the pages whose automation is gone::

                for app in noclick.Project.list():
                    if app.published and app.workflow is None:
                        app.unpublish()

            Or take one down, then change your mind::

                item = noclick.Project.from_name("bakery").unpublish()
                item.restore()
        """
        raw = await self._request("POST", f"{await self._project_path()}/unpublish", json={})
        return trashed(raw, client=self._client, user=self._call_scope())
