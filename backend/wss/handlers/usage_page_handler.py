"""
The usage page (Settings → Usage).

``usage:page`` answers the whole page in one read: the period, the signed-in
account's charges grouped every way the page breaks them down
(repositories/usage_page.py), names for what they were for, and the first page
of charges; ``usage:charges`` pages through the charges, narrowed to the groups
a drill or a search picked. Where the deployment bills (the ``USAGE_BILLING``
capability), its period is the plan's window and the page also gets the money
behind it; elsewhere the period is the UTC calendar month and each charge is
what it cost.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Optional

from billing.clock import billing_month_start_utc, billing_now
from repositories.usage_page import ChargesCursor, GROUP_FIELDS, UsagePageRepo
from utils.capabilities import USAGE_BILLING, capability
from utils.database_pool import get_native_pool
from wss.receiver.client_events import UsageChargesRequest, UsagePageRequest
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.session_actor import session_actor

logger = logging.getLogger(__name__)

FIRST_PAGE = 50

# Group fields that name a thing a deployment's own tables hold, by the directory
# they're looked up in (``USAGE_BILLING.names``).
OWNED_IDS = {
    "projects": ("project_id", "pa_project_id"),
    "databases": ("database_id",),
    "numbers": ("phone_number_id",),
    "inboxes": ("inbox_id",),
    "agents": ("pa_agent_id",),
    "keys": ("pa_key_id",),
    "people": ("pa_tenant_id",),
}


def _plain(value: Any) -> Any:
    """A row value as the wire carries it: numbers, ISO times, parsed metadata."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: _plain(v) for k, v in row.items()}
    if isinstance(out.get("metadata"), str):
        out["metadata"] = json.loads(out["metadata"])
    return out


def _parse_time(raw: str) -> datetime:
    at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def calendar_period(now: datetime) -> Dict[str, Any]:
    """The period where nobody is billed: the UTC calendar month."""
    start = billing_month_start_utc(now)
    end = (start + timedelta(days=32)).replace(day=1)
    previous = (start - timedelta(days=1)).replace(day=1)
    return {"window_start": start, "window_end": end, "previous_start": previous, "billing": None}


class UsagePageHandler(SocketIOHandler):
    def get_events(self) -> Dict[str, Callable]:
        return {
            "usage:page": self.handle_page,
            "usage:charges": self.handle_charges,
        }

    async def _respond(self, sid: str, request_id: str, op) -> None:
        try:
            actor = await session_actor(self.sio, sid)
            if actor is None:
                await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=None, error="Not authenticated"))
                return
            data = await op(actor[0])
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=data))
        except ValueError as e:
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=None, error=str(e)))
        except Exception as e:
            logger.error("[UsagePage] request failed: %s", e, exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=None, error="Usage didn't load"))

    async def handle_page(self, sid: str, request: UsagePageRequest) -> None:
        await self._respond(sid, request.request_id, page)

    async def handle_charges(self, sid: str, request: UsageChargesRequest) -> None:
        async def op(user_id: str) -> Dict[str, Any]:
            return await charges_page(
                user_id, start=_parse_time(request.start), end=_parse_time(request.end), keys=request.keys,
                day=request.day, cursor=ChargesCursor.decode(request.cursor) if request.cursor else None,
                limit=request.limit,
            )
        await self._respond(sid, request.request_id, op)


async def page(user_id: str) -> Dict[str, Any]:
    """Everything the usage page shows for ``user_id``, the payer."""
    pool = get_native_pool()
    billing = capability(USAGE_BILLING)
    now = billing_now()
    period = await billing.period(pool, user_id) if billing else calendar_period(now)
    repo = UsagePageRepo(pool)
    groups = [
        {**_row(g), "user_id": user_id}
        for g in await repo.groups(
            user_id=user_id, window_start=period["window_start"], window_end=period["window_end"],
            previous_start=period["previous_start"], extra_columns=billing.columns if billing else None,
        )
    ]
    directory = await repo.names(
        workflow_ids=(g["workflow_id"] for g in groups),
        agents={(g["workflow_id"], g["node_id"]) for g in groups if g["workflow_id"] and g["node_id"]},
        people=[user_id, *(g["actual_user_id"] for g in groups)],
    )
    if billing:
        owned = {kind: sorted({g[f] for g in groups for f in fields if g[f]}) for kind, fields in OWNED_IDS.items()}
        for kind, names in (await billing.names(pool, user_id, owned)).items():
            directory.setdefault(kind, {}).update(names)
    first = await charges_page(user_id, start=period["window_start"], end=period["window_end"], limit=FIRST_PAGE)
    return {
        "now": now.isoformat(),
        "account": {"id": user_id},
        "period": {k: _plain(period[k]) for k in ("window_start", "window_end", "previous_start")},
        "billing": period["billing"],
        "groups": groups,
        "directory": directory,
        "charges": first,
        "fields": [name for name, _ in GROUP_FIELDS],
    }


async def charges_page(
    user_id: str, *, start: datetime, end: datetime, keys: Optional[List[str]] = None, day: Optional[str] = None,
    cursor: Optional[ChargesCursor] = None, limit: int = FIRST_PAGE,
) -> Dict[str, Any]:
    """One page of charges, the runs they belong to, and where the next page starts."""
    pool = get_native_pool()
    billing = capability(USAGE_BILLING)
    repo = UsagePageRepo(pool)
    day_start = _parse_time(f"{day}T00:00:00+00:00") if day else None
    rows = [_row(r) for r in await repo.charges(
        user_id=user_id, start=start, end=end, keys=keys, day_start=day_start, cursor=cursor, limit=limit + 1,
        extra_columns=billing.columns if billing else None,
    )]
    more = len(rows) > limit
    rows = rows[:limit]
    runs = await repo.runs(user_id=user_id, execution_ids=_execution_ids(rows))
    last = rows[-1] if rows else None
    return {
        "rows": rows,
        "runs": {r["id"]: _run(r) for r in runs},
        "next": ChargesCursor(_parse_time(last["created_at"]), last["id"]).encode() if more and last else None,
    }


def _execution_ids(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [r["metadata"].get("execution_id") for r in rows if r["metadata"].get("execution_id")]


def _run(row: Dict[str, Any]) -> Dict[str, Any]:
    started, finished = row["started_at"], row["finished_at"]
    return {
        "id": row["id"],
        "workflow": {"id": row["workflow_id"], "name": row["workflow_name"] or "Untitled automation"},
        "status": row["status"],
        "startedAt": _plain(started),
        "durationMs": int((finished - started).total_seconds() * 1000) if started and finished else None,
        "trigger": row["trigger_source"] or "manual",
        "nodesExecuted": row["nodes_executed"] or 0,
        **({"error": row["error"]} if row["error"] else {}),
    }
