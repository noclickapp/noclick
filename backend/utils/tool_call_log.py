"""Durable, best-effort audit records for agent tool calls.

A logging failure never fails the tool invocation. Records are scoped by
execution and conversation so the execution log can reconstruct each run.
"""

import json
import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Caps keep rows bounded; full payloads live in the provider systems anyway.
_MAX_ARGUMENTS_BYTES = 16_384
_MAX_PREVIEW_CHARS = 500

# A response package's tool timeline is capped so a turn that ran a huge number
# of tools can't bloat the agent node's output blob.
_PACKAGE_TOOLS_CAP = 200

_INSERT_SQL = """
    INSERT INTO tool_call_events (
        user_id, workflow_id, execution_id, conversation_id, agent_node_id,
        tool_name, tool_type, provider_node_id, operation, credential_id,
        arguments, result_status, error, result_preview, duration_ms, model
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
"""


def _to_uuid(value: Optional[str]) -> Optional[_uuid.UUID]:
    if not value:
        return None
    try:
        return value if isinstance(value, _uuid.UUID) else _uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _bounded_arguments(arguments: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(arguments, dict):
        return None
    try:
        size = len(json.dumps(arguments, default=str).encode("utf-8"))
    except Exception:
        return {"_unserializable": True}
    if size <= _MAX_ARGUMENTS_BYTES:
        return arguments
    return {
        "_truncated": True,
        "_original_bytes": size,
        "_keys": sorted(arguments.keys()),
    }


def record_tool_call(
    *,
    user_id: Optional[str],
    tool_name: str,
    tool_type: str,
    result_status: str,
    workflow_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    agent_node_id: Optional[str] = None,
    provider_node_id: Optional[str] = None,
    operation: Optional[str] = None,
    credential_id: Optional[str] = None,
    arguments: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    result_preview: Optional[str] = None,
    duration_ms: Optional[float] = None,
    model: Optional[str] = None,
) -> None:
    """Schedule one durable tool-call record. Never raises.

    ``model`` identifies the model or runner in the persisted audit row.
    """
    if not user_id:
        return
    try:
        from utils.async_helpers import spawn

        spawn(
            _insert(
                user_id=user_id,
                tool_name=tool_name,
                tool_type=tool_type,
                result_status=result_status,
                workflow_id=workflow_id,
                execution_id=execution_id,
                conversation_id=conversation_id,
                agent_node_id=agent_node_id,
                provider_node_id=provider_node_id,
                operation=operation,
                credential_id=credential_id,
                arguments=arguments,
                error=error,
                result_preview=result_preview,
                duration_ms=duration_ms,
                model=model,
            ),
            name=f"tool-call-log:{tool_name}",
        )
    except Exception as e:
        logger.warning(f"[ToolCallLog] Failed to schedule record for {tool_name}: {e}")

# ── package assembly (read side) ─────────────────────────────────────────────
# Response packages gather tool calls by agent, conversation, and an advancing
# timestamp boundary. The first response uses a bounded fallback window; later
# responses advance the stored boundary so concurrent conversations stay isolated.

_SELECT_SINCE_SQL = """
    SELECT tool_name, tool_type, operation, provider_node_id,
           credential_id::text AS credential_id, result_status, error,
           result_preview, arguments, duration_ms, model, created_at,
           now() AS query_now
    FROM tool_call_events
    WHERE agent_node_id = $1
      AND conversation_id = $2
      AND created_at > COALESCE($3::timestamptz, now() - $4 * interval '1 second')
    ORDER BY created_at ASC
    LIMIT $5
"""


def _row_to_tool_call(r) -> Dict[str, Any]:
    created = r["created_at"]
    return {
        "tool_name": r["tool_name"],
        "tool_type": r["tool_type"],
        "operation": r["operation"],
        "provider_node_id": r["provider_node_id"],
        "credential_id": r["credential_id"],
        "result_status": r["result_status"],
        "error": r["error"],
        "result_preview": r["result_preview"],
        "arguments": r["arguments"],
        "duration_ms": r["duration_ms"],
        "model": r["model"],
        "created_at": created.isoformat() if created else None,
    }


async def fetch_tool_calls_since(
    *,
    agent_node_id: str,
    conversation_id: str,
    after: Optional[str],
    lookback_s: int,
    limit: int = _PACKAGE_TOOLS_CAP,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """The (agent_node, conversation) tool calls newer than ``after`` (an ISO
    timestamp from the previous response, or None for the first response — then
    bounded by ``lookback_s`` so an expired-boundary first package can't reach
    back across an old session), oldest first.

    Returns ``(tool_calls, new_boundary)`` where ``new_boundary`` is the DB
    ``now()`` to store as the next window's lower bound — None when no calls were
    found, so the boundary is left untouched and a late-landing fire-and-forget
    insert is still caught by the next response's window. Best-effort: returns
    ``([], None)`` on any error (observability must never fail a turn)."""
    if not (agent_node_id and conversation_id):
        return [], None
    try:
        from utils.database_pool import get_native_pool

        # Redis hands the boundary back as an ISO string; asyncpg's timestamptz
        # codec only takes datetimes, and passing the str raised a DataError the
        # except below would otherwise degrade the audit timeline silently.
        after_dt = datetime.fromisoformat(after) if after else None
        rows = await get_native_pool().fetch(
            _SELECT_SINCE_SQL, agent_node_id, conversation_id, after_dt, lookback_s, limit
        )
        if not rows:
            return [], None
        boundary = rows[0]["query_now"]
        return [_row_to_tool_call(r) for r in rows], (
            boundary.isoformat() if boundary else None
        )
    except Exception as e:
        logger.warning(f"[ToolCallLog] fetch_tool_calls_since failed: {e}")
        return [], None


_boundary_redis = None


def _get_boundary_redis():
    global _boundary_redis
    if _boundary_redis is None:
        import os

        import redis.asyncio as redis

        from utils.redis_client import RESILIENCE_KWARGS, redis_url_or_none

        redis_url = redis_url_or_none()
        if not redis_url:
            # Callers treat every failure here as "no boundary recorded", which
            # is the correct degraded behaviour: a turn's tool calls are then
            # gathered from the lookback window alone.
            return None
        _boundary_redis = redis.from_url(
            redis_url, decode_responses=True, **RESILIENCE_KWARGS,
        )
    return _boundary_redis


_TURN_BOUNDARY_TTL_S = 6 * 3600


async def gather_turn_tool_calls(
    *, node_id: Optional[str], conversation_id: Optional[str],
) -> List[Dict[str, Any]]:
    """The tool calls this (node, conversation) ran since its previous response —
    the turn's tool timeline. Shared by every assistant-persistence path so the
    per-(node, conversation) boundary advances exactly once per response.
    Best-effort: returns [] on any error."""
    if not (node_id and conversation_id):
        return []
    from nodes.agent.runtime_limits import TURN_TOOL_LOOKBACK_S

    key = f"nc:agent_pkg:boundary:{node_id}:{conversation_id}"
    try:
        prev = await _get_boundary_redis().get(key)
    except Exception:
        logger.debug("[ToolCallLog] turn boundary read unavailable", exc_info=True)
        prev = None

    tool_calls, new_boundary = await fetch_tool_calls_since(
        agent_node_id=node_id, conversation_id=conversation_id,
        after=prev, lookback_s=TURN_TOOL_LOOKBACK_S,
    )
    if new_boundary:
        try:
            await _get_boundary_redis().set(key, new_boundary, ex=_TURN_BOUNDARY_TTL_S)
        except Exception:
            logger.debug("[ToolCallLog] turn boundary write failed", exc_info=True)
    return tool_calls


def compact_tool_calls_for_transcript(
    tool_calls: List[Dict[str, Any]], cap: int = 50
) -> List[Dict[str, Any]]:
    """Bounded projection of a turn's tool calls for persistence on the
    conversation's assistant event — what the chat timeline needs to restore
    its step rows across reloads (name, args preview, result preview, timing)
    without bloating conversations.events with full argument payloads."""
    out: List[Dict[str, Any]] = []
    for t in tool_calls[:cap]:
        if not isinstance(t, dict) or not t.get("tool_name"):
            continue
        args = t.get("arguments")
        try:
            args_preview = json.dumps(args, default=str)[:_MAX_PREVIEW_CHARS] if args else ""
        except Exception:
            args_preview = ""
        out.append({
            "tool_name": t["tool_name"],
            "arguments_preview": args_preview,
            "result_status": t.get("result_status"),
            "result_preview": t.get("result_preview"),
            "duration_ms": t.get("duration_ms"),
            "created_at": t.get("created_at"),
        })
    return out


async def _insert(**kw) -> None:
    try:
        from utils.database_pool import get_native_pool

        await get_native_pool().execute(
            _INSERT_SQL,
            _to_uuid(kw["user_id"]),
            _to_uuid(kw["workflow_id"]),
            _to_uuid(kw["execution_id"]),
            kw["conversation_id"],
            kw["agent_node_id"],
            kw["tool_name"],
            kw["tool_type"],
            kw["provider_node_id"],
            kw["operation"],
            _to_uuid(kw["credential_id"]),
            # Plain dict — the runtime pool's jsonb codec serializes;
            # pre-dumping would double-encode (see jsonb codec memory).
            _bounded_arguments(kw["arguments"]),
            kw["result_status"],
            (kw["error"] or None) and str(kw["error"])[:2000],
            (kw["result_preview"] or None) and str(kw["result_preview"])[:_MAX_PREVIEW_CHARS],
            int(kw["duration_ms"]) if kw["duration_ms"] is not None else None,
            kw.get("model") or None,
        )
    except Exception as e:
        logger.warning(f"[ToolCallLog] Insert failed for {kw.get('tool_name')}: {e}")
