"""What an event's channel sees while an agent works it.

A WhatsApp chat sees the account typing as soon as an agent takes its message into a turn, not only once the reply
is sent; the gateway counts typing already shown toward the pause it keeps before a send, so the reply then goes at
once. The trigger's node class decides what to show (``WorkflowNode.agent_pickup``) and
shows it (``agent_working``); the turn's end takes it down unless the reply did (``agent_turn_ended``), and a turn
that stopped partway tells the channel so rather than leaving it looking at work.

A turn ends where its harness answers: in the agent node for one it runs itself, in the CLI turn callback for one
a sandbox runs, and where its run settles for one stopped short of either (a platform turn whose server stopped).
So the record of what a turn showed is kept in Redis under the turn's conversation id, the one the CLI dispatch and
its callback name the turn by. All of it is best-effort beside the turn: nothing here may fail one
or hold one up, and a record nothing ends lapses on its own.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from utils import redis_client
from utils.async_helpers import spawn

logger = logging.getLogger(__name__)

# Outlives the longest turn a sandbox runs (its hard wall is 4 hours).
RECORD_TTL_S = 5 * 3600
# How long a turn's end waits for what its pickup is still showing, so it never takes it down first.
SHOWING_WAIT_S = 5.0
# What an agent's output says when its turn stopped short of its end (``coder.coordinator.tasks.turn_error``'s).
_STOPPED_SHORT = frozenset({"failed", "error", "turn_lost", "canceled"})
_showing: Dict[str, asyncio.Task] = {}


def _key(conversation_id: str) -> str:
    return f"agent:pickup:{conversation_id}"


def _shown_key(conversation_id: str) -> str:
    return f"agent:pickup:{conversation_id}:shown"


def _node_class(node_type: str):
    from nodes.core.registry import NODE_REGISTRY

    return NODE_REGISTRY.get(node_type)


async def picked_up(conversation_id: Optional[str], event: Dict[str, Any]) -> None:
    """An agent took ``event`` (``AgentNode._resolve_trigger_event``'s) into the turn of ``conversation_id``: show it
    on its channel, as its trigger's node class says."""
    node_cls = _node_class(str(event.get("node_type") or ""))
    output = event.get("output")
    if not conversation_id or node_cls is None or not isinstance(output, dict):
        return
    try:
        picked = node_cls.agent_pickup(output)
    except Exception:
        logger.warning("[event pickup] %s couldn't read what to show", event.get("node_type"), exc_info=True)
        return
    if not picked:
        return
    client = redis_client.get_shared_redis()
    if client is None:
        return  # with nowhere to keep it, no turn's end could take it down
    try:
        await client.set(_key(conversation_id), json.dumps({"node_type": event["node_type"], "picked": picked}),
                         ex=RECORD_TTL_S)
    except Exception:
        logger.warning("[event pickup] keeping what %s shows failed; showing nothing", conversation_id, exc_info=True)
        return
    task = spawn(node_cls.agent_working(picked), name="agent-event-pickup")
    _showing[conversation_id] = task
    task.add_done_callback(lambda done: _showing.pop(conversation_id, None) if _showing.get(conversation_id) is done
                           else None)


async def shown(conversation_id: Optional[str], name: str, fact: Optional[Dict[str, Any]]) -> None:
    """``fact``, JSON-safe, is what the turn of ``conversation_id`` put on its event's channel as it worked (a WhatsApp
    live status), kept as ``name`` for the turn's end (``agent_turn_ended``'s ``shown``); None: it no longer stands
    (the status became the answer). Kept only for a turn that picked its event up."""
    client = redis_client.get_shared_redis()
    if not conversation_id or client is None:
        return
    try:
        if fact is None:
            await client.hdel(_shown_key(conversation_id), name)
        elif await client.exists(_key(conversation_id)):
            async with client.pipeline(transaction=True) as pipe:
                pipe.hset(_shown_key(conversation_id), name, json.dumps(fact))
                pipe.expire(_shown_key(conversation_id), RECORD_TTL_S)
                await pipe.execute()
    except Exception:
        logger.warning("[event pickup] keeping what %s showed failed", conversation_id, exc_info=True)


def stopped_short(output: Any) -> bool:
    """Whether an agent's output says its turn failed rather than got to its end."""
    return isinstance(output, dict) and (bool(output.get("error")) or output.get("status") in _STOPPED_SHORT)


async def turn_ended(conversation_id: Optional[str], *, finished: bool = True, again: bool = False) -> None:
    """The turn of ``conversation_id`` ended: take down what its pickup showed, unless its reply did. ``finished``
    False: it stopped partway, which the channel is told (``agent_turn_ended``); ``again``: it runs again, so the
    record stays for that run's end."""
    if not conversation_id:
        return
    showing = _showing.get(conversation_id)
    if showing is not None:
        await asyncio.wait([showing], timeout=SHOWING_WAIT_S)
    client = redis_client.get_shared_redis()
    if client is None:
        return
    # What it showed is dealt with here; the record itself stays for a run that goes round again.
    done = [_shown_key(conversation_id)] + ([] if again else [_key(conversation_id)])
    try:
        async with client.pipeline(transaction=True) as pipe:
            pipe.get(_key(conversation_id))
            pipe.hgetall(_shown_key(conversation_id))
            pipe.delete(*done)
            raw, kept, _ = await pipe.execute()
    except Exception:
        logger.warning("[event pickup] reading what %s showed failed", conversation_id, exc_info=True)
        return
    if not raw:
        return
    record = json.loads(raw)
    node_cls = _node_class(record["node_type"])
    if node_cls is None:
        return
    shown_then = {(k.decode() if isinstance(k, bytes) else k): json.loads(v) for k, v in (kept or {}).items()}
    try:
        await node_cls.agent_turn_ended(record["picked"], shown=shown_then, finished=finished, again=again)
    except Exception:
        logger.warning("[event pickup] taking down what %s showed failed", conversation_id, exc_info=True)
