"""An agent's model history, one row per item (``conversation_history_items``).

The SDK's input items of a conversation (``coder/openai_agent/session.py``) were one JSON array in
``conversations.metadata.sdk_history``, which every append rewrote whole: megabytes of writes per turn
for a long thread. Here each item is a row, a conversation's in order of ``id``, so an append writes
only what it adds and a replay can read only the tail.

Every function takes a connection inside the caller's transaction, after the caller has taken the
conversation's row (each one updates or inserts it first): that lock is what keeps two appends to one
conversation from interleaving.

While the move is under way, every write of ``sdk_history`` also lands here, and reads still come from
the key; ``scripts/backfill_conversation_history.py`` copies each history written before.
"""
from typing import Any, List, Optional


async def append(conn, conversation_id: str, items: List[Any]) -> None:
    """``items`` after the conversation's history, in their order."""
    if not items:
        return
    await conn.execute(
        """INSERT INTO conversation_history_items (conversation_id, item)
           SELECT $1, item FROM jsonb_array_elements($2::jsonb) WITH ORDINALITY AS a(item, n) ORDER BY n""",
        conversation_id, items)


async def clear(conn, conversation_id: str) -> None:
    await conn.execute("DELETE FROM conversation_history_items WHERE conversation_id = $1", conversation_id)


async def replace(conn, conversation_id: str, items: List[Any]) -> None:
    """The conversation's history becomes ``items``."""
    await clear(conn, conversation_id)
    await append(conn, conversation_id, items)


async def pop(conn, conversation_id: str) -> Optional[Any]:
    """Remove the conversation's last item and return it."""
    return await conn.fetchval(
        """DELETE FROM conversation_history_items WHERE conversation_id = $1
             AND id = (SELECT max(id) FROM conversation_history_items WHERE conversation_id = $1)
           RETURNING item""", conversation_id)


async def append_from(conn, source: str, target: str) -> None:
    """``source``'s history after ``target``'s (a copied or merged thread)."""
    await conn.execute(
        """INSERT INTO conversation_history_items (conversation_id, item)
           SELECT $2, item FROM conversation_history_items WHERE conversation_id = $1 ORDER BY id""",
        source, target)


async def read(conn, conversation_id: str) -> List[Any]:
    rows = await conn.fetch(
        "SELECT item FROM conversation_history_items WHERE conversation_id = $1 ORDER BY id", conversation_id)
    return [r["item"] for r in rows]
