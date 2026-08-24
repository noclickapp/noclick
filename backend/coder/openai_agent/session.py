"""Postgres-backed Session for the OpenAI Agents SDK.

Implements the SDK's ``agents.memory.Session`` protocol so
``Runner.run_streamed(..., session=session)`` can auto-prepend
conversation history and auto-write new items back. With this in
place the Agent wrapper drops its in-memory ``_history`` accumulator
in favor of a real durable store that survives container restarts.

Storage model
-------------
Items live in ``conversations.metadata.sdk_history`` (JSONB array on
the existing ``conversations`` table — no migration needed). The
existing ``conversations.events`` array is left untouched; it's the
chat UI's display log, which has a different shape (action/source/
args/message/timestamp) and a different lifecycle (the chat handler
writes those events directly when rendering).

Why two sources of truth?
  1. ``events`` is what the frontend's ``persistedEventsToChatMessages``
     consumes — changing its shape would break every chat history view.
  2. ``sdk_history`` stores raw ``TResponseInputItem`` dicts (the
     SDK's wire format). Keeping it separate means we don't have to
     convert back and forth on every read/write, and the SDK's
     ``Runner`` consumes its native shape directly.

The SDK ``Runner`` flow per call:
  1. ``await session.get_items()`` → prepend to current user input.
  2. Run the model + tool loop.
  3. ``await session.add_items(new_items)`` → persist the user
     message + assistant reply + any tool calls/outputs.

All four methods (``get_items``, ``add_items``, ``pop_item``,
``clear_session``) read/write the same JSONB array atomically via
``jsonb_set`` so concurrent runs on the same conversation don't lose
each other's writes.
"""
from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


# Conversations table → metadata column → key under which we stash
# raw SDK input items. Stable string; if you ever rename it, write a
# migration to move existing data.
_HISTORY_KEY = "sdk_history"


class PostgresSession:
    """Session protocol impl backed by ``conversations.metadata.sdk_history``.

    One instance per ``conversation_id``. Cheap to construct (no I/O until
    the first method call). Safe to reuse across many ``Runner.run_streamed``
    invocations.
    """

    # Required by the protocol. SDK reads it to identify the session.
    session_id: str
    session_settings: Optional[Any] = None

    def __init__(
        self,
        conversation_id: str,
        *,
        user_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> None:
        if not conversation_id:
            raise ValueError("PostgresSession requires conversation_id")
        self.session_id = conversation_id
        self._user_id = user_id
        self._workflow_id = workflow_id
        self._node_id = node_id

    # ------------------------------------------------------------------ #
    # SDK Session protocol
    # ------------------------------------------------------------------ #
    async def get_items(self, limit: int | None = None) -> List[dict]:
        """Return the latest N items (or all) in chronological order."""
        from utils.database_pool import get_native_pool
        row = await get_native_pool().fetchrow(
            "SELECT metadata FROM conversations WHERE conversation_id = $1",
            self.session_id,
        )
        if not row:
            return []
        from .output_limits import clip_history_item

        # Bound stored tool outputs on replay: one oversized item (pre-cap
        # execute_bash rows) otherwise kills EVERY subsequent turn on the
        # provider's context limit — the conversation heals instead of
        # staying bricked. Read-side only; the stored row is untouched.
        items = [clip_history_item(it) for it in _extract_history(row["metadata"])]
        if limit is not None and limit < len(items):
            return items[-limit:]
        return items

    async def add_items(self, items: List[dict]) -> None:
        """Append new items to the history (creating the row if needed)."""
        if not items:
            return

        # Strip non-portable fields the SDK injects (matches what
        # OpenAIConversationsSession does — id/provider_data don't round-trip
        # across providers so dropping them keeps the history portable).
        cleaned = [_strip_runtime_fields(it) for it in items]

        # asyncpg has a JSON codec installed on the pool (set by the
        # database_pool module), so we pass the Python list directly —
        # asyncpg encodes it to JSONB inline. ``json.dumps``-ing first
        # double-encodes and the column ends up storing each batch as a
        # single string element instead of a flat list of items.
        # Concat happens server-side via ``||`` so concurrent runs each
        # see the prior writes.
        from utils.database_pool import get_native_pool
        await get_native_pool().execute(
            f"""
            INSERT INTO conversations (conversation_id, user_id, workflow_id, node_id, metadata)
            VALUES ($1, $2, $3, $4,
                    jsonb_build_object('{_HISTORY_KEY}', $5::jsonb))
            ON CONFLICT (conversation_id) DO UPDATE SET
                metadata = jsonb_set(
                    COALESCE(conversations.metadata, '{{}}'::jsonb),
                    '{{{_HISTORY_KEY}}}',
                    COALESCE(conversations.metadata->'{_HISTORY_KEY}', '[]'::jsonb) || $5::jsonb,
                    true
                ),
                last_activity = NOW(),
                deleted_at = NULL
            """,
            self.session_id,
            self._user_id,
            self._workflow_id,
            self._node_id,
            cleaned,
        )

    async def pop_item(self) -> Optional[dict]:
        """Remove and return the most recent item, or None if empty.

        Wrapped in a CTE so the pre-update last-element is captured
        BEFORE the UPDATE rewrites the row. Without the CTE the
        RETURNING clause would see the post-update metadata and we'd
        return the second-to-last element instead of the popped one.
        """
        from utils.database_pool import get_native_pool
        row = await get_native_pool().fetchrow(
            f"""
            WITH old AS (
                SELECT metadata->'{_HISTORY_KEY}'->-1 AS popped,
                       jsonb_array_length(metadata->'{_HISTORY_KEY}') AS prev_len
                FROM conversations
                WHERE conversation_id = $1
                  AND metadata->'{_HISTORY_KEY}' IS NOT NULL
                  AND jsonb_array_length(metadata->'{_HISTORY_KEY}') > 0
            )
            UPDATE conversations
            SET metadata = jsonb_set(
                COALESCE(metadata, '{{}}'::jsonb),
                '{{{_HISTORY_KEY}}}',
                COALESCE(
                    (SELECT jsonb_agg(elem ORDER BY ord)
                       FROM jsonb_array_elements(metadata->'{_HISTORY_KEY}')
                            WITH ORDINALITY AS t(elem, ord)
                       WHERE ord < (SELECT prev_len FROM old)),
                    '[]'::jsonb
                ),
                true
            )
            WHERE conversation_id = $1
              AND EXISTS (SELECT 1 FROM old)
            RETURNING (SELECT popped FROM old) AS popped
            """,
            self.session_id,
        )
        if not row:
            return None
        return _decode_jsonb(row["popped"])

    async def clear_session(self) -> None:
        """Wipe all items for this session (does NOT delete the row)."""
        from utils.database_pool import get_native_pool
        await get_native_pool().execute(
            f"""
            UPDATE conversations
            SET metadata = jsonb_set(
                COALESCE(metadata, '{{}}'::jsonb),
                '{{{_HISTORY_KEY}}}',
                '[]'::jsonb,
                true
            )
            WHERE conversation_id = $1
            """,
            self.session_id,
        )


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #
def _extract_history(metadata: Any) -> List[dict]:
    """Pull the sdk_history array out of a conversations.metadata cell."""
    if metadata is None:
        return []
    decoded = _decode_jsonb(metadata)
    if not isinstance(decoded, dict):
        return []
    items = decoded.get(_HISTORY_KEY) or []
    if not isinstance(items, list):
        return []
    return items


def _decode_jsonb(value: Any) -> Any:
    """asyncpg returns JSONB either as a Python object (when the JSON codec
    is set) or as a raw string. Handle both."""
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            logger.warning("[session] could not decode JSONB string: %r", value[:200])
            return None
    return value


def _strip_runtime_fields(item: dict) -> dict:
    """Drop fields the SDK injects that don't round-trip across providers.

    Mirrors what ``OpenAIConversationsSession`` does internally: ``id``
    and ``provider_data`` are tied to a specific provider's response;
    a chat that switches from OpenAI to Anthropic mid-conversation
    would break if we replayed them as-is.
    """
    if not isinstance(item, dict):
        return item
    return {k: v for k, v in item.items() if k not in ("id", "provider_data")}
