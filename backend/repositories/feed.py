"""FeedRepo — SQL for approval requests, activity logs, and tool-call events.

Owns the SELECTs behind ``feed_handler`` (the frontend's approval queue,
activity feed, and tool-call feed) plus the two-statement approval-resolve
write. Everything crosses the boundary as a typed dataclass or a plain
dict — asyncpg records never leak.

Workspace scoping — the three feeds share the same "org context or personal
context" predicate, but each SELECT keys off a different table alias
(`ar`, `al`, `tce`+`w`). ``_workspace_scope`` centralizes it against a
frozen allowlist so alias interpolation into SQL stays repo-owned.
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import uuid as uuid_module

from repositories.organization import PRIMARY_ORG_SQL


@dataclass(frozen=True)
class ApprovalRow:
    """One row from the approvals feed (pending or resolved)."""
    id: Any
    workflow_id: Any
    execution_id: Any
    node_id: Optional[str]
    title: Optional[str]
    content: Any
    status: str
    created_at: datetime
    decided_by: Optional[Any]
    decided_at: Optional[datetime]
    workflow_name: Optional[str]
    decided_by_email: Optional[str]


@dataclass(frozen=True)
class ActivityLogRow:
    """One row from the activity_logs feed."""
    id: Any
    workflow_id: Any
    execution_id: Any
    node_id: Optional[str]
    message: Optional[str]
    level: Optional[str]
    created_at: datetime
    workflow_name: Optional[str]


@dataclass(frozen=True)
class ToolCallRow:
    """One row from the tool_call_events feed."""
    id: Any
    workflow_id: Optional[Any]
    execution_id: Optional[Any]
    conversation_id: Optional[str]
    agent_node_id: Optional[str]
    tool_name: Optional[str]
    tool_type: Optional[str]
    provider_node_id: Optional[str]
    operation: Optional[str]
    credential_id: Optional[Any]
    arguments: Any
    result_status: Optional[str]
    error: Optional[str]
    result_preview: Optional[str]
    duration_ms: Optional[int]
    model: Optional[str]
    created_at: datetime
    workflow_name: Optional[str]
    credential_name: Optional[str]
    credential_type: Optional[str]


@dataclass(frozen=True)
class ApprovalDecision:
    """Identifying fields of an approval row after it was resolved."""
    id: Any
    workflow_id: Any
    execution_id: Any
    node_id: Optional[str]
    user_id: Any
    organization_id: Optional[Any]


class FeedRepo:
    """Read/write SQL for the feed handler (approvals, activity, tool calls).

    Constructor takes a pool proxy from ``DatabasePoolMixin.get_pool()``.
    """

    # Alias whitelist for scope-clause interpolation. Only table aliases used
    # by SELECTs owned by this repo — never accepts caller input.
    _ALLOWED_SCOPE_ALIASES = frozenset({
        "ar",   # approval_requests
        "al",   # activity_logs
        "tce",  # tool_call_events (user_id side of the tool-call join)
        "w",    # workflows (organization_id side of the tool-call join)
    })

    def __init__(self, pool):
        self._pool = pool

    # ------------------------------------------------------------------
    # scope helper — shared by approvals / activity / tool_calls
    # ------------------------------------------------------------------

    def _workspace_scope(
        self,
        *,
        table_alias: str,
        user_id: str,
        org_uuid: Optional[uuid_module.UUID],
        org_alias: Optional[str] = None,
    ) -> Tuple[str, List[Any]]:
        """Build a (clause, params) pair for the workspace-scoped WHERE.

        Personal context: ``(<user>.user_id = $1 AND <org>.organization_id IS NULL)``.
        Org context: ``<org>.organization_id = $1::uuid``.

        ``org_alias`` defaults to ``table_alias``; the tool-call join is the
        one caller that splits them (user_id lives on ``tce``, org lives on
        the joined ``w``). Aliases are guarded by an allowlist because they
        interpolate straight into SQL.
        """
        if table_alias not in self._ALLOWED_SCOPE_ALIASES:
            raise ValueError(f"disallowed table alias: {table_alias!r}")
        org = org_alias or table_alias
        if org not in self._ALLOWED_SCOPE_ALIASES:
            raise ValueError(f"disallowed org alias: {org!r}")
        if org_uuid is not None:
            return f"{org}.organization_id = $1::uuid", [org_uuid]
        return (
            f"({table_alias}.user_id = $1 AND {org}.organization_id IS NULL)",
            [user_id],
        )

    # ------------------------------------------------------------------
    # primary-org lookup
    # ------------------------------------------------------------------

    async def get_primary_org_id(self, user_id: str) -> Optional[str]:
        """Return the user's active-workspace org id, or None for personal."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(PRIMARY_ORG_SQL, user_id)
        return str(row["organization_id"]) if row else None

    # ------------------------------------------------------------------
    # approvals — pending + resolved
    # ------------------------------------------------------------------

    async def list_approvals(
        self,
        *,
        user_id: str,
        org_uuid: Optional[uuid_module.UUID],
    ) -> Tuple[List[ApprovalRow], List[ApprovalRow]]:
        """Return (pending, resolved) approval rows for the workspace."""
        scope_clause, scope_params = self._workspace_scope(
            table_alias="ar", user_id=user_id, org_uuid=org_uuid,
        )
        pending_sql = f"""
            SELECT
                ar.id, ar.workflow_id, ar.execution_id, ar.node_id,
                ar.title, ar.content, ar.status, ar.created_at,
                ar.decided_by, ar.decided_at,
                w.name AS workflow_name,
                NULL AS decided_by_email
            FROM approval_requests ar
            LEFT JOIN workflows w ON w.id = ar.workflow_id
            WHERE ar.status = 'pending'
              AND {scope_clause}
            ORDER BY ar.created_at DESC
            LIMIT 100
        """
        resolved_sql = f"""
            SELECT
                ar.id, ar.workflow_id, ar.execution_id, ar.node_id,
                ar.title, ar.content, ar.status, ar.created_at,
                ar.decided_by, ar.decided_at,
                w.name AS workflow_name,
                u.email AS decided_by_email
            FROM approval_requests ar
            LEFT JOIN workflows w ON w.id = ar.workflow_id
            LEFT JOIN auth.users u ON u.id = ar.decided_by
            WHERE ar.status IN ('approved', 'rejected')
              AND {scope_clause}
            ORDER BY ar.decided_at DESC
            LIMIT 50
        """
        async with self._pool.acquire() as conn:
            pending_rows = await conn.fetch(pending_sql, *scope_params)
            resolved_rows = await conn.fetch(resolved_sql, *scope_params)
        return (
            [self._to_approval(r) for r in pending_rows],
            [self._to_approval(r) for r in resolved_rows],
        )

    @staticmethod
    def _to_approval(r: Any) -> ApprovalRow:
        return ApprovalRow(
            id=r["id"],
            workflow_id=r["workflow_id"],
            execution_id=r["execution_id"],
            node_id=r["node_id"],
            title=r["title"],
            content=r["content"],
            status=r["status"],
            created_at=r["created_at"],
            decided_by=r["decided_by"],
            decided_at=r["decided_at"],
            workflow_name=r["workflow_name"],
            decided_by_email=r["decided_by_email"],
        )

    # ------------------------------------------------------------------
    # activity logs
    # ------------------------------------------------------------------

    async def list_activity(
        self,
        *,
        user_id: str,
        org_uuid: Optional[uuid_module.UUID],
        limit: int,
    ) -> List[ActivityLogRow]:
        """Recent activity_logs entries for the workspace."""
        scope_clause, scope_params = self._workspace_scope(
            table_alias="al", user_id=user_id, org_uuid=org_uuid,
        )
        sql = f"""
            SELECT
                al.id, al.workflow_id, al.execution_id, al.node_id,
                al.message, al.level, al.created_at,
                w.name AS workflow_name
            FROM activity_logs al
            LEFT JOIN workflows w ON w.id = al.workflow_id
            WHERE {scope_clause}
            ORDER BY al.created_at DESC
            LIMIT ${len(scope_params) + 1}
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *scope_params, limit)
        return [
            ActivityLogRow(
                id=r["id"],
                workflow_id=r["workflow_id"],
                execution_id=r["execution_id"],
                node_id=r["node_id"],
                message=r["message"],
                level=r["level"],
                created_at=r["created_at"],
                workflow_name=r["workflow_name"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # tool-call events (with per-workflow graph fetch)
    # ------------------------------------------------------------------

    async def list_tool_calls(
        self,
        *,
        user_id: str,
        org_uuid: Optional[uuid_module.UUID],
        limit: int,
    ) -> Tuple[List[ToolCallRow], Dict[str, Any]]:
        """Return (tool-call rows, workflow_graph_by_id).

        The graph JSON is fetched once per referenced workflow — the handler
        resolves node labels from it. Both fetches share one acquire so the
        graph read reuses the connection the tool-call read pinned.
        """
        scope_clause, scope_params = self._workspace_scope(
            table_alias="tce", user_id=user_id, org_uuid=org_uuid,
            org_alias="w",
        )
        sql = f"""
            SELECT
                tce.id, tce.workflow_id, tce.execution_id, tce.conversation_id,
                tce.agent_node_id, tce.tool_name, tce.tool_type,
                tce.provider_node_id, tce.operation, tce.credential_id,
                tce.arguments, tce.result_status, tce.error,
                tce.result_preview, tce.duration_ms, tce.model, tce.created_at,
                w.name AS workflow_name,
                c.name AS credential_name, c.credential_type AS credential_type
            FROM tool_call_events tce
            LEFT JOIN workflows w ON w.id = tce.workflow_id
            LEFT JOIN credentials c ON c.id = tce.credential_id
            WHERE {scope_clause}
            ORDER BY tce.created_at DESC
            LIMIT ${len(scope_params) + 1}
        """
        graphs: Dict[str, Any] = {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *scope_params, limit)
            wf_ids = list({row["workflow_id"] for row in rows if row["workflow_id"]})
            if wf_ids:
                graph_rows = await conn.fetch(
                    "SELECT id, workflow FROM workflows WHERE id = ANY($1::uuid[])",
                    wf_ids,
                )
                for gr in graph_rows:
                    graphs[str(gr["id"])] = gr["workflow"]
        return (
            [
                ToolCallRow(
                    id=r["id"],
                    workflow_id=r["workflow_id"],
                    execution_id=r["execution_id"],
                    conversation_id=r["conversation_id"],
                    agent_node_id=r["agent_node_id"],
                    tool_name=r["tool_name"],
                    tool_type=r["tool_type"],
                    provider_node_id=r["provider_node_id"],
                    operation=r["operation"],
                    credential_id=r["credential_id"],
                    arguments=r["arguments"],
                    result_status=r["result_status"],
                    error=r["error"],
                    result_preview=r["result_preview"],
                    duration_ms=r["duration_ms"],
                    model=r["model"],
                    created_at=r["created_at"],
                    workflow_name=r["workflow_name"],
                    credential_name=r["credential_name"],
                    credential_type=r["credential_type"],
                )
                for r in rows
            ],
            graphs,
        )

    # ------------------------------------------------------------------
    # approval decision — read current content, patch values, resolve
    # ------------------------------------------------------------------

    async def resolve_approval(
        self,
        *,
        approval_id: uuid_module.UUID,
        decision: str,
        decided_by_user_id: str,
        values: Optional[Dict[str, Any]],
    ) -> Optional[ApprovalDecision]:
        """Apply the decision (optionally editing the form values) and return
        the resolved row's identifying fields, or None if it wasn't found.

        Preserves the handler's ordering: patch content first if values were
        edited, then flip status. Both statements share one acquire so the
        content patch and the status flip land on the same physical
        connection (matches the original handler's ``async with
        pool.acquire()`` block).
        """
        async with self._pool.acquire() as conn:
            if values is not None:
                current = await conn.fetchrow(
                    "SELECT content FROM approval_requests WHERE id = $1",
                    approval_id,
                )
                if current and current["content"]:
                    raw = current["content"]
                    try:
                        content_data = (
                            _json.loads(raw) if isinstance(raw, str) else raw
                        )
                    except (ValueError, TypeError):
                        content_data = {}
                    content_data["values"] = values
                    await conn.execute(
                        "UPDATE approval_requests SET content = $1 WHERE id = $2",
                        _json.dumps(content_data),
                        approval_id,
                    )
            row = await conn.fetchrow(
                """
                UPDATE approval_requests
                SET status = $1, decided_by = $2, decided_at = NOW()
                WHERE id = $3 AND status IN ('pending', 'approved', 'rejected')
                RETURNING id, workflow_id, execution_id, node_id, user_id, organization_id
                """,
                decision, decided_by_user_id, approval_id,
            )
        if not row:
            return None
        return ApprovalDecision(
            id=row["id"],
            workflow_id=row["workflow_id"],
            execution_id=row["execution_id"],
            node_id=row["node_id"],
            user_id=row["user_id"],
            organization_id=row["organization_id"],
        )
