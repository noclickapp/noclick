"""Regions: where a resource runs and keeps its data, in NoClick's own names
(``us-east``, ``us-west``, ``eu``, ``ap``, and ``in`` for machines), never a cloud's.

A resource takes its region when it's created and keeps it: the ``region=``
you pass, else (for a child agent) its parent's, else your account's default
region, else none, which means wherever NoClick has capacity. Pass
``region=other.region`` to put two resources together.

    for region in noclick.regions():
        print(region.name, region.label, region.default)
    with noclick.Sandbox.create(region="eu") as sb:
        print(sb.region)   # eu
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from ._client import Client, resolve_client
from ._sync import synced


@dataclass(frozen=True)
class Region:
    """A place NoClick runs resources and keeps their data; ``region=`` takes its ``name``."""

    #: What ``region=`` takes: ``us-east``, ``us-west``, ``eu``, ``ap`` or ``in`` (India: machines only).
    name: str
    #: For people: ``US East``, ``US West``, ``Europe``, ``Asia-Pacific``, ``India``.
    label: str
    #: Where it is, in words.
    location: str
    #: The kinds of resource it places today: ``sandbox``, ``agent``, ``bucket``, ``database``, ``project`` (an
    #: app) and ``machine`` everywhere, ``browser`` everywhere but ``us-west``, ``dict`` and ``queue`` in ``us-east``.
    kinds: List[str]
    #: Whether it's your account's default region, which a resource takes when you name none.
    default: bool
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "Region":
        return cls(raw["name"], raw["label"], raw["location"], list(raw["kinds"]), bool(raw["default"]), raw)


@synced
async def regions(kind: Optional[str] = None, *, client: Optional[Client] = None) -> List[Region]:
    """Every region, or those that place ``kind`` (``"sandbox"``, ``"agent"``, ``"bucket"``,
    ``"database"``, ``"project"``, ``"machine"``, ``"browser"``, ``"dict"`` or ``"queue"``; any other
    raises ``noclick.InvalidRequest`` naming those that are placed by region). Dicts and queues are
    kept in ``us-east`` only for now, and browsers run everywhere but ``us-west``. Your account's
    default is set in the console. Needs the scope of any kind it places: ``sandboxes``, ``agents``,
    ``storage``, ``databases``, ``apps``, ``machines``, ``browsers``, ``dicts``, ``queues`` or ``volumes``.

    Returns:
        Each region's ``name`` (what ``region=`` takes), its ``label`` and ``location``, the
        ``kinds`` it places, and whether it's your account's ``default``.

    Usage:
        See where things can run, and your account's default::

            for region in noclick.regions():
                print(region.name, region.location, "(default)" if region.default else "")

        Put a sandbox where an agent already runs::

            analyst = noclick.Agent.from_name("analyst")
            with noclick.Sandbox.create(region=analyst.region) as sb:
                print(sb.exec("python -c 'print(1 + 1)'").stdout)
    """
    page = await resolve_client(client).request("GET", "/v1/regions", params={"kind": kind}, user=None)
    return [Region._from(row) for row in page["data"]]
