"""UsagePageRepo — the usage page's reads over ``user_usage_events``.

The page groups a payer's rows by everything a breakdown splits them by (one
group per window, UTC day and set of fields) and reads its charges a page at a
time. A group's key is the same SQL expression in both reads, so a drill the
page works out over the groups ("this model inside this automation") narrows the
charges to the keys it picked: nothing about services or models is restated in
SQL.

Rows are the payer's (``user_id``): Owner Pays has already put a workspace's
work under its owner, with the member who ran it as ``metadata.actual_user_id``.
Metadata is ``json`` in one schema and ``jsonb`` in another; both reads take the
fields they need from it in one pass a row (``json_to_record``), which on a heavy
account is a quarter of the time of reading each field on its own.

A deployment that bills adds the columns that say how each charge was paid
(``extra_columns``: {name: (row expression, group aggregate)}); the engine's
schema keeps no such allocation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from repositories.users import user_label_sql
from utils.graph_nodes import node_meta_map

# The metadata fields a breakdown splits by, read once a row as ``m``.
_RECORD_FIELDS = ("workflow_id", "node_id", "surface", "actual_user_id", "project_id", "database_id", "repo_id",
                  "inbox_id", "phone_number_id", "number", "channel", "from", "credential_id", "domain")
METADATA_RECORD_SQL = "json_to_record(e.metadata::json) AS m({}, platform_api json, prompt_tokens text, completion_tokens text)".format(
    ", ".join(f'"{f}" text' for f in _RECORD_FIELDS))

# (name, expression): every field a breakdown splits charges by. Only an email's
# ``from`` is a sender: an app's metered storage names the stretch it covers there.
GROUP_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("usage_type", "e.usage_type"),
    ("usage_subtype", "e.usage_subtype"),
    ("unit_type", "e.unit_type"),
    ("user_resource", "e.user_resource"),
    *(("sender", """CASE WHEN e.usage_subtype LIKE 'email/%' THEN m."from" END""") if f == "from" else (f, f'm."{f}"')
      for f in _RECORD_FIELDS),
    ("pa_agent_id", "m.platform_api->>'agent_id'"),
    ("pa_tenant_id", "m.platform_api->>'tenant_id'"),
    ("pa_key_id", "m.platform_api->>'key_id'"),
    ("pa_project_id", "m.platform_api->>'project_id'"),
    ("pa_surface", "m.platform_api->>'surface'"),
)
GROUP_KEY_SQL = "md5(json_build_array({})::text)".format(", ".join(expr for _, expr in GROUP_FIELDS))

# The metadata a charge shows; anything else a writer stored stays in the table.
CHARGE_METADATA_KEYS: Tuple[str, ...] = (
    "workflow_id", "node_id", "execution_id", "surface", "actual_user_id", "coordinator_job_id", "project_id",
    "database_id", "repo_id", "inbox_id", "phone_number_id", "number", "direction", "channel", "from", "to", "operation",
    "model", "prompt_tokens", "completion_tokens", "credential_id", "domain", "years", "call_sid", "minutes", "requests",
    "reverses", "reason", "platform_api",
)

# Every ``$n`` below is bound by the methods that run these.
GROUPS_SQL = """
    SELECT e.created_at >= $2 AS current,
           to_char(e.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS day,
           min(e.created_at) AS created_at,
           {key} AS k,
           {fields},
           count(*) AS n,
           COALESCE(sum(e.quantity), 0) AS quantity,
           COALESCE(sum(e.total_cost), 0) AS total_cost,
           COALESCE(sum(m.prompt_tokens::numeric), 0) AS prompt_tokens,
           COALESCE(sum(m.completion_tokens::numeric), 0) AS completion_tokens{extra}
      FROM user_usage_events e, {record}
     WHERE e.user_id = $1 AND e.created_at >= $3 AND e.created_at < $4
     GROUP BY 1, 2, {group_by}
"""

# The period's total as the page shows it: every charge the payer was billed in
# the window, the account's own keys' (user_resource) left out, as its breakdowns are.
PERIOD_SPENT_SQL = """
    SELECT COALESCE(sum(total_cost), 0) FROM user_usage_events
     WHERE user_id = $1 AND created_at >= $2 AND created_at < $3 AND NOT user_resource
"""


async def period_spent(db, user_id: str, start: datetime, end: datetime) -> Decimal:
    """What the usage page totals for ``[start, end)``, in dollars. ``db`` is a pool or a connection."""
    return Decimal(str(await db.fetchval(PERIOD_SPENT_SQL, user_id, start, end)))


CHARGE_COLUMNS_SQL = """
    e.id::text AS id, e.created_at, e.user_id::text AS user_id, e.organization_id::text AS organization_id,
    e.usage_type, e.usage_subtype, e.quantity, e.unit_type, e.total_cost, e.user_resource,
    {key} AS k, json_strip_nulls(json_build_object({metadata})) AS metadata{extra}
"""

RUNS_SQL = """
    SELECT e.id::text AS id, e.workflow_id::text AS workflow_id, w.name AS workflow_name, e.status,
           e.started_at, e.finished_at, e.trigger_source, e.nodes_executed, e.error
      FROM workflow_executions e
      JOIN workflows w ON w.id = e.workflow_id
     WHERE e.id = ANY($1::uuid[])
       AND (w.owner_id = $2 OR e.user_id = $2
            OR w.organization_id IN (SELECT organization_id FROM organization_members WHERE user_id = $2 AND role = 'owner'))
"""

WORKFLOWS_SQL = "SELECT id::text AS id, name, workflow FROM workflows WHERE id = ANY($1::uuid[])"

PEOPLE_SQL = f"SELECT id::text AS id, {user_label_sql()} AS label FROM auth.users WHERE id = ANY($1::uuid[])"

ExtraColumns = Mapping[str, Tuple[str, str]]


@dataclass(frozen=True)
class ChargesCursor:
    """Where a page of charges stopped: the last row's time and id (newest first)."""
    at: datetime
    id: str

    def encode(self) -> str:
        return f"{self.at.isoformat()}|{self.id}"

    @classmethod
    def decode(cls, raw: str) -> "ChargesCursor":
        at, _, row_id = raw.rpartition("|")
        if not at or not row_id:
            raise ValueError("not a charges cursor")
        return cls(datetime.fromisoformat(at), row_id)


class UsagePageRepo:
    def __init__(self, pool):
        self._pool = pool

    async def groups(
        self, *, user_id: str, window_start: datetime, window_end: datetime, previous_start: datetime,
        extra_columns: Optional[ExtraColumns] = None,
    ) -> List[Dict[str, Any]]:
        """The payer's rows from the previous window's start to this one's end,
        grouped by window (``current``), UTC day and every field in GROUP_FIELDS."""
        sql = GROUPS_SQL.format(
            key=GROUP_KEY_SQL,
            record=METADATA_RECORD_SQL,
            fields=", ".join(f"{expr} AS {name}" for name, expr in GROUP_FIELDS),
            group_by=", ".join(expr for _, expr in GROUP_FIELDS),
            extra="".join(f",\n           {agg} AS {name}" for name, (_, agg) in (extra_columns or {}).items()),
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, user_id, window_start, previous_start, window_end)
        return [dict(r) for r in rows]

    async def charges(
        self,
        *,
        user_id: str,
        start: datetime,
        end: datetime,
        keys: Optional[List[str]] = None,
        day_start: Optional[datetime] = None,
        cursor: Optional[ChargesCursor] = None,
        limit: int = 50,
        extra_columns: Optional[ExtraColumns] = None,
    ) -> List[Dict[str, Any]]:
        """One page of the payer's charges in ``[start, end)``, newest first,
        narrowed to the groups in ``keys`` (None: every group) and to one UTC day."""
        clauses = ["e.user_id = $1", "e.created_at >= $2", "e.created_at < $3"]
        params: List[Any] = [user_id, start, end]
        if day_start is not None:
            params.append(day_start)
            clauses.append(f"e.created_at >= ${len(params)} AND e.created_at < ${len(params)} + interval '1 day'")
        if keys is not None:
            params.append(keys)
            clauses.append(f"{GROUP_KEY_SQL} = ANY(${len(params)}::text[])")
        if cursor is not None:
            params.extend([cursor.at, cursor.id])
            clauses.append(f"(e.created_at, e.id) < (${len(params) - 1}, ${len(params)}::uuid)")
        params.append(limit)
        columns = CHARGE_COLUMNS_SQL.format(
            key=GROUP_KEY_SQL,
            metadata=", ".join(f"'{k}', e.metadata->'{k}'" for k in CHARGE_METADATA_KEYS),
            extra="".join(f", {expr} AS {name}" for name, (expr, _) in (extra_columns or {}).items()),
        )
        sql = (
            f"SELECT {columns} FROM user_usage_events e, {METADATA_RECORD_SQL} "
            f"WHERE {' AND '.join(clauses)} ORDER BY e.created_at DESC, e.id DESC LIMIT ${len(params)}"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def runs(self, *, user_id: str, execution_ids: Iterable[str]) -> List[Dict[str, Any]]:
        """The runs charges belong to, in workflows the payer owns or ran, or in a workspace it owns (Owner Pays)."""
        ids = _uuids(sorted({i for i in execution_ids if i}))
        if not ids:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(RUNS_SQL, ids, user_id)
        return [dict(r) for r in rows]

    async def names(
        self, *, workflow_ids: Iterable[str], agents: Iterable[Tuple[str, str]], people: Iterable[str],
    ) -> Dict[str, Dict[str, Dict[str, str]]]:
        """Names for the automations, agent nodes (``(workflow_id, node_id)``) and
        people the rows carry ids for. A deleted automation keeps its name."""
        workflow_ids = sorted({w for w in workflow_ids if w} | {w for w, _ in agents if w})
        people = sorted({p for p in people if p})
        out: Dict[str, Dict[str, Dict[str, str]]] = {"workflows": {}, "agents": {}, "people": {}}
        async with self._pool.acquire() as conn:
            graphs = await conn.fetch(WORKFLOWS_SQL, _uuids(workflow_ids)) if workflow_ids else []
            labels = await conn.fetch(PEOPLE_SQL, _uuids(people)) if people else []
        meta = {}
        for row in graphs:
            out["workflows"][row["id"]] = {"name": row["name"] or "Untitled automation"}
            meta[row["id"]] = node_meta_map(row["workflow"])
        for workflow_id, node_id in agents:
            label = meta.get(workflow_id, {}).get(node_id, {}).get("label")
            if label:
                out["agents"][f"{workflow_id}:{node_id}"] = {"name": label}
        for row in labels:
            if row["label"]:
                out["people"][row["id"]] = {"name": row["label"]}
        return out


def _uuids(ids: Iterable[str]) -> List[str]:
    """The ids that are uuids: metadata can carry anything a writer put there."""
    import uuid

    keep = []
    for raw in ids:
        try:
            keep.append(str(uuid.UUID(str(raw))))
        except ValueError:
            continue
    return keep
