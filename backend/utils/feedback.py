"""Persist feedback locally without forwarding user context off-installation."""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID


TYPE_LABELS = {
    "bug": "Bug",
    "idea": "Idea",
    "general": "Feedback",
    "agent_bug": "Agent-reported bug",
}


async def record_feedback(
    pool,
    *,
    user_id: str,
    feedback_type: str,
    message: str,
    page_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    dedupe_key: Optional[str] = None,
    dedupe_window_hours: int = 24,
) -> bool:
    metadata = metadata or {}
    async with pool.acquire() as conn:
        async with conn.transaction():
            if dedupe_key:
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    f"feedback:{user_id}:{feedback_type}:{dedupe_key}",
                )
                duplicate = await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM user_feedback
                        WHERE user_id = $1
                          AND type = $2
                          AND metadata->>'agent_dedupe_key' = $3
                          AND created_at > NOW() - ($4::int * INTERVAL '1 hour')
                    )
                    """,
                    UUID(user_id),
                    feedback_type,
                    dedupe_key,
                    dedupe_window_hours,
                )
                if duplicate:
                    return False
            await conn.execute(
                """
                INSERT INTO user_feedback (user_id, type, message, page_url, metadata)
                VALUES ($1, $2, $3, $4, $5)
                """,
                UUID(user_id),
                feedback_type,
                message,
                page_url,
                metadata,
            )
    return True
