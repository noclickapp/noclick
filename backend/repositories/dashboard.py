"""SQL for the Dashboard tab's ``dashboard:overview`` aggregate.

Scope is resolved ONCE: ``list_workflows`` applies the workspace rule (an org
context filters on ``workflows.organization_id``; a personal context on the
owner with no org) and every per-workflow query after it takes that list of
ids — ``workflow_id = ANY($1)`` — instead of re-joining ``workflows``. That
keeps each query on its table's ``(workflow_id, …)`` index (the executions
index is covering: ``(workflow_id, started_at DESC) INCLUDE (status,
trigger_source)``), and every executions query is bounded by a time window so
a heavy account never scans its whole run history. Cross-cutting rules:
``deleted_at IS NULL`` everywhere, and ``jsonb`` parameters travel as
``($n::text)::jsonb``.
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from repositories.workflow import USER_VISIBLE_RUN_SQL


class DashboardRepo:
    def __init__(self, pool):
        self._pool = pool

    # ------------------------------------------------------------------
    # scope helpers — clauses always bind the scope value as $1
    # ------------------------------------------------------------------

    @staticmethod
    def _workflow_scope(user_id: str, org_uuid: Optional[uuid_module.UUID]) -> Tuple[str, List[Any]]:
        if org_uuid is not None:
            return "w.organization_id = $1::uuid", [org_uuid]
        return "(w.owner_id = $1::uuid AND w.organization_id IS NULL)", [user_id]

    @staticmethod
    def _ids(workflow_ids: List[Any]) -> List[uuid_module.UUID]:
        return [uuid_module.UUID(str(w)) for w in workflow_ids]

    # ------------------------------------------------------------------
    # identity
    # ------------------------------------------------------------------

    async def workspace_identity(self, user_id: str, org_uuid: Optional[uuid_module.UUID]) -> Dict[str, Any]:
        """The greeting's inputs: the user's display name and the workspace name."""
        async with self._pool.acquire() as conn:
            user_row = await conn.fetchrow(
                """
                SELECT COALESCE(
                    NULLIF(raw_user_meta_data->>'full_name', ''),
                    NULLIF(raw_user_meta_data->>'name', ''),
                    split_part(email, '@', 1)
                ) AS name
                FROM auth.users WHERE id = $1::uuid
                """,
                user_id,
            )
            org_name = None
            is_personal = True
            if org_uuid is not None:
                org_row = await conn.fetchrow("SELECT name, is_personal_workspace FROM organizations WHERE id = $1::uuid", org_uuid)
                if org_row:
                    org_name = org_row["name"]
                    # A personal workspace is an org row too (2026-03 model); the tab still calls it personal.
                    is_personal = bool(org_row["is_personal_workspace"])
        return {"userName": (user_row["name"] if user_row else None) or "there", "orgName": org_name, "isPersonal": is_personal}

    # ------------------------------------------------------------------
    # workflows
    # ------------------------------------------------------------------

    async def list_workflows(self, user_id: str, org_uuid: Optional[uuid_module.UUID], *, limit: int = 300) -> List[Dict[str, Any]]:
        """Live workflows in scope with their graph blobs (marks, node labels,
        trigger mirrors and credential usage all derive from the graph)."""
        clause, params = self._workflow_scope(user_id, org_uuid)
        sql = f"""
            SELECT w.id, w.name, w.workflow, w.organization_id, w.owner_id, w.updated_at
            FROM workflows w
            WHERE {clause} AND w.deleted_at IS NULL
            ORDER BY w.updated_at DESC
            LIMIT $2
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params, limit)
        return [dict(r) for r in rows]

    async def workflow_graphs(self, workflow_ids: List[Any]) -> Dict[str, Dict[str, Any]]:
        """Name + graph for workflows referenced by rows outside the scoped list
        (a tool call on a since-shared workflow, say)."""
        if not workflow_ids:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, workflow FROM workflows WHERE id = ANY($1::uuid[])",
                [uuid_module.UUID(str(w)) for w in workflow_ids],
            )
        return {str(r["id"]): {"name": r["name"], "workflow": r["workflow"]} for r in rows}

    # ------------------------------------------------------------------
    # runs
    # ------------------------------------------------------------------

    @staticmethod
    def _window_start(days: int) -> datetime:
        today = datetime.now(timezone.utc).date()
        return datetime.combine(today - timedelta(days=days - 1), datetime.min.time(), tzinfo=timezone.utc)

    async def runs_window(self, workflow_ids: List[Any], *, days: int = 14) -> Dict[str, Any]:
        """The window's runs, bucketed per workflow per UTC day (zero-filled,
        oldest first), plus each workflow's latest run — and the same buckets
        summed per day for the chart. One aggregate scan serves both. Agent
        delivery runs are hidden plumbing (``DELIVERED_STATUS``) and never count."""
        if not workflow_ids:
            return {"by_day": self._zero_days(days), "by_workflow": []}
        start = self._window_start(days)
        ids = self._ids(workflow_ids)
        per_day_sql = f"""
            SELECT e.workflow_id, (e.started_at AT TIME ZONE 'UTC')::date AS day,
                   COUNT(*) FILTER (WHERE e.status <> 'error') AS ok,
                   COUNT(*) FILTER (WHERE e.status = 'error') AS failed
            FROM workflow_executions e
            WHERE e.workflow_id = ANY($1::uuid[]) AND e.started_at >= $2 AND e.{USER_VISIBLE_RUN_SQL}
            GROUP BY 1, 2
        """
        latest_sql = f"""
            SELECT DISTINCT ON (e.workflow_id) e.workflow_id, e.status, e.started_at
            FROM workflow_executions e
            WHERE e.workflow_id = ANY($1::uuid[]) AND e.started_at >= $2 AND e.{USER_VISIBLE_RUN_SQL}
            ORDER BY e.workflow_id, e.started_at DESC
        """
        async with self._pool.acquire() as conn:
            per_day = await conn.fetch(per_day_sql, ids, start)
            latest = await conn.fetch(latest_sql, ids, start)
        series: Dict[str, Dict[date, Tuple[int, int]]] = {}
        totals: Dict[date, Tuple[int, int]] = {}
        for r in per_day:
            ok, failed = int(r["ok"]), int(r["failed"])
            series.setdefault(str(r["workflow_id"]), {})[r["day"]] = (ok, failed)
            t = totals.get(r["day"], (0, 0))
            totals[r["day"]] = (t[0] + ok, t[1] + failed)
        latest_by_wf = {str(r["workflow_id"]): r for r in latest}
        by_workflow = []
        for wf_id, buckets in series.items():
            day_list = self._fill_days(start, days, buckets)
            last = latest_by_wf.get(wf_id)
            by_workflow.append({
                "workflow_id": wf_id,
                "runs": sum(b["ok"] + b["failed"] for b in day_list),
                "failed": sum(b["failed"] for b in day_list),
                "last_run_at": last["started_at"] if last else None,
                "last_status": (last["status"] if last else None),
                "days": day_list,
            })
        by_workflow.sort(key=lambda x: -x["runs"])
        return {"by_day": self._fill_days(start, days, totals), "by_workflow": by_workflow}

    @classmethod
    def _zero_days(cls, days: int) -> List[Dict[str, Any]]:
        return cls._fill_days(cls._window_start(days), days, {})

    @staticmethod
    def _fill_days(start: datetime, days: int, buckets: Dict[date, Tuple[int, int]]) -> List[Dict[str, Any]]:
        out = []
        for i in range(days):
            d: date = start.date() + timedelta(days=i)
            ok, failed = buckets.get(d, (0, 0))
            out.append({"date": d.isoformat(), "ok": ok, "failed": failed})
        return out

    async def recent_runs(self, workflow_ids: List[Any], *, days: int = 14, limit: int = 12) -> List[Dict[str, Any]]:
        """Newest runs in the window. Bounded to the window on purpose: an
        unbounded newest-N over many workflows has to fetch every run first."""
        if not workflow_ids:
            return []
        sql = f"""
            SELECT e.id, e.workflow_id, e.status, e.started_at, e.finished_at,
                   e.nodes_executed, e.error, e.trigger_source
            FROM workflow_executions e
            WHERE e.workflow_id = ANY($1::uuid[]) AND e.started_at >= $2 AND e.{USER_VISIBLE_RUN_SQL}
            ORDER BY e.started_at DESC, e.id DESC
            LIMIT $3
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, self._ids(workflow_ids), self._window_start(days), limit)
        return [dict(r) for r in rows]

    # A parked run older than this is not going to wake; the bound keeps the
    # status filter inside the index range instead of the workflows' whole history.
    _AWAITING_LOOKBACK_DAYS = 90

    async def awaiting_delay(self, workflow_ids: List[Any], *, limit: int = 20) -> List[Dict[str, Any]]:
        """Runs parked on a delay node — they resume at ``wake_at``."""
        if not workflow_ids:
            return []
        sql = """
            SELECT e.id, e.workflow_id, e.resume_node_id, e.wake_at
            FROM workflow_executions e
            WHERE e.workflow_id = ANY($1::uuid[]) AND e.started_at >= $2
              AND e.status = 'awaiting_delay' AND e.wake_at IS NOT NULL
            ORDER BY e.wake_at ASC
            LIMIT $3
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, self._ids(workflow_ids), self._window_start(self._AWAITING_LOOKBACK_DAYS), limit)
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # triggers
    # ------------------------------------------------------------------

    async def webhook_rows(self, workflow_ids: List[Any]) -> List[Dict[str, Any]]:
        if not workflow_ids:
            return []
        sql = """
            SELECT wh.id, wh.workflow_id, wh.node_id, wh.is_active, wh.registered_operation,
                   wh.registered_fingerprint, wh.last_triggered_at, wh.trigger_count
            FROM webhooks wh
            WHERE wh.workflow_id = ANY($1::uuid[])
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, self._ids(workflow_ids))
        return [dict(r) for r in rows]

    async def subscription_rows(self, workflow_ids: List[Any]) -> List[Dict[str, Any]]:
        if not workflow_ids:
            return []
        sql = """
            SELECT ws.workflow_id, ws.node_id, ws.provider, ws.event_type, ws.created_at
            FROM webhook_subscriptions ws
            WHERE ws.workflow_id = ANY($1::uuid[])
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, self._ids(workflow_ids))
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # attention sources without an existing repo method
    # ------------------------------------------------------------------

    async def pending_bridge_links(self, user_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
        sql = """
            SELECT id, workflow_id, builder_conversation_id, ask_id, agent_conversation_id,
                   agent_node_id, inputs, workflow_name, created_at, expires_at
            FROM builder_input_links
            WHERE user_id = $1::uuid AND status = 'pending' AND expires_at > NOW()
            ORDER BY created_at DESC
            LIMIT $2
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, user_id, limit)
        return [dict(r) for r in rows]

    async def unanswered_builder_prompts(self, user_id: str, *, limit: int = 20) -> List[Dict[str, Any]]:
        """``builder_prompt`` cards in the user's agent chats with no matching
        ``builder_decision`` — an agent asked for a builder edit and nobody answered.
        Bounded to recent conversations: ``events`` has no GIN index."""
        sql = """
            WITH ev AS (
                SELECT c.conversation_id, c.workflow_id, c.node_id, c.last_activity, e.value AS event
                FROM conversations c,
                     LATERAL jsonb_array_elements(c.events) AS e
                WHERE c.user_id = $1::uuid
                  AND c.deleted_at IS NULL
                  AND c.node_id IS NOT NULL
                  AND c.last_activity > NOW() - INTERVAL '30 days'
                  AND jsonb_typeof(c.events) = 'array'
                  AND c.events @> '[{"builder_prompt": {}}]'::jsonb
            ),
            props AS (
                SELECT conversation_id, workflow_id, node_id, last_activity,
                       event->'builder_prompt'->>'proposal_id' AS proposal_id,
                       event->'builder_prompt'->>'prompt' AS prompt,
                       event->'builder_prompt'->>'anchored_prompt' AS anchored_prompt,
                       event->'builder_prompt'->>'node_id' AS prompt_node_id,
                       event->>'timestamp' AS created_at
                FROM ev WHERE event ? 'builder_prompt'
            ),
            decs AS (
                SELECT conversation_id, event->'builder_decision'->>'proposal_id' AS proposal_id
                FROM ev WHERE event ? 'builder_decision'
            )
            SELECT p.* FROM props p
            WHERE p.proposal_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM decs d
                  WHERE d.conversation_id = p.conversation_id AND d.proposal_id = p.proposal_id
              )
            ORDER BY p.last_activity DESC
            LIMIT $2
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, user_id, limit)
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # agent conversations (workspace enumeration + running-agent titles)
    # ------------------------------------------------------------------

    async def agent_conversations(self, user_id: str, workflow_ids: List[Any], *, limit: int = 40) -> List[Dict[str, Any]]:
        """The user's agent threads on the scoped workflows, newest first. Modern
        rows carry ``node_id``; legacy ones are found by their ``ck:`` id.
        ``conversations.workflow_id`` is text, so the ids travel as text."""
        if not workflow_ids:
            return []
        sql = """
            SELECT c.conversation_id, c.workflow_id, c.node_id,
                   COALESCE(NULLIF(c.title, ''), LEFT(c.events->0->>'message', 100),
                            LEFT(c.events->0->'args'->>'content', 100), '') AS title,
                   c.agent_model, c.last_activity, c.created_at, c.turn_count
            FROM conversations c
            WHERE c.user_id = $1::uuid
              AND c.deleted_at IS NULL
              AND (c.node_id IS NOT NULL OR c.conversation_id LIKE 'ck:%')
              AND c.workflow_id = ANY($2::text[])
            ORDER BY c.last_activity DESC NULLS LAST
            LIMIT $3
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, user_id, [str(w) for w in workflow_ids], limit)
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # notifications
    # ------------------------------------------------------------------

    async def notifications(self, user_id: str, *, limit: int = 30) -> Tuple[List[Dict[str, Any]], int]:
        sql = """
            SELECT id, category, title, body, cta_text, cta_url, metadata,
                   suppressed_count, read_at, created_at
            FROM user_notifications
            WHERE user_id = $1::uuid
            ORDER BY created_at DESC
            LIMIT $2
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, user_id, limit)
            unread = await conn.fetchval(
                "SELECT COUNT(*) FROM user_notifications WHERE user_id = $1::uuid AND read_at IS NULL",
                user_id,
            )
        return [dict(r) for r in rows], int(unread or 0)

    async def mark_notifications_read(self, user_id: str, ids: Optional[List[str]]) -> int:
        """Mark the given notifications (or all of the user's) read. The
        ``user_id`` predicate is the authorization — the table has no RLS policies."""
        sql = """
            UPDATE user_notifications SET read_at = NOW()
            WHERE user_id = $1::uuid AND read_at IS NULL
              AND ($2::uuid[] IS NULL OR id = ANY($2::uuid[]))
        """
        id_list = [uuid_module.UUID(str(i)) for i in ids] if ids else None
        async with self._pool.acquire() as conn:
            status = await conn.execute(sql, user_id, id_list)
        try:
            return int(status.split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0

    # ------------------------------------------------------------------
    # files
    # ------------------------------------------------------------------

    async def resources(self, workflow_ids: List[Any], *, limit: int = 200) -> List[Dict[str, Any]]:
        """Workflow resources (uploads, attachments, node outputs) in scope."""
        if not workflow_ids:
            return []
        sql = """
            SELECT wr.id, wr.workflow_id, wr.node_id, wr.resource_type, wr.name, wr.mime_type,
                   wr.size_bytes, wr.storage_ref, wr.metadata, wr.created_at, wr.updated_at
            FROM workflow_resources wr
            WHERE wr.workflow_id = ANY($1::uuid[])
            ORDER BY wr.updated_at DESC
            LIMIT $2
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, self._ids(workflow_ids), limit)
        return [dict(r) for r in rows]
