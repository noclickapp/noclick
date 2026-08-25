"""Cache-tier resume checkpoints for the AI builder.

A checkpoint records, for one conversation's in-flight turn, the brain's parsed
plan (the XmlOps) plus which nodes have already finished node drafting. An
interrupted run (container drained/killed mid-stream — the 2026-06-17 shape)
can then resume PAST the brain: replay the plan (idempotent) and run node drafting
only for the nodes not yet completed, instead of re-running the ~50s brain turn
and rebuilding nodes that already exist.

It is deliberately CACHE-tier, not a system-of-record:
  - Stored in Redis with a short TTL (resume happens seconds-to-minutes after
    an interruption; the TTL just bounds staleness).
  - Every operation is best-effort — a missing checkpoint (never written,
    expired, evicted, or Redis unavailable) makes resume fall back to a full
    re-run. So the checkpoint is a pure optimization and NEVER a correctness
    dependency, which is exactly why cache-tier storage is appropriate.

Layout (two keys per conversation, both TTL'd):
  builder:resume:{cid}:plan  → JSON {turn, prompt, ops:[{tag,attrs,body}]}
  builder:resume:{cid}:done  → Redis SET of completed node ids (SADD is atomic,
                               so the per-node cursor needs no read-modify-write)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)

# Resume fires within seconds/minutes of an interruption; a day is plenty and
# bounds how long an abandoned plan lingers.
CHECKPOINT_TTL_SECONDS = 24 * 60 * 60

_CLIENT: Optional[redis.Redis] = None
_CLIENT_INITED = False


def _client() -> Optional[redis.Redis]:
    """Lazily build (and cache) the async Redis client, or None if unavailable.

    Returning None on any failure is what makes the whole module graceful: callers
    no-op and resume degrades to a full re-run. Monkeypatched in tests.
    """
    global _CLIENT, _CLIENT_INITED
    if _CLIENT_INITED:
        return _CLIENT
    _CLIENT_INITED = True
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        _CLIENT = redis.from_url(url, decode_responses=True)
    except Exception as e:
        logger.debug(f"[resume_checkpoint] Redis unavailable: {e}")
        _CLIENT = None
    return _CLIENT


def _plan_key(conversation_id: str) -> str:
    return f"builder:resume:{conversation_id}:plan"


def _done_key(conversation_id: str) -> str:
    return f"builder:resume:{conversation_id}:done"


def _attempt_key(conversation_id: str) -> str:
    return f"builder:attempt:{conversation_id}"


def _serialize_op(op: Any) -> dict:
    """Accept an XmlOp (tag/attrs/body) or an already-shaped dict."""
    if isinstance(op, dict):
        return {"tag": op.get("tag"), "attrs": dict(op.get("attrs") or {}), "body": op.get("body")}
    return {"tag": op.tag, "attrs": dict(op.attrs or {}), "body": op.body}


async def save_plan(conversation_id: Optional[str], *, turn: int, prompt: str, ops: list) -> None:
    """Persist the brain's plan for a turn. Resets the completed-node cursor.

    Called at the ops_parsed boundary. Best-effort: any failure is swallowed —
    a run with no checkpoint just re-runs the brain on resume.
    """
    if not conversation_id:
        return
    client = _client()
    if client is None:
        return
    payload = json.dumps({
        "turn": turn,
        "prompt": prompt,
        "ops": [_serialize_op(op) for op in ops],
    })
    try:
        # New plan for the turn → drop any stale cursor from a prior attempt.
        await client.delete(_done_key(conversation_id))
        await client.set(_plan_key(conversation_id), payload, ex=CHECKPOINT_TTL_SECONDS)
    except Exception as e:
        logger.debug(f"[resume_checkpoint] save_plan failed: {e}")


async def mark_node_completed(conversation_id: Optional[str], node_id: str) -> None:
    """Advance the completed-node cursor as each node finishes node drafting.

    SADD is atomic, so concurrent/repeated marks are safe and need no read.
    Best-effort: a lost mark just means resume re-fills that node (idempotent).
    """
    if not conversation_id or not node_id:
        return
    client = _client()
    if client is None:
        return
    try:
        key = _done_key(conversation_id)
        await client.sadd(key, node_id)
        await client.expire(key, CHECKPOINT_TTL_SECONDS)
    except Exception as e:
        logger.debug(f"[resume_checkpoint] mark_node_completed failed: {e}")


async def load_checkpoint(conversation_id: Optional[str]) -> Optional[dict]:
    """Return {turn, prompt, ops, completed_node_ids} for a conversation, or None.

    None means "no usable checkpoint" — resume must fall back to a full re-run.
    """
    if not conversation_id:
        return None
    client = _client()
    if client is None:
        return None
    try:
        raw = await client.get(_plan_key(conversation_id))
        if not raw:
            return None
        data = json.loads(raw)
        done = await client.smembers(_done_key(conversation_id))
        data["completed_node_ids"] = sorted(done) if done else []
        return data
    except Exception as e:
        logger.debug(f"[resume_checkpoint] load_checkpoint failed: {e}")
        return None


async def clear_checkpoint(conversation_id: Optional[str]) -> None:
    """Drop the checkpoint once the run reaches a terminal state. TTL backstops
    this if it fails."""
    if not conversation_id:
        return
    client = _client()
    if client is None:
        return
    try:
        await client.delete(_plan_key(conversation_id), _done_key(conversation_id))
    except Exception as e:
        logger.debug(f"[resume_checkpoint] clear_checkpoint failed: {e}")


async def refresh_checkpoint_ttl(conversation_id: Optional[str]) -> None:
    """Push the plan + cursor TTLs forward. Called when a resume CONSUMES (but
    keeps) the checkpoint, so a long resume chain can't let the 24h TTL lapse
    mid-flight (mark_node_completed only refreshes the cursor key)."""
    if not conversation_id:
        return
    client = _client()
    if client is None:
        return
    try:
        await client.expire(_plan_key(conversation_id), CHECKPOINT_TTL_SECONDS)
        await client.expire(_done_key(conversation_id), CHECKPOINT_TTL_SECONDS)
    except Exception as e:
        logger.debug(f"[resume_checkpoint] refresh_checkpoint_ttl failed: {e}")


# ─── Epoch fence (attempt counter) ───────────────────────────────────────
# A monotonic per-conversation attempt counter. Every builder run claims one at
# start; only the LATEST attempt may execute (older ones self-cancel). This is
# the safety layer that makes a spurious resume (a noisy-neighbor stall wrongly
# read as death) harmless: the stale original notices a higher attempt and stands
# down instead of double-running. Every op is best-effort and FAIL-OPEN — a Redis
# blip must never cancel a live run, so on uncertainty we report "not superseded".


async def claim_attempt(conversation_id: Optional[str]) -> Optional[int]:
    """Claim this run's attempt number (atomic INCR). Returns the number, or None
    if the epoch can't be claimed (Redis absent) — in which case fencing is off
    for this run and it runs unfenced (legacy behavior)."""
    if not conversation_id:
        return None
    client = _client()
    if client is None:
        return None
    try:
        key = _attempt_key(conversation_id)
        attempt = await client.incr(key)
        await client.expire(key, CHECKPOINT_TTL_SECONDS)
        return int(attempt)
    except Exception as e:
        logger.debug(f"[resume_checkpoint] claim_attempt failed: {e}")
        return None


async def is_superseded(conversation_id: Optional[str], my_attempt: Optional[int]) -> bool:
    """True if a newer attempt has claimed this conversation since `my_attempt`.
    Fail-open: unknown epoch / Redis error / missing key all return False so a
    live run is never cancelled on uncertainty."""
    if not conversation_id or my_attempt is None:
        return False
    client = _client()
    if client is None:
        return False
    try:
        current = await client.get(_attempt_key(conversation_id))
        if current is None:
            return False
        return int(current) > my_attempt
    except Exception as e:
        logger.debug(f"[resume_checkpoint] is_superseded check failed: {e}")
        return False


async def is_current_attempt(conversation_id: Optional[str], my_attempt: Optional[int]) -> bool:
    """True if this run still holds the latest attempt — i.e. it's safe to clear
    the checkpoint at a terminal. No epoch claimed / no key → True (clear as
    before). A superseded run → False (the superseder owns the checkpoint). On a
    Redis error → False (fail-open-to-KEEP: don't risk wiping an active
    checkpoint; the TTL reaps a leftover)."""
    if not conversation_id or my_attempt is None:
        return True
    client = _client()
    if client is None:
        return True
    try:
        current = await client.get(_attempt_key(conversation_id))
        if current is None:
            return True
        return int(current) == my_attempt
    except Exception as e:
        logger.debug(f"[resume_checkpoint] is_current_attempt check failed: {e}")
        return False
