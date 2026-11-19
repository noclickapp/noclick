"""What something would cost a month before you make it: an app, its database and bucket, a repo, live editing.

Each charge comes back on its own line with the unit it's billed by, the unit price NoClick charges for it (what
the service costs NoClick, nothing added), the quantity a month and the dollars, priced for your account's plan.
Leave usage out and a modest default is assumed, and the line says so. Nothing is made or charged by asking.

    est = noclick.estimate([
        {"kind": "project", "runtime": "edge", "usage": {"requests": 100_000}},
        {"kind": "database", "engine": "sqlite"},
        {"kind": "bucket"},
    ])
    print(f"${est.monthly_usd:.2f} a month")
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ._client import Client, resolve_client
from ._object import required_number as num
from ._scope import AMBIENT
from ._sync import synced


def _maybe(value: Any) -> Optional[float]:
    return None if value is None else float(value)


@dataclass(frozen=True)
class EstimateLine:
    """One charge of an estimate: what is billed, by which unit, at what price, and how much of it a month."""

    #: The kind of the item it's for: ``project``, ``durable_objects``, ``database``, ``bucket``, ``repo`` or
    #: ``live_editing``.
    kind: str
    #: The ``name`` you gave the item, if any.
    item: Optional[str]
    #: Which charge it is, e.g. ``front_door``, ``rows_written`` or ``storage``.
    charge: str
    #: What it charges for, in words.
    description: str
    #: The unit it's billed by, e.g. ``million requests`` or ``GB-month``.
    unit: str
    #: The price of one ``unit``, in US dollars.
    unit_usd: float
    #: How many units a month.
    quantity: float
    #: What it would cost your account a month, in US dollars.
    usd: float
    #: Whether a default decided it: its ``quantity`` came from usage you left out, or its price from an option you
    #: left out (an edge app's ``framework``, a container's ``region``).
    assumed: bool
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any], kind: str, item: Optional[str]) -> "EstimateLine":
        return cls(kind, item, raw["charge"], raw["description"], raw["unit"], float(num(raw, "unit_usd")),
                   float(num(raw, "quantity")), float(num(raw, "usd")), bool(raw["assumed"]), raw)


@dataclass(frozen=True)
class EstimateItem:
    """One thing you asked about, priced: its options, the usage it was priced at, and its lines."""

    kind: str
    #: For people, e.g. ``App on the edge``.
    label: str
    name: Optional[str]
    #: What it was priced as: a project's ``runtime``, ``region`` and ``framework`` (and a container's ``container``
    #: settings, each as an app's ``container`` reads it), a database's ``engine``.
    options: Dict[str, Any]
    #: Every usage it was priced at, by name: what you gave and the defaults for the rest.
    usage: Dict[str, float]
    #: The usage names you left out, and the options you left out whose default changes a price.
    assumed: List[str]
    monthly_usd: float
    lines: List[EstimateLine]
    #: What its meters also charge that no usage here prices (an app's calls to AI, say), in words.
    not_included: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)
    #: A container app's: what its warm instances (``min_instances``) cost a month with nothing calling it, in US
    #: dollars, counted in ``monthly_usd`` too. None for any other item.
    idle_usd_per_month: Optional[float] = None
    #: A container app's: what its settings cost or change beyond each request, in a sentence (None when nothing).
    note: Optional[str] = None

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "EstimateItem":
        return cls(raw["kind"], raw["label"], raw.get("name"), dict(raw.get("options") or {}),
                   {k: float(v) for k, v in (raw.get("usage") or {}).items()}, list(raw.get("assumed") or []),
                   float(num(raw, "monthly_usd")),
                   [EstimateLine._from(line, raw["kind"], raw.get("name")) for line in raw.get("lines") or []],
                   list(raw.get("not_included") or []), raw, _maybe(raw.get("idle_usd_per_month")), raw.get("note"))


@dataclass(frozen=True)
class EstimateUsageField:
    """A usage a kind takes: what it counts, and the default assumed when you leave it out."""

    name: str
    unit: str
    description: str
    default: float
    #: The most it can be (a share is at most 1), else None.
    most: Optional[float]


@dataclass(frozen=True)
class EstimatePrice:
    """A charge a kind makes, at its unit price."""

    charge: str
    description: str
    unit: str
    unit_usd: float
    #: The usage names its quantity comes from.
    usage_fields: List[str]


@dataclass(frozen=True)
class EstimateKind:
    """Something an estimate takes: the usage it's priced by and the charges it makes."""

    #: What ``kind`` an item names; a project and a database come in variants (``options``).
    kind: str
    label: str
    description: str
    #: What this variant is priced as: a project's ``runtime`` and ``region``, a database's ``engine``.
    options: Dict[str, Any]
    usage: List[EstimateUsageField]
    prices: List[EstimatePrice]
    not_included: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "EstimateKind":
        return cls(
            raw["kind"], raw["label"], raw["description"], dict(raw.get("options") or {}),
            [EstimateUsageField(u["name"], u["unit"], u["description"], float(num(u, "default")),
                                None if u.get("most") is None else float(u["most"])) for u in raw.get("usage") or []],
            [EstimatePrice(p["charge"], p["description"], p["unit"], float(num(p, "unit_usd")),
                           list(p.get("usage_fields") or [])) for p in raw.get("prices") or []],
            list(raw.get("not_included") or []), raw)


@dataclass(frozen=True)
class Estimate:
    """What the items would cost a month: a usage-based estimate, priced for your account's plan."""

    monthly_usd: float
    #: Always true: these charges are by usage, so what's charged is what's used.
    estimated: bool
    items: List[EstimateItem]
    #: Every item's lines, in order.
    lines: List[EstimateLine]
    #: Your account's plan, as ``GET /v1/status`` names it (None for a key acting for one of your users).
    plan: Optional[Dict[str, Any]]
    #: The usage the plan includes a month, in dollars, which every charge to the account draws from (None without
    #: a plan). ``plan`` says whether a day's share of it is capped too.
    included_usd_per_month: Optional[float]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "Estimate":
        items = [EstimateItem._from(item) for item in raw.get("items") or []]
        return cls(float(num(raw, "monthly_usd")), bool(raw.get("estimated")), items,
                   [line for item in items for line in item.lines], raw.get("plan"),
                   _maybe(raw.get("included_usd_per_month")), raw)

    @synced
    @staticmethod
    async def kinds(*, region: Optional[str] = None, user: Any = AMBIENT,
                    client: Optional[Client] = None) -> List[EstimateKind]:
        """What ``noclick.estimate`` takes: each kind and variant, the usage it's priced by with the default assumed
        for any you leave out, and each charge's unit price. A container app's prices depend on its ``region``
        (default: where a new app of yours would go). Needs the ``usage`` scope.

        Returns:
            Each ``EstimateKind``: its ``kind`` and ``options`` (a project's ``runtime``, a database's ``engine``),
            its ``usage`` fields with their defaults, and its ``prices``.

        Usage::

            for kind in noclick.Estimate.kinds():
                print(kind.kind, kind.options, [(u.name, u.default) for u in kind.usage])
                for price in kind.prices:
                    print(f"  {price.charge}: ${price.unit_usd} per {price.unit}")
        """
        page = await resolve_client(client).request("GET", "/v1/estimates/kinds", params={"region": region},
                                                    user=user)
        return [EstimateKind._from(row) for row in page["data"]]


@synced
async def estimate(items: Sequence[Mapping[str, Any]], *, user: Any = AMBIENT,
                   client: Optional[Client] = None) -> Estimate:
    """What ``items`` would cost a month, before you make any of them. Each item is a dict naming its ``kind``
    (``project``, ``durable_objects``, ``database``, ``bucket``, ``repo`` or ``live_editing``), its options (a
    project's ``runtime``, ``region`` and ``framework``, a database's ``engine``), an optional ``name`` of your own,
    and the ``usage`` you expect a month by name (``noclick.Estimate.kinds()`` lists each kind's). Usage you leave
    out is assumed from the kind's defaults, and so is an option you leave out whose default changes a price (an
    edge app's ``framework`` picks its build machine); every line a default decided says so (``assumed``). A
    container app (``"runtime": "container"``) also takes the ``container`` settings ``Project.create`` takes
    (``cpu``, ``memory``, ``min_instances``, ``max_instances``, ``cpu_always``, ``request_timeout_s``): its item then
    says what its warm instances cost with nothing calling it (``idle_usd_per_month``, its ``warm_instances`` line)
    and why (``note``). Prices are what each service costs NoClick, nothing added, priced for your account's plan.
    Needs the ``usage`` scope; nothing is made, held or charged.

    Returns:
        An ``Estimate``: ``monthly_usd``, every charge in ``lines`` (its ``unit``, ``unit_usd``, ``quantity`` and
        ``usd``), the ``items`` each with its own total, and your ``plan`` with the usage it includes a month.
        A kind, option or usage it can't price raises ``noclick.InvalidRequest`` naming the field.

    Usage:
        A small site on the edge with a SQLite database and a bucket, at 100,000 requests a month::

            est = noclick.estimate([
                {"kind": "project", "runtime": "edge", "usage": {"requests": 100_000}},
                {"kind": "database", "engine": "sqlite"},
                {"kind": "bucket"},
            ])
            print(f"${est.monthly_usd:.2f} a month")
            for line in est.lines:
                note = " (assumed)" if line.assumed else ""
                print(f"{line.kind} {line.charge}: {line.quantity:g} {line.unit} x ${line.unit_usd:g} = "
                      f"${line.usd:.4f}{note}")

        A Postgres database awake 200 hours a month, at its smallest size::

            est = noclick.estimate([{"kind": "database", "engine": "postgres",
                                     "usage": {"active_hours": 200, "compute_units": 0.25, "storage_gb": 2}}])

        A bot in a container that stays connected, before you make it::

            est = noclick.estimate([{"kind": "project", "runtime": "container",
                                     "container": {"cpu_always": True, "min_instances": 1}}])
            bot = est.items[0]
            print(f"${bot.monthly_usd:.2f} a month, ${bot.idle_usd_per_month:.2f} of it idle: {bot.note}")
    """
    if isinstance(items, (str, bytes, Mapping)):
        raise TypeError("items is a list of dicts, one per thing to estimate.")
    body = {"items": [dict(item) for item in items]}
    return Estimate._from(await resolve_client(client).request("POST", "/v1/estimates", json=body, user=user))
