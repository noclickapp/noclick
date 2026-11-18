"""Spend: ``noclick.usage(group_by="user")``, ``noclick.Usage.series(group_by="agent")``,
``noclick.Usage.limits()``."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from ._client import Client, resolve_client
from ._object import iso_time, parse_time, read_scope, ref_id, required_number as num
from ._sync import synced
from ._scope import AMBIENT


@dataclass(frozen=True)
class UsageGroup:
    """Spend of one user, key, agent or app (``id``) in the period."""

    id: Optional[str]
    usd: float
    events: int
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class UsagePoint:
    """Spend in one interval starting at ``t``."""

    t: Any
    usd: float
    events: int


@dataclass(frozen=True)
class UsageSeriesLine:
    """One key, user, agent or usage type's spend over the period. ``label`` is
    a key name (``Console`` for the console key), your id for a user, an
    agent name or a type label."""

    id: Optional[str]
    label: Optional[str]
    total_usd: float
    events: int
    points: List[UsagePoint]
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class UsageSeries:
    interval: str
    from_: Any
    to: Any
    total_usd: float
    series: List[UsageSeriesLine]
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class KeyCap:
    """A capped key's spend this month."""

    id: str
    name: Optional[str]
    cap: Optional[float]
    spent: float
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class UserCap:
    """A capped user's spend this month; ``id`` is your id for the user."""

    id: str
    cap: Optional[float]
    spent: float
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class AgentBudget:
    """A budgeted agent's spend this month; ``subtree_spent`` adds the agents it spawned."""

    id: str
    name: Optional[str]
    budget: Optional[float]
    spent: float
    subtree_spent: float
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class ProjectBudget:
    """A budgeted app's spend this month: ``id`` and ``name`` are the app's, ``user_id`` the
    user it belongs to (None for your account's own)."""

    id: str
    name: Optional[str]
    user_id: Optional[str]
    budget: Optional[float]
    spent: float
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class UsageLimits:
    """Every capped key, user and agent with this month's spend, and every app with a budget."""

    period_start: Any
    resets_at: Any
    keys: List[KeyCap]
    users: List[UserCap]
    agents: List[AgentBudget]
    #: Each app with a ``budget_usd_per_month``.
    projects: List[ProjectBudget]
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class Usage:
    """What the account (or the current user) spent in ``period``."""

    period: Any
    total_usd: float
    groups: List[UsageGroup]
    raw: Dict[str, Any] = dc_field(repr=False)

    def __getitem__(self, group_id: Optional[str]) -> UsageGroup:
        """The spend of one user, key, agent or app id in a grouped usage (``None`` is the account's own).

        Returns:
            That id's spend and event count; an id that spent nothing reads as ``$0`` with no events.

        Usage::

            user = noclick.User.from_id("user_42")
            month = noclick.usage(group_by="user")
            print(month[user.id].usd)   # 0.0 for a user who spent nothing
        """
        return self.get(group_id) or UsageGroup(group_id, 0.0, 0, {})

    def get(self, group_id: Optional[str], default: Any = None) -> Any:
        """The group of an id that spent something in a grouped usage, else ``default``.

        Returns:
            The ``UsageGroup``, or ``default`` when the id spent nothing in the period.

        Usage::

            support = noclick.Agent.from_name("support")
            month = noclick.usage(group_by="agent")
            if month.get(support.id) is None:
                print("support has cost nothing this month")
        """
        if not self.raw.get("group_by"):
            raise ValueError("This usage isn't grouped: read it with noclick.usage(group_by=...).")
        return next((group for group in self.groups if group.id == group_id), default)

    @synced
    @staticmethod
    async def series(
        *,
        from_: Any = None,
        to: Any = None,
        interval: Optional[str] = None,
        group_by: Optional[str] = None,
        key: Optional[str] = None,
        agent: Any = None,
        user_filter: Any = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> UsageSeries:
        """Daily spend between ``from_`` and ``to`` (default: the current month,
        at most 92 days), one line per ``group_by`` ``key``, ``user``,
        ``agent``, ``type`` or ``project`` (an app). ``key``
        is a key id or prefix.

        Returns:
            The lines, largest first, each with its ``label``, ``total_usd`` and daily ``points``.
            A day with no spend has no point.

        Usage:
            Chart this month's spend by what it was for::

                series = noclick.Usage.series(group_by="type")
                for line in series.series:
                    print(line.label, line.total_usd, [point.usd for point in line.points])

            Or one agent's last 30 days, one line per user::

                from datetime import datetime, timedelta, timezone

                support = noclick.Agent.from_name("support")
                now = datetime.now(timezone.utc)
                series = noclick.Usage.series(from_=now - timedelta(days=30), to=now, group_by="user", agent=support)
        """
        scope, user_id = await read_scope(user, user_filter)
        params = {
            "from": iso_time(from_), "to": iso_time(to), "interval": interval, "group_by": group_by,
            "key_id": key, "user_id": user_id, "agent_id": await ref_id(agent),
        }
        raw = await resolve_client(client).request("GET", "/v1/usage/series", params=params, user=scope) or {}
        return UsageSeries(
            interval=raw.get("interval") or "",
            from_=parse_time(raw.get("from")),
            to=parse_time(raw.get("to")),
            total_usd=float(num(raw, "total_usd")),
            series=[
                UsageSeriesLine(
                    line.get("id"), line.get("label"), float(num(line, "total_usd")), int(num(line, "events")),
                    [
                        UsagePoint(parse_time(p.get("t")), float(num(p, "usd")), int(num(p, "events")))
                        for p in line.get("points") or []
                    ],
                    line,
                )
                for line in raw.get("series") or []
            ],
            raw=raw,
        )

    @synced
    @staticmethod
    async def limits(*, client: Optional[Client] = None) -> UsageLimits:
        """This month's spend of every capped key, user and agent (account principals), and of
        every app with a budget.

        Returns:
            Each capped key and user with its ``cap`` and ``spent``, each budgeted agent with its
            ``budget``, ``spent`` and ``subtree_spent``, each budgeted app (``projects``) with its
            ``budget`` and ``spent``, and when the caps reset (``resets_at``).

        Usage::

            limits = noclick.Usage.limits()
            for cap in limits.users:
                print(cap.id, cap.spent, cap.cap)
            for app in limits.projects:
                print(app.name, app.user_id, app.spent, app.budget)
            print(limits.resets_at)
        """
        raw = await resolve_client(client).request("GET", "/v1/usage/limits", user=None) or {}
        return UsageLimits(
            period_start=parse_time(raw.get("period_start")),
            resets_at=parse_time(raw.get("resets_at")),
            keys=[KeyCap(r["id"], r.get("name"), r.get("cap"), float(num(r, "spent")), r) for r in raw.get("keys") or []],
            users=[
                UserCap(r["id"], r.get("cap"), float(num(r, "spent")), r)
                for r in raw.get("users") or []
            ],
            agents=[
                AgentBudget(r["id"], r.get("name"), r.get("budget"), float(num(r, "spent")), float(num(r, "subtree_spent")), r)
                for r in raw.get("agents") or []
            ],
            projects=[
                ProjectBudget(r["id"], r.get("name"), r.get("user_id"), r.get("budget"), float(num(r, "spent")), r)
                for r in raw.get("projects") or []
            ],
            raw=raw,
        )


@synced
async def usage(
    period: str = "month",
    *,
    group_by: Optional[str] = None,
    agent: Any = None,
    user: Any = AMBIENT,
    client: Optional[Client] = None,
) -> Usage:
    """Spend for ``period`` (``"month"``), optionally split ``group_by``
    ``"user"``, ``"key"``, ``"agent"`` or ``"project"`` (each app), and narrowed to one ``agent`` (an ``Agent`` or its id). Needs the ``usage`` scope.

    Returns:
        The period's ``total_usd`` and, with ``group_by``, one group per user, key, agent or app
        that spent, largest first. Without ``group_by``, ``groups`` is empty.

    Usage:
        See this month's spend per user::

            month = noclick.usage(group_by="user")
            print(month.total_usd)
            for group in month.groups:
                print(group.id, group.usd, group.events)

        Inside ``as_user``, it covers only that user::

            with noclick.as_user("user_42"):
                print(noclick.usage().total_usd)

        What one agent cost this month, per user it talked to::

            support = noclick.Agent.from_name("support")
            by_user = noclick.usage(group_by="user", agent=support)
            print(by_user.total_usd, by_user["user_42"].usd)

        What each app spent, to bill its user on::

            booking = noclick.Project.from_name("booking", user="user_42")
            by_app = noclick.usage(group_by="project")
            print(by_app[booking.id].usd)
    """
    params = {"period": period, "group_by": group_by, "agent_id": await ref_id(agent)}
    raw = await resolve_client(client).request("GET", "/v1/usage", params=params, user=user) or {}
    return Usage(
        period=raw.get("period", period),
        total_usd=float(raw.get("total_usd") or 0),
        groups=[
            UsageGroup(g.get("id"), float(g.get("usd") or 0), int(g.get("events") or 0), g)
            for g in raw.get("groups") or []
        ],
        raw=raw,
    )
