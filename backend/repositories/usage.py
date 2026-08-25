"""Read-side repository for provider-neutral usage events."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from repositories.organization import IS_ORG_MEMBER_SQL


@dataclass(frozen=True)
class UsageLogEntry:
    created_at: datetime
    usage_type: Optional[str]
    usage_subtype: Optional[str]
    quantity: Optional[float]
    unit_type: Optional[str]
    total_cost: Optional[float]
    metadata: Optional[Dict[str, Any]]


class UsageRepo:
    """Workspace-scoped aggregates over ``user_usage_events``."""

    _ALLOWED_DATE_TRUNC = frozenset({"day", "week", "month"})

    def __init__(self, pool):
        self._pool = pool

    @staticmethod
    def _where(
        *,
        user_id: str,
        organization_id: Optional[str],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        usage_type_filter: Optional[str] = None,
        usage_subtype_filter: Optional[str] = None,
        before: Optional[datetime] = None,
        search: Optional[str] = None,
    ) -> tuple[str, List[Any]]:
        if organization_id is None:
            clauses, params = ["user_id = $1"], [user_id]
        else:
            clauses, params = ["organization_id = $1"], [organization_id]

        def add(clause: str, value: Any) -> None:
            params.append(value)
            clauses.append(clause.format(index=len(params)))

        if start_date is not None:
            add("created_at >= ${index}", start_date)
        if end_date is not None:
            add("created_at <= ${index}", end_date)
        if usage_type_filter is not None:
            add("usage_type = ${index}", usage_type_filter)
        if usage_subtype_filter is not None:
            add("usage_subtype = ${index}", usage_subtype_filter)
        if before is not None:
            add("created_at < ${index}", before)
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            add("usage_subtype ILIKE ${index}", f"%{escaped}%")
        return " AND ".join(clauses), params

    async def dashboard_aggregates(
        self,
        *,
        user_id: str,
        organization_id: Optional[str],
        start_date: datetime,
        end_date: datetime,
        usage_type_filter: Optional[str],
        usage_subtype_filter: Optional[str],
        date_trunc: str,
    ) -> Dict[str, Any]:
        if date_trunc not in self._ALLOWED_DATE_TRUNC:
            raise ValueError(f"unsupported aggregation interval: {date_trunc!r}")

        where, params = self._where(
            user_id=user_id,
            organization_id=organization_id,
            start_date=start_date,
            end_date=end_date,
            usage_type_filter=usage_type_filter,
            usage_subtype_filter=usage_subtype_filter,
        )
        total_sql = f"SELECT COALESCE(SUM(total_cost), 0) FROM user_usage_events WHERE {where}"
        by_type_sql = (
            "SELECT usage_type, SUM(total_cost) AS total_cost "
            f"FROM user_usage_events WHERE {where} GROUP BY usage_type"
        )
        by_subtype_sql = (
            "SELECT usage_subtype, SUM(total_cost) AS total_cost, "
            "MAX(unit_type) AS unit_type "
            f"FROM user_usage_events WHERE {where} "
            "GROUP BY usage_subtype ORDER BY total_cost DESC"
        )
        time_series_sql = (
            f"SELECT DATE_TRUNC('{date_trunc}', created_at) AS period, "
            "SUM(total_cost) AS total_cost, SUM(quantity) AS total_tokens, "
            "usage_type, usage_subtype "
            f"FROM user_usage_events WHERE {where} "
            f"GROUP BY DATE_TRUNC('{date_trunc}', created_at), usage_type, usage_subtype "
            "ORDER BY period ASC"
        )

        async def one(sql: str, scalar: bool):
            async with self._pool.acquire() as conn:
                if scalar:
                    return await conn.fetchval(sql, *params)
                return await conn.fetch(sql, *params)

        async with asyncio.TaskGroup() as group:
            total = group.create_task(one(total_sql, True))
            by_type = group.create_task(one(by_type_sql, False))
            by_subtype = group.create_task(one(by_subtype_sql, False))
            time_series = group.create_task(one(time_series_sql, False))
        return {
            "total": total.result(),
            "by_type": by_type.result(),
            "by_subtype": by_subtype.result(),
            "time_series": time_series.result(),
        }

    async def recent_logs(
        self,
        *,
        user_id: str,
        organization_id: Optional[str],
        usage_type_filter: Optional[str],
        limit: int,
        before: Optional[datetime] = None,
        search: Optional[str] = None,
    ) -> List[UsageLogEntry]:
        where, params = self._where(
            user_id=user_id,
            organization_id=organization_id,
            usage_type_filter=usage_type_filter,
            before=before,
            search=search,
        )
        params.append(limit)
        sql = (
            "SELECT created_at, usage_type, usage_subtype, quantity, unit_type, "
            f"total_cost, metadata FROM user_usage_events WHERE {where} "
            f"ORDER BY created_at DESC LIMIT ${len(params)}"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [
            UsageLogEntry(
                created_at=row["created_at"],
                usage_type=row["usage_type"],
                usage_subtype=row["usage_subtype"],
                quantity=row["quantity"],
                unit_type=row["unit_type"],
                total_cost=row["total_cost"],
                metadata=row["metadata"],
            )
            for row in rows
        ]

    async def is_org_member(self, organization_id: str, user_id: str) -> bool:
        async with self._pool.acquire() as conn:
            value = await conn.fetchval(IS_ORG_MEMBER_SQL, organization_id, user_id)
        return value is not None
