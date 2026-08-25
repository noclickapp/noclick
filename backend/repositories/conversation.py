"""ConversationRepo — SQL for the ``conversations`` table.

Owns every read/write against ``conversations`` across the interactive chat
agent (``agent_handler``) and the AI workflow builder (``workflow_builder_handler``).

Tables in scope: ``conversations`` only. ``sdk_history`` writes in
``PostgresSession`` are also out of scope.

Rows are converted to ``dict`` at the repo boundary so ``asyncpg.Record``
never leaks. Reads that fetch the ``events`` JSONB column normalize
possibly-double-encoded values (older rows can carry a JSON string wrapped
in a string) via ``_normalize_events``.

SQL text is preserved verbatim from the source handlers so any tests
asserting on the exact SQL shape stay green.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _normalize_events(value: Any) -> List[Dict[str, Any]]:
    """Coerce a ``conversations.events`` cell to a Python list.

    The pool's JSONB codec normally returns Python objects. Rows written
    before the codec fix (or through raw SQL) may be JSON strings; peel
    once and fall back to ``[]`` on shape mismatch.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    return value if isinstance(value, list) else []


class ConversationRepo:
    """SQL for the ``conversations`` domain.

    Constructor takes a pool from ``DatabasePoolMixin.get_pool()`` or the
    native asyncpg pool. Every method acquires a pinned connection for the
    duration of its work; multi-statement writes wrap in a real transaction
    so BEGIN/COMMIT/ROLLBACK fire (see ``backend/utils/DB_MIGRATION.md``).
    """

    def __init__(self, pool):
        self._pool = pool

    # ══════════════════════════════════════════════════════════════════════
    # Reads
    # ══════════════════════════════════════════════════════════════════════

    async def get_events_active(
        self, conversation_id: str, user_id: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """Events for an active (non-soft-deleted) conversation.

        Used by ``_load_conversation_history`` — filters ``deleted_at IS
        NULL`` so a resumed edit on a deleted row returns None. Returns
        None when the row is missing; returns an empty list when the row
        exists but ``events`` is null / not a list.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT events FROM conversations
                WHERE conversation_id = $1 AND user_id = $2 AND deleted_at IS NULL
                """,
                conversation_id, user_id,
            )
        if row is None:
            return None
        return _normalize_events(row["events"])

    async def read_events(
        self, conversation_id: str, user_id: str,
    ) -> List[Dict[str, Any]]:
        """Events for a conversation, ignoring the ``deleted_at`` flag.

        Backs ``_read_conversation_events``, which is called on the save
        path where we always want the current row's events (even for a
        row a delete may be racing with). Returns ``[]`` when the row is
        missing.

        NB: uses ``::text`` casts on both sides — matches the original
        query so callers can pass string ids for UUID columns without a
        codec mismatch.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT events FROM conversations "
                "WHERE conversation_id::text = $1::text AND user_id::text = $2::text",
                conversation_id, user_id,
            )
        if row is None:
            return []
        return _normalize_events(row["events"])

    async def get_workflow_id(
        self, conversation_id: str, user_id: str,
    ) -> Optional[str]:
        """Return the ``workflow_id`` (as text) for a conversation, or None.

        Used by ``_handle_input_response_impl`` to look up the workflow
        the paused conversation belongs to. Preserves the ``::text`` casts
        the original query relied on.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT workflow_id::text AS wfid FROM conversations "
                "WHERE conversation_id::text = $1::text AND user_id::text = $2::text",
                conversation_id, user_id,
            )
        return row["wfid"] if row else None

    async def list_builder_conversations(
        self, user_id: str, *, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Builder-chat conversations for the current user (node_id IS NULL).

        Backs ``handle_list_conversations``. Rows include the app-context
        (``app_id``, ``app_name``) columns the FE sidebar renders.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT conversation_id, title, preview, last_activity, created_at,
                       app_id, app_name
                FROM conversations
                WHERE user_id = $1
                  AND deleted_at IS NULL
                  AND node_id IS NULL
                ORDER BY last_activity DESC
                LIMIT $2
                """,
                user_id, limit,
            )
        return [dict(r) for r in rows]

    async def get_for_resume(
        self, conversation_id: str, user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch (events, workflow_id) for the resume endpoint.

        Backs ``handle_resume_conversation`` — soft-deleted rows are hidden
        so a delete during a paused-conversation session doesn't accidentally
        rehydrate the ask drawer.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    c.events,
                    c.workflow_id::text AS workflow_id,
                    c.node_id
                FROM conversations c
                WHERE c.conversation_id::text = $1::text
                  AND c.user_id::text = $2::text
                  AND c.deleted_at IS NULL
                """,
                conversation_id, user_id,
            )
        if row is None:
            return None
        return {
            "events": _normalize_events(row["events"]),
            "workflow_id": row["workflow_id"],
            "node_id": row["node_id"],
        }

    async def list_recent_for_workflow(
        self, user_id: str, workflow_id: str, *, limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Top-N builder-chat conversations for a workflow, most recent first.

        Backs ``handle_get_latest_for_workflow``. Caller walks the candidates
        with a priority function (pending_ask > has-messages > most-recent).
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    c.conversation_id,
                    c.events,
                    c.pending_ask
                FROM conversations c
                WHERE c.user_id::text = $1::text
                  AND c.deleted_at IS NULL
                  AND c.workflow_id::text = $2::text
                  AND c.node_id IS NULL
                ORDER BY c.last_activity DESC
                LIMIT $3
                """,
                user_id, workflow_id, limit,
            )
        return [dict(r) for r in rows]

    async def list_pending_asks(
        self, user_id: str, workflow_id: Optional[str], *, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Conversations paused on an ``<ask/>`` for the current user.

        Uses the denormalized ``pending_ask`` column (fast index lookup via
        ``idx_conversations_paused``) — backs ``handle_list_pending``.

        The optional ``workflow_id`` filter is applied through a static
        SQL fragment (no user input) so parameter numbering stays stable
        between the two variants.
        """
        # Static fragment — no user-derived text is interpolated. The
        # filter is present iff `workflow_id` is provided, and we number
        # the extra parameter into $2 to keep the LIMIT in $3.
        if workflow_id is not None:
            sql = """
                SELECT
                    conversation_id,
                    workflow_id::text AS workflow_id,
                    pending_ask,
                    turn_count,
                    last_activity
                FROM conversations
                WHERE user_id::text = $1::text
                  AND deleted_at IS NULL
                  AND pending_ask IS NOT NULL
                  AND node_id IS NULL
                  AND workflow_id::text = $2::text
                ORDER BY last_activity DESC
                LIMIT $3
            """
            params: List[Any] = [user_id, workflow_id, limit]
        else:
            sql = """
                SELECT
                    conversation_id,
                    workflow_id::text AS workflow_id,
                    pending_ask,
                    turn_count,
                    last_activity
                FROM conversations
                WHERE user_id::text = $1::text
                  AND deleted_at IS NULL
                  AND pending_ask IS NOT NULL
                  AND node_id IS NULL
                ORDER BY last_activity DESC
                LIMIT $2
            """
            params = [user_id, limit]

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def list_for_agent(
        self,
        user_id: str,
        workflow_id: str,
        node_id: str,
        ck_prefix_like: str,
        *,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Every conversation belonging to ``user_id`` that's scoped to a
        specific AgentChatBlock (``workflow_id``/``node_id``).

        Backs ``handle_list_conversations_for_agent`` — union of the
        ``workflow_id/node_id`` columns (newer rows) and the legacy
        ``conversation_id LIKE 'ck:{wf}:{node}:%'`` pattern (older rows).
        Caller passes the LIKE pattern already suffixed with ``'%'``.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT conversation_id,
                       COALESCE(
                           NULLIF(title, ''),
                           LEFT(events->0->>'message', 100),
                           LEFT(events->0->'args'->>'content', 100),
                           ''
                       ) AS title,
                       COALESCE(
                           NULLIF(preview, ''),
                           LEFT(events->0->>'message', 100),
                           LEFT(events->0->'args'->>'content', 100),
                           ''
                       ) AS preview,
                       agent_model,
                       last_activity, created_at, turn_count
                FROM conversations
                WHERE user_id = $1
                  AND deleted_at IS NULL
                  AND (
                    (workflow_id = $2 AND node_id = $3)
                    OR conversation_id LIKE $4
                  )
                ORDER BY last_activity DESC NULLS LAST
                LIMIT $5
                """,
                user_id, workflow_id, node_id, ck_prefix_like, limit,
            )
        return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════════════════════════
    # Writes
    # ══════════════════════════════════════════════════════════════════════

    async def append_event_if_user_tail(
        self,
        conversation_id: str,
        event: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> bool:
        """Append one event ONLY IF the conversation's newest event is still a
        user turn — the atomic tail guard the lost-turn resolvers rely on: a
        reply (or a concurrent heal) that landed first flips the tail, so this
        write loses cleanly instead of stacking a stale "interrupted" bubble
        after a real response.

        ``user_id=None`` is a system write (internal turn-loss reconciler —
        access was verified when the turn was accepted); pass it on
        caller-facing paths for scope safety. Returns True iff the row was
        appended."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE conversations
                SET events = COALESCE(events, '[]'::jsonb) || $2::jsonb,
                    last_activity = NOW()
                WHERE conversation_id::text = $1::text
                  AND ($3::text IS NULL OR user_id::text = $3::text)
                  AND deleted_at IS NULL
                  AND jsonb_typeof(events) = 'array'
                  AND events->-1->>'role' = 'user'
                """,
                conversation_id, [event], user_id,
            )
        return result == "UPDATE 1"

    async def ensure_stub(
        self,
        conversation_id: str,
        user_id: str,
        prompt: str,
        workflow_id: Optional[str] = None,
    ) -> None:
        """Guarantee a stub conversation row exists for a new builder edit.

        Idempotent: if the row already exists, only ``last_activity`` (and
        ``workflow_id`` if previously null) are touched. Paused runs that
        never reach ``_finalize_run_complete``'s save still show up in the
        chat history dropdown thanks to this stub.
        """
        title = (prompt or "Workflow Edit")[:50]
        preview = (prompt or "")[:100]
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO conversations (conversation_id, user_id, workflow_id, title, preview, events, created_at, last_activity)
                VALUES ($1, $2, $3, $4, $5, '[]'::jsonb, NOW(), NOW())
                ON CONFLICT (conversation_id) DO UPDATE SET
                    workflow_id = COALESCE(conversations.workflow_id, EXCLUDED.workflow_id),
                    last_activity = NOW()
                """,
                conversation_id, user_id, workflow_id, title, preview,
            )

    async def upsert_events(
        self,
        conversation_id: str,
        user_id: str,
        workflow_id: Optional[str],
        title: str,
        preview: str,
        events: List[Dict[str, Any]],
        pending_ask: Optional[Dict[str, Any]],
        cost_delta: float,
        token_delta: int,
        turn_delta: int,
    ) -> None:
        """Full replace of ``events`` plus additive billing accumulator bumps.

        Backs ``_save_conversation``. On INSERT we set title/preview from
        the first user message; on UPDATE we set the JSONB blob fresh
        (caller already merged existing + new_messages), bump the three
        counters additively, and refresh ``pending_ask``.

        ``workflow_id`` is coalesced on UPDATE so a later save can't
        clobber a value set by an earlier one; ``title`` on UPDATE stays
        put because the first-turn's title is the one the user sees in
        history.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO conversations (
                    conversation_id, user_id, workflow_id, title, preview,
                    events, pending_ask, total_cost, total_tokens, turn_count,
                    created_at, last_activity
                )
                VALUES (
                    $1, $2, $3, $4, $5,
                    $6::jsonb, $7::jsonb, $8, $9, $10,
                    NOW(), NOW()
                )
                ON CONFLICT (conversation_id) DO UPDATE SET
                    workflow_id  = COALESCE(conversations.workflow_id, EXCLUDED.workflow_id),
                    events       = $6::jsonb,
                    preview      = $5,
                    pending_ask  = $7::jsonb,
                    total_cost   = conversations.total_cost   + $8,
                    total_tokens = conversations.total_tokens + $9,
                    turn_count   = conversations.turn_count   + $10,
                    last_activity = NOW()
                """,
                conversation_id, user_id, workflow_id, title, preview,
                events, pending_ask,
                cost_delta, token_delta, turn_delta,
            )

    async def record_mcp_delivery(
        self,
        conversation_id: str,
        *,
        last_delivery: Dict[str, Any],
        failure_entry: Optional[Dict[str, Any]],
        max_failures: int = 20,
    ) -> None:
        """Stamp a turn's MCP-delivery telemetry onto ``conversations.metadata``:
        overwrite ``last_mcp_delivery`` and, when ``failure_entry`` is non-None (the
        tools didn't fully land), append it to the bounded ``mcp_delivery_failures``
        list (newest last, trimmed to ``max_failures``). UPDATE-only — the row is
        created by the message persist that runs first, so a missing row no-ops
        (telemetry still lands in the span). ``jsonb`` params are passed as Python
        objects (the pool's JSONB codec encodes them — never ``json.dumps`` first).
        """
        failures_param = [failure_entry] if failure_entry is not None else None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                WITH cur AS (
                    SELECT COALESCE(metadata->'mcp_delivery_failures', '[]'::jsonb) AS failures
                    FROM conversations WHERE conversation_id::text = $1::text
                ),
                appended AS (
                    SELECT CASE WHEN $3::jsonb IS NULL THEN (SELECT failures FROM cur)
                                ELSE (SELECT failures FROM cur) || $3::jsonb END AS arr
                ),
                trimmed AS (
                    SELECT COALESCE(jsonb_agg(elem ORDER BY ord), '[]'::jsonb) AS arr
                    FROM jsonb_array_elements((SELECT arr FROM appended))
                         WITH ORDINALITY AS t(elem, ord)
                    WHERE ord > (SELECT jsonb_array_length((SELECT arr FROM appended))) - $4
                )
                UPDATE conversations
                SET metadata = jsonb_set(
                        jsonb_set(COALESCE(metadata, '{}'::jsonb),
                                  '{last_mcp_delivery}', $2::jsonb, true),
                        '{mcp_delivery_failures}', (SELECT arr FROM trimmed), true
                    ),
                    last_activity = NOW()
                WHERE conversation_id::text = $1::text
                """,
                conversation_id, last_delivery, failures_param, max_failures,
            )

    async def soft_delete(
        self, conversation_id: str, user_id: str,
    ) -> Optional[str]:
        """Soft-delete a conversation. Returns the conversation_id if the
        UPDATE hit a row (owner-gated + not-already-deleted), else None.

        Backs ``handle_delete_conversation`` — the caller uses the presence
        of the return value to distinguish "deleted" from "not found".
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE conversations SET deleted_at = NOW()
                WHERE conversation_id = $1 AND user_id = $2 AND deleted_at IS NULL
                RETURNING conversation_id
                """,
                conversation_id, user_id,
            )
        return row["conversation_id"] if row else None

    # ──────────────────────────────────────────────────────────────────────
    # Chat-agent path (agent_handler)
    # ──────────────────────────────────────────────────────────────────────

    # Single UPSERT used by every chat-side persist (user message, agent
    # response, terminal error). Same wire shape OpenHands' PostgresStore
    # emitted, so ``persistedEventsToChatMessages`` on the frontend keeps
    # working unchanged. ``title``/``preview`` are locked on the first
    # non-empty write via ``COALESCE(NULLIF(..., ''), ...)`` so they always
    # reflect the user's opening message, not a later assistant reply.
    _UPSERT_CHAT_EVENT_SQL = """
        INSERT INTO conversations (
            conversation_id, user_id, workflow_id, node_id,
            events, title, preview, agent_model,
            created_at, last_activity
        )
        VALUES ($1, $2, $3, $4, $5, $6, $6, $7, NOW(), NOW())
        ON CONFLICT (conversation_id) DO UPDATE
        SET events = COALESCE(conversations.events, '[]'::jsonb) || EXCLUDED.events,
            last_activity = NOW(),
            deleted_at = NULL,
            workflow_id = COALESCE(conversations.workflow_id, EXCLUDED.workflow_id),
            node_id = COALESCE(conversations.node_id, EXCLUDED.node_id),
            title = COALESCE(NULLIF(conversations.title, ''), EXCLUDED.title),
            preview = COALESCE(NULLIF(conversations.preview, ''), EXCLUDED.preview),
            agent_model = COALESCE(conversations.agent_model, EXCLUDED.agent_model)
    """

    async def append_chat_event(
        self,
        *,
        conversation_id: str,
        user_id: str,
        workflow_id: Optional[str],
        node_id: Optional[str],
        event: Dict[str, Any],
        label: Optional[str],
        model: Optional[str],
    ) -> None:
        """Append one chat event (user message, agent response, terminal
        error) to a conversation's ``events`` array.

        Backs ``agent_handler._persist_chat_event`` and ``_persist_chat_error``.
        Passes the event wrapped in a single-element list so the ON CONFLICT
        concatenation appends exactly one JSONB element per call.

        ``label`` is only non-null on the first user message in a
        conversation; the COALESCE guards lock title/preview to that first
        write, so later calls with ``label=None`` leave them alone.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                self._UPSERT_CHAT_EVENT_SQL,
                conversation_id,
                user_id,
                workflow_id,
                node_id,
                [event],
                label,
                model,
            )

    # Builder outcome events relayed to the agent's next turn: the kind key on
    # the event object → the payload field that identifies it for exactly-once
    # marking. builder_decision predates the generic relay and keys on its
    # proposal_id; the later kinds carry an explicit relay_id.
    _BUILDER_EVENT_KINDS: Dict[str, str] = {
        "builder_decision": "proposal_id",
        "builder_ask": "relay_id",
        "builder_result": "relay_id",
    }

    async def fetch_unrelayed_builder_events(
        self, conversation_id: str
    ) -> List[Dict[str, Any]]:
        """Builder outcome events (verdicts, parked-ask bridge links, run
        results) not yet relayed to the agent — consumed by
        ``AgentNode._relay_builder_updates`` when composing the next turn.
        Returns ``[{kind, payload}]`` in event order."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT e.value AS event
                FROM conversations, jsonb_array_elements(events) WITH ORDINALITY e
                WHERE conversation_id = $1
                  AND (e.value ?| $2::text[])
                ORDER BY e.ordinality
                """,
                conversation_id,
                list(self._BUILDER_EVENT_KINDS),
            )
        out: List[Dict[str, Any]] = []
        for r in rows:
            ev = r["event"]
            if isinstance(ev, str):
                import json

                ev = json.loads(ev)
            for kind in self._BUILDER_EVENT_KINDS:
                payload = ev.get(kind)
                if isinstance(payload, dict) and not payload.get("relayed"):
                    out.append({"kind": kind, "payload": payload})
        return out

    async def mark_builder_events_relayed(
        self, conversation_id: str, relay_keys: List[tuple]
    ) -> None:
        """Stamp ``relayed: true`` on the given ``(kind, id)`` events so each
        outcome is delivered to the agent exactly once."""
        if not relay_keys:
            return
        ids_by_kind: Dict[str, List[str]] = {}
        for kind, rid in relay_keys:
            if kind in self._BUILDER_EVENT_KINDS and rid:
                ids_by_kind.setdefault(kind, []).append(str(rid))
        if not ids_by_kind:
            return
        async with self._pool.acquire() as conn:
            for kind, ids in ids_by_kind.items():
                id_field = self._BUILDER_EVENT_KINDS[kind]
                await conn.execute(
                    f"""
                    UPDATE conversations SET events = (
                        SELECT COALESCE(jsonb_agg(
                            CASE WHEN e.value ? '{kind}'
                                      AND (e.value->'{kind}'->>'{id_field}') = ANY($2::text[])
                                 THEN jsonb_set(e.value, '{{{kind},relayed}}', 'true'::jsonb)
                                 ELSE e.value END
                            ORDER BY e.ordinality), '[]'::jsonb)
                        FROM jsonb_array_elements(events) WITH ORDINALITY e
                    )
                    WHERE conversation_id = $1 AND events IS NOT NULL
                    """,
                    conversation_id,
                    ids,
                )

    async def update_app_context(
        self,
        *,
        conversation_id: str,
        user_id: str,
        app_id: Optional[str],
        app_name: Optional[str],
    ) -> None:
        """Update the app context (``app_id``/``app_name``) on a chat
        conversation and bump ``last_activity``.

        Backs ``agent_handler.handle_set_cwd`` — user-scoped so a
        collaborator can't retag another user's chat.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE conversations
                SET app_id = $1, app_name = $2, last_activity = now()
                WHERE conversation_id = $3 AND user_id = $4
                """,
                app_id, app_name, conversation_id, user_id,
            )
