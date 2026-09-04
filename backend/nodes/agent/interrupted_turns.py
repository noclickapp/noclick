"""Self-heal for chat turns whose backing run died before any terminal evidence."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


_INTERRUPTED_TURN_MIN_IDLE_S = 90

_INTERRUPTED_TURN_MSG = (
    "The agent was interrupted before it could reply — the backend run died "
    "mid-turn. Send another message to retry."
)


async def resolve_interrupted_chat_turn(
    pool,
    *,
    conversation_id: str,
    workflow_id: str,
    node_id: str,
    conversation_key: str,
    owner_user_id: Optional[str] = None,
    min_idle_s: float = _INTERRUPTED_TURN_MIN_IDLE_S,
) -> bool:
    """Self-heal (on resume-read) for chat turns that died BEFORE any terminal
    evidence existed — a worker killed mid-dispatch (deploy, preemption, dev
    reload) persists the user's message but neither an awaiting marker nor a
    response, so the marker-keyed reconciler/sweep can never see the loss and a
    chat surface polling ``conversations.events`` waits forever.

    Guards — each protects a live turn from a false kill:
    - Tail + idle: the newest event must be the user's message AND the row idle
      past ``min_idle_s`` (a healthy dispatch appends/persists well inside it).
    - Awaiting marker: the node's latest output being THIS conversation's
      ``awaiting_agent_turn`` marker means the asynchronous runtime owns the turn — the
      gone-beat reconciler / stale sweep resolve that class, never this.
    - Running execution: any in-flight run of the workflow may be this turn
      (SDK turns run inside it; CLI delivery runs persist the marker at run
      end) — wait for the next poll.

    The append itself is tail-guarded SQL, so a concurrently-landing response
    (or a second resolver racing this one) wins cleanly. Returns True iff the
    interrupted event was appended."""
    from repositories.conversation import ConversationRepo
    from utils.node_outputs import latest_output_meta

    if not (conversation_id and workflow_id and node_id and conversation_key):
        return False
    try:
        row = await pool.fetchrow(
            """
            SELECT (events->-1->>'role') AS tail_role,
                   last_activity < now() - make_interval(secs => $3) AS idle
            FROM conversations
            WHERE conversation_id::text = $1::text
              AND ($2::text IS NULL OR user_id::text = $2::text)
              AND deleted_at IS NULL
              AND jsonb_typeof(events) = 'array'
            """,
            conversation_id, owner_user_id, min_idle_s,
        )
        if not row or row["tail_role"] != "user" or not row["idle"]:
            return False

        meta = await latest_output_meta(pool, workflow_id, node_id)
        output = (meta or {}).get("output")
        if (
            isinstance(output, dict)
            and output.get("status") == "awaiting_agent_turn"
            and _marker_matches_conversation(output, workflow_id, node_id, conversation_key)
        ):
            return False  # delivered turn — the runtime's reconciler and sweep own it

        # awaiting_* = suspended (approval/delay) — a live turn's run, however
        # old. A 'running' row is only credible while young: a worker killed
        # mid-run leaves its row 'running' FOREVER (no abandoned-row sweep
        # exists), and trusting it unboundedly would re-wedge the exact class
        # this resolver exists to heal.
        running = await pool.fetchval(
            "SELECT 1 FROM workflow_executions "
            "WHERE workflow_id = $1 "
            "AND ((status = 'running' AND started_at > now() - interval '30 minutes') "
            "     OR status LIKE 'awaiting\\_%') LIMIT 1",
            workflow_id,
        )
        if running:
            return False

        healed = await ConversationRepo(pool).append_event_if_user_tail(
            conversation_id,
            {"role": "assistant", "message": _INTERRUPTED_TURN_MSG, "cancelled": True},
            owner_user_id,
        )
        if healed:
            logger.warning(
                f"[AgentTurn] resolved INTERRUPTED turn for {workflow_id}/{node_id} "
                f"ck={conversation_key!r} (no marker, no running execution)"
            )
        return healed
    except Exception:
        logger.warning(
            f"[AgentTurn] interrupted-turn resolve failed for {conversation_id}",
            exc_info=True,
        )
        return False
