"""What runs on NoClick for you now: your machines (with the conversations on
each), every agent's sandbox that's up, and your live sandboxes, each with its
price an hour.

    running = noclick.compute(user_filter="all")
    per_hour = sum(c.usd_per_hour or 0 for c in running if c.status == "running")
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Dict, List, Optional

from ._client import Client, resolve_client
from ._object import parse_time, read_scope
from ._scope import AMBIENT
from ._sync import synced


@dataclass(frozen=True)
class ComputeRun:
    """A conversation running on a machine or in an agent's sandbox."""

    agent_id: Optional[str]
    agent_name: Optional[str]
    #: The agent's conversation, as ``agent.message(conversation=...)`` names it.
    conversation: Optional[str]
    harness: Optional[str]
    #: ``starting``, ``live`` or ``running``.
    state: str


@dataclass(frozen=True)
class ComputeItem:
    """A machine, an agent's sandbox or a sandbox, as it runs now."""

    #: ``machine`` (a NoClick machine, any status), ``agent_sandbox`` (an agent's warm sandbox) or ``sandbox``.
    kind: str
    #: Its id (an agent's sandbox: its name).
    id: str
    #: The machine's name, the agent's, or a sandbox's image.
    name: Optional[str]
    status: Optional[str]
    user_id: Optional[str]
    region: Optional[str]
    cpu: Optional[float]
    memory_gb: Optional[float]
    started_at: Any
    #: What an hour of it costs (a machine: its month's price over 730 hours).
    usd_per_hour: Optional[float]
    #: A machine's price a month.
    usd_per_month: Optional[float]
    #: What an agent's sandbox charged since midnight UTC.
    spent_usd_today: Optional[float]
    running: List[ComputeRun]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ComputeItem":
        return cls(
            raw["kind"], raw["id"], raw.get("name"), raw.get("status"), raw.get("user_id"), raw.get("region"),
            raw.get("cpu"), raw.get("memory_gb"), parse_time(raw.get("started_at")), raw.get("usd_per_hour"),
            raw.get("usd_per_month"), raw.get("spent_usd_today"),
            [ComputeRun(r.get("agent_id"), r.get("agent_name"), r.get("conversation"), r.get("harness"),
                        r.get("state") or "") for r in raw.get("running") or []],
            raw,
        )


@synced
async def compute(*, user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None) -> List[ComputeItem]:
    """Your machines (any status, with the conversations on each), every agent's sandbox up now and every live
    ``Sandbox``, each with its price an hour. Each part needs its area's scope (``machines``, ``agents``,
    ``sandboxes``); a key with only some gets those. Your own computers aren't in it.

    Returns:
        Each machine or sandbox: its ``kind``, status, size, price an hour and what runs on it.

    Usage::

        for item in noclick.compute(user_filter="all"):
            print(item.kind, item.name, item.usd_per_hour, [r.agent_name for r in item.running])
    """
    scope, user_id = await read_scope(user, user_filter)
    page = await resolve_client(client).request("GET", "/v1/compute", params={"user_id": user_id}, user=scope)
    return [ComputeItem._from(row) for row in page["data"]]
