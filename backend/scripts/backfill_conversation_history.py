"""Copy each conversation's model history into ``conversation_history_items``.

An agent's model history was one JSON array in ``conversations.metadata.sdk_history``; it now also
lives one row per item (``repositories/conversation_history.py``), and reads move there once every
history is copied. Run this after the deploy that writes both: it copies, conversation by
conversation, the history the key holds, replacing what the table has for it (a history whose first
items were written before that deploy). Each copy takes the conversation's row first, as every writer
does, so a turn appending meanwhile waits and lands after it. The copy happens in the database; no
history passes through this process. Safe to run again.

Dry run by default (counts what it would copy). ``--verify`` compares both for every conversation.

    BACKFILL_POSTGRES_URL=postgres://… python -u scripts/backfill_conversation_history.py
    BACKFILL_POSTGRES_URL=postgres://… python -u scripts/backfill_conversation_history.py --apply
    BACKFILL_POSTGRES_URL=postgres://… python -u scripts/backfill_conversation_history.py --verify
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import asyncpg

PAGE = 200

IDS_SQL = """
    SELECT conversation_id FROM conversations
     WHERE metadata ? 'sdk_history' AND conversation_id > $1
     ORDER BY conversation_id LIMIT $2"""

HISTORY = "CASE WHEN jsonb_typeof(c.metadata->'sdk_history') = 'array' THEN c.metadata->'sdk_history' ELSE '[]' END"

COUNT_SQL = f"SELECT jsonb_array_length({HISTORY}) FROM conversations c WHERE c.conversation_id = $1"

LOCK_SQL = "SELECT 1 FROM conversations WHERE conversation_id = $1 FOR UPDATE"

COPY_SQL = f"""
    INSERT INTO conversation_history_items (conversation_id, item)
    SELECT c.conversation_id, a.item FROM conversations c, jsonb_array_elements({HISTORY}) WITH ORDINALITY AS a(item, n)
     WHERE c.conversation_id = $1 ORDER BY a.n"""

# A conversation whose rows aren't its key's history, item for item, in order.
DIFFERS_SQL = f"""
    SELECT c.conversation_id FROM conversations c
     WHERE c.conversation_id = ANY($1::text[])
       AND {HISTORY} IS DISTINCT FROM COALESCE(
           (SELECT jsonb_agg(i.item ORDER BY i.id) FROM conversation_history_items i
             WHERE i.conversation_id = c.conversation_id), '[]')"""

# Rows for a conversation whose key holds no history.
STRAY_SQL = """
    SELECT DISTINCT i.conversation_id FROM conversation_history_items i JOIN conversations c USING (conversation_id)
     WHERE NOT (c.metadata ? 'sdk_history')"""


async def copy(conn, conversation_id: str) -> int:
    async with conn.transaction():
        if not await conn.fetchval(LOCK_SQL, conversation_id):
            return 0
        await conn.execute("DELETE FROM conversation_history_items WHERE conversation_id = $1", conversation_id)
        status = await conn.execute(COPY_SQL, conversation_id)
    return int(status.split()[-1])


async def pages(conn):
    cursor = ""
    while True:
        page = [r["conversation_id"] for r in await conn.fetch(IDS_SQL, cursor, PAGE)]
        if not page:
            return
        yield page
        cursor = page[-1]


async def run(conn, *, apply: bool, verify: bool) -> dict:
    stats = {"conversations": 0, "items": 0, "differ": 0}
    started = time.time()
    async for page in pages(conn):
        stats["conversations"] += len(page)
        if verify:
            differ = [r["conversation_id"] for r in await conn.fetch(DIFFERS_SQL, page)]
            stats["differ"] += len(differ)
            for conversation_id in differ:
                print(f"differs: {conversation_id}")
            continue
        for conversation_id in page:
            stats["items"] += await copy(conn, conversation_id) if apply else (
                await conn.fetchval(COUNT_SQL, conversation_id) or 0)
        print(f"{stats['conversations']} conversations, {stats['items']} items, {time.time() - started:.0f}s",
              flush=True)
    if verify:
        stray = [r["conversation_id"] for r in await conn.fetch(STRAY_SQL)]
        stats["stray"] = len(stray)
        for conversation_id in stray:
            print(f"rows without a key: {conversation_id}")
    return stats


async def main() -> None:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="copy (default: count what would be copied)")
    mode.add_argument("--verify", action="store_true", help="compare the table with the key for every conversation")
    args = ap.parse_args()

    url = os.environ.get("BACKFILL_POSTGRES_URL")
    if not url:
        sys.exit("BACKFILL_POSTGRES_URL is required")
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        await conn.execute("SET statement_timeout = 0")
        stats = await run(conn, apply=args.apply, verify=args.verify)
    finally:
        await conn.close()
    print(stats)
    if args.verify and (stats["differ"] or stats.get("stray")):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
